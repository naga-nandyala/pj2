# PKG Installer Bundling System

This document provides comprehensive documentation for the macOS PKG installer approach used to distribute the `mycli` application via Homebrew Cask.

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

**Challenge**: Homebrew Formula cannot handle dependencies with native binaries that lack source code. Therefore, we must use **Homebrew Cask** with pre-built installers.

### Solution: macOS PKG Installer System

We create native macOS PKG installers that:
- Install a complete Python virtual environment to system locations
- Provide a system-wide launcher script in `/usr/local/bin`
- Follow macOS application distribution conventions
- Integrate seamlessly with Homebrew Cask management

## Architecture

### Installation Structure

```
/usr/local/bin/
└── mycli                    # System-wide launcher script (executable)

/usr/local/libexec/
└── mycli-venv/             # Complete Python virtual environment
    ├── bin/                # Python executables (python3, pip, etc.)
    ├── lib/                # Site-packages with all dependencies
    ├── include/            # Python headers
    ├── share/              # Shared data
    └── pyvenv.cfg          # Virtual environment configuration
```

### Key Design Principles

1. **System Integration**: Installs to standard macOS system paths
2. **Self-contained**: Complete Python runtime with all dependencies
3. **Cross-platform**: Supports both ARM64 and x86_64 architectures
4. **Native Installation**: Uses macOS PKG format for proper system integration
5. **Homebrew Compatible**: Works seamlessly with `brew install --cask`

## Build Process

### Core Script: `scripts/build_pkg_installer.py`

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

#### Phase 3: PKG Staging
```python
def _stage_pkg_contents(venv_source: Path, *, staging_root: Path) -> None:
```
- Creates proper macOS system directory structure
- Copies virtual environment to `usr/local/libexec/mycli-venv/`
- Generates launcher script in `usr/local/bin/`
- Sets proper file permissions and ownership

#### Phase 4: PKG Creation
```python
def _build_pkg(staging_root: Path, *, platform_tag: str, artifacts_dir: Path) -> Path:
```
- Uses `pkgbuild` to create component package
- Uses `productbuild` to create distribution package
- Generates proper package metadata and identifiers
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

### Launcher Script Generation

#### System Launcher (`/usr/local/bin/mycli`)
```bash
#!/usr/bin/env bash
set -euo pipefail

# Simple direct path - no symlink resolution needed
VENV_DIR="/usr/local/libexec/mycli-venv"
PYTHON="${VENV_DIR}/bin/python3"

# Verify installation integrity
if [[ ! -x "${PYTHON}" ]]; then
    echo "Error: mycli installation appears corrupted" >&2
    echo "Python executable not found at: ${PYTHON}" >&2
    echo "Try reinstalling with: brew reinstall --cask mycli" >&2
    exit 1
fi

# Execute the application
exec "${PYTHON}" -m mycli_app "$@"
```

### PKG Package Structure

The PKG installer contains:

#### Component Package Metadata
```xml
<!-- Generated by pkgbuild -->
<pkg-info format-version="2" identifier="com.naga-nandyala.mycli" version="2.0.0" install-location="/" auth="root">
    <payload numberOfFiles="xxx" installKBytes="xxx"/>
    <bundle-version>
        <bundle id="com.naga-nandyala.mycli" CFBundleShortVersionString="2.0.0" path="./mycli-2.0.0-macos-arm64.pkg"/>
    </bundle-version>
</pkg-info>
```

#### Installation Scripts
- **Preinstall**: Cleanup previous installations
- **Postinstall**: Set proper permissions and PATH integration
- **Uninstall**: Remove all installed components (via Homebrew Cask)

## GitHub Actions Workflows

### 1. PKG Build Workflow: `pkg-build-installer.yml`

**Trigger**: Manual dispatch with version input
**Purpose**: Build and release platform-specific PKG installers

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
2. **Build**: `python scripts/build_pkg_installer.py --platform-tag ${{ matrix.platform_tag }}`
3. **Rename**: Add version to PKG filenames
4. **Upload**: Store as GitHub Actions artifacts
5. **Release**: Create GitHub release with all platform PKG files

#### Artifacts Produced
- `mycli-{version}-macos-arm64.pkg`
- `mycli-{version}-macos-arm64.pkg.sha256`
- `mycli-{version}-macos-x86_64.pkg`
- `mycli-{version}-macos-x86_64.pkg.sha256`

### 2. Homebrew Cask Update: `pkg-update-homebrew-cask.yml`

**Trigger**: Manual dispatch with version input
**Purpose**: Update Homebrew tap with new PKG release

