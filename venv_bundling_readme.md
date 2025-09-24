# Virtual Environment Bundling System

This document provides comprehensive documentation for the virtual environment bundling approach used to distribute the `mycli` application via Homebrew Cask.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Build Process](#build-process)
- [GitHub Actions Workflows](#github-actions-workflows)
- [Entry Point Strategy](#entry-point-strategy)
- [Distribution Strategy](#distribution-strategy)
- [Technical Implementation](#technical-implementation)
- [Usage Guide](#usage-guide)
- [Troubleshooting](#troubleshooting)

## Overview

### Problem Statement

The `mycli` application has complex dependencies including:
- Azure authentication libraries (`azure-identity`, `azure-core`)
- MSAL authentication with broker support (`msal[broker]`)
- Native binaries like `pymsalruntime` (Windows Authentication Broker)

**Challenge**: Homebrew Formula cannot handle dependencies with native binaries that lack source code. Therefore, we must use **Homebrew Cask** with pre-built bundles.

### Solution: Relocatable Virtual Environment Bundling

We create self-contained bundles that include:
- Complete Python runtime (virtual environment)
- All Python dependencies installed
- Platform-specific launcher scripts
- Homebrew Cask-compatible directory structure

## Architecture

### Bundle Structure

```
mycli-{version}-{platform}/
├── bin/
│   ├── mycli           # POSIX launcher script (executable)
│   └── mycli.bat       # Windows launcher script
└── libexec/
    └── mycli-venv/     # Complete Python virtual environment
        ├── bin/        # Python executables (python3, pip, etc.)
        ├── lib/        # Site-packages with all dependencies
        ├── include/    # Python headers
        ├── share/      # Shared data
        └── pyvenv.cfg  # Virtual environment configuration
```

### Key Design Principles

1. **Relocatable**: Bundle can be moved to any location
2. **Self-contained**: No external Python dependencies required
3. **Cross-platform**: Works on macOS ARM64 and x86_64
4. **Homebrew Compatible**: Follows Cask conventions (`bin/` + `libexec/`)

## Build Process

### Core Script: `scripts/build_venv_bundle.py`

The build process consists of several phases:

#### Phase 1: Environment Setup
```python
def _create_virtualenv(venv_dir: Path) -> Path:
    """Create a virtual environment specifically for building the bundle."""
```
- Creates temporary virtual environment with `--copies` flag
- Upgrades pip, setuptools, wheel
- Returns path to Python executable

#### Phase 2: Project Installation
```python
def _install_project(python_path: Path, extras: Optional[str]) -> None:
```
- Installs current project with optional extras (e.g., `broker`)
- Uses editable install from project root
- Handles dependency resolution

#### Phase 3: Bundle Staging
```python
def _stage_bundle(venv_source: Path, *, platform_tag: str, artifacts_dir: Path) -> Path:
```
- Creates Homebrew Cask-compatible structure
- Copies virtual environment to `libexec/mycli-venv/`
- Generates launcher scripts in `bin/`
- Removes bytecode files for size optimization

#### Phase 4: Archive Creation
```python
def _create_tarball(staging_root: Path) -> Path:
def _emit_sha256(artifact_path: Path) -> Path:
```
- Creates `.tar.gz` archive
- Generates SHA256 checksum file
- Prepares artifacts for distribution

### Version Detection

Uses AST parsing to extract version without importing the package:

```python
def _detect_version() -> str:
    """Extract the package version without importing optional dependencies."""
    init_path = SRC_DIR / PACKAGE_NAME / "__init__.py"
    # Parse AST to find __version__ = "x.y.z"
```

### Launcher Script Generation

#### POSIX Launcher (`bin/mycli`)
```bash
#!/usr/bin/env bash
set -euo pipefail
# Resolve symlinks to get the actual script location
SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_PATH}")" && pwd)"
APP_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${APP_ROOT}/libexec/mycli-venv"

# Try different python executable names
if [[ -f "${VENV_DIR}/bin/python3" ]] && [[ -x "${VENV_DIR}/bin/python3" ]]; then
    PYTHON="${VENV_DIR}/bin/python3"
elif [[ -f "${VENV_DIR}/bin/python" ]] && [[ -x "${VENV_DIR}/bin/python" ]]; then
    PYTHON="${VENV_DIR}/bin/python"
# ... more fallbacks
fi

exec "${PYTHON}" -m mycli_app "$@"
```

#### Windows Launcher (`bin/mycli.bat`)
```batch
@echo off
setlocal
set SCRIPT_DIR=%~dp0
set APP_ROOT=%SCRIPT_DIR%..\\
set VENV=%APP_ROOT%libexec\\mycli-venv
set PYTHON=%VENV%\\Scripts\\python.exe
if exist "%PYTHON%" (
    "%PYTHON%" -m mycli_app %*
    goto :eof
)
# ... fallbacks for different Python locations
```

## GitHub Actions Workflows

### 1. Release Build Workflow: `venv-bundle-macos-arm.yml`

**Trigger**: Manual dispatch with version input
**Purpose**: Build and release platform-specific bundles

#### Matrix Strategy
```yaml
strategy:
  matrix:
    include:
      - runner: macos-14      # Apple Silicon
        arch: arm64
        platform_tag: macos-arm64
      - runner: macos-13      # Intel
        arch: x86_64  
        platform_tag: macos-x86_64
```

#### Key Steps
1. **Build**: `python scripts/build_venv_bundle.py --platform-tag ${{ matrix.platform_tag }}`
2. **Rename**: Add version to artifact names
3. **Upload**: Store as GitHub Actions artifacts
4. **Release**: Create GitHub release with all platform bundles

#### Artifacts Produced
- `mycli-{version}-macos-arm64.tar.gz`
- `mycli-{version}-macos-arm64.tar.gz.sha256`
- `mycli-{version}-macos-x86_64.tar.gz`
- `mycli-{version}-macos-x86_64.tar.gz.sha256`

### 2. Homebrew Tap Update: `update-homebrew-cask.yml`

**Trigger**: Release published or manual dispatch
**Purpose**: Update Homebrew tap with new release

#### Process Flow
1. **Version Resolution**: Determine target version (from release or input)
2. **Download Artifacts**: Get release tarballs from GitHub
3. **Checksum Calculation**: Compute SHA256 for each platform
4. **Cask Generation**: Update Ruby cask file with new URLs and checksums
5. **Cross-repo Push**: Commit to `homebrew-mycli-app` repository

#### Cask Template
```ruby
cask "mycli-app-venv-pj2" do
  version "__VERSION__"

  on_arm do
    sha256 "__ARM64_SHA__"
    url "https://github.com/naga-nandyala/pj2/releases/download/v#{version}/__ARM64_FILE__"
    binary "bin/mycli", target: "mycli"
  end

  on_intel do
    sha256 "__X86_SHA__"
    url "https://github.com/naga-nandyala/pj2/releases/download/v#{version}/__X86_FILE__"
    binary "bin/mycli", target: "mycli"
  end
  
  # ... metadata and caveats
end
```

### 3. Installation Test: `venv-test-homebrew-cask.yml`

**Trigger**: Release published or manual dispatch
**Purpose**: Validate Homebrew Cask installation

#### Test Matrix
- `macos-latest` (ARM64)
- `macos-13` (x86_64)

#### Test Steps
1. **Tap Installation**: `brew tap naga-nandyala/mycli-app`
2. **Cask Install**: `brew install --cask mycli-app-venv-pj2`
3. **Structure Inspection**: Verify file layout and permissions
4. **Functional Testing**: Run `mycli --version`, `mycli status`
5. **Cleanup**: Remove installation

## Entry Point Strategy

### Module-Based Execution

**Primary Method**: `python -m mycli_app`
- Uses `src/mycli_app/__main__.py` as entry point
- More reliable for bundled environments
- Avoids script path resolution issues

### Project Configuration

#### `pyproject.toml` Entry Points
```toml
[project.scripts]
mycli = "mycli_app.cli:main"
```

#### Module Structure
```
src/mycli_app/
├── __init__.py      # Contains __version__ = "1.0.0"
├── __main__.py      # Entry point: from mycli_app.cli import main; main()
├── cli.py           # Main CLI implementation with Click commands
└── config.yaml      # Application configuration
```

### Why Module Execution?

1. **Path Independence**: Works regardless of installation location
2. **Import Reliability**: Python handles module resolution
3. **Bundle Compatibility**: No dependency on script file locations
4. **Error Handling**: Better error messages for import issues

## Distribution Strategy

### Homebrew Cask Rationale

**Why not Homebrew Formula?**
- Dependencies include native binaries without source code
- `pymsalruntime` is a compiled authentication broker
- Formula requires building from source

**Why Cask?**
- Designed for pre-built applications
- Handles binary distributions naturally
- Supports architecture-specific downloads
- Provides user-friendly installation experience

### Architecture Support

**Universal2 Approach**: Separate builds for ARM64 and x86_64
- More reliable than universal binaries
- Smaller download sizes
- Platform-specific optimization
- Easier debugging and testing

### Repository Structure

**Main Repository** (`naga-nandyala/pj2`):
- Source code
- Build scripts  
- GitHub Actions workflows
- Release artifacts

**Homebrew Tap** (`naga-nandyala/homebrew-mycli-app`):
- Ruby cask definitions
- Updated automatically by workflows
- Consumed by `brew tap` users

## Technical Implementation

### Cross-Platform Considerations

#### Path Handling
```python
def _virtualenv_python(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python3"
```

#### Launcher Script Robustness
- **Symlink Resolution**: Handles complex installation paths
- **Multiple Python Names**: Tries `python3`, `python`, `python3.12`
- **Error Handling**: Clear messages when Python not found
- **Path Escaping**: Proper handling of spaces in paths

### Build Optimization

#### Size Reduction
```python
def _prune_bytecode(root: Path) -> None:
    """Remove __pycache__ directories and .pyc files"""
    for path in root.rglob("__pycache__"):
        shutil.rmtree(path, ignore_errors=True)
    for suffix in (".pyc", ".pyo"):
        for file in root.rglob(f"*{suffix}"):
            file.unlink()
```

#### Virtual Environment Creation
- Uses `--copies` flag for relocatable binaries
- Upgrades essential tools (pip, setuptools, wheel)
- Installs with specific extras configuration

### Error Handling

#### Build Failures
```python
class BuildError(RuntimeError):
    """Raised when the packaging pipeline fails."""

def _run(cmd: Iterable[str], **kwargs) -> subprocess.CompletedProcess:
    """Execute subprocess with detailed error reporting"""
    # Captures stdout/stderr and provides context
```

#### Runtime Failures
- Launcher scripts provide diagnostics
- Multiple fallback Python executable locations
- Clear error messages for missing components

## Usage Guide

### Local Development Build

```bash
# Build for current platform
python scripts/build_venv_bundle.py --platform-tag macos-arm64

# Build with specific extras
python scripts/build_venv_bundle.py --extras broker --platform-tag macos-arm64

# Build without extras
python scripts/build_venv_bundle.py --extras "" --platform-tag macos-arm64
```

### Manual Release Process

1. **Update Version**: Modify `src/mycli_app/__init__.py`
2. **Trigger Workflow**: Go to Actions → "venv bundle - release"
3. **Set Version**: Input version number (e.g., "1.2.0")
4. **Wait for Build**: Monitor matrix builds for both platforms
5. **Verify Release**: Check GitHub releases page
6. **Test Installation**: Homebrew tap updates automatically

### Local Testing

```bash
# Extract and test bundle locally
cd dist/artifacts
tar -xzf mycli-1.0.0-macos-arm64.tar.gz
cd mycli-1.0.0-macos-arm64

# Test launcher
./bin/mycli --version
./bin/mycli status

# Test Python module execution
./libexec/mycli-venv/bin/python3 -m mycli_app --version
```

### Homebrew Installation (End Users)

```bash
# Add tap
brew tap naga-nandyala/mycli-app

# Install via cask
brew install --cask mycli-app-venv-pj2

# Use application
mycli --version
mycli login
mycli status
```

## Troubleshooting

### Common Build Issues

#### **Virtual Environment Creation Failed**
```
ERROR: Command failed with exit code 1: python -m venv --copies /tmp/bundle-venv
```
**Solution**: Ensure Python 3.8+ is available and `venv` module is installed

#### **Version Detection Failed**  
```
ERROR: Could not determine version from package (__version__ missing)
```
**Solution**: Verify `__version__ = "x.y.z"` exists in `src/mycli_app/__init__.py`

#### **Dependency Installation Failed**
```
ERROR: Could not install packages due to an EnvironmentError
```
**Solution**: Check internet connectivity and PyPI access

### Runtime Issues

#### **Python Executable Not Found**
```
Error: Could not locate executable python interpreter in libexec/mycli-venv
```
**Diagnosis Steps**:
1. Check if `libexec/mycli-venv/bin/` exists
2. List contents: `ls -la libexec/mycli-venv/bin/`
3. Verify permissions: `ls -l bin/mycli`

#### **Module Import Errors**
```
ModuleNotFoundError: No module named 'mycli_app'
```
**Solution**: Ensure bundle was built with project properly installed

#### **Authentication Issues**
```
azure.core.exceptions.ClientAuthenticationError
```
**Solution**: Check if `broker` extras were included in build:
```bash
python scripts/build_venv_bundle.py --extras broker
```

### GitHub Actions Issues

#### **Matrix Build Failures**
- Check runner availability (macOS runners can be limited)
- Verify Python setup step succeeded
- Check for dependency resolution conflicts

#### **Homebrew Tap Update Failed**
- Verify `HOMEBREW_TAP_TOKEN` secret is set
- Check if tap repository exists and is accessible
- Ensure artifact download succeeded

#### **Release Creation Failed**
- Verify `GITHUB_TOKEN` has appropriate permissions
- Check if tag already exists
- Ensure all matrix jobs completed successfully

### Performance Considerations

#### **Bundle Size**
- Typical bundle size: 50-100MB (includes full Python + dependencies)
- Size comparison: Larger than zipapp, smaller than some PyInstaller builds
- Optimization: `_prune_bytecode()` removes ~10% size

#### **Build Time**
- Local build: 2-5 minutes (depends on dependency complexity)
- GitHub Actions: 5-10 minutes per platform
- Bottleneck: Dependency installation from PyPI

#### **Download Time**
- ARM64 bundle: ~50-80MB
- x86_64 bundle: ~50-80MB  
- Homebrew cask downloads only relevant architecture

### Monitoring and Maintenance

#### **Regular Maintenance Tasks**
1. **Dependency Updates**: Monitor for security updates in Azure/MSAL libraries
2. **Python Version**: Test with new Python releases
3. **macOS Compatibility**: Test on new macOS versions
4. **Homebrew Changes**: Monitor Homebrew cask specification changes

#### **Health Checks**
- **Build Success Rate**: Monitor GitHub Actions success/failure rates
- **Installation Testing**: Automated tests catch regressions
- **User Feedback**: Monitor issues in Homebrew tap repository

This documentation provides a complete understanding of the virtual environment bundling system, enabling effective maintenance, debugging, and enhancement of the distribution mechanism.