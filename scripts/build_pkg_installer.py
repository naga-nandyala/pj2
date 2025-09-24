#!/usr/bin/env python3
"""Build a macOS .pkg installer for the mycli application.

This script creates a native macOS installer package (.pkg) that installs the
mycli application directly to system locations (/usr/local). This eliminates
the complexity of symlink management that comes with .tar.gz Homebrew Casks.

The installer includes:
1. Complete Python virtual environment with all dependencies
2. Direct installation to /usr/local/bin and /usr/local/libexec
3. Native macOS installer experience
4. Proper integration with Homebrew Cask using 'pkg' directive

Example artifact layout:

```
artifacts/
  mycli-1.0.0-macos-arm64.pkg
  mycli-1.0.0-macos-arm64.pkg.sha256
```

Installation layout on target system:
```
/usr/local/
├── bin/
│   └── mycli                    # Direct executable (no symlinks)
└── libexec/
    └── mycli-venv/             # Complete Python environment
        ├── bin/python3
        └── lib/python3.12/site-packages/
```

Notes:
- Requires macOS with pkgbuild (part of Xcode Command Line Tools)
- Creates component package suitable for Homebrew Cask distribution
- Admin privileges required during installation (standard for system installs)
- Simpler launcher scripts (no symlink resolution needed)
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
PACKAGE_NAME = "mycli_app"
APP_NAME = "mycli"
VENV_NAME = f"{APP_NAME}-venv"
PKG_IDENTIFIER = "com.naga-nandyala.mycli"


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
    """Extract the package version, checking environment variable first, then __init__.py."""

    # Check if VERSION environment variable is set (from GitHub workflow)
    env_version = os.environ.get("VERSION")
    if env_version:
        print(f"Using version from environment: {env_version}")
        return env_version

    # Fall back to reading from __init__.py
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
                        print(f"Using version from __init__.py: {value.value}")
                        return value.value
    raise BuildError("Could not determine version from package (__version__ missing)")


def _virtualenv_python(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python3"


def _ensure_clean(paths: Iterable[Path]) -> None:
    for path in paths:
        if path.is_file() or path.is_symlink():
            print(f"Cleaning file {path}")
            path.unlink()
        elif path.is_dir():
            print(f"Cleaning directory {path}")
            shutil.rmtree(path)


def _create_virtualenv(venv_dir: Path) -> Path:
    """Create a virtual environment specifically for building the package."""

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


def _create_system_launcher(bin_dir: Path) -> None:
    """Create simplified launcher script for direct system installation."""

    launcher_script = f"""#!/usr/bin/env bash
set -euo pipefail

# Simple direct path - no symlink resolution needed
VENV_DIR="/usr/local/libexec/{VENV_NAME}"
PYTHON="${{VENV_DIR}}/bin/python3"

# Verify installation integrity
if [[ ! -x "${{PYTHON}}" ]]; then
    echo "Error: {APP_NAME} installation appears corrupted" >&2
    echo "Python executable not found at: ${{PYTHON}}" >&2
    echo "Try reinstalling with: brew reinstall --cask {APP_NAME}" >&2
    exit 1
fi