#### Process Flow
1. **Version Input**: Use provided version number
2. **Download PKG Files**: Get release PKG installers from GitHub
3. **Checksum Calculation**: Compute SHA256 for each platform PKG
4. **Cask Generation**: Update Ruby cask file with new URLs and checksums
5. **Cross-repo Push**: Commit to `homebrew-mycli-app` repository

#### Cask Template
```ruby
cask "mycli-app-pkg-pj2" do
  version "__VERSION__"

  on_arm do
    sha256 "__ARM64_SHA__"
    url "https://github.com/naga-nandyala/pj2/releases/download/v#{version}/__ARM64_FILE__"
    pkg "__ARM64_FILE__"
    binary "/usr/local/bin/mycli"
  end

  on_intel do
    sha256 "__X86_SHA__"
    url "https://github.com/naga-nandyala/pj2/releases/download/v#{version}/__X86_FILE__"
    pkg "__X86_FILE__"
    binary "/usr/local/bin/mycli"
  end

  name "MyCliApp"
  desc "A simple CLI application with dummy commands"
  homepage "https://github.com/naga-nandyala/pj2"

  uninstall pkgutil: "com.naga-nandyala.mycli"

  caveats do
    <<~EOS
      MyCliApp has been installed to /usr/local/bin/mycli
      
      The application runtime is located at:
      /usr/local/libexec/mycli-venv/
      
      To get started, run:
        mycli --help
        mycli status
    EOS
  end
end
```

### 3. Installation Test: `pkg-test-homebrew-cask.yml`

**Trigger**: Manual dispatch (typically after PKG build)
**Purpose**: Validate Homebrew Cask PKG installation

#### Test Matrix
- `macos-latest` (ARM64)
- `macos-13` (x86_64)

#### Comprehensive Test Steps

1. **Environment Info**: System details and architecture verification
2. **Cleanup**: Remove any existing installations
3. **Tap Installation**: `brew tap naga-nandyala/mycli-app`
4. **PKG Install**: `brew install --cask mycli-app-pkg-pj2`
5. **Structure Verification**: Check system installation paths
6. **Functional Testing**: Version check, help output, status command
7. **Launcher Script Testing**: Verify script content and permissions
8. **Installation Integrity**: Module imports and dependency checks
9. **Working Directory Independence**: Test from multiple locations
10. **Performance Check**: Startup time and installation size
11. **Authentication Test**: Non-blocking broker authentication test
12. **Cleanup Test**: Verify complete uninstallation

#### Key Verification Points
```bash
# Executable location
ls -la /usr/local/bin/mycli

# Runtime environment
du -sh /usr/local/libexec/mycli-venv

# PATH availability
which mycli

# Package manager records
pkgutil --pkgs | grep -i mycli

# Functional testing
mycli --version
mycli status
```

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
├── __init__.py      # Contains __version__ = "1.0.0"  
├── __main__.py      # Entry point: from mycli_app.cli import main; main()
├── cli.py           # Main CLI implementation with Click commands
└── config.yaml      # Application configuration
```

### Why Module Execution?

1. **System Integration**: Works perfectly with system-wide installations
2. **Path Reliability**: No dependency on symlink resolution
3. **Error Handling**: Clear diagnostics for missing components
4. **Consistency**: Same execution method across all platforms

## Distribution Strategy

### PKG Installer Advantages

**Why PKG instead of simple bundles?**
- **Native macOS Integration**: Uses standard system installation patterns
- **System-wide Availability**: Installs to `/usr/local/bin` for all users
- **Proper Uninstallation**: PKG utilities track installed files
- **Security**: Signed packages (when certificates available)
- **User Experience**: Familiar installation process for macOS users

**Why with Homebrew Cask?**
- **Package Management**: Users can manage with `brew install/uninstall`
- **Automatic Updates**: Tap updates provide new versions seamlessly  
- **Dependency Handling**: Cask manages PKG download and installation
- **Consistency**: Same interface as other Homebrew-managed applications

### Architecture Support

**Platform-Specific PKG Files**: Separate installers for ARM64 and x86_64
- **Native Performance**: Architecture-optimized Python runtime
- **Smaller Downloads**: Users only download relevant architecture
- **Better Compatibility**: Avoids universal binary complexity
- **Easier Testing**: Platform-specific validation

### Repository Structure

**Main Repository** (`naga-nandyala/pj2`):
- Source code
- Build scripts (`scripts/build_pkg_installer.py`)
- GitHub Actions workflows
- Release artifacts (PKG files)

**Homebrew Tap** (`naga-nandyala/homebrew-mycli-app`):
- Ruby cask definitions (`mycli-app-pkg-pj2.rb`)
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

#### System Directory Structure
```python
def _stage_pkg_contents(venv_source: Path, *, staging_root: Path) -> None:
    # Create system directory structure
    usr_local_bin = staging_root / "usr" / "local" / "bin"
    usr_local_libexec = staging_root / "usr" / "local" / "libexec"
    
    # Copy virtual environment
    venv_dest = usr_local_libexec / "mycli-venv"
    shutil.copytree(venv_source, venv_dest)
    
    # Generate launcher script
    launcher_script = _generate_launcher_script()
    launcher_path = usr_local_bin / "mycli"
    launcher_path.write_text(launcher_script)
    launcher_path.chmod(0o755)
