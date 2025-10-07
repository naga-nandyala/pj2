# PKG Signing - GitHub Actions Learning Path

> **Learn macOS PKG signing using GitHub Actions**
> 
> No Mac required! Everything runs in the cloud.

---

## 🚀 Start Here

### **[QUICKSTART.md](QUICKSTART.md)** ⭐

**Complete this first** - Gets you signing PKGs in 5 minutes:
1. Generate self-signed certificate in GitHub Actions
2. Store certificate in GitHub secrets
3. Trigger automated signing workflow
4. Verify signed PKG in logs

**Time:** 5 minutes | **Cost:** Free | **Mac needed:** No ❌

---

## 📚 Documentation

### 1. [QUICKSTART.md](QUICKSTART.md) ⭐ **START HERE**

**Your complete quick start guide**

- Step-by-step certificate generation
- GitHub secrets configuration
- First signed PKG in 5 minutes
- Troubleshooting guide
- Terminal commands
- Real-time workflow monitoring

**When to use:** Always start here

---

### 2. [04-test-signing-workflow.md](04-test-signing-workflow.md)

**Deep dive into GitHub Actions signing**

- Complete workflow YAML reference
- Conditional signing implementation
- Certificate import in CI/CD
- Signing step breakdown
- Error handling patterns
- Production-ready examples

**When to use:** After quickstart, when you want to understand the automation

---

## 🎯 Learning Path

### ✅ Phase 1: Complete
- Built unsigned PKG workflows
- Created `pkgsign-*` workflows for signing

### 🔄 Phase 2: In Progress (Self-Signed Learning)

**Goal:** Learn signing mechanics before paying $99/year

```
Step 1: Generate Certificate (5 min)
  └─> Use QUICKSTART.md
  └─> Run create-self-signed-cert.yml workflow
  └─> Copy base64 to GitHub secrets

Step 2: First Signed PKG (5 min)
  └─> Push a tag or trigger workflow
  └─> Watch signing in real-time
  └─> Verify in workflow logs

Step 3: Master Automation (30 min)
  └─> Study 04-test-signing-workflow.md
  └─> Understand conditional signing
  └─> Learn error handling
```

**Total Time:** ~45 minutes | **Cost:** Free

### 💰 Phase 3: Future (Production - Optional)

**Goal:** Deploy PKGs with zero macOS warnings

```
Decision Point: Is $99/year worth it for your project?
  
  ✅ YES → Enroll in Apple Developer Program
    └─> Generate Developer ID Installer certificate
    └─> Replace APPLE_SIGNING_CERTIFICATE secret
    └─> Same workflows, now trusted!
  
  ❌ NO → Continue with self-signed
    └─> PKGs are signed (integrity verified)
    └─> Users still see Gatekeeper warnings
    └─> Fine for internal/test distributions
```

**Considerations:**
- Number of users installing your app
- Professional image requirements
- Distribution method (Homebrew, direct download)
- Budget constraints

---

## 🛠️ Repository Structure

```
pj2/
├── .github/workflows/
│   ├── create-self-signed-cert.yml    # Generate certificate in cloud
│   ├── pkgsign-build-installer.yml    # Build & sign PKG
│   ├── pkgsign-test-homebrew-cask.yml # Test Homebrew installation
│   ├── pkgsign-test-sudoinstaller.yml # Test direct installation
│   └── pkgsign-update-homebrew-cask.yml # Auto-update Homebrew tap
│
├── docs/signing/
│   ├── README.md                       # This file
│   ├── QUICKSTART.md                   # ⭐ Start here
│   └── 04-test-signing-workflow.md    # Automation deep dive
│
└── scripts/
    └── build_pkgnew_installer.py      # PKG builder (used by workflows)
```

---

## 🎓 What You'll Learn

### Technical Skills

- ✅ macOS PKG signing with `productsign`
- ✅ Certificate management in GitHub Actions
- ✅ Self-signed vs Apple Developer ID certificates
- ✅ GitHub secrets for secure credential storage
- ✅ Conditional workflow execution
- ✅ Cross-platform development (any OS → macOS cloud runners)

### Concepts
- ✅ Public key cryptography basics
- ✅ Certificate chain of trust
- ✅ macOS Gatekeeper system
- ✅ Code signing vs notarization (different!)
- ✅ CI/CD security best practices

### Real-World Skills
- ✅ Professional software distribution
- ✅ User trust building
- ✅ Automated release workflows
- ✅ Multi-architecture builds (arm64 + x86_64)

---

## 💡 Key Concepts

### What is PKG Signing?

```
Unsigned PKG                 Self-Signed PKG              Apple Developer ID PKG
     📦                            🔏📦                           ✅📦
     
⚠️  Unknown creator          ⚠️  Self-signed creator         ✅ Verified creator
❌ Could be modified         ✅ Integrity verified           ✅ Integrity verified
❌ Gatekeeper warns          ⚠️  Gatekeeper warns            ✅ Gatekeeper allows
❌ Users hesitant            ⚠️  Users hesitant              ✅ Users trust
```

### Certificate Types

| Type | Cost | Trust | Best For | Warnings |
|------|------|-------|----------|----------|
| **Unsigned** | Free | None | Development | ⚠️⚠️⚠️ |
| **Self-Signed** | Free | Self-only | Learning, Testing | ⚠️⚠️ |
| **Apple Dev ID** | $99/year | macOS Trust Store | Production | ✅ None |

### GitHub Actions Advantage

**Why GitHub Actions?**

