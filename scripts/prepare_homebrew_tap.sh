#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAP_DIR="${1:-$ROOT_DIR/../homebrew-opencarstream}"

mkdir -p "$TAP_DIR/Formula" "$TAP_DIR/Casks"
cp "$ROOT_DIR/Formula/opencarstream.rb" "$TAP_DIR/Formula/opencarstream.rb"
cp "$ROOT_DIR/Casks/opencarstream.rb" "$TAP_DIR/Casks/opencarstream.rb"
cp "$ROOT_DIR/Casks/opencarstream-cli.rb" "$TAP_DIR/Casks/opencarstream-cli.rb"

cat > "$TAP_DIR/README.md" <<'MD'
# Homebrew Tap for OpenCarStream

Install the menu-bar app:

```bash
brew tap trinityhades/opencarstream
brew install --cask opencarstream
```

Install only the CLI package:

```bash
brew tap trinityhades/opencarstream
brew install --cask opencarstream-cli
```

Install the formula variant:

```bash
brew install opencarstream
```
MD

echo "Prepared tap files in $TAP_DIR"
