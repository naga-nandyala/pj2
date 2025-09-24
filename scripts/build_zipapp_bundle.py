#!/usr/bin/env python3
"""Build a zipapp-based bundle of the mycli application without PyInstaller.

This script produces a Homebrew Cask-friendly artifact that wraps the project
inside a `.pyz` archive generated with ``shiv``. Compared to the PyInstaller
bundle, the resulting archive depends on a system-provided Python 3.8+ runtime
but avoids the native binary freeze step.

High-level workflow:

1. Creates an isolated virtual environment dedicated to the build.
2. Installs the current project (with optional extras) into that environment.
3. Installs ``shiv`` and packages the environment into a zipapp (`mycli.pyz`).
4. Stages a ``bin``/``libexec`` layout with launcher scripts for macOS/Linux and
   Windows.
5. Archives the staging directory into a ``.tar.gz`` file and emits a SHA256
   checksum alongside it.
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
    return venv_dir / "bin" / "python"


def _ensure_clean(paths: Iterable[Path]) -> None:
    for path in paths:
        if path.is_file() or path.is_symlink():
            print(f"Cleaning file {path}")
            path.unlink()
        elif path.is_dir():
            print(f"Cleaning directory {path}")
            shutil.rmtree(path)


def _create_virtualenv(venv_dir: Path) -> Path:
    _ensure_clean([venv_dir])
    print(f"Creating build virtual environment at {venv_dir}")
    _run([sys.executable, "-m", "venv", str(venv_dir)])
    python_path = _virtualenv_python(venv_dir)
    _run([str(python_path), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
    return python_path


def _install_project(python_path: Path, extras: Optional[str]) -> None:
    project_spec = str(PROJECT_ROOT)
    if extras:
        project_spec += f"[{extras}]"
    _run([str(python_path), "-m", "pip", "install", project_spec])
    _run([str(python_path), "-m", "pip", "install", "shiv>=1.0.0"])


def _discover_site_packages(python_path: Path) -> list[Path]:
    code = "import sysconfig; paths = sysconfig.get_paths(); print(paths['purelib']); print(paths['platlib'])"
    result = _run([str(python_path), "-c", code], capture_output=True)
    seen: set[Path] = set()
    ordered: list[Path] = []
    for line in result.stdout.splitlines():
        candidate = Path(line.strip())
        if candidate and candidate not in seen:
            seen.add(candidate)
            ordered.append(candidate)
    return ordered


def _build_zipapp(python_path: Path, site_packages: list[Path], output_dir: Path) -> Path:
    zipapp_path = output_dir / f"{APP_NAME}.pyz"
    _ensure_clean([zipapp_path])

    if not site_packages:
        raise BuildError("Could not locate site-packages directory inside the build environment")

    cmd = [str(python_path), "-m", "shiv", "--compressed", "--reproducible", "-c", APP_NAME, "-o", str(zipapp_path)]
    for path in site_packages:
        cmd.extend(["--site-packages", str(path)])

    _run(cmd)
    if not zipapp_path.exists():
        raise BuildError(f"shiv did not produce the expected zipapp at {zipapp_path}")
    return zipapp_path


def _write_file(path: Path, content: str, *, executable: bool = False) -> None:
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def _create_launchers(bin_dir: Path) -> None:
    posix_launcher = f"""#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
APP_ROOT="$(cd "${{SCRIPT_DIR}}/.." && pwd)"
PYZ_PATH="${{APP_ROOT}}/libexec/{APP_NAME}.pyz"

if command -v python3 >/dev/null 2>&1; then
    exec python3 "${{PYZ_PATH}}" "$@"
elif command -v python >/dev/null 2>&1; then
    exec python "${{PYZ_PATH}}" "$@"
else
    echo "Python 3.8+ is required to run {APP_NAME}. Please install Python from https://www.python.org/." >&2
    exit 1
fi
"""

    windows_launcher = f"""@echo off
setlocal
set SCRIPT_DIR=%~dp0
set APP_ROOT=%SCRIPT_DIR%..\
set PYZ=%APP_ROOT%libexec\\{APP_NAME}.pyz

where python >nul 2>nul
if %ERRORLEVEL%==0 (
    python "%PYZ%" %*
    goto :eof
)

where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py -3 "%PYZ%" %*
    goto :eof
)

echo Python 3.8+ is required to run {APP_NAME}. Please install Python from https://www.python.org/.
exit /b 1
"""

    _write_file(bin_dir / APP_NAME, posix_launcher, executable=True)
    _write_file(bin_dir / f"{APP_NAME}.bat", windows_launcher)


def _stage_bundle(zipapp_path: Path, *, platform_tag: str, artifacts_dir: Path) -> Path:
    staging_root = artifacts_dir / f"{APP_NAME}-{platform_tag}"
    _ensure_clean([staging_root])

    bin_dir = staging_root / "bin"
    libexec_dir = staging_root / "libexec"
    bin_dir.mkdir(parents=True, exist_ok=True)
    libexec_dir.mkdir(parents=True, exist_ok=True)

    target_pyz = libexec_dir / zipapp_path.name
    shutil.copy2(zipapp_path, target_pyz)
    _create_launchers(bin_dir)

    return staging_root


def _create_tarball(staging_root: Path) -> Path:
    archive_path = staging_root.parent / f"{staging_root.name}.tar.gz"
    _ensure_clean([archive_path])
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(staging_root, arcname=staging_root.name)
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

    print(f"Building {APP_NAME} version {version} for {platform_tag} (zipapp style)")

    with tempfile.TemporaryDirectory(prefix="mycli-zipapp-build-") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        venv_dir = tmp_dir / "build-env"
        python_path = _create_virtualenv(venv_dir)
        _install_project(python_path, extras)
        site_packages = _discover_site_packages(python_path)
        zipapp_path = _build_zipapp(python_path, site_packages, tmp_dir)

        staging_root = _stage_bundle(
            zipapp_path,
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
    print("  1. Ensure target machines have Python 3.8+ installed.")
    print("  2. Optionally codesign/notarize the tarball (macOS).")
    print("  3. Publish the tarball and update distribution metadata (e.g. Homebrew Cask).")


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a zipapp bundle for mycli (no PyInstaller)")
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