```
Your Local Machine                 GitHub Actions (Cloud)
     💻                                    ☁️
      |                                     |
      |--- git push ------------------->   |
      |                                     |
      |                              [macOS runner spins up]
      |                                     |
      |                              [Imports certificate]
      |                                     |
      |                              [Runs productsign]
      |                                     |
      |                              [Verifies signature]
      |                                     |
      |<---- Signed PKG uploaded -----     |
      
✅ No Mac needed
✅ Same tools as production
✅ Free macOS runners
✅ Automatic & repeatable
```

---

## 🔧 Quick Commands

### From Your Terminal

```bash
# Generate certificate (first time) - Open in browser
# https://github.com/YOUR_USERNAME/pj2/actions/workflows/create-self-signed-cert.yml

# Trigger signing workflow
git tag v0.1.0-test
git push origin v0.1.0-test

# Watch workflows - Open in browser
# https://github.com/YOUR_USERNAME/pj2/actions

# Manage secrets - Open in browser
# https://github.com/YOUR_USERNAME/pj2/settings/secrets/actions

# View releases - Open in browser
# https://github.com/YOUR_USERNAME/pj2/releases
```

### Using GitHub CLI (Optional)

```bash
# Install GitHub CLI (platform-specific)
# macOS: brew install gh
# Linux: See https://github.com/cli/cli#installation
# Windows: winget install GitHub.cli

# Trigger workflow
gh workflow run "pkgsign-build-installer.yml"

# Watch in real-time
gh run watch

# View latest run
gh run view
```

---

## 🎯 Success Indicators

### ✅ You're Ready for Phase 2 When:

- [ ] You have the workflows committed
- [ ] You've read QUICKSTART.md
- [ ] You understand local machine → GitHub Actions → macOS concept

### ✅ Phase 2 Complete When:
- [ ] Certificate generated in GitHub Actions
- [ ] Secrets added to repository
- [ ] First signed PKG created
- [ ] Verified signature in logs
- [ ] Understand self-signed limitations (still shows warnings)

### ✅ Ready for Phase 3 When:
- [ ] Comfortable with signing automation
- [ ] Decided $99/year is worth it
- [ ] Enrolled in Apple Developer Program
- [ ] Have Apple Developer ID certificate

---

## 🆘 Troubleshooting

### "Workflow doesn't sign PKGs"

**Expected behavior:**
```
⚠️  Signing credentials not found - will build unsigned packages
```

**Solution:** Add GitHub secrets:
1. Run `create-self-signed-cert.yml` workflow
2. Copy base64 from logs
3. Add `APPLE_SIGNING_CERTIFICATE` and `APPLE_CERT_PASSWORD` secrets

---

### "Certificate import failed"

**Check:**
- Secret name exactly: `APPLE_SIGNING_CERTIFICATE` (no typos)
- Secret value is the full base64 string (might be 500+ characters)
- Password secret: `APPLE_CERT_PASSWORD` = `test123`

**Solution:** Re-run certificate generation workflow, copy again carefully

---

### "Signed but still shows warnings"

**Expected!** Self-signed certificates work differently:

```
Self-Signed Certificate:
  ✅ PKG is signed (integrity protected)
  ✅ Can verify signature with pkgutil
  ❌ Not in macOS trust store
  ⚠️  Gatekeeper still warns users
  
Purpose: Learning & testing before $99 investment
```

**Solution:** This is correct behavior. Read `05-signed-vs-unsigned.md` to understand why.

---

## 📖 Additional Resources

### Official Apple Documentation
- [Developer ID Installer Certificates](https://developer.apple.com/developer-id/)
- [Notarizing macOS Software](https://developer.apple.com/documentation/security/notarizing_macos_software_before_distribution)
- [Gatekeeper Overview](https://support.apple.com/guide/security/gatekeeper-and-runtime-protection-sec5599b66df/web)

### GitHub Actions
- [Using Secrets in Workflows](https://docs.github.com/en/actions/security-guides/encrypted-secrets)
- [macOS Runners](https://docs.github.com/en/actions/using-github-hosted-runners/about-github-hosted-runners#supported-runners-and-hardware-resources)

### Tools Used
- `productsign` - Sign PKG installers
- `pkgutil` - Verify PKG signatures
- `security` - Keychain management
- `openssl` - Certificate generation (self-signed)

---

## 🎉 Your Learning Journey

```
[✅] Phase 1: Building
      └─> Created unsigned PKG workflows
      └─> Tested builds on GitHub Actions
      └─> Multi-architecture support (arm64 + x86_64)

[🔄] Phase 2: Learning (You Are Here!)
      ├─> [ ] Generate self-signed certificate
      ├─> [ ] Sign first PKG
      ├─> [ ] Understand certificate chains
      └─> [ ] Master automation

[📋] Phase 3: Production (Optional)
      ├─> [ ] Decide on Apple Developer Program
      ├─> [ ] Get Developer ID certificate
      ├─> [ ] Replace test certificate
      └─> [ ] Deploy trusted PKGs
```

**Next Step:** Open [QUICKSTART.md](QUICKSTART.md) and get your first signed PKG in 5 minutes! 🚀

---

## 📝 Notes

- **No Mac Required:** Everything in this guide works using GitHub Actions
- **Cost:** Phase 2 is free; Phase 3 requires Apple Developer Program ($99/year)
- **Time Investment:** ~1 hour to learn, 5 minutes to implement
- **Scalability:** Same workflows work for 1 user or 10,000 users

**Questions?** Check the troubleshooting sections in each guide, or review the workflow logs in GitHub Actions.

**Happy signing! 🔐**