```

#### PKG Creation with `pkgbuild`
```python
def _build_pkg(staging_root: Path, *, platform_tag: str, artifacts_dir: Path) -> Path:
    pkg_name = f"mycli-{version}-{platform_tag}.pkg"
    pkg_path = artifacts_dir / pkg_name
    
    # Build component package
    cmd = [
        "pkgbuild",
        "--root", str(staging_root),
        "--identifier", "com.naga-nandyala.mycli",
        "--version", version,
        "--install-location", "/",
        str(pkg_path)
    ]
    _run(cmd, cwd=artifacts_dir)
```

### Cross-Platform Considerations

#### macOS Version Compatibility
- **Minimum Target**: macOS 10.15 (Catalina)
- **ARM64 Support**: Native Apple Silicon compatibility
- **Intel Support**: x86_64 compatibility for older Macs

#### Python Runtime Compatibility
```python
def _virtualenv_python(venv_dir: Path) -> Path:
    """Get Python executable path for macOS"""
    return venv_dir / "bin" / "python3"
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
# Launcher script error handling
if [[ ! -x "${PYTHON}" ]]; then
    echo "Error: mycli installation appears corrupted" >&2
    echo "Python executable not found at: ${PYTHON}" >&2
    echo "Try reinstalling with: brew reinstall --cask mycli" >&2
    exit 1
fi
```

## Usage Guide

### Local Development Build

```bash
# Build for current platform
python scripts/build_pkg_installer.py --platform-tag macos-arm64

# Build with specific extras
python scripts/build_pkg_installer.py --extras broker --platform-tag macos-arm64

# Build without extras  
python scripts/build_pkg_installer.py --extras "" --platform-tag macos-arm64

# Override version (useful for testing)
VERSION=2.1.0-beta python scripts/build_pkg_installer.py --platform-tag macos-arm64
```

### Manual Release Process

1. **Update Version**: Modify `src/mycli_app/__init__.py`
2. **Trigger Build Workflow**: Actions → "PKG build - release"
3. **Set Version**: Input version number (e.g., "2.0.0")
4. **Monitor Builds**: Watch matrix builds for both platforms
5. **Update Homebrew Cask**: Run "PKG update - homebrew cask" workflow
6. **Test Installation**: Run "PKG test - homebrew cask" workflow

### Local PKG Testing

```bash
# Install PKG directly (bypassing Homebrew)
sudo installer -pkg dist/artifacts/mycli-2.0.0-macos-arm64.pkg -target /

# Test installation
/usr/local/bin/mycli --version
/usr/local/bin/mycli status

# Test Python module execution
/usr/local/libexec/mycli-venv/bin/python3 -m mycli_app --version

# Uninstall (manual)
sudo rm -f /usr/local/bin/mycli
sudo rm -rf /usr/local/libexec/mycli-venv
```

### Homebrew Installation (End Users)

```bash
# Add tap
brew tap naga-nandyala/mycli-app

# Install via cask (downloads and installs PKG)
brew install --cask mycli-app-pkg-pj2

# Use application  
mycli --version
mycli login
mycli status

# Uninstall
brew uninstall --cask mycli-app-pkg-pj2
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

#### **Dependency Installation Failed**
```
ERROR: Could not install packages due to an EnvironmentError
```
**Solution**: Check internet connectivity and PyPI access

### Runtime Issues

#### **Python Executable Not Found**
```
Error: mycli installation appears corrupted
Python executable not found at: /usr/local/libexec/mycli-venv/bin/python3
```
**Diagnosis Steps**:
1. Check if directory exists: `ls -la /usr/local/libexec/`
2. Verify PKG installation: `pkgutil --pkgs | grep mycli`
3. Check file permissions: `ls -la /usr/local/bin/mycli`

