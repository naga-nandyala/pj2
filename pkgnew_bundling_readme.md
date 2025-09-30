# PKG Direct Installation System

This document provides comprehensive documentation for the macOS PKG direct installer approach used to distribute the `mycli` application with PowerShell-style system integration.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Build Process](#build-process)
- [GitHub Actions Workflows](#github-actions-workflows)
- [Installation Methods](#installation-methods)
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

**Challenge**: Traditional distribution methods cannot handle dependencies with native binaries that lack source code. We need a robust system-level installation approach.

### Solution: PowerShell-Style PKG Direct Installation

We create native macOS PKG installers that:
- Install using PowerShell-inspired directory conventions
- Provide direct system installation via `sudo installer`
- Follow Microsoft's macOS application distribution patterns
- Support both Homebrew and direct installation methods

## Architecture

### Installation Structure (PowerShell-Style)

```
/usr/local/bin/
└── mycli                           # System-wide launcher script (executable)

/usr/local/microsoft/
└── mycli/                          # PowerShell-style application directory
    ├── bin/                        # Python executables (python3, pip, etc.)
    ├── lib/                        # Site-packages with all dependencies
    ├── include/                    # Python headers
    ├── share/                      # Shared data
    └── pyvenv.cfg                  # Virtual environment configuration
```

### Key Design Principles

1. **PowerShell Integration**: Mirrors Microsoft PowerShell's `/usr/local/microsoft/` path structure
2. **System Integration**: Installs to standard macOS system paths with Microsoft conventions
3. **Self-contained**: Complete Python runtime with all dependencies
4. **Cross-platform**: Supports both ARM64 and x86_64 architectures
5. **Dual Installation**: Works with both Homebrew and direct PKG installation
6. **Native Performance**: Architecture-optimized for each platform

## Build Process

### Core Script: `scripts/build_venv_bundle.py`

The build process creates PowerShell-style PKG installers:

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

#### Phase 3: PowerShell-Style PKG Staging
```python
def _stage_pkg_contents(venv_source: Path, *, staging_root: Path) -> None:
```
- Creates PowerShell-inspired directory structure
- Copies virtual environment to `usr/local/microsoft/mycli/`
- Generates launcher script in `usr/local/bin/`
- Sets proper file permissions and ownership

#### Phase 4: PKG Creation

```python
def _create_pkg_installer(pkg_root: Path, *, version: str, platform_tag: str, artifacts_dir: Path, staging_dir: Path) -> Path:
```

**PKG Build Process:**
- Creates component package with `pkgbuild`
- Generates proper package metadata and identifiers
- Uses PowerShell-style installation paths
- Creates signed installer (if certificates available)

#### Phase 5: Archive Creation
```python
def _emit_sha256(artifact_path: Path) -> Path:
```
- Generates SHA256 checksum file
- Prepares artifacts for distribution

### Version Detection

Enhanced version detection with environment variable override:

```python
def _detect_version() -> str:
    """Extract version from environment variable or package __init__.py"""
    # Check environment variable first (for CI/CD overrides)
    if version := os.environ.get("VERSION"):
        return version.strip()
    
    # Fallback to AST parsing of __init__.py
    init_path = SRC_DIR / PACKAGE_NAME / "__init__.py"
    # Parse AST to find __version__ = "x.y.z"
```

### PowerShell-Style Launcher Script Generation

#### System Launcher (`/usr/local/bin/mycli`)
```bash
#!/usr/bin/env bash
set -euo pipefail

# PowerShell-style direct path - follows Microsoft conventions
MICROSOFT_DIR="/usr/local/microsoft/mycli"
PYTHON="${MICROSOFT_DIR}/bin/python3"

# Verify installation integrity
if [[ ! -x "${PYTHON}" ]]; then
    echo "Error: mycli installation appears corrupted" >&2
    echo "Python executable not found at: ${PYTHON}" >&2
    echo "Microsoft-style installation directory: ${MICROSOFT_DIR}" >&2
    echo "Try reinstalling with direct PKG installation or Homebrew" >&2
    exit 1
fi

# Execute the application using PowerShell-style paths
exec "${PYTHON}" -m mycli_app "$@"
```

### PKG Package Structure

The PKG installer contains:

#### Component Package Metadata
```xml
<!-- Generated by pkgbuild -->
<pkg-info format-version="2" identifier="com.naga-nandyala.mycli" version="4.0.0" install-location="/" auth="root">
    <payload numberOfFiles="xxx" installKBytes="xxx"/>
    <bundle-version>
        <bundle id="com.naga-nandyala.mycli" CFBundleShortVersionString="4.0.0" path="./mycli-4.0.0-macos-arm64.pkg"/>
    </bundle-version>
</pkg-info>
```

#### Installation Scripts
- **Preinstall**: Cleanup previous installations
- **Postinstall**: Set proper permissions and PATH integration
- **Uninstall**: Remove all installed components

## GitHub Actions Workflows

### 1. PKG Build Workflow: `pkgnew-build-installer.yml`

**Trigger**: Manual dispatch with version input
**Purpose**: Build and release platform-specific PKG installers with PowerShell-style paths

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
1. **Version Override**: Set `VERSION` environment variable from workflow input
2. **Build**: `python scripts/build_venv_bundle.py --platform-tag ${{ matrix.platform_tag }}`
3. **Rename**: Add version to PKG filenames
4. **Upload**: Store as GitHub Actions artifacts
5. **Release**: Create GitHub release with all platform PKG files

#### Artifacts Produced
- `mycli-{version}-macos-arm64.pkg`
- `mycli-{version}-macos-arm64.pkg.sha256`
- `mycli-{version}-macos-x86_64.pkg`
- `mycli-{version}-macos-x86_64.pkg.sha256`

### 2. Homebrew Cask Update: `pkgnew-update-homebrew-cask.yml`

**Trigger**: Manual dispatch with version input
**Purpose**: Update Homebrew tap with new PKG release

#### Process Flow
1. **Version Input**: Use provided version number (e.g., "4.0.0")
2. **Download PKG Files**: Get release PKG installers from GitHub
3. **Checksum Calculation**: Compute SHA256 for each platform PKG
4. **Cask Generation**: Update Ruby cask file with new URLs and checksums
5. **Cross-repo Push**: Commit to `homebrew-mycli-app` repository

#### Cask Template
```ruby
cask "mycli-app-pkgnew-pj2" do
  version "__VERSION__"

  on_arm do
    sha256 "__ARM64_SHA__"
    url "https://github.com/naga-nandyala/pj2/releases/download/v#{version}/__ARM64_FILE__"
  end

  on_intel do
    sha256 "__X86_SHA__"
    url "https://github.com/naga-nandyala/pj2/releases/download/v#{version}/__X86_FILE__"
  end

  name "MyCLI App (PKG Installer)"
  desc "Azure-inspired CLI with native macOS installer"
  homepage "https://github.com/naga-nandyala/pj2"

  depends_on macos: ">= :catalina"

  on_arm do
    pkg "__ARM64_FILE__"
  end

  on_intel do
    pkg "__X86_FILE__"
  end

  uninstall pkgutil: "com.naga-nandyala.mycli"

  caveats <<~EOS
    MyCLI installs directly to system locations:
      • Executable: /usr/local/bin/mycli
      • Runtime: /usr/local/microsoft/mycli/

    No symlinks or complex path resolution required.

    Basic usage:
      mycli --version
      mycli login
      mycli status

    To uninstall manually:
      sudo rm -f /usr/local/bin/mycli
      sudo rm -rf /usr/local/microsoft/mycli

    For the venv bundle version instead:
      brew install --cask naga-nandyala/mycli-app/mycli-app-venv-pj2
  EOS
end
```

### 3. Direct Installation Test: `pkgnew-test-sudoinstaller.yml`

**Trigger**: Manual dispatch with version input
**Purpose**: Validate direct PKG installation via `sudo installer`

#### Test Matrix
- `macos-latest` (ARM64)
- `macos-13` (x86_64)

#### Comprehensive Test Steps

1. **Environment Info**: System details and architecture verification
2. **Cleanup**: Remove any existing installations
3. **PKG Download**: Download architecture-specific PKG from GitHub releases
4. **Direct Install**: `sudo installer -pkg mycli-{version}-macos-{arch}.pkg -target /`
5. **Structure Verification**: Check PowerShell-style installation paths
6. **Functional Testing**: Version check, help output, status command
7. **Launcher Script Testing**: Verify script content and permissions
8. **Installation Integrity**: Module imports and dependency checks
9. **Working Directory Independence**: Test from multiple locations
10. **Performance Check**: Startup time and installation size
11. **Authentication Test**: Non-blocking broker authentication test
12. **Cleanup Test**: Verify complete manual uninstallation

#### Key Verification Points
```bash
# Executable location
ls -la /usr/local/bin/mycli

# PowerShell-style runtime environment
du -sh /usr/local/microsoft/mycli

# PATH availability
which mycli

# Package manager records
pkgutil --pkgs | grep -i mycli

# Functional testing
mycli --version
mycli status
```

### 4. Homebrew Installation Test: `pkgnew-test-homebrew-cask.yml`

**Trigger**: Manual dispatch with version input
**Purpose**: Validate Homebrew Cask PKG installation

#### Test Steps
1. **Environment Setup**: System verification
2. **Tap Addition**: `brew tap naga-nandyala/mycli-app`
3. **Cask Install**: `brew install --cask mycli-app-pkgnew-pj2`
4. **Verification**: Same verification as direct installation
5. **Homebrew Uninstall**: `brew uninstall --cask mycli-app-pkgnew-pj2`

## Installation Methods

### Method 1: Direct PKG Installation

**Advantages:**
- No dependency on Homebrew
- Works on any macOS system
- Fastest installation method
- Direct control over installation process

**Process:**
```bash
# Download PKG file (manual or automated)
curl -L -o mycli-4.0.0-macos-arm64.pkg \
  "https://github.com/naga-nandyala/pj2/releases/download/v4.0.0/mycli-4.0.0-macos-arm64.pkg"

# Install directly with sudo
sudo installer -pkg mycli-4.0.0-macos-arm64.pkg -target /

# Verify installation
mycli --version

# Manual uninstall if needed
sudo rm -f /usr/local/bin/mycli
sudo rm -rf /usr/local/microsoft/mycli
```

**Use Cases:**
- System administrators
- Automated deployment scripts
- Users without Homebrew
- Corporate environments with strict package management

### Method 2: Homebrew Cask Installation

**Advantages:**
- Integrated with Homebrew ecosystem
- Automatic dependency management
- Easy update mechanism
- Familiar interface for Homebrew users

**Process:**
```bash
# Add the tap
brew tap naga-nandyala/mycli-app

# Install via Homebrew Cask
brew install --cask mycli-app-pkgnew-pj2

# Verify installation
mycli --version

# Update when new version available
brew upgrade --cask mycli-app-pkgnew-pj2

# Uninstall cleanly
brew uninstall --cask mycli-app-pkgnew-pj2
```

**Use Cases:**
- Individual developers
- Homebrew-centric workflows
- Users wanting automatic updates
- Development environments

### Installation Method Comparison

| Feature | Direct PKG | Homebrew Cask |
|---------|------------|---------------|
| **Installation Speed** | ⚡ Fastest | 🔄 Moderate |
| **Dependencies** | ✅ None | 📦 Requires Homebrew |
| **Update Management** | 🔧 Manual | 🔄 Automatic |
| **Uninstall** | 🔧 Manual | 🗑️ Automated |
| **System Integration** | ✅ Direct | ✅ Via Homebrew |
| **Corporate Use** | ✅ Ideal | ⚠️ Policy Dependent |
| **Developer Use** | ✅ Good | ✅ Preferred |

## Entry Point Strategy

### Module-Based Execution

**Primary Method**: `python -m mycli_app`
- Uses `src/mycli_app/__main__.py` as entry point
- More reliable for system installations
- Avoids complex script path resolution

### Project Configuration

#### `pyproject.toml` Entry Points
```toml
[project.scripts]
mycli = "mycli_app.cli:main"
```

#### Module Structure
```
src/mycli_app/
├── __init__.py      # Contains __version__ = "4.0.0"  
├── __main__.py      # Entry point: from mycli_app.cli import main; main()
├── cli.py           # Main CLI implementation with Click commands
└── config.yaml      # Application configuration
```

### Why Module Execution?

1. **System Integration**: Works perfectly with PowerShell-style installations
2. **Path Reliability**: No dependency on symlink resolution
3. **Error Handling**: Clear diagnostics for missing components
4. **Consistency**: Same execution method across all platforms

## Distribution Strategy

### PKG Installer Advantages

**Why PKG instead of simple bundles?**
- **Native macOS Integration**: Uses standard system installation patterns
- **PowerShell Compatibility**: Follows Microsoft's macOS conventions
- **System-wide Availability**: Installs to `/usr/local/bin` for all users
- **Proper Uninstallation**: PKG utilities track installed files
- **Security**: Signed packages (when certificates available)
- **User Experience**: Familiar installation process for macOS users

**Why PowerShell-Style Paths?**
- **Microsoft Consistency**: Aligns with PowerShell Core installations
- **Clear Ownership**: `/usr/local/microsoft/` clearly indicates Microsoft-style apps
- **Conflict Avoidance**: Separate from other application directories
- **Professional Appearance**: Enterprise-grade directory structure

### Architecture Support

**Platform-Specific PKG Files**: Separate installers for ARM64 and x86_64
- **Native Performance**: Architecture-optimized Python runtime
- **Smaller Downloads**: Users only download relevant architecture
- **Better Compatibility**: Avoids universal binary complexity
- **Easier Testing**: Platform-specific validation

### Repository Structure

**Main Repository** (`naga-nandyala/pj2`):
- Source code
- Build scripts (`scripts/build_venv_bundle.py`)
- GitHub Actions workflows
- Release artifacts (PKG files)

**Homebrew Tap** (`naga-nandyala/homebrew-mycli-app`):
- Ruby cask definitions (`mycli-app-pkgnew-pj2.rb`)
- Updated automatically by workflows
- Consumed by `brew tap` users

## Technical Implementation

### PKG Build Process

#### Virtual Environment Preparation
```python
def _create_virtualenv(venv_dir: Path) -> Path:
    """Create relocatable virtual environment with --copies flag"""
    cmd = [sys.executable, "-m", "venv", "--copies", str(venv_dir)]
    _run(cmd, cwd=PROJECT_ROOT)
```

#### PowerShell-Style Directory Structure
```python
def _stage_pkg_contents(venv_source: Path, *, staging_root: Path) -> None:
    # Create PowerShell-style directory structure
    usr_local_bin = staging_root / "usr" / "local" / "bin"
    usr_local_microsoft = staging_root / "usr" / "local" / "microsoft"
    
    # Copy virtual environment to PowerShell-style location
    venv_dest = usr_local_microsoft / "mycli"
    shutil.copytree(venv_source, venv_dest)
    
    # Generate launcher script
    launcher_script = _generate_launcher_script()
    launcher_path = usr_local_bin / "mycli"
    launcher_path.write_text(launcher_script)
    launcher_path.chmod(0o755)
```

#### PKG Creation Process

```python
def _create_pkg_installer(pkg_root: Path, *, version: str, platform_tag: str, artifacts_dir: Path, staging_dir: Path) -> Path:
    """Create PKG installer using pkgbuild"""
    
    pkg_name = f"{APP_NAME}-{version}-{platform_tag}.pkg"
    pkg_path = artifacts_dir / pkg_name

    cmd = [
        "pkgbuild",
        "--root", str(pkg_root),
        "--identifier", PKG_IDENTIFIER,
        "--version", version,
        "--install-location", "/",  # Root installation for system paths
        str(pkg_path),
    ]
    _run(cmd)
    
    return pkg_path
```

### Cross-Platform Considerations

#### macOS Version Compatibility
- **Minimum Target**: macOS 10.15 (Catalina)
- **ARM64 Support**: Native Apple Silicon compatibility
- **Intel Support**: x86_64 compatibility for older Macs

#### PowerShell Path Consistency
```python
# PowerShell-style installation paths
MICROSOFT_BASE = "/usr/local/microsoft"
MYCLI_RUNTIME = f"{MICROSOFT_BASE}/mycli"
SYSTEM_BIN = "/usr/local/bin"
```

### Error Handling

#### Build Failures
```python
class BuildError(RuntimeError):
    """Raised when the PKG build pipeline fails."""

def _run(cmd: Iterable[str], **kwargs) -> subprocess.CompletedProcess:
    """Execute subprocess with detailed error reporting"""
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        raise BuildError(f"Command failed: {' '.join(cmd)}\nStderr: {result.stderr}")
```

#### Runtime Diagnostics
```bash
# PowerShell-style launcher script error handling
if [[ ! -x "${PYTHON}" ]]; then
    echo "Error: mycli installation appears corrupted" >&2
    echo "Python executable not found at: ${PYTHON}" >&2
    echo "Microsoft-style installation directory: ${MICROSOFT_DIR}" >&2
    echo "Try reinstalling with direct PKG or: brew reinstall --cask mycli-app-pkgnew-pj2" >&2
    exit 1
fi
```

## Usage Guide

### Local Development Build

```bash
# Build PKG with PowerShell-style paths
python scripts/build_venv_bundle.py --platform-tag macos-arm64

# Build with specific extras
python scripts/build_venv_bundle.py --extras broker --platform-tag macos-arm64

# Build without extras  
python scripts/build_venv_bundle.py --extras "" --platform-tag macos-arm64

# Override version (useful for testing)
VERSION=4.1.0-beta python scripts/build_venv_bundle.py --platform-tag macos-arm64
```

### Manual Release Process

1. **Update Version**: Modify `src/mycli_app/__init__.py`
2. **Trigger Build Workflow**: Actions → "PKG build - pkgnew installer"
3. **Set Version**: Input version number (e.g., "4.0.0")
4. **Monitor Builds**: Watch matrix builds for both platforms
5. **Update Homebrew Cask**: Run "PKG update - homebrew cask" workflow
6. **Test Both Methods**: 
   - Run "PKG test - sudoinstaller" workflow
   - Run "PKG test - homebrew cask" workflow

### Direct PKG Testing

```bash
# Download PKG from releases
curl -L -o mycli-4.0.0-macos-arm64.pkg \
  "https://github.com/naga-nandyala/pj2/releases/download/v4.0.0/mycli-4.0.0-macos-arm64.pkg"

# Install PKG directly
sudo installer -pkg mycli-4.0.0-macos-arm64.pkg -target /

# Test installation
/usr/local/bin/mycli --version
/usr/local/bin/mycli status

# Test PowerShell-style path
/usr/local/microsoft/mycli/bin/python3 -m mycli_app --version

# Manual uninstall
sudo rm -f /usr/local/bin/mycli
sudo rm -rf /usr/local/microsoft/mycli
```

### Homebrew Installation (End Users)

```bash
# Add tap
brew tap naga-nandyala/mycli-app

# Install via cask (downloads and installs PKG)
brew install --cask mycli-app-pkgnew-pj2

# Use application  
mycli --version
mycli login
mycli status

# Update when available
brew upgrade --cask mycli-app-pkgnew-pj2

# Uninstall cleanly
brew uninstall --cask mycli-app-pkgnew-pj2
```

## Troubleshooting

### Common Build Issues

#### **Virtual Environment Creation Failed**
```
ERROR: Command failed with exit code 1: python -m venv --copies /tmp/pkg-venv
```
**Solution**: Ensure Python 3.8+ is available and `venv` module is installed

#### **Version Detection Failed**
```
ERROR: Could not determine version from package (__version__ missing)
```
**Solution**: Verify `__version__ = "x.y.z"` exists in `src/mycli_app/__init__.py`

#### **PKG Build Failed**
```
ERROR: Command failed: pkgbuild --root ...
```
**Solutions**:
- Ensure running on macOS (pkgbuild not available on other platforms)
- Check file permissions in staging directory
- Verify PKG identifier is valid

#### **PowerShell Path Issues**
```
ERROR: Failed to create /usr/local/microsoft directory
```
**Solutions**:
- Ensure proper directory permissions in staging
- Verify PowerShell-style path construction
- Check for conflicts with existing Microsoft installations

### Runtime Issues

#### **Python Executable Not Found**
```
Error: mycli installation appears corrupted
Python executable not found at: /usr/local/microsoft/mycli/bin/python3
```
**Diagnosis Steps**:
1. Check PowerShell directory: `ls -la /usr/local/microsoft/`
2. Verify PKG installation: `pkgutil --pkgs | grep mycli`
3. Check launcher permissions: `ls -la /usr/local/bin/mycli`

**Solutions**:
```bash
# Reinstall via Homebrew
brew reinstall --cask mycli-app-pkgnew-pj2

# Direct reinstall
sudo installer -pkg /path/to/mycli-pkg-file.pkg -target /
```

#### **PowerShell Path Conflicts**
```
Permission denied: '/usr/local/microsoft/mycli'
```
**Solutions**:
```bash
# Fix PowerShell directory permissions
sudo chown -R root:wheel /usr/local/microsoft/mycli

# Verify Microsoft directory structure
ls -la /usr/local/microsoft/
```

#### **Module Import Errors**
```
ModuleNotFoundError: No module named 'mycli_app'
```
**Solution**: Ensure PKG was built with project properly installed:
```bash
# Check PowerShell-style virtual environment
/usr/local/microsoft/mycli/bin/python3 -c "import mycli_app; print('OK')"
```

#### **Authentication Issues**
```
azure.core.exceptions.ClientAuthenticationError
```
**Solution**: Ensure PKG was built with `broker` extras:
```bash
# Check if Azure dependencies are available
/usr/local/microsoft/mycli/bin/python3 -c "import azure.identity; print('Azure deps OK')"
```

### Installation Method Specific Issues

#### **Direct PKG Installation Issues**

**Download Failures:**
```bash
# Verify PKG file exists in release
curl -I "https://github.com/naga-nandyala/pj2/releases/download/v4.0.0/mycli-4.0.0-macos-arm64.pkg"

# Check file size
ls -lh mycli-4.0.0-macos-arm64.pkg
```

**Installation Failures:**
```bash
# Check installer logs
tail -f /var/log/install.log

# Verify PKG integrity
pkgutil --check-signature mycli-4.0.0-macos-arm64.pkg
```

#### **Homebrew Cask Issues**

**Tap Issues:**
```bash
# Verify tap exists
brew tap-info naga-nandyala/mycli-app

# Refresh tap
brew tap --repair naga-nandyala/mycli-app
```

**Cask Issues:**
```bash
# Debug cask installation
brew install --cask --verbose mycli-app-pkgnew-pj2

# Check cask info
brew info --cask mycli-app-pkgnew-pj2
```

### GitHub Actions Issues

#### **Matrix Build Failures**
- **Runner Availability**: macOS runners can have limited capacity
- **Python Setup**: Verify Python setup step succeeded  
- **Dependency Conflicts**: Check for version resolution issues

#### **Version Input Issues**
```
ERROR: Version input format incorrect
```
**Solution**: Use format "4.0.0" (without 'v' prefix) in workflow inputs

#### **PKG Download Failed**
```
ERROR: Failed to download PKG from GitHub releases
```
**Solutions**:
- Verify release exists with correct tag format
- Check PKG filename matches expected pattern
- Ensure artifacts were uploaded correctly

### Performance Considerations

#### **PKG Size**
- Typical PKG size: 13-15MB (optimized PowerShell-style installation)
- Smaller than traditional venv bundles due to efficient packaging
- Quick download on modern connections

#### **Build Time**
- Local build: 2-5 minutes (PowerShell path optimization)
- GitHub Actions: 5-8 minutes per platform
- Bottlenecks: Dependency installation and PKG metadata

#### **Installation Time**
- Direct PKG installation: 10-30 seconds
- Homebrew installation: 30-60 seconds (includes download)
- Faster than traditional bundle installations

### Monitoring and Maintenance

#### **Regular Maintenance Tasks**
1. **Dependency Updates**: Monitor Azure/MSAL library security updates
2. **Python Version**: Test with new Python releases
3. **macOS Compatibility**: Test on new macOS versions
4. **PowerShell Compatibility**: Monitor Microsoft PowerShell changes
5. **Homebrew Changes**: Monitor Cask specification updates

#### **Health Checks**
- **Build Success Rate**: Monitor GitHub Actions workflow success
- **Installation Testing**: Automated tests for both installation methods
- **User Feedback**: Monitor GitHub issues and Homebrew tap feedback
- **System Integration**: Test with different macOS configurations

#### **Security Considerations**
- **Code Signing**: Consider signing PKG files for enhanced trust
- **Dependency Scanning**: Monitor for vulnerabilities in bundled libraries
- **Installation Verification**: Checksum verification in both installation methods
- **PowerShell Security**: Follow Microsoft security guidelines

This documentation provides comprehensive coverage of the PKG direct installation system with PowerShell-style integration, enabling effective development, maintenance, and troubleshooting of both direct and Homebrew installation methods.