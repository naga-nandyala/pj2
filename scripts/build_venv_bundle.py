#!/usr/bin/env python3
"""Build a relocatable virtualenv bundle of the mycli application.

This script assembles the project together with all of its Python dependencies
inside a pre-populated virtual environment. The resulting layout mirrors what a
Homebrew Cask expects (`bin/` + `libexec/`), but instead of a frozen binary it
ships a ready-to-run interpreter that executes ``mycli`` via ``python -m``.

The bundle is larger than a zipapp but does not rely on a system Python runtime.
It is also simpler than a PyInstaller freeze because it avoids native binary
analysis. Build the bundle on the target operating system (e.g. macOS) to ensure
compatible binaries end up in the virtual environment.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Iterable, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
PACKAGE_NAME = "mycli_app"
APP_NAME = "mycli"
VENV_NAME = f"{APP_NAME}-venv"


class BuildError(RuntimeError):
    """Raised when the packaging pipeline fails."""


def _run(
    cmd: Iterable[str], *, env: Optional[dict[str, str]] = None, capture_output: bool = False
) -> subprocess.CompletedProcess:
    """Execute a subprocess command, optionally capturing stdout/stderr."""

    command_list = list(cmd)
    print(f"→ {' '.join(command_list)}")
    try:
        return subprocess.run(
            command_list,
            check=True,
            env=env,
            stdout=subprocess.PIPE if capture_output else None,
            stderr=subprocess.PIPE if capture_output else None,
            text=True,
        )
    except subprocess.CalledProcessError as exc:  # pragma: no cover - thin wrapper
        output = exc.stdout if capture_output else ""
        error = exc.stderr if capture_output else ""
        message = f"Command failed with exit code {exc.returncode}: {' '.join(command_list)}"
        if output:
            message += f"\nSTDOUT:\n{output}"
        if error:
            message += f"\nSTDERR:\n{error}"
        raise BuildError(message) from exc


def _detect_version() -> str:
    """Extract the package version without importing optional dependencies."""

    init_path = SRC_DIR / PACKAGE_NAME / "__init__.py"
    try:
        source = init_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:  # pragma: no cover - defensive
        raise BuildError(f"Could not locate {init_path} to determine version") from exc

    module = ast.parse(source, filename=str(init_path))
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__version__":
                    value = node.value
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        return value.value
    raise BuildError("Could not determine version from package (__version__ missing)")


def _virtualenv_python(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python3"


def _virtualenv_bin_dir(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts"
    return venv_dir / "bin"


def _ensure_clean(paths: Iterable[Path]) -> None:
    for path in paths:
        if path.is_file() or path.is_symlink():
            print(f"Cleaning file {path}")
            path.unlink()
        elif path.is_dir():
            print(f"Cleaning directory {path}")
            shutil.rmtree(path)


def _create_virtualenv(venv_dir: Path) -> Path:
    """Create a virtual environment specifically for building the bundle."""

    _ensure_clean([venv_dir])
    print(f"Creating build virtual environment at {venv_dir}")
    cmd = [sys.executable, "-m", "venv", "--copies", str(venv_dir)]
    _run(cmd)
    python_path = _virtualenv_python(venv_dir)
    _run([str(python_path), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
    return python_path


def _install_project(python_path: Path, extras: Optional[str]) -> None:
    project_spec = str(PROJECT_ROOT)
    if extras:
        project_spec += f"[{extras}]"
    _run([str(python_path), "-m", "pip", "install", project_spec])


def _prune_bytecode(root: Path) -> None:
    for path in root.rglob("__pycache__"):
        shutil.rmtree(path, ignore_errors=True)
    for suffix in (".pyc", ".pyo"):
        for file in root.rglob(f"*{suffix}"):
            try:
                file.unlink()
            except FileNotFoundError:  # pragma: no cover - defensive
                pass


def _write_file(path: Path, content: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def _create_launchers(bin_dir: Path, venv_rel_path: str) -> None:
    venv_rel_path_win = venv_rel_path.replace("/", "\\\\")
    posix_launcher = f"""#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
APP_ROOT="$(cd "${{SCRIPT_DIR}}/.." && pwd)"
VENV_DIR="${{APP_ROOT}}/{venv_rel_path}"

# Try different python executable names and check if they exist and are executable
if [[ -f "${{VENV_DIR}}/bin/python3" ]] && [[ -x "${{VENV_DIR}}/bin/python3" ]]; then
    PYTHON="${{VENV_DIR}}/bin/python3"
elif [[ -f "${{VENV_DIR}}/bin/python" ]] && [[ -x "${{VENV_DIR}}/bin/python" ]]; then
    PYTHON="${{VENV_DIR}}/bin/python"
elif [[ -f "${{VENV_DIR}}/bin/python3.12" ]] && [[ -x "${{VENV_DIR}}/bin/python3.12" ]]; then
    PYTHON="${{VENV_DIR}}/bin/python3.12"
