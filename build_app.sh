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
    <key>CFBundleIconFile</key>
    <string>icon.icns</string>
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

# Copy app icon
if [ -f "${PROJECT_DIR}/assets/icon.icns" ]; then
    cp "${PROJECT_DIR}/assets/icon.icns" "${RESOURCES}/icon.icns"
fi

# Copy menubar icon (template image, all scales)
for f in "${PROJECT_DIR}/src/optsnap/resources"/menubar_icon*.png; do
    [ -f "$f" ] && cp "$f" "${RESOURCES}/"
done

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

# Create shell launcher
#
# 路径必须相对 .app 自身解析，不能硬编码 build/ 的绝对路径：否则把这个 .app 复制到
# /Applications 之后，它仍然去跑 build/ 里那份 __boot__.py —— 用户以为装的是新版本，
# 实际运行的却是别处的旧代码（真实踩过）。
#
# 只有 venv 的 python 是项目内的绝对路径（这个 app 依赖项目 venv，不做独立分发）。
cat > "${MACOS}/OptSnap" << SHEOF
#!/bin/bash
# 解析出 .app 自身所在位置：本脚本在 <app>/Contents/MacOS/ 下
SELF_DIR="\$(cd "\$(dirname "\$0")" && pwd)"
CONTENTS_DIR="\$(dirname "\${SELF_DIR}")"
exec "${VENV_PYTHON}" "\${CONTENTS_DIR}/Resources/__boot__.py"
SHEOF

chmod +x "${MACOS}/OptSnap"

echo "=== ${APP_NAME}.app built at ${APP_PATH} ==="
echo "Run: open ${APP_PATH}"
