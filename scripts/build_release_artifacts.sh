#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-$(python3 -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])' 2>/dev/null || echo "0.1.0")}"

"$ROOT_DIR/scripts/build_cli_pkg.sh" "$VERSION"
"$ROOT_DIR/scripts/build_macos_app.sh" "$VERSION"
"$ROOT_DIR/scripts/update_cask_shas.sh" "$VERSION"

echo
echo "Release artifacts:"
ls -lh "$ROOT_DIR/dist"
