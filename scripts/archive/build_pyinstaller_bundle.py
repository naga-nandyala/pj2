#!/usr/bin/env python3
"""Utility for producing a PyInstaller-based bundle of the mycli application.

The script can be executed on any platform supported by PyInstaller (macOS,
Windows, Linux). It automates the following workflow:

1. Creates an isolated virtual environment dedicated to the build.
2. Installs the current project (with optional extras) into that environment.
3. Invokes PyInstaller to freeze ``mycli`` into a self-contained executable or
   directory bundle.
4. Structures the output in a distribution-friendly layout (e.g. Homebrew Cask)
   and produces a ``.tar.gz`` archive.
5. Emits a SHA256 checksum next to the archive for easy integrity verification.

Example artifact layout:

```
artifacts/
  mycli-macos-universal2/
    bin/mycli
  mycli-macos-universal2.tar.gz
  mycli-macos-universal2.tar.gz.sha256
```

Notes
-----
* Run the script on the target platform (e.g. macOS for universal2 builds,
  Windows for win32/win_amd64 builds) to ensure PyInstaller collects the proper
  binaries.
* PyInstaller 6.3+ is required; the script installs it inside the transient
  build environment so the host Python stays untouched.
* Codesigning / notarization are not handled here – perform those steps on the
  generated tarball as part of your release pipeline if required.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import os
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
CLI_ENTRY = SRC_DIR / PACKAGE_NAME / "__main__.py"
CONFIG_FILE = SRC_DIR / PACKAGE_NAME / "config.yaml"


class BuildError(RuntimeError):
    """Raised when the packaging pipeline fails."""


def _run(cmd: Iterable[str], *, env: Optional[dict[str, str]] = None) -> None:
    """Execute a subprocess command, streaming its output live."""
    command_list = list(cmd)
    print(f"→ {' '.join(command_list)}")
    try:
        subprocess.run(command_list, check=True, env=env)
    except subprocess.CalledProcessError as exc:  # pragma: no cover - thin wrapper
        raise BuildError(f"Command failed with exit code {exc.returncode}: {' '.join(command_list)}") from exc


def _normalize_path(path: Path) -> str:
    """Return a string representation suitable for PyInstaller --add-data."""
    sep = ";" if os.name == "nt" else ":"
    return f"{path}{sep}{PACKAGE_NAME}"


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
    """Return the path to the Python executable inside a virtual environment."""
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _ensure_clean(paths: Iterable[Path]) -> None:
    for path in paths:
        if path.is_file():
            print(f"Cleaning file {path}")
            path.unlink()
        elif path.is_dir():
            print(f"Cleaning directory {path}")
            shutil.rmtree(path)


def _create_virtualenv(venv_dir: Path) -> Path:
    """Create a virtual environment specifically for building the bundle."""
    _ensure_clean([venv_dir])
    print(f"Creating build virtual environment at {venv_dir}")
    _run([sys.executable, "-m", "venv", str(venv_dir)])
    python_path = _virtualenv_python(venv_dir)
    # Upgrade core packaging tooling in the isolated environment
    _run([str(python_path), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
    return python_path


def _install_project(python_path: Path, extras: Optional[str]) -> None:
    project_spec = str(PROJECT_ROOT)
    if extras:
        project_spec += f"[{extras}]"
    _run([str(python_path), "-m", "pip", "install", project_spec])
    _run([str(python_path), "-m", "pip", "install", "pyinstaller>=6.3"])


def _invoke_pyinstaller(python_path: Path, *, app_name: str, dist_dir: Path, onefile: bool) -> Path:
    build_dir = PROJECT_ROOT / "build"
    spec_file = PROJECT_ROOT / f"{app_name}.spec"
    _ensure_clean([build_dir, dist_dir, spec_file])

    pyinstaller_cmd = [
        str(python_path),
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--console",
        "--name",
        app_name,
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(build_dir),
        "--paths",
        str(SRC_DIR),
        "--collect-all",
        "azure.identity",
        "--collect-all",
        "azure.core",
        "--collect-all",
        "msal",
        "--hidden-import",
        "colorama",
        "--add-data",
        _normalize_path(CONFIG_FILE),
    ]

    if onefile:
        pyinstaller_cmd.append("--onefile")
    else:
        pyinstaller_cmd.append("--onedir")

    pyinstaller_cmd.append(str(CLI_ENTRY))

    _run(pyinstaller_cmd)

    product = dist_dir / app_name
    if onefile:
        candidate_paths = []
        if sys.platform == "win32":
            candidate_paths.append(product.with_suffix(".exe"))
        candidate_paths.extend([product, product.with_suffix("")])

        for candidate in candidate_paths:
            if candidate.exists():
                product = candidate
                break
        else:  # pragma: no cover - defensive guardrail
            raise BuildError("PyInstaller onefile output was not produced")
    elif not product.exists():
        raise BuildError(f"PyInstaller output not found at {product}")

    return product


def _stage_bundle(product_path: Path, *, app_name: str, platform_tag: str, artifacts_dir: Path, onefile: bool) -> Path:
    staging_root = artifacts_dir / f"{app_name}-{platform_tag}"
    _ensure_clean([staging_root])
    bin_dir = staging_root / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    if onefile:
        extension = product_path.suffix
        target_name = app_name + (extension if extension else "")
        target_binary = bin_dir / target_name
        shutil.copy2(product_path, target_binary)
        if not extension:
            target_binary.chmod(0o755)
    else:
        # When using --onedir, embed the whole folder
        final_dir = bin_dir / app_name
        shutil.copytree(product_path, final_dir)

    return staging_root


def _create_tarball(staging_root: Path) -> Path:
    archive_name = staging_root.name + ".tar.gz"
    archive_path = staging_root.parent / archive_name
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


def build_bundle(*, extras: Optional[str], platform_tag: str, onefile: bool) -> None:
    version = _detect_version()
    app_name = "mycli"
    artifacts_dir = PROJECT_ROOT / "dist" / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    print(f"Building {app_name} version {version} for {platform_tag}")

    with tempfile.TemporaryDirectory(prefix="mycli-build-") as tmp_dir:
        venv_dir = Path(tmp_dir) / "build-env"
        python_path = _create_virtualenv(venv_dir)
        _install_project(python_path, extras)
        product_path = _invoke_pyinstaller(
            python_path, app_name=app_name, dist_dir=Path(tmp_dir) / "dist", onefile=onefile
        )

        staging_root = _stage_bundle(
            product_path,
            app_name=app_name,
            platform_tag=platform_tag,
            artifacts_dir=artifacts_dir,
            onefile=onefile,
        )

    archive_path = _create_tarball(staging_root)
    checksum_path = _emit_sha256(archive_path)

    print("\nBundle complete! Artifacts:")
    print(f"  - Bundle directory: {staging_root}")
    print(f"  - Tarball:          {archive_path}")
    print(f"  - SHA256:           {checksum_path}")
    print("\nNext steps:")
    print("  1. Codesign and notarize the tarball as required (macOS).")
    print("  2. Upload the tarball to the release channel (e.g. GitHub Releases).")
    print("  3. Update your Homebrew Cask with the new version and checksum.")


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a PyInstaller bundle for mycli")
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
    parser.add_argument(
        "--onedir",
        action="store_true",
        help="Produce a directory-style bundle instead of a single-file binary.",
    )

    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Iterable[str]] = None) -> None:
    args = parse_args(argv)
    extras = (args.extras or "").strip()
    extras = extras if extras else None

    try:
        build_bundle(extras=extras, platform_tag=args.platform_tag, onefile=not args.onedir)
    except BuildError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":  # pragma: no cover - manual invocation
    main()