else
    echo "Error: Could not locate executable python interpreter in {venv_rel_path}" >&2
    echo "Available files in ${{VENV_DIR}}/bin/:" >&2
    ls -la "${{VENV_DIR}}/bin/" 2>/dev/null || echo "Directory ${{VENV_DIR}}/bin does not exist" >&2
    exit 1
fi

exec "${{PYTHON}}" -m {PACKAGE_NAME} "$@"
"""

    windows_launcher = f"""@echo off
setlocal
set SCRIPT_DIR=%~dp0
set APP_ROOT=%SCRIPT_DIR%..\\
set VENV=%APP_ROOT%{venv_rel_path_win}
set PYTHON=%VENV%\\Scripts\\python.exe
if exist "%PYTHON%" (
    "%PYTHON%" -m {PACKAGE_NAME} %*
    goto :eof
)
set PYTHON=%VENV%\\Scripts\\python3.exe
if exist "%PYTHON%" (
    "%PYTHON%" -m {PACKAGE_NAME} %*
    goto :eof
)
set PYTHON=%VENV%\\bin\\python3
if exist "%PYTHON%" (
    "%PYTHON%" -m {PACKAGE_NAME} %*
    goto :eof
)
echo Could not locate python interpreter inside {venv_rel_path}
exit /b 1
"""

    _write_file(bin_dir / APP_NAME, posix_launcher, executable=True)
    _write_file(bin_dir / f"{APP_NAME}.bat", windows_launcher)


def _stage_bundle(venv_source: Path, *, platform_tag: str, artifacts_dir: Path) -> Path:
    staging_root = artifacts_dir / f"{APP_NAME}-{platform_tag}"
    _ensure_clean([staging_root])

    bin_dir = staging_root / "bin"
    libexec_dir = staging_root / "libexec"
    venv_target = libexec_dir / VENV_NAME
    bin_dir.mkdir(parents=True, exist_ok=True)
    libexec_dir.mkdir(parents=True, exist_ok=True)

    shutil.copytree(venv_source, venv_target)
    _prune_bytecode(venv_target)

    _create_launchers(bin_dir, f"libexec/{VENV_NAME}")

    return staging_root


def _create_tarball(staging_root: Path) -> Path:
    archive_path = staging_root.parent / f"{staging_root.name}.tar.gz"
    _ensure_clean([archive_path])
    with tarfile.open(archive_path, "w:gz") as tar:
        # Add contents of staging_root directly to archive root (no version folder)
        for item in staging_root.iterdir():
            tar.add(item, arcname=item.name)
    return archive_path


def _emit_sha256(artifact_path: Path) -> Path:
    digest = hashlib.sha256()
    with artifact_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    checksum_path = artifact_path.with_suffix(artifact_path.suffix + ".sha256")
    checksum_line = f"{digest.hexdigest()}  {artifact_path.name}\n"
    checksum_path.write_text(checksum_line, encoding="utf-8")
    print(checksum_line.strip())
    return checksum_path


def build_bundle(*, extras: Optional[str], platform_tag: str) -> None:
    version = _detect_version()
    artifacts_dir = PROJECT_ROOT / "dist" / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    print(f"Building {APP_NAME} version {version} for {platform_tag} (virtualenv style)")

    with tempfile.TemporaryDirectory(prefix="mycli-venv-build-") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        venv_dir = tmp_dir / "bundle-venv"
        python_path = _create_virtualenv(venv_dir)
        _install_project(python_path, extras)

        staging_root = _stage_bundle(
            venv_dir,
            platform_tag=platform_tag,
            artifacts_dir=artifacts_dir,
        )

    archive_path = _create_tarball(staging_root)
    checksum_path = _emit_sha256(archive_path)

    print("\nBundle complete! Artifacts:")
    print(f"  - Bundle directory: {staging_root}")
    print(f"  - Tarball:          {archive_path}")
    print(f"  - SHA256:           {checksum_path}")
    print("\nNext steps:")
    print("  1. Codesign/notarize the tarball on macOS if distributing externally.")
    print("  2. Upload the tarball and update distribution metadata (e.g. Homebrew Cask).")


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a virtualenv bundle for mycli")
    parser.add_argument(
        "--extras",
        default="broker",
        help=(
            "Comma-separated optional dependency groups to install before bundling. "
            "Pass an empty string to skip extras."
        ),
    )
    parser.add_argument(
        "--platform-tag",
        default="macos-universal2",
        help="Suffix added to artifact names to describe the target platform.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Iterable[str]] = None) -> None:
    args = parse_args(argv)
    extras = (args.extras or "").strip() or None

    try:
        build_bundle(extras=extras, platform_tag=args.platform_tag)
    except BuildError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":  # pragma: no cover - manual invocation 
    main()