**Solutions**:
```bash
# Reinstall via Homebrew
brew reinstall --cask mycli-app-pkg-pj2

# Manual reinstall
sudo installer -pkg /path/to/mycli-pkg-file.pkg -target /
```

#### **Module Import Errors**
```
ModuleNotFoundError: No module named 'mycli_app'
```
**Solution**: Ensure PKG was built with project properly installed:
```bash
# Check virtual environment
/usr/local/libexec/mycli-venv/bin/python3 -c "import mycli_app; print('OK')"
```

#### **Permission Errors**
```
Permission denied: '/usr/local/bin/mycli'
```
**Solutions**:
```bash
# Fix launcher permissions
sudo chmod +x /usr/local/bin/mycli

# Fix virtual environment permissions  
sudo chown -R root:wheel /usr/local/libexec/mycli-venv
```

#### **Authentication Issues**
```
azure.core.exceptions.ClientAuthenticationError
```
**Solution**: Ensure PKG was built with `broker` extras:
```bash
# Check if Azure dependencies are available
/usr/local/libexec/mycli-venv/bin/python3 -c "import azure.identity; print('Azure deps OK')"
```

### GitHub Actions Issues

#### **Matrix Build Failures**
- **Runner Availability**: macOS runners can have limited capacity
- **Python Setup**: Verify Python setup step succeeded
- **Dependency Conflicts**: Check for version resolution issues

#### **PKG Build Tool Missing**
```
ERROR: pkgbuild: command not found
```
**Solution**: Ensure running on macOS runners (not Linux/Windows)

#### **Homebrew Cask Update Failed**
- **Token Permissions**: Verify `HOMEBREW_TAP_TOKEN` secret has write access
- **Repository Access**: Check tap repository exists and is accessible
- **PKG Download**: Ensure artifacts were uploaded correctly

#### **Release Creation Failed**
- **GITHUB_TOKEN**: Verify token has appropriate permissions
- **Tag Conflicts**: Check if release tag already exists
- **Artifact Upload**: Ensure all matrix jobs completed successfully

### PKG-Specific Issues

#### **Installation Fails**
```
installer: Package name is mycli-2.0.0-macos-arm64.pkg
installer: Installing at base path /
installer: The install failed.
```
**Diagnosis**:
```bash
# Check installer logs
tail -f /var/log/install.log

# Verify PKG integrity
pkgutil --check-signature mycli-2.0.0-macos-arm64.pkg
```

#### **Partial Installation**
```bash
# Check what was actually installed
pkgutil --files com.naga-nandyala.mycli

# Verify installation receipt
pkgutil --pkg-info com.naga-nandyala.mycli
```

#### **Uninstallation Issues**
```bash
# Manual uninstallation
sudo pkgutil --forget com.naga-nandyala.mycli
sudo rm -f /usr/local/bin/mycli  
sudo rm -rf /usr/local/libexec/mycli-venv
```

### Performance Considerations

#### **PKG Size**
- Typical PKG size: 60-120MB (includes full Python + dependencies)
- Larger than venv bundles due to PKG metadata overhead
- Still reasonable for modern internet connections

#### **Build Time**
- Local build: 3-7 minutes (PKG creation adds overhead)
- GitHub Actions: 7-12 minutes per platform
- Bottlenecks: Dependency installation and PKG creation

#### **Installation Time**
- PKG installation: 30-90 seconds (system-wide installation)
- Faster than building from source
- Slower than simple file extraction

### Monitoring and Maintenance

#### **Regular Maintenance Tasks**
1. **Dependency Updates**: Monitor Azure/MSAL library security updates
2. **Python Version**: Test with new Python releases
3. **macOS Compatibility**: Test on new macOS versions
4. **PKG Tools**: Monitor for pkgbuild/productbuild changes
5. **Homebrew Changes**: Monitor Cask specification updates

#### **Health Checks**
- **Build Success Rate**: Monitor GitHub Actions workflow success
- **Installation Testing**: Automated tests catch integration issues
- **User Feedback**: Monitor Homebrew tap issue reports
- **System Integration**: Test with different macOS configurations

#### **Security Considerations**
- **Code Signing**: Consider signing PKG files for enhanced trust
- **Dependency Scanning**: Monitor for vulnerabilities in bundled libraries
- **Installation Verification**: Checksum verification in Homebrew Cask

This documentation provides comprehensive coverage of the PKG installer bundling system, enabling effective development, maintenance, and troubleshooting of the macOS distribution mechanism.