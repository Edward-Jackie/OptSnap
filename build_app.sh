#!/bin/bash
# Build OptSnap.app — manual .app bundle creation

set -e

APP_NAME="OptSnap"
APP_PATH="build/${APP_NAME}.app"
CONTENTS="${APP_PATH}/Contents"
MACOS="${CONTENTS}/MacOS"
RESOURCES="${CONTENTS}/Resources"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Building ${APP_NAME}.app ==="
echo "Project dir: ${PROJECT_DIR}"

# Clean previous build
rm -rf "build"
mkdir -p "${MACOS}" "${RESOURCES}"

# Store project root for the launcher to find src/
echo "${PROJECT_DIR}" > "${RESOURCES}/_PROJECT_ROOT"

# Create Info.plist
cat > "${CONTENTS}/Info.plist" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>OptSnap</string>
    <key>CFBundleDisplayName</key>
    <string>OptSnap</string>
    <key>CFBundleIdentifier</key>
    <string>com.optsnap.app</string>
    <key>CFBundleVersion</key>
    <string>0.1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>0.1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>NSHumanReadableCopyright</key>
    <string>OptSnap</string>
    <key>NSRequiresAquaSystemAppearance</key>
    <true/>
    <key>NSAccessibilityUsageDescription</key>
    <string>OptSnap needs Accessibility permission to move and resize windows.</string>
</dict>
</plist>
EOF

# Create Python launcher
VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python3"

cat > "${RESOURCES}/__boot__.py" << PYEOF
#!/usr/bin/env python3
"""OptSnap launcher — resolves paths and starts the app."""

import os
import sys

# Read project root from embedded file
resources = os.path.dirname(os.path.abspath(__file__))
project_root_file = os.path.join(resources, '_PROJECT_ROOT')
if os.path.exists(project_root_file):
    with open(project_root_file) as f:
        project_root = f.read().strip()
else:
    project_root = os.path.join(os.path.dirname(resources), '..')
    project_root = os.path.abspath(project_root)

src_dir = os.path.join(project_root, 'src')
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

os.chdir(project_root)

from optsnap.__main__ import main
main()
PYEOF

# Create PkgInfo
echo -n "APPL????" > "${CONTENTS}/PkgInfo"

# Create shell launcher (use absolute path)
RESOURCES_ABS="$(cd "${RESOURCES}" && pwd)"
cat > "${MACOS}/OptSnap" << SHEOF
#!/bin/bash
exec "${VENV_PYTHON}" "${RESOURCES_ABS}/__boot__.py"
SHEOF

chmod +x "${MACOS}/OptSnap"

echo "=== ${APP_NAME}.app built at ${APP_PATH} ==="
echo "Run: open ${APP_PATH}"
