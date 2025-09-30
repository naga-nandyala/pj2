#!/usr/bin/env python3
"""Build a macOS .pkg installer for the mycli application.

This script creates a native macOS installer package (.pkg) that installs the
mycli application directly to system locations (/usr/local). This eliminates
the complexity of symlink management that comes with .tar.gz Homebrew Casks.

The installer includes:
1. Complete Python virtual environment with all dependencies
2. Direct installation to /usr/local/bin and /usr/local/microsoft
3. Native macOS installer experience
4. Proper integration with Homebrew Cask using 'pkg' directive
5. Optional productbuild support for enhanced installers

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
└── microsoft/
    └── mycli/                   # Complete Python environment
        ├── bin/python3
        └── lib/python3.12/site-packages/
```

Notes:
- Requires macOS with pkgbuild (part of Xcode Command Line Tools)
- Creates component package suitable for Homebrew Cask distribution
- Admin privileges required during installation (standard for system installs)
- Simpler launcher scripts (no symlink resolution needed)
- Optional productbuild for enhanced installer UI
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
APP_VERSION = "0.2.1"
INSTALL_PREFIX = "microsoft"  # PowerShell-style: /usr/local/microsoft/
INSTALL_DIR = f"{INSTALL_PREFIX}/{APP_NAME}"  # Results in: microsoft/mycli (no version suffix for simplicity)
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
VENV_DIR="/usr/local/{INSTALL_DIR}"
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
    install_prefix_dir = pkg_root / INSTALL_PREFIX
    venv_target = install_prefix_dir / APP_NAME

    _ensure_clean([pkg_root])
    bin_dir.mkdir(parents=True, exist_ok=True)
    install_prefix_dir.mkdir(parents=True, exist_ok=True)

    # Copy the virtual environment
    print(f"Copying virtual environment to {venv_target}")
    shutil.copytree(venv_source, venv_target)
    _prune_bytecode(venv_target)

    # Create the launcher script
    print("Creating system launcher script")
    _create_system_launcher(bin_dir)

    return pkg_root


def _create_pkg_installer(
    pkg_root: Path,
    *,
    version: str,
    platform_tag: str,
    artifacts_dir: Path,
    staging_dir: Path,
) -> Path:
    """Create macOS .pkg installer using pkgbuild + productbuild for enhanced installer."""

    pkg_filename = f"{APP_NAME}-{version}-{platform_tag}.pkg"
    final_pkg_path = artifacts_dir / pkg_filename
    _ensure_clean([final_pkg_path])

    # Check if pkgbuild is available
    try:
        _run(["which", "pkgbuild"], capture_output=True)
    except BuildError:
        raise BuildError("pkgbuild not found. Install Xcode Command Line Tools: xcode-select --install")

    # Check if productbuild is available for enhanced installer
    try:
        _run(["which", "productbuild"], capture_output=True)
    except BuildError:
        raise BuildError("productbuild not found. Install Xcode Command Line Tools: xcode-select --install")

    # Always use two-step process: component + distribution
    # Always use two-step process: component + distribution
    # Create component package first
    component_pkg_name = f"{APP_NAME}-component-{version}-{platform_tag}.pkg"
    component_pkg_path = staging_dir / component_pkg_name

    print(f"Creating component package: {component_pkg_path}")
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
        str(component_pkg_path),
    ]
    _run(cmd)

    # Verify component package was created
    if not component_pkg_path.exists():
        raise BuildError(f"Component package creation failed: {component_pkg_path} does not exist")

    # Check component package size for debugging
    component_size_mb = component_pkg_path.stat().st_size / (1024 * 1024)
    print(f"Component package size: {component_size_mb:.1f} MB")
    if component_size_mb < 1.0:
        print(f"⚠️  WARNING: Component package is unusually small ({component_size_mb:.1f} MB)")

    # Create distribution XML BEFORE productbuild
    print("Creating distribution XML for productbuild...")
    _create_distribution_xml(staging_dir, version=version, platform_tag=platform_tag)

    # Create distribution package using productbuild
    print(f"Creating distribution package: {final_pkg_path}")
    distribution_xml_path = staging_dir / "distribution.xml"

    cmd = [
        "productbuild",
        "--distribution",
        str(distribution_xml_path),
        "--package-path",
        str(staging_dir),
        str(final_pkg_path),
    ]
    _run(cmd)

    print(f"Created distribution package: {final_pkg_path} ({final_pkg_path.stat().st_size / (1024*1024):.1f} MB)")

    # Verify the final package was created
    if not final_pkg_path.exists():
        raise BuildError(f"Package creation failed: {final_pkg_path} does not exist")

    return final_pkg_path


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


def _create_distribution_xml(staging_dir: Path, *, version: str, platform_tag: str) -> Path:
    """Create distribution XML for productbuild with proper package references."""

    distribution_xml = staging_dir / "distribution.xml"
    component_pkg_name = f"{APP_NAME}-component-{version}-{platform_tag}.pkg"

    # Create distribution XML with proper references
    root = ET.Element("installer-gui-script", minSpecVersion="2")

    # Title
    ET.SubElement(root, "title").text = f"MyCLI {version}"

    # Package reference - this MUST come before choices
    pkg_ref = ET.SubElement(root, "pkg-ref", id="com.naga-nandyala.mycli")
    pkg_ref.text = component_pkg_name

    # Choices outline
    choices = ET.SubElement(root, "choices-outline")
    ET.SubElement(choices, "line", choice="mycli-choice")

    # Choice definition
    choice_elem = ET.SubElement(root, "choice", id="mycli-choice", title="MyCLI")
    choice_elem.set("description", f"Install MyCLI {version} command-line application")
    choice_elem.set("start_selected", "true")
    ET.SubElement(choice_elem, "pkg-ref", id="com.naga-nandyala.mycli")

    # Write XML with proper formatting
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ", level=0)
    tree.write(distribution_xml, encoding="utf-8", xml_declaration=True)

    print(f"Created distribution XML: {distribution_xml}")

    # Debug: Show XML content and verify component package reference
    print("Distribution XML content:")
    with open(distribution_xml, "r") as f:
        print(f.read())

    # Verify component package exists in staging directory
    expected_component = staging_dir / component_pkg_name
    if expected_component.exists():
        print(
            f"✅ Component package found: {expected_component} ({expected_component.stat().st_size / (1024*1024):.1f} MB)"
        )
    else:
        print(f"❌ Component package missing: {expected_component}")
        print(f"Available files in staging: {list(staging_dir.glob('*.pkg'))}")

    return distribution_xml


def build_pkg_installer(*, extras: Optional[str], platform_tag: str) -> None:
    """Build a .pkg installer for macOS using pkgbuild + productbuild."""

    version = _detect_version()
    artifacts_dir = PROJECT_ROOT / "dist" / "pkg_artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    print(f"Building {APP_NAME} version {version} for {platform_tag} (.pkg installer)")

    with tempfile.TemporaryDirectory(prefix="mycli-pkg-build-") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)

        # Phase 1: Create virtual environment (KEEP ORIGINAL WORKING CODE)
        venv_dir = tmp_dir / "bundle-venv"
        python_path = _create_virtualenv(venv_dir)
        _install_project(python_path, extras)

        # Phase 2: Stage package root (KEEP ORIGINAL WORKING CODE)
        pkg_root = _create_package_root(venv_dir, platform_tag=platform_tag, staging_dir=tmp_dir)

        # Phase 3: Create .pkg installer
        pkg_path = _create_pkg_installer(
            pkg_root,
            version=version,
            platform_tag=platform_tag,
            artifacts_dir=artifacts_dir,
            staging_dir=tmp_dir,
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
    print("  Build Method: productbuild (distribution)")
    print()
    print("Installation Details:")
    print("  Target:      /usr/local/")
    print(f"  Executable:  /usr/local/bin/{APP_NAME}")
    print(f"  Runtime:     /usr/local/{INSTALL_DIR}/")
    print()
    print("Next steps:")
    print("  1. Test locally: sudo installer -pkg <pkg-file> -target /")
    print("  2. Upload to GitHub releases")
    print("  3. Update Homebrew Cask to use .pkg")
    print("  4. Custom installer UI available via distribution package")
    print("  5. Consider code signing for distribution outside Homebrew")


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
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Iterable[str]] = None) -> None:
    """Main entry point."""
    args = parse_args(argv)
    extras = (args.extras or "").strip() or None

    try:
        build_pkg_installer(extras=extras, platform_tag=args.platform_tag)
    except BuildError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":  # pragma: no cover - manual invocation
    main()
