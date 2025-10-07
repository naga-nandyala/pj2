# Phase 2: Test Signing in GitHub Actions Workflow

Learn how to integrate signing into your GitHub Actions workflow and test it with self-signed certificates.

## Goal

Create a workflow that:

- ✅ Works with self-signed certificates (for testing)
- ✅ Will work with real Apple Developer ID (when ready)
- ✅ Gracefully handles missing credentials
- ✅ Provides clear feedback on signing status

---

## Understanding Conditional Signing

### The Pattern

```yaml
# Check if signing credentials are available
- name: Check signing credentials
  id: check_signing
  run: |
    if [ -n "${{ secrets.APPLE_SIGNING_CERTIFICATE }}" ]; then
      echo "signing_available=true" >> $GITHUB_OUTPUT
    else
      echo "signing_available=false" >> $GITHUB_OUTPUT
    fi

# Sign only if credentials are available
- name: Sign PKG
  if: steps.check_signing.outputs.signing_available == 'true'
  run: |
    # Signing code here
```

---

## Complete Signing Step for Workflow

Add this step to `pkgsign-build-installer.yml` after the "Build PKG installer" step:

```yaml
      - name: Check signing credentials
        id: check_signing
        run: |
          if [ -n "${{ secrets.APPLE_SIGNING_CERTIFICATE }}" ] && \
             [ -n "${{ secrets.APPLE_CERT_PASSWORD }}" ]; then
            echo "signing_available=true" >> $GITHUB_OUTPUT
            echo "✅ Signing credentials found"
          else
            echo "signing_available=false" >> $GITHUB_OUTPUT
            echo "⚠️  Signing credentials not found - will build unsigned packages"
          fi

      - name: Sign PKG installer
        if: steps.check_signing.outputs.signing_available == 'true'
        env:
          APPLE_SIGNING_CERTIFICATE: ${{ secrets.APPLE_SIGNING_CERTIFICATE }}
          APPLE_CERT_PASSWORD: ${{ secrets.APPLE_CERT_PASSWORD }}
        run: |
          echo "=== Setting up Code Signing ==="
          
          # Create temporary keychain
          KEYCHAIN_PATH="$RUNNER_TEMP/build.keychain"
          KEYCHAIN_PASSWORD=$(openssl rand -base64 32)
          
          # Create and configure keychain
          security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
          security set-keychain-settings -lut 21600 "$KEYCHAIN_PATH"
          security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
          
          # Import certificate
          echo "$APPLE_SIGNING_CERTIFICATE" | base64 --decode > certificate.p12
          security import certificate.p12 -k "$KEYCHAIN_PATH" \
            -P "$APPLE_CERT_PASSWORD" \
            -T /usr/bin/codesign \
            -T /usr/bin/productsign
          
          # Set keychain to be used for signing
          security list-keychains -d user -s "$KEYCHAIN_PATH"
          security default-keychain -s "$KEYCHAIN_PATH"
          security set-key-partition-list -S apple-tool:,apple: \
            -s -k "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
          
          # List available signing identities
          echo "=== Available Signing Identities ==="
          security find-identity -v -p codesigning
          
          # Get certificate name
          CERT_NAME=$(security find-identity -v -p codesigning | \
            grep "Developer ID Installer" | head -1 | \
            sed 's/.*"\(.*\)".*/\1/')
          
          # Fallback to first available identity if no Developer ID found
          if [ -z "$CERT_NAME" ]; then
            CERT_NAME=$(security find-identity -v -p codesigning | \
              head -1 | sed 's/.*"\(.*\)".*/\1/')
          fi
          
          echo "Using certificate: $CERT_NAME"
          
          # Sign all PKG files
          echo "=== Signing PKG Files ==="
          for pkg in dist/pkg_artifacts/*.pkg; do
            if [ -f "$pkg" ]; then
              echo "Signing: $(basename "$pkg")"
              
              # Create signed version
              SIGNED_PKG="${pkg%.pkg}-signed.pkg"
              
              # Sign with timestamp (or without if timestamp fails)
              if productsign --sign "$CERT_NAME" --timestamp "$pkg" "$SIGNED_PKG" 2>/dev/null; then
                echo "✅ Signed with timestamp: $(basename "$SIGNED_PKG")"
              else
                echo "⚠️  Timestamp failed, signing without..."
                productsign --sign "$CERT_NAME" "$pkg" "$SIGNED_PKG"
                echo "✅ Signed without timestamp: $(basename "$SIGNED_PKG")"
              fi
              
              # Verify signature
              echo "Verifying signature..."
              pkgutil --check-signature "$SIGNED_PKG"
              
              # Replace unsigned with signed
              mv "$SIGNED_PKG" "$pkg"
              echo "✅ Replaced unsigned with signed version"
              echo ""
            fi
          done
          
          echo "=== Signing Complete ==="
          
          # Cleanup
          rm -f certificate.p12

      - name: Cleanup keychain
        if: always() && steps.check_signing.outputs.signing_available == 'true'
        run: |
          KEYCHAIN_PATH="$RUNNER_TEMP/build.keychain"
          if [ -f "$KEYCHAIN_PATH" ]; then
            security delete-keychain "$KEYCHAIN_PATH" || true
          fi
```

