# mycli-app-naga

A demonstration command-line interface that mimics a mini Azure CLI experience, including optional authentication helpers for Azure Active Directory.

## Project layout

```text
├── pyproject.toml         # Project metadata and entry point definition
├── src/mycli_app          # CLI implementation
├── scripts/build_pyinstaller_bundle.py  # Utility for packaging a PyInstaller-based bundle
├── scripts/build_zipapp_bundle.py # Utility for packaging a zipapp bundle (no PyInstaller)
└── README.md
```

## Getting started

```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\Activate.ps1 on Windows
pip install --upgrade pip
pip install -e .[dev]
```

Run the CLI locally:

```bash
mycli --help
```

## Building release bundles

### PyInstaller bundle (includes Python runtime)

Use the helper script in `scripts/` to create a Homebrew Cask-friendly tarball. The script builds in an isolated virtual environment, installs the project (and optional extras), freezes the CLI with PyInstaller, stages a `bin/mycli` layout, and writes a checksum file for easy Cask updates.

```bash
python scripts/build_pyinstaller_bundle.py \
  --extras broker \
  --platform-tag macos-universal2
```

Outputs are written to `dist/artifacts/`, for example:

```text
dist/artifacts/
  mycli-macos-universal2/
    bin/mycli
  mycli-macos-universal2.tar.gz
  mycli-macos-universal2.tar.gz.sha256
```

Pass `--onedir` if you prefer PyInstaller's directory layout instead of a single-file binary, or set `--extras ""` to skip installing optional dependency groups.

### Zipapp bundle (requires system Python)

If you prefer to avoid PyInstaller, the companion script `scripts/build_zipapp_bundle.py` produces a lighter-weight archive using [`shiv`](https://github.com/linkedin/shiv). The resulting bundle expects Python 3.8+ to be available on the target machine but otherwise follows the same directory structure and checksum workflow.

```bash
python scripts/build_zipapp_bundle.py \
  --extras broker \
  --platform-tag macos-universal2
```

Example contents:

```text
dist/artifacts/
  mycli-macos-universal2/
    bin/mycli
    bin/mycli.bat
    libexec/mycli.pyz
  mycli-macos-universal2.tar.gz
  mycli-macos-universal2.tar.gz.sha256
```

Homebrew users typically rely on the `bin/mycli` launcher, which defers to the system `python3`. Ensure your documentation calls out the Python requirement if you distribute this variant.

### Virtualenv bundle (ships a full Python runtime)

To package the CLI together with an embedded Python interpreter, use `scripts/build_venv_bundle.py`. This script creates an isolated virtual environment, installs the project, and stages the venv under `libexec/`. The resulting tarball is larger than the zipapp but does not require Python to be present on the target machine.

```bash
python scripts/build_venv_bundle.py \
  --extras broker \
  --platform-tag macos-universal2
```

Example contents:

```text
dist/artifacts/
  mycli-macos-universal2/
    bin/mycli
    libexec/mycli-venv/
      bin/python3
      ...
  mycli-macos-universal2.tar.gz
  mycli-macos-universal2.tar.gz.sha256
```

Build this bundle on the operating system you plan to target so the embedded interpreter matches (e.g. run on macOS for the `macos-universal2` artifact). After signing/notarizing, reference it in the same Homebrew Cask structure via `binary "mycli-macos-universal2/bin/mycli"`.

### Signing & notarization

Before distributing the tarball you should:

1. **Codesign** the bundled binary:

   ```bash
   codesign --deep --force --timestamp --options=runtime \
     --sign "Developer ID Application: Example Corp (TEAMID)" \
     dist/artifacts/mycli-macos-universal2/bin/mycli
   ```

2. **Archive** the staging directory again if you signed in-place.
3. **Notarize** the tarball:

   ```bash
   xcrun notarytool submit dist/artifacts/mycli-macos-universal2.tar.gz \
     --apple-id your@apple-id.example \
     --team-id TEAMID \
     --password "app-specific-password" \
     --wait
   ```

4. **Staple** the ticket: `xcrun stapler staple dist/artifacts/mycli-macos-universal2.tar.gz`

Automate these steps in CI to ensure every release is signed consistently.

### Homebrew Cask template

After uploading the tarball (e.g. to a GitHub Release), create or update a Homebrew Cask:

```ruby
cask "mycli" do
  version "1.0.0"
  sha256 "REPLACE_WITH_SHA_FROM_.sha256_FILE"

  url "https://github.com/your-org/mycli-app/releases/download/v#{version}/mycli-macos-universal2.tar.gz"
  name "mycli"
  desc "Mini Azure CLI-style tool"
  homepage "https://github.com/your-org/mycli-app"

  binary "mycli-macos-universal2/bin/mycli"

  caveats <<~EOS
    The bundled binary embeds a Python runtime and msal[broker] support.
    Run `xattr -dr com.apple.quarantine $(brew --prefix)/Caskroom/mycli/#{version}`
    if Gatekeeper warns on first launch.
  EOS
end
```

Use `brew audit --cask --online mycli` and `brew install --cask ./mycli.rb` to vet the definition locally before opening a PR.

## Running tests

The project currently ships without automated tests. Add your preferred test suite under `tests/` and use `pytest` via `pip install .[dev]` to execute them.

## Troubleshooting

* **PyInstaller missing import** – add `--collect-all` or `--hidden-import` flags in `scripts/build_pyinstaller_bundle.py`.
* **Broker login prompts fail on macOS** – ensure the Microsoft Company Portal app is installed and Touch ID is enabled; fallback to `mycli login --use-device-code` if needed.
* **Codesign warnings about entitlements** – double-check your signing identity and include `--options=runtime` to satisfy notarization requirements.
