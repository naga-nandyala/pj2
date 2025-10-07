# Quick Start: PKG Signing with GitHub Actions

**Learn macOS PKG signing using GitHub Actions - no Mac required!**

## ⚡ 5-Minute Quick Start

### Step 1: Review What You Have (1 min)

You already have these workflows created:
- ✅ `pkgsign-build-installer.yml` - Will build and sign PKGs
- ✅ `create-self-signed-cert.yml` - Will create test certificate

### Step 2: Create Self-Signed Certificate (2 min)

From your terminal:

```bash
# 1. Commit the new workflow
git add .github/workflows/create-self-signed-cert.yml
git commit -m "Add self-signed cert creation workflow"
git push

# 2. Open GitHub Actions in browser
# Go to: https://github.com/YOUR_USERNAME/pj2/actions
```

In GitHub:
1. Click "Create Self-Signed Certificate (Learning)" workflow
2. Click "Run workflow" button (top right)
3. Click green "Run workflow" button
4. Wait ~30 seconds for completion ⏳

### Step 3: Copy Certificate to Secrets (2 min)

1. Click on the completed workflow run
2. Expand the "Create self-signed certificate" step
3. Scroll down - you'll see a long base64 string
4. **Copy the entire base64 string** (might be 500+ characters)
5. Go to: `https://github.com/YOUR_USERNAME/pj2/settings/secrets/actions`
6. Click "New repository secret"
7. Add first secret:
   - Name: `APPLE_SIGNING_CERTIFICATE`
   - Value: *paste the base64 string*
8. Click "Add secret"
9. Click "New repository secret" again
10. Add second secret:
    - Name: `APPLE_CERT_PASSWORD`
    - Value: `test123`
11. Click "Add secret"

✅ **Done! Your self-signed certificate is now ready!**

---

## 🚀 Test Signing (5 minutes)

### Option A: Manual Trigger

```bash
# Open GitHub Actions in browser
# https://github.com/YOUR_USERNAME/pj2/actions/workflows/pkgsign-build-installer.yml
```

1. Click "Run workflow" button
2. Select branch: `main`
3. Click "Run workflow"
4. Wait ~3-5 minutes for build
5. Check logs for signing success!

### Option B: Tag-Based Release

```bash
# Create and push a test tag
git tag v0.1.0-test-signing
git push origin v0.1.0-test-signing

# Watch in browser
# https://github.com/YOUR_USERNAME/pj2/actions
```

---

## ✅ Verify Signing Worked

### In Workflow Logs

Look for these success indicators:

```
✅ Signing credentials found
✅ Available Signing Identities
  1) ABCD1234... "My Test Installer Certificate"
✅ Using certificate: My Test Installer Certificate
✅ Signing: mycli-1.0.0-macos-arm64.pkg
⚠️  Timestamp failed, signing without...
✅ Signed without timestamp
Package "mycli-1.0.0-macos-arm64.pkg":
   Status: signed by untrusted certificate
   Certificate Chain:
    1. My Test Installer Certificate
✅ Replaced unsigned with signed version
✅ Signing Complete
```

**If you see these ✅ markers - SUCCESS! You've signed your first PKG!** 🎉

---

## 📦 Download Signed Package (Optional)

```bash
# Download the signed PKG to examine it
VERSION="0.1.0-test-signing"
ARCH="arm64"  # or "x86_64"

# Download using curl or wget
curl -L -o mycli-signed.pkg \
  "https://github.com/YOUR_USERNAME/pj2/releases/download/v${VERSION}/mycli-${VERSION}-macos-${ARCH}.pkg"

# Check file size (signed should be slightly larger than unsigned)
ls -lh mycli-signed.pkg
```

**Note:** You need macOS to test the `.pkg`, but you now have a signed macOS installer!

---

## 🎓 What You Just Learned

In 5 minutes, you:

- ✅ Created a self-signed certificate in GitHub Actions (macOS runner)
- ✅ Stored it securely in GitHub Secrets
- ✅ Triggered a signing workflow
- ✅ Verified the PKG was signed
- ✅ Downloaded a signed macOS installer

**All without needing a Mac!** ☁️ → 📦

---

## 🧠 Understanding What Happened

### What is the Certificate?

The workflow created:
- **Private key** - Kept secret in GitHub (via base64 encoding)
- **Public certificate** - Self-signed, identifies you as signer
- **Password** - Protects the private key (`test123`)

### Why "Untrusted"?

Your certificate is **self-signed**, not signed by Apple:

```
Your Certificate (self-signed)
    ❌ Not in macOS trust store

vs.

Apple Developer ID Certificate
    → Signed by Developer ID CA
    → Signed by Apple Root CA
    ✅ Pre-installed in every macOS
```

**This is expected for Phase 2 learning!**

### User Experience

When someone tries to install your signed (but untrusted) PKG:

- ⚠️ macOS still shows: "from an unidentified developer"
- Same warnings as unsigned
- **But the PKG IS signed** - you can verify integrity