---

## Testing with Self-Signed Certificate

### Step 1: Create Test Secrets Locally

```bash
# Export your self-signed certificate
cd ~/Documents

# From Keychain Access:
# Right-click "My Test Installer Certificate" → Export
# Save as: test-signing-cert.p12
# Password: test123

# Convert to base64
base64 -i test-signing-cert.p12 -o test-cert-base64.txt

# View the base64 string
cat test-cert-base64.txt
```

### Step 2: Add Secrets to GitHub

1. Go to your repository: `https://github.com/naga-nandyala/pj2`
2. Settings → Secrets and variables → Actions
3. New repository secret:
   - Name: `APPLE_SIGNING_CERTIFICATE`
   - Value: Paste contents of `test-cert-base64.txt`
4. New repository secret:
   - Name: `APPLE_CERT_PASSWORD`
   - Value: `test123` (or whatever password you used)

### Step 3: Trigger Workflow

```bash
# From your local machine
git add .
git commit -m "Add signing workflow"
git push

# Or trigger manually via GitHub UI:
# Actions → (pkgsign enhanced installer) - release → Run workflow
```

### Step 4: Monitor the Build

Watch the workflow output:
- ✅ "Signing credentials found" means secrets are working
- ✅ "Available Signing Identities" shows your certificate
- ✅ "Signed with timestamp" or "Signed without timestamp"
- ✅ Package signature verification

---

## Local Testing Script

Test the signing logic locally before pushing to GitHub:

```bash
cat > test-signing-locally.sh << 'EOF'
#!/bin/bash
set -euo pipefail

echo "=== Local Signing Test ==="
echo ""

# Configuration
CERT_NAME="My Test Installer Certificate"
TEST_PKG="dist/pkg_artifacts/mycli-1.0.0-macos-arm64.pkg"

# Check if certificate exists
if ! security find-identity -v -p codesigning | grep -q "$CERT_NAME"; then
  echo "❌ Certificate not found: $CERT_NAME"
  echo "Available certificates:"
  security find-identity -v -p codesigning
  exit 1
fi

echo "✅ Certificate found: $CERT_NAME"
echo ""

# Check if PKG exists
if [ ! -f "$TEST_PKG" ]; then
  echo "❌ Test PKG not found: $TEST_PKG"
  echo "Build it first with:"
  echo "  python scripts/build_pkgnew_installer.py --platform-tag macos-arm64"
  exit 1
fi

echo "✅ Test PKG found: $TEST_PKG"
echo ""

# Create temporary keychain (simulating GitHub Actions)
echo "Creating temporary keychain..."
TEMP_KEYCHAIN="$HOME/Library/Keychains/test-signing.keychain-db"
KEYCHAIN_PASSWORD="test-$(date +%s)"

# Clean up any existing test keychain
security delete-keychain "$TEMP_KEYCHAIN" 2>/dev/null || true

# Create new keychain
security create-keychain -p "$KEYCHAIN_PASSWORD" "$TEMP_KEYCHAIN"
security set-keychain-settings -lut 21600 "$TEMP_KEYCHAIN"
security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$TEMP_KEYCHAIN"

echo "✅ Temporary keychain created"
echo ""

# Export and import certificate (simulating CI/CD)
echo "Exporting certificate to test import process..."
TEMP_P12="$HOME/Desktop/temp-test-cert.p12"
TEMP_PASS="test123"

# Note: You'll need to export manually from Keychain Access first
if [ ! -f "$TEMP_P12" ]; then
  echo "⚠️  Please export your certificate manually:"
  echo "  1. Open Keychain Access"
  echo "  2. Find '$CERT_NAME'"
  echo "  3. Right-click → Export"
  echo "  4. Save as: $TEMP_P12"
  echo "  5. Password: $TEMP_PASS"
  echo ""
  read -p "Press Enter when ready..."
fi

# Import to temporary keychain
security import "$TEMP_P12" -k "$TEMP_KEYCHAIN" \
  -P "$TEMP_PASS" \
  -T /usr/bin/productsign

echo "✅ Certificate imported to temporary keychain"
echo ""

# Set as default keychain
security list-keychains -d user -s "$TEMP_KEYCHAIN"
security default-keychain -s "$TEMP_KEYCHAIN"

# Grant access
security set-key-partition-list -S apple-tool:,apple: \
  -s -k "$KEYCHAIN_PASSWORD" "$TEMP_KEYCHAIN"

echo "✅ Keychain configured"
echo ""

# List identities
echo "Available identities in temporary keychain:"
security find-identity -v -p codesigning
echo ""

# Sign the package
SIGNED_PKG="${TEST_PKG%.pkg}-signed-test.pkg"

echo "Signing package..."
if productsign --sign "$CERT_NAME" --timestamp "$TEST_PKG" "$SIGNED_PKG" 2>/dev/null; then
  echo "✅ Signed with timestamp"
else
  echo "⚠️  Timestamp failed, signing without..."
  productsign --sign "$CERT_NAME" "$TEST_PKG" "$SIGNED_PKG"
  echo "✅ Signed without timestamp"
fi
echo ""

# Verify
echo "Verifying signature..."
pkgutil --check-signature "$SIGNED_PKG"
echo ""

# Cleanup
echo "Cleaning up..."
security delete-keychain "$TEMP_KEYCHAIN"
rm -f "$TEMP_P12"

echo ""
echo "✅ Local signing test complete!"
echo "Signed package: $SIGNED_PKG"
EOF

chmod +x test-signing-locally.sh
```

