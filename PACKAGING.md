# Packaging OpenCarStream

## Python CLI

Install from the repo:

```bash
python3 -m pip install .
opencarstream serve --port 33333 --config-dir ./config
```

The legacy entry point still works:

```bash
python3 server.py
```

## Release Artifacts

Build the CLI package, menu-bar app DMG, and refresh cask SHA values:

```bash
scripts/build_release_artifacts.sh 0.1.0
```

Artifacts are written to `dist/`:

```text
OpenCarStreamCLI-0.1.0.pkg
OpenCarStream-0.1.0.dmg
```

For local development, the app build is ad-hoc signed and the cask removes
Homebrew's quarantine attribute after installation. For public distribution,
use a Developer ID Application certificate and notarize the DMG:

```bash
export OPENCARSTREAM_SIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)"
export OPENCARSTREAM_NOTARY_PROFILE="opencarstream-notary"
scripts/build_macos_app.sh 0.1.0
scripts/update_cask_shas.sh 0.1.0
```

Create the notary profile once with:

```bash
xcrun notarytool store-credentials opencarstream-notary \
  --apple-id "you@example.com" \
  --team-id "TEAMID" \
  --password "app-specific-password"
```

After notarization is working, remove the temporary quarantine-removal
`postflight` block from `Casks/opencarstream.rb`.

Upload both files to the matching GitHub release:

```text
https://github.com/trinityhades/opencarstream/releases/tag/v0.1.0
```

## Homebrew Formula

The tap formula lives at `Formula/opencarstream.rb`.

Before publishing:

1. Create and push a release tag, for example `v0.1.0`.
2. Download the source tarball and calculate its SHA:

```bash
curl -L -o opencarstream-0.1.0.tar.gz \
  https://github.com/trinityhades/opencarstream/archive/refs/tags/v0.1.0.tar.gz
shasum -a 256 opencarstream-0.1.0.tar.gz
```

3. Update `Formula/opencarstream.rb` if the source tarball SHA changed.
4. Put the formula in the tap repo, usually `homebrew-opencarstream`.

Local test:

```bash
brew install --build-from-source ./Formula/opencarstream.rb
opencarstream serve --port 33333
```

The formula installs FFmpeg, Node, yt-dlp, the Python CLI, and OGV.js runtime
assets. It also defines a `brew services` service:

```bash
brew services start opencarstream
brew services stop opencarstream
```

## Homebrew Casks

The casks live in `Casks/`:

```text
Casks/opencarstream-cli.rb
Casks/opencarstream.rb
```

`opencarstream-cli` installs the packaged command-line server. `opencarstream`
installs the menu-bar app and depends on the CLI cask.

Prepare a sibling tap repo:

```bash
scripts/prepare_homebrew_tap.sh ../homebrew-opencarstream
```

Users install with:

```bash
brew tap trinityhades/opencarstream
brew trust trinityhades/opencarstream
brew install opencarstream
```

## macOS Menu-Bar App

The Swift source and bundle metadata live in `macos/OpenCarStreamMenuBar/`.
The app starts/stops the CLI server, opens the dashboard, exposes basic
settings, writes logs under the configured app support directory, and stays in
the menu bar through `LSUIElement`.
