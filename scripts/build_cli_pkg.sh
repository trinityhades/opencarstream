#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-$(python3 -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])' 2>/dev/null || echo "0.1.0")}"
DIST_DIR="$ROOT_DIR/dist"
WORK_DIR="$(mktemp -d)"
STAGE_DIR="$WORK_DIR/stage"
VENDOR_DIR="$STAGE_DIR/usr/local/lib/opencarstream-cli/vendor"
OGV_DIR="$STAGE_DIR/usr/local/lib/opencarstream-cli/ogv-dist"
BIN_DIR="$STAGE_DIR/usr/local/bin"
SCRIPTS_DIR="$WORK_DIR/scripts"

cleanup() {
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

mkdir -p "$DIST_DIR" "$VENDOR_DIR" "$OGV_DIR" "$BIN_DIR" "$SCRIPTS_DIR"

echo "Installing Python package into cask payload..."
python3 -m pip install --upgrade --target "$VENDOR_DIR" "$ROOT_DIR"

echo "Installing OGV.js runtime assets..."
npm install --prefix "$WORK_DIR" ogv --no-save
cp -R "$WORK_DIR/node_modules/ogv/dist/." "$OGV_DIR/"

cat > "$BIN_DIR/opencarstream" <<'SH'
#!/bin/bash
set -e

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
export PYTHONPATH="/usr/local/lib/opencarstream-cli/vendor"
export OGV_DIST_DIR="/usr/local/lib/opencarstream-cli/ogv-dist"

if [ -x "/opt/homebrew/opt/python@3.12/bin/python3.12" ]; then
  PYTHON_BIN="/opt/homebrew/opt/python@3.12/bin/python3.12"
elif [ -x "/usr/local/opt/python@3.12/bin/python3.12" ]; then
  PYTHON_BIN="/usr/local/opt/python@3.12/bin/python3.12"
else
  PYTHON_BIN="python3"
fi

exec "$PYTHON_BIN" -m opencarstream "$@"
SH
chmod 0755 "$BIN_DIR/opencarstream"

cat > "$SCRIPTS_DIR/postinstall" <<'SH'
#!/bin/bash
set -e
mkdir -p "/Users/Shared/OpenCarStream"
exit 0
SH
chmod 0755 "$SCRIPTS_DIR/postinstall"

PKG_PATH="$DIST_DIR/OpenCarStreamCLI-$VERSION.pkg"
echo "Building $PKG_PATH..."
pkgbuild \
  --root "$STAGE_DIR" \
  --scripts "$SCRIPTS_DIR" \
  --identifier "com.opencarstream.cli" \
  --version "$VERSION" \
  --install-location "/" \
  "$PKG_PATH"

shasum -a 256 "$PKG_PATH"
