@echo off
REM Local Windows de-risk build — runs the SAME gate sequence as CI, stops on the first failure,
REM so a packaging break is never discovered first in CI. Run from the project root.
setlocal
cd /d "%~dp0"

echo === Installing pinned deps (Python 3.11 expected) ===
python -m pip install --upgrade pip || goto :fail
pip install -r requirements-desktop.txt || goto :fail

echo === GATE 1: pytest (logic) ===
python -m pytest tests\test_smoke.py -q || goto :fail

echo === GATE 2: dependency-completeness (clean-env import scan) ===
python -m pytest tests\test_deps_complete.py -q || goto :fail

echo === GATE 3: PyInstaller build ===
pyinstaller --clean --noconfirm build\PRF_Review.spec || goto :fail

echo === GATE 4: BOOT SELF-TEST (launch the .exe, poll /health) ===
set "PRF_EXE=dist\PRF Review.exe"
python -m pytest -m boot tests\test_boot_exe.py -q || goto :fail

echo === GATE 5: Inno Setup installer ===
where iscc >nul 2>nul && (iscc installer\PRF_Review.iss || goto :fail) || echo [skip] Inno Setup (iscc) not on PATH

echo.
echo ALL GATES PASSED. Installer (if Inno present) in installer_out\
exit /b 0

:fail
echo.
echo *** BUILD FAILED at a gate above — nothing is published. ***
exit /b 1
