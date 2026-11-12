#!/bin/zsh
set -e
cd "$(dirname "$0")/.."
APP="Calm Week.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
swiftc -O mac/CalmWeek.swift -o "$APP/Contents/MacOS/CalmWeek"
cp mac/AppIcon.icns "$APP/Contents/Resources/AppIcon.icns"
cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Calm Week</string>
  <key>CFBundleIdentifier</key><string>local.calmweek</string>
  <key>CFBundleExecutable</key><string>CalmWeek</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
  <key>CalmWeekProject</key><string>$PWD</string>
</dict>
</plist>
EOF
codesign --force --sign - "$APP"
echo "Built $APP"
