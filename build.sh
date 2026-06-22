#!/usr/bin/env bash
# macOS build — produces the downloadable "PRF Review.app" and boot-tests it (same launch logic CI
# uses for Windows). Run before pushing so a packaging break never surfaces first in CI. Also the
# de-risk path for the Windows pipeline. From the project root: bash build.sh
set -e
cd "$(dirname "$0")"

echo "=== pinned deps ==="
python3 -m pip install -r requirements-desktop.txt >/dev/null

echo "=== GATE 1: pytest (logic) ==="
python3 -m pytest tests/test_smoke.py -q

echo "=== GATE 2: dependency-completeness ==="
python3 -m pytest tests/test_deps_complete.py -q

echo "=== GATE 3: PyInstaller build (macOS .app bundle) ==="
pyinstaller --clean --noconfirm build/PRF_Review_mac.spec

echo "=== GATE 4: BOOT SELF-TEST (launch the .app binary, poll /health) ==="
PRF_EXE="dist/PRF Review.app/Contents/MacOS/PRF Review" python3 -m pytest -m boot tests/test_boot_exe.py -q

echo "=== Package the downloadable zip ==="
( cd dist && ditto -c -k --sequesterRsrc --keepParent "PRF Review.app" "PRF-Review-macOS.zip" )
echo "  -> dist/PRF-Review-macOS.zip"

echo
echo "macOS app built and boot-tested. (Windows .exe + Inno installer are produced by CI.)"
