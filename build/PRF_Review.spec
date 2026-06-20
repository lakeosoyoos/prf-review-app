# PyInstaller spec — single self-contained Windows .exe for the PRF Review desktop app.
# Run from the project root:  pyinstaller build/PRF_Review.spec
# NOTE: PyInstaller resolves Analysis paths relative to the SPEC FILE's directory, so we anchor
# everything to the project ROOT (the spec lives in build/).
import os
from PyInstaller.utils.hooks import collect_all

# PyInstaller is always invoked from the project ROOT (CI workflow, build.bat, build.sh all do so),
# so the cwd is the reliable anchor. (SPECPATH is the spec *file* path, which would point at build/.)
ROOT = os.getcwd()
if not os.path.exists(os.path.join(ROOT, "launcher.py")):
    # fallback: spec lives in <ROOT>/build/, so the parent of the spec dir is the root
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(SPECPATH)))
assert os.path.exists(os.path.join(ROOT, "launcher.py")), f"cannot locate launcher.py from ROOT={ROOT}"
block_cipher = None

datas, binaries, hiddenimports = [], [], []
# collect_all() pulls code + data + hidden imports for fragile packages (reportlab ships fonts, etc.)
for pkg in ["reportlab", "openpyxl", "flask"]:
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

# Belt-and-suspenders for the setuptools/pkg_resources vendoring crash (declare, don't deep-scan).
hiddenimports += ["pkg_resources", "jaraco.text", "jaraco.functools", "jaraco.context", "jaraco.collections"]

# UI assets + the dynamically-imported vendored pipeline scripts.
datas += [(os.path.join(ROOT, "web"), "web")]
hiddenimports += [
    "name_match", "trs_match", "doc_index", "build_grid_sufficiency", "verify_locations",
    "align_to_prior_aip", "set_specificity", "build_location_verified",
]

a = Analysis(
    [os.path.join(ROOT, "launcher.py")],
    pathex=[ROOT, os.path.join(ROOT, "core", "scripts")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["shapely", "pyproj", "shapefile", "numpy", "matplotlib", "tkinter", "webview"],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name="PRF Review",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon=None,
)
