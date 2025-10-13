# macOS Signing and Notarization Process for PowerShell

## Overview

This document describes the code signing and notarization process for PowerShell packages on macOS, particularly in relation to Homebrew Cask distribution.

## Table of Contents

1. [Package Creation Process](#package-creation-process)
2. [Code Signing Process](#code-signing-process)
3. [Notarization Process](#notarization-process)
4. [Homebrew Cask Distribution](#homebrew-cask-distribution)
5. [Technical Implementation Details](#technical-implementation-details)
6. [Verification and Validation](#verification-and-validation)

---

## Package Creation Process

### 1. Build Architecture Support

PowerShell supports two macOS architectures:
- **x86_64** (Intel-based Macs)
- **arm64** (Apple Silicon Macs)

### 2. Package Types Created

The build pipeline creates two types of packages for macOS:

#### a. `.pkg` Installer (Primary for Homebrew Cask)
- Created using `productbuild` (Xcode command-line tool)
- Distribution-style package with custom resources
- Contains installation scripts and metadata
- **File naming convention**: `powershell-{version}-osx-{arch}.pkg`
  - Example: `powershell-7.5.0-osx-arm64.pkg`

#### b. `.tar.gz` Archive
- Compressed tarball for manual installation
- Does not require installation, can be extracted directly
- **File naming convention**: `powershell-{version}-osx-{arch}.tar.gz`

### 3. Package Components

The macOS `.pkg` installer includes:
- **PowerShell binaries** (signed)
- **Distribution XML** - defines installation behavior and requirements
- **Resources** - background image (`macDialog.png`)
- **Scripts** - after-install script for creating symlinks
- **Minimum OS version** - macOS 10.14+
- **Package Identifier** - Unique bundle ID for the package

---

## Code Signing Process

### 1. Signing Pipeline Architecture

The signing process is split into multiple stages in Azure DevOps:

```
┌─────────────────────────────────────────────────────────┐
│  Stage 1: Build Package (macOS Agent)                  │
│  - Builds unsigned .pkg on macOS-latest                │
│  - Uses productbuild to create distribution package    │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Stage 2: Sign Package (Windows Agent)                 │
│  - Compresses .pkg to .zip                             │
│  - Uses OneBranch signing pipeline                      │
│  - Signs with MacAppDeveloperSign operation            │
│  - Extracts signed .pkg                                 │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Stage 3: Publish to GitHub Release                     │
│  - Uploads signed .pkg to GitHub Releases              │
│  - Updates release notes with checksums                 │
└─────────────────────────────────────────────────────────┘
```

### 2. Signing Configuration

**Pipeline**: `.pipelines/templates/mac-package-build.yml`

**Key Configuration**:
```yaml
- task: onebranch.pipeline.signing@1
  displayName: 'OneBranch CodeSigning Package'
  inputs:
    command: 'sign'
    files_to_sign: '**/*-osx-*.zip'
    search_root: '$(Pipeline.Workspace)'
    inline_operation: |
      [
        {
          "KeyCode": "$(KeyCode)",
          "OperationCode": "MacAppDeveloperSign",
          "ToolName": "sign",
          "ToolVersion": "1.0",
          "Parameters": {
            "Hardening": "Enable",
            "OpusInfo": "http://microsoft.com"
          }
        }
      ]
```

**Key Components**:
- **KeyCode**: Secret stored in Azure Key Vault (`mscodehub-macos-package-signing` group)
- **OperationCode**: `MacAppDeveloperSign` - Uses Apple Developer ID certificate
- **Hardening**: Enabled - Enforces secure runtime and hardened runtime capabilities
- **OpusInfo**: Microsoft attribution URL

### 3. Certificate Details

The signing uses:
- **Developer ID Application Certificate**: For signing application bundles
- **Developer ID Installer Certificate**: For signing `.pkg` installers
- Issued by Apple to Microsoft Corporation
- Stored securely in Microsoft's internal code signing infrastructure

### 4. Code Signing Benefits

✅ **Gatekeeper Approval**: Signed packages pass macOS Gatekeeper without warnings
✅ **User Trust**: Users see "Microsoft Corporation" as the verified developer
✅ **Tamper Detection**: Any modification after signing invalidates the signature
✅ **Homebrew Cask Requirement**: Signed packages are preferred for Cask distribution

---

## Notarization Process

### Current State: Limited Automation

**Important**: The PowerShell repository **does not currently include automated notarization** in the build pipeline.

### What is Notarization?

Apple's notarization is an additional security layer beyond code signing:
- Packages are submitted to Apple for automated malware scanning
- Apple's notary service checks the package for malicious content
- If approved, Apple issues a "ticket" that's stapled to the package
- Required for distribution outside the Mac App Store (starting macOS 10.15+)

### Manual Notarization Workflow

If notarization is performed (likely done separately by Microsoft's release team):

#### 1. Submit for Notarization
```bash
# Using notarytool (modern method)
xcrun notarytool submit powershell-7.5.0-osx-arm64.pkg \
  --apple-id "apple-id@microsoft.com" \
  --team-id "TEAMID" \
  --password "app-specific-password" \
  --wait
```

#### 2. Check Notarization Status
```bash
xcrun notarytool info <submission-id> \
  --apple-id "apple-id@microsoft.com" \
  --password "app-specific-password"
```

#### 3. Staple Notarization Ticket
```bash
# Attach the notarization ticket to the package
xcrun stapler staple powershell-7.5.0-osx-arm64.pkg
```

#### 4. Verify Stapling
```bash
xcrun stapler validate powershell-7.5.0-osx-arm64.pkg
spctl -a -v -t install powershell-7.5.0-osx-arm64.pkg
```

### Why Notarization Matters for Homebrew Cask

- **Modern macOS Requirement**: macOS 10.15+ (Catalina) requires notarization for downloaded software
- **Silent Installation**: Notarized packages install without user intervention
- **Cask Quality**: Homebrew Cask maintainers prefer notarized packages
- **User Experience**: No scary security warnings during installation

---

## Homebrew Cask Distribution

### How PowerShell Gets to Homebrew Cask

PowerShell does **NOT** directly publish to Homebrew Cask. Instead:

```
┌──────────────────────────────────────────────────────────┐
│  1. PowerShell Team                                      │
│     - Builds and signs .pkg package                      │
│     - Publishes to GitHub Releases                       │
│     - Includes SHA256 checksum in release notes          │
└────────────────────┬─────────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────────────┐
│  2. Homebrew Automation (or Community Contributors)      │
│     - Detects new PowerShell release                     │
│     - Updates Cask formula with new version              │
│     - Updates download URL and SHA256 hash               │
│     - Submits PR to homebrew-cask repository             │
└────────────────────┬─────────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────────────┐
│  3. Homebrew Maintainers                                 │
│     - Reviews and merges PR                              │
│     - New version available via `brew install powershell`│
└──────────────────────────────────────────────────────────┘
```

### Homebrew Cask Formula Location

The actual Cask formula is maintained at:
```
https://github.com/Homebrew/homebrew-cask/blob/master/Casks/p/powershell.rb
```

### Typical Cask Formula Structure

```ruby
cask "powershell" do
  arch arm: "arm64", intel: "x64"
  
  version "7.5.0"
  sha256 arm:   "abc123...",
         intel: "def456..."

  url "https://github.com/PowerShell/PowerShell/releases/download/v#{version}/powershell-#{version}-osx-#{arch}.pkg"
  name "PowerShell"
  desc "Command-line shell and scripting language"
  homepage "https://microsoft.com/powershell"

  depends_on macos: ">= :mojave"

  pkg "powershell-#{version}-osx-#{arch}.pkg"

  uninstall pkgutil: "com.microsoft.powershell"

  zap trash: [
    "~/.cache/powershell",
    "~/.config/powershell",
    "~/.local/share/powershell",
  ]
end
```

### Key Cask Elements

- **Architecture Support**: Automatically selects correct package (Intel vs Apple Silicon)
- **Version**: Updated for each new release
- **SHA256**: Security hash to verify package integrity
- **Download URL**: Points to GitHub Releases
- **Package Identifier**: `com.microsoft.powershell` (from package metadata)
- **Uninstall**: Uses `pkgutil` to remove package
- **Zap**: Removes user data and configuration

---

## Technical Implementation Details

### 1. Package Creation Code

**File**: `PowerShell/tools/packaging/packaging.psm1`

**Function**: `New-MacOsDistributionPackage`

Key steps:
1. Takes FPM-built base package
2. Creates distribution XML with installation parameters
3. Adds background image to resources
4. Uses `productbuild` to create final distributable `.pkg`

```powershell
# Key code snippet from packaging.psm1 (line ~1424)
Start-NativeExecution -sb {
    productbuild --distribution $distributionXmlPath \
                 --resources $resourcesDir \
                 $newPackagePath
} -VerboseOutputOnError
```

### 2. Distribution XML Template

The package includes a distribution XML that defines:
- Minimum OS version requirement (10.14)
- Host architecture (x86_64 or arm64)
- Installation location
- Welcome message and license agreement
- Package identifier

### 3. Pipeline Variables

**Important Variables**:
- `HOMEBREW_NO_ANALYTICS: 1` - Disables Homebrew telemetry during builds
- `runCodesignValidationInjection: false` - Manages signing validation
- `ob_sdl_binskim_enabled: true` - Security scanning
- `mscodehub-macos-package-signing` - Variable group with signing secrets

### 4. Build Dependencies

Required tools on macOS build agent:
- **productbuild** (Xcode command-line tools)
- **Homebrew** or **MacPorts**
- **FPM** (Effing Package Management)
- **.NET SDK**
- **OpenSSL**

---

## Verification and Validation

### 1. Verify Package Signature

```bash
# Check signature of the .pkg
pkgutil --check-signature powershell-7.5.0-osx-arm64.pkg

# Should show:
# Package "powershell-7.5.0-osx-arm64.pkg":
#    Status: signed by a developer certificate issued by Apple (Development)
#    Signed with a trusted timestamp on: 2024-10-14 12:34:56 +0000
#    Certificate Chain:
#     1. Developer ID Installer: Microsoft Corporation (...)
#        Expires: 2028-01-01 12:00:00 +0000
#     2. Developer ID Certification Authority
#        Expires: 2027-02-01 22:12:15 +0000
#     3. Apple Root CA
#        Expires: 2035-02-09 21:40:36 +0000
```

### 2. Verify Gatekeeper Acceptance

```bash
# Check if Gatekeeper will allow installation
spctl --assess --verbose=4 --type install powershell-7.5.0-osx-arm64.pkg

# Should show:
# powershell-7.5.0-osx-arm64.pkg: accepted
# source=Developer ID
```

### 3. Verify Notarization (if applied)

```bash
# Check if package is notarized
spctl -a -vv -t install powershell-7.5.0-osx-arm64.pkg

# Or check stapler ticket
xcrun stapler validate powershell-7.5.0-osx-arm64.pkg
```

### 4. Verify Package Contents

```bash
# List package contents
pkgutil --payload-files powershell-7.5.0-osx-arm64.pkg | head -20

# Examine package info
pkgutil --expand powershell-7.5.0-osx-arm64.pkg ./expanded
cat ./expanded/Distribution
```

### 5. Test Installation

```bash
# Install via Homebrew Cask
brew install --cask powershell

# Verify installation
which pwsh
/usr/local/bin/pwsh

pwsh --version
PowerShell 7.5.0

# Check installation location
ls -la /usr/local/microsoft/powershell/7/
```

---

## Security Considerations

### 1. Hardened Runtime

The signing process enables **Hardened Runtime**, which:
- Prevents code injection attacks
- Enforces memory protection
- Validates library loading
- Required for notarization

### 2. Secure Timestamp

Signatures include a **secure timestamp** from Apple:
- Ensures signature validity even after certificate expiration
- Proves when the package was signed
- Critical for long-term package distribution

### 3. Certificate Chain Validation

The signing certificate chain includes:
1. **Developer ID Installer** - Microsoft Corporation
2. **Developer ID Certification Authority** - Apple
3. **Apple Root CA** - Apple's root certificate

All certificates must be valid and trusted by macOS.

---

## Troubleshooting

### Common Issues

#### 1. "Package is damaged and can't be opened"
- **Cause**: Signature verification failed or package corrupted
- **Solution**: Re-download package, verify SHA256 checksum

#### 2. "Package can't be opened because Apple cannot check it for malicious software"
- **Cause**: Package not notarized or notarization ticket missing
- **Solution**: Right-click → Open (bypass for testing) or use notarized version

#### 3. Gatekeeper Blocks Installation
- **Cause**: Certificate expired or revoked
- **Solution**: Check certificate validity with `pkgutil --check-signature`

#### 4. Homebrew Installation Fails
- **Cause**: SHA256 mismatch or download failure
- **Solution**: Update Homebrew (`brew update`) and retry

---

## References

### PowerShell Repository Files

- **Packaging Module**: `PowerShell/tools/packaging/packaging.psm1`
- **Build Pipeline**: `PowerShell/.pipelines/templates/mac-package-build.yml`
- **macOS Build Docs**: `PowerShell/docs/building/macos.md`

### External Resources

- **Homebrew Cask**: https://github.com/Homebrew/homebrew-cask
- **PowerShell Cask Formula**: https://github.com/Homebrew/homebrew-cask/blob/master/Casks/p/powershell.rb
- **Apple Code Signing**: https://developer.apple.com/documentation/security/notarizing_macos_software_before_distribution
- **OneBranch Documentation**: (Microsoft Internal)

### Apple Developer Documentation

- [Notarizing macOS Software](https://developer.apple.com/documentation/security/notarizing_macos_software_before_distribution)
- [Code Signing Guide](https://developer.apple.com/library/archive/documentation/Security/Conceptual/CodeSigningGuide/)
- [Hardened Runtime](https://developer.apple.com/documentation/security/hardened_runtime)

---

## Summary

### Key Takeaways

1. ✅ **PowerShell packages are code-signed** using Microsoft's Developer ID certificate
2. ⚠️ **Notarization is likely performed separately**, not in the automated pipeline
3. 🔄 **Homebrew Cask distribution is community-driven**, not directly by PowerShell team
4. 📦 **Two package types**: `.pkg` (for Cask) and `.tar.gz` (for manual install)
5. 🏗️ **Build process uses productbuild** from Xcode command-line tools
6. 🔐 **Signing happens on Windows agents** using OneBranch pipeline
7. 🍺 **Homebrew Cask formula is maintained separately** in homebrew-cask repository

### Workflow Summary

```
Build (macOS) → Sign (Windows) → Publish (GitHub) → Update Cask (Community) → Install (Users)
```

---

**Document Version**: 1.0  
**Last Updated**: October 14, 2025  
**Author**: System Documentation  
**Repository**: PowerShell/PowerShell