# Execute the application
exec "${{PYTHON}}" -m {PACKAGE_NAME} "$@"
"""

    _write_file(bin_dir / APP_NAME, launcher_script, executable=True)


def _create_package_root(venv_source: Path, *, platform_tag: str, staging_dir: Path) -> Path:
    """Stage files in the layout they should appear on the target system."""

    # Create the installation structure that mirrors /usr/local
    pkg_root = staging_dir / "pkg_root"
    bin_dir = pkg_root / "bin"
    libexec_dir = pkg_root / "libexec"
    venv_target = libexec_dir / VENV_NAME

    _ensure_clean([pkg_root])
    bin_dir.mkdir(parents=True, exist_ok=True)
    libexec_dir.mkdir(parents=True, exist_ok=True)

    # Copy the virtual environment
    print(f"Copying virtual environment to {venv_target}")
    shutil.copytree(venv_source, venv_target)
    _prune_bytecode(venv_target)

    # Create the launcher script
    print("Creating system launcher script")
    _create_system_launcher(bin_dir)

    return pkg_root


def _create_pkg_installer(pkg_root: Path, *, version: str, platform_tag: str, artifacts_dir: Path) -> Path:
    """Create macOS .pkg installer using pkgbuild."""

    pkg_filename = f"{APP_NAME}-{version}-{platform_tag}.pkg"
    pkg_path = artifacts_dir / pkg_filename
    _ensure_clean([pkg_path])

    # Check if pkgbuild is available
    try:
        _run(["which", "pkgbuild"], capture_output=True)
    except BuildError:
        raise BuildError("pkgbuild not found. Install Xcode Command Line Tools: xcode-select --install")

    # Create the package
    print(f"Creating .pkg installer: {pkg_path}")
    cmd = [
        "pkgbuild",
        "--root",
        str(pkg_root),
        "--identifier",
        PKG_IDENTIFIER,
        "--version",
        version,
        "--install-location",
        "/usr/local",
        str(pkg_path),
    ]
    _run(cmd)

    # Verify the package was created
    if not pkg_path.exists():
        raise BuildError(f"Package creation failed: {pkg_path} does not exist")

    print(f"Created package: {pkg_path} ({pkg_path.stat().st_size / (1024*1024):.1f} MB)")
    return pkg_path


def _emit_sha256(artifact_path: Path) -> Path:
    """Generate SHA256 checksum file."""
    digest = hashlib.sha256()
    with artifact_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    checksum_path = artifact_path.with_suffix(artifact_path.suffix + ".sha256")
    checksum_line = f"{digest.hexdigest()}  {artifact_path.name}\n"
    checksum_path.write_text(checksum_line, encoding="utf-8")
    print(f"SHA256: {checksum_line.strip()}")
    return checksum_path


def _create_distribution_xml(staging_dir: Path, *, version: str) -> Path:
    """Create distribution XML for advanced installer features (optional)."""

    distribution_xml = staging_dir / "distribution.xml"

    # Create distribution XML with welcome message and requirements
    root = ET.Element("installer-gui-script", minSpecVersion="2")

    # Title and welcome
    ET.SubElement(root, "title").text = f"MyCLI {version}"
    ET.SubElement(root, "welcome", file="welcome.html")

    # Requirements
    req_elem = ET.SubElement(root, "requirements")
    ET.SubElement(req_elem, "requirement", file="InstallationCheck", script="InstallationCheck()")

    # Choices outline (simple single choice)
    choices = ET.SubElement(root, "choices-outline")
    line = ET.SubElement(choices, "line", choice="default")
    ET.SubElement(line, "line", choice="com.naga-nandyala.mycli")

    # Choice definition
    choice_elem = ET.SubElement(root, "choice", id="default", title="MyCLI")
    ET.SubElement(choice_elem, "pkg-ref", id="com.naga-nandyala.mycli")

    # Package reference (will be updated by productbuild)
    ET.SubElement(root, "pkg-ref", id="com.naga-nandyala.mycli", version=version, onConclusion="none")

    # Write XML
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ", level=0)
    tree.write(distribution_xml, encoding="utf-8", xml_declaration=True)

    return distribution_xml


def build_pkg_installer(*, extras: Optional[str], platform_tag: str, use_distribution: bool = False) -> None:
    """Build a .pkg installer for macOS."""

    version = _detect_version()
    artifacts_dir = PROJECT_ROOT / "dist" / "pkg_artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    print(f"Building {APP_NAME} version {version} for {platform_tag} (.pkg installer)")

    with tempfile.TemporaryDirectory(prefix="mycli-pkg-build-") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)

        # Phase 1: Create virtual environment
        venv_dir = tmp_dir / "bundle-venv"
        python_path = _create_virtualenv(venv_dir)
        _install_project(python_path, extras)

        # Phase 2: Stage package root
        pkg_root = _create_package_root(venv_dir, platform_tag=platform_tag, staging_dir=tmp_dir)

        # Phase 3: Create .pkg installer
        if use_distribution:
            # Advanced installer with custom UI (future enhancement)
            distribution_xml = _create_distribution_xml(tmp_dir, version=version)
            print("Distribution XML created (not yet implemented)")

        pkg_path = _create_pkg_installer(
            pkg_root, version=version, platform_tag=platform_tag, artifacts_dir=artifacts_dir
        )

    # Phase 4: Generate checksum
    checksum_path = _emit_sha256(pkg_path)

    print("\n" + "=" * 60)
    print("PKG INSTALLER BUILD COMPLETE!")
    print("=" * 60)
    print(f"  Package:     {pkg_path}")
    print(f"  SHA256:      {checksum_path}")
    print(f"  Platform:    {platform_tag}")
    print(f"  Version:     {version}")
    print(f"  Identifier:  {PKG_IDENTIFIER}")
    print()
    print("Installation Details:")
    print(f"  Target:      /usr/local/")
    print(f"  Executable:  /usr/local/bin/{APP_NAME}")
    print(f"  Runtime:     /usr/local/libexec/{VENV_NAME}/")
    print()
    print("Next steps:")
    print("  1. Test locally: sudo installer -pkg <pkg-file> -target /")
    print("  2. Upload to GitHub releases")
    print("  3. Update Homebrew Cask to use .pkg")
    print("  4. Consider code signing for distribution outside Homebrew")


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a .pkg installer for mycli")
    parser.add_argument(
        "--extras",
        default="broker",
        help=(
            "Comma-separated optional dependency groups to install before packaging. "
            "Pass an empty string to skip extras."
        ),
    )
    parser.add_argument(
        "--platform-tag",
        default="macos-universal2",
        help="Suffix added to artifact names to describe the target platform.",
    )
    parser.add_argument(
        "--use-distribution",
        action="store_true",
        help="Create distribution XML for advanced installer features (experimental)",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Iterable[str]] = None) -> None:
    """Main entry point."""
    args = parse_args(argv)
    extras = (args.extras or "").strip() or None

    try:
        build_pkg_installer(extras=extras, platform_tag=args.platform_tag, use_distribution=args.use_distribution)
    except BuildError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":  # pragma: no cover - manual invocation
    main()
