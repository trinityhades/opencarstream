#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-$(python3 -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])' 2>/dev/null || echo "0.1.0")}"
CLI_PKG="$ROOT_DIR/dist/OpenCarStreamCLI-$VERSION.pkg"
APP_DMG="$ROOT_DIR/dist/OpenCarStream-$VERSION.dmg"

if [ ! -f "$CLI_PKG" ]; then
  echo "Missing $CLI_PKG" >&2
  exit 1
fi

if [ ! -f "$APP_DMG" ]; then
  echo "Missing $APP_DMG" >&2
  exit 1
fi

CLI_SHA="$(shasum -a 256 "$CLI_PKG" | awk '{print $1}')"
APP_SHA="$(shasum -a 256 "$APP_DMG" | awk '{print $1}')"

ruby -pi -e 'if $. == 3; puts "  sha256 \"'"$CLI_SHA"'\""; $_ = ""; end' "$ROOT_DIR/Casks/opencarstream-cli.rb"
ruby -pi -e 'if $. == 3; puts "  sha256 \"'"$APP_SHA"'\""; $_ = ""; end' "$ROOT_DIR/Casks/opencarstream.rb"

echo "Updated Casks/opencarstream-cli.rb: $CLI_SHA"
echo "Updated Casks/opencarstream.rb: $APP_SHA"
