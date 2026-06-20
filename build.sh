#!/usr/bin/env bash
# macOS DE-RISK build — you can't make a Windows .exe here, but you CAN run Gates 1-2 and freeze +
# boot-test a *mac* binary, which exercises the exact same freeze/launch logic. Run this before
# pushing so a packaging break never surfaces first in CI. From the project root: bash build.sh
set -e
cd "$(dirname "$0")"

echo "=== pinned deps ==="
python3 -m pip install -r requirements-desktop.txt >/dev/null

echo "=== GATE 1: pytest (logic) ==="
python3 -m pytest tests/test_smoke.py -q

echo "=== GATE 2: dependency-completeness ==="
python3 -m pytest tests/test_deps_complete.py -q

echo "=== GATE 3: PyInstaller build (mac binary, proxy for the freeze logic) ==="
pyinstaller --clean --noconfirm build/PRF_Review.spec

echo "=== GATE 4: BOOT SELF-TEST (launch the frozen binary, poll /health) ==="
PRF_EXE="dist/PRF Review" python3 -m pytest -m boot tests/test_boot_exe.py -q

echo
echo "All cross-platform gates passed locally. (Windows .exe + Inno installer are produced by CI.)"
