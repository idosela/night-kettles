#!/bin/sh
# Builds "Night Kettles.saver" with the Xcode Command Line Tools; no Xcode project.
#
#   ./build.sh            build into build/
#   ./build.sh install    build, then copy into ~/Library/Screen Savers
#
# The sprite sheets in saver/Resources are checked in. To redraw them:
#   python3 art/make_sprites.py
set -eu
cd "$(dirname "$0")"

if [ "$(uname)" != Darwin ]; then
    echo "Night Kettles builds on macOS: it links ScreenSaver.framework." >&2
    exit 1
fi

BUNDLE="build/Night Kettles.saver"
rm -rf "$BUNDLE"
mkdir -p "$BUNDLE/Contents/MacOS" "$BUNDLE/Contents/Resources"

xcrun clang -bundle -fobjc-arc -O2 -Wall -Wextra -Wno-unused-parameter \
    -arch arm64 -arch x86_64 -mmacosx-version-min=11.0 \
    -framework ScreenSaver -framework AppKit -framework QuartzCore -framework ImageIO \
    saver/NightKettlesView.m -o "$BUNDLE/Contents/MacOS/NightKettles"

cp saver/Info.plist "$BUNDLE/Contents/Info.plist"
cp saver/Resources/*.png "$BUNDLE/Contents/Resources/"
codesign --force --sign - "$BUNDLE"
echo "Built $BUNDLE"

if [ "${1:-}" = install ]; then
    DEST="$HOME/Library/Screen Savers"
    mkdir -p "$DEST"
    rm -rf "$DEST/Night Kettles.saver"
    cp -R "$BUNDLE" "$DEST/"
    # The host keeps a loaded saver in memory; restart it so the new build shows.
    killall legacyScreenSaver 2>/dev/null || true
    echo "Installed. Pick Night Kettles in System Settings > Screen Saver"
    echo "(quit and reopen System Settings if it was already showing the old build)."
fi