**For production (no warnings):** Need Apple Developer ID ($99/year)

---

## 📚 What to Read Next

Now that signing works, understand the concepts:

1. **[05-signed-vs-unsigned.md](05-signed-vs-unsigned.md)**
   - Why self-signed still shows warnings
   - Certificate chain explained
   - User experience comparison

2. **[04-test-signing-workflow.md](04-test-signing-workflow.md)**
   - Deep dive into GitHub Actions automation
   - Workflow implementation details

---

## 🔧 Troubleshooting

### Workflow Failed: "No identity found"

**Problem:** Certificate not in GitHub secrets.

**Solution:**
1. Go to: `https://github.com/naga-nandyala/pj2/settings/secrets/actions`
2. Verify you have both secrets:
   - `APPLE_SIGNING_CERTIFICATE`
   - `APPLE_CERT_PASSWORD`
3. If missing, re-run "Create Self-Signed Certificate" workflow
4. Copy secrets again from logs

### Workflow Skipped Signing

**Expected behavior:**
```
⚠️  Signing credentials not found - will build unsigned packages
```

**Solution:** Same as above - add the secrets.

### Wrong Base64 Value

**Problem:** Copied wrong text, certificate import fails.

**Solution:**
1. Re-run "Create Self-Signed Certificate" workflow
2. Look for the section that says:
   ```
   Secret Name: APPLE_SIGNING_CERTIFICATE
   Secret Value (base64):
   <VERY LONG STRING HERE>
   ```
3. Copy **only** the long base64 string (no extra text)

---

## 🎯 Next Challenges

### Challenge 1: Sign Both Architectures

Your workflow already builds both arm64 and x86_64. Check that **both** are signed:

```
Signing: mycli-1.0.0-macos-arm64.pkg ✅
Signing: mycli-1.0.0-macos-x86_64.pkg ✅
```

### Challenge 2: Update Homebrew Cask

After successful release, the `pkgsign-update-homebrew-cask.yml` workflow should:
- Download signed PKGs
- Calculate SHA256
- Update your Homebrew tap

Check: `https://github.com/naga-nandyala/homebrew-mycli-app`

### Challenge 3: Test Installation (Need a Mac)

If you can borrow a Mac:
1. Download the signed PKG
2. Try to open it
3. See the Gatekeeper warning (expected for self-signed)
4. Verify signature: `pkgutil --check-signature mycli-*.pkg`

---

## 💡 Pro Tips

### Tip 1: Use GitHub CLI

For easier workflow management:

```bash
# Install GitHub CLI (platform-specific)
# macOS: brew install gh
# Linux: See https://github.com/cli/cli#installation  
# Windows: winget install GitHub.cli

# Watch workflow runs
gh run watch

# Trigger workflows
gh workflow run "pkgsign-build-installer.yml"
```

### Tip 2: Use GitHub Codespaces

For a cloud development environment:

```bash
# Create a codespace directly from GitHub
# Navigate to your repo → Code button → Codespaces tab → New codespace
# You get a full VS Code environment in the browser
```

### Tip 3: Automate with Tags

```bash
# Set up automatic signing on version tags
git tag -a v1.0.0 -m "Release version 1.0.0"
git push origin v1.0.0

# Workflow automatically:
# 1. Builds PKG installers
# 2. Signs them (if secrets present)
# 3. Creates GitHub release
# 4. Updates Homebrew cask
```

---

## 📊 Your Progress

- [x] ✅ Phase 1 Complete - Unsigned PKG building
- [x] ✅ Phase 2 Started - Self-signed certificate created
- [x] ✅ Phase 2 Tested - Signed first PKG
- [ ] 📚 Phase 2 Understanding - Read comparison guides
- [ ] 💰 Phase 3 Decision - Apple Developer Program?
- [ ] 🚀 Phase 3 Production - Deploy trusted signatures

**You're 50% through the learning journey!** 🎓

---

## 🎉 Congratulations

You've successfully learned macOS PKG signing using GitHub Actions!

**Key Takeaways:**

- ✅ No Mac needed for learning or production
- ✅ GitHub Actions handles all macOS-specific tools
- ✅ Self-signed certificates work for testing
- ✅ Same workflow scales to production

**Next Steps:**

1. Read the comparison guide (05-signed-vs-unsigned.md)
2. Decide if $99/year is worth it for your project
3. Study the automation guide (04-test-signing-workflow.md)

---

## Quick Commands Reference

```bash
# Create certificate - Open in browser
# https://github.com/YOUR_USERNAME/pj2/actions/workflows/create-self-signed-cert.yml

# Test signing
git tag v0.1.0-test
git push origin v0.1.0-test

# Watch results - Open in browser
# https://github.com/YOUR_USERNAME/pj2/actions

# Manage secrets - Open in browser
# https://github.com/YOUR_USERNAME/pj2/settings/secrets/actions

# View releases - Open in browser
# https://github.com/YOUR_USERNAME/pj2/releases
```

**Happy signing! 🔐**