### Run Local Test

```bash
# Test the signing process locally
./test-signing-locally.sh
```

---

## Troubleshooting CI/CD Signing

### Issue: "No identity found"

```yaml
# Problem: Certificate not imported correctly

# Solution: Check base64 encoding
- name: Debug certificate
  run: |
    echo "$APPLE_SIGNING_CERTIFICATE" | base64 --decode > cert.p12
    file cert.p12  # Should say "data" not "ASCII text"
```

### Issue: "User interaction required"

```yaml
# Problem: Keychain locked or needs permission

# Solution: Ensure partition list is set
- name: Fix keychain permissions
  run: |
    security set-key-partition-list -S apple-tool:,apple: \
      -s -k "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
```

### Issue: "Timestamp failed"

```yaml
# Problem: Apple timestamp server unavailable or self-signed cert

# Solution: Fallback to no timestamp
if productsign --sign "$CERT" --timestamp input.pkg output.pkg; then
  echo "Signed with timestamp"
else
  productsign --sign "$CERT" input.pkg output.pkg
  echo "Signed without timestamp"
fi
```

---

## Verify Signed Packages in CI

Add verification step after signing:

```yaml
      - name: Verify signed packages
        run: |
          echo "=== Verifying Signed Packages ==="
          for pkg in dist/pkg_artifacts/*.pkg; do
            echo ""
            echo "Package: $(basename "$pkg")"
            
            # Check signature
            if pkgutil --check-signature "$pkg" 2>&1 | grep -q "signed"; then
              echo "✅ Package is signed"
              pkgutil --check-signature "$pkg"
            else
              echo "⚠️  Package is NOT signed"
            fi
          done
```

---

## What Success Looks Like

### With Self-Signed Certificate

```
✅ Signing credentials found
✅ Available Signing Identities
  1) ABC123... "My Test Installer Certificate"
✅ Using certificate: My Test Installer Certificate
✅ Signing: mycli-1.0.0-macos-arm64.pkg
⚠️  Timestamp failed, signing without...
✅ Signed without timestamp: mycli-1.0.0-macos-arm64-signed.pkg
Package "mycli-1.0.0-macos-arm64.pkg":
   Status: signed by untrusted certificate
   Certificate Chain:
    1. My Test Installer Certificate
✅ Replaced unsigned with signed version
✅ Signing Complete
```

### With Apple Developer ID (Production)

```
✅ Signing credentials found
✅ Available Signing Identities
  1) ABC123... "Developer ID Installer: Your Name (TEAM123)"
✅ Using certificate: Developer ID Installer: Your Name (TEAM123)
✅ Signing: mycli-1.0.0-macos-arm64.pkg
✅ Signed with timestamp: mycli-1.0.0-macos-arm64-signed.pkg
Package "mycli-1.0.0-macos-arm64.pkg":
   Status: signed by a certificate trusted by macOS
   Certificate Chain:
    1. Developer ID Installer: Your Name (TEAM123)
    2. Developer ID Certification Authority
    3. Apple Root CA
✅ Replaced unsigned with signed version
✅ Signing Complete
```

---

## Next Steps

You've now learned:

- ✅ How to add conditional signing to GitHub Actions
- ✅ How to test with self-signed certificates
- ✅ How to verify signing in CI/CD
- ✅ How to troubleshoot common signing issues

**Continue to:**

1. `05-signed-vs-unsigned.md` - User experience comparison
2. `06-prepare-for-production.md` - Ready for real Apple Developer ID

---

## Cleanup Test Secrets (When Done Testing)

```bash
# After testing with self-signed certs
# Remove test secrets from GitHub before adding real ones

# Settings → Secrets and variables → Actions
# Delete: APPLE_SIGNING_CERTIFICATE (test version)
# Delete: APPLE_CERT_PASSWORD (test version)

# Later, add real Apple Developer ID secrets with same names
```

**You're ready for production signing! 🎓**
