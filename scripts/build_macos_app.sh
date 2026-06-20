#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-$(python3 -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])' 2>/dev/null || echo "0.1.0")}"
SRC_DIR="$ROOT_DIR/macos/OpenCarStreamMenuBar"
DIST_DIR="$ROOT_DIR/dist"
BUILD_DIR="$ROOT_DIR/build/macos"
APP_DIR="$BUILD_DIR/OpenCarStream.app"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"
DMG_STAGING="$BUILD_DIR/dmg"
DMG_PATH="$DIST_DIR/OpenCarStream-$VERSION.dmg"
ARCH="$(uname -m)"

mkdir -p "$DIST_DIR"
rm -rf "$BUILD_DIR"
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR" "$DMG_STAGING"

cp "$SRC_DIR/Info.plist" "$CONTENTS_DIR/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$CONTENTS_DIR/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $VERSION" "$CONTENTS_DIR/Info.plist"

echo "Compiling OpenCarStream.app..."
swiftc \
  -O \
  -parse-as-library \
  -target "$ARCH-apple-macos13.0" \
  "$SRC_DIR/OpenCarStreamMenuBarApp.swift" \
  -o "$MACOS_DIR/OpenCarStream"

chmod 0755 "$MACOS_DIR/OpenCarStream"

cp -R "$APP_DIR" "$DMG_STAGING/OpenCarStream.app"
ln -s /Applications "$DMG_STAGING/Applications"

rm -f "$DMG_PATH"
echo "Building $DMG_PATH..."
hdiutil create \
  -volname "OpenCarStream" \
  -srcfolder "$DMG_STAGING" \
  -ov \
  -format UDZO \
  "$DMG_PATH"

shasum -a 256 "$DMG_PATH"
