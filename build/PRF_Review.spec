# PyInstaller spec — single self-contained Windows .exe for the PRF Review desktop app.
# Run from the project root:  pyinstaller build/PRF_Review.spec
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# collect_all() pulls code + data + hidden imports for fragile packages (reportlab ships fonts;
# jaraco/setuptools have vendoring quirks; flask is generally fine but cheap to be safe).
datas, binaries, hiddenimports = [], [], []
for pkg in ["reportlab", "openpyxl", "jaraco.text", "jaraco.functools", "jaraco.context",
            "jaraco.collections", "flask"]:
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception:
        pass

# Belt-and-suspenders for the setuptools-vendoring crash.
hiddenimports += collect_submodules("setuptools") + ["pkg_resources", "jaraco"]

# Bundle the UI assets.
datas += [("web", "web")]

# The vendored pipeline scripts are imported dynamically (sys.path insert) -> declare explicitly.
hiddenimports += [
    "name_match", "trs_match", "doc_index", "build_grid_sufficiency", "verify_locations",
    "align_to_prior_aip", "set_specificity", "build_location_verified",
]

a = Analysis(
    ["launcher.py"],
    pathex=["core/scripts"],            # so the vendored modules resolve at build time
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # heavy libs not used at runtime (parcels.pkl is prebuilt) — exclude to keep the .exe lean.
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
    console=False,                      # windowed app (no console window for the boss)
    disable_windowed_traceback=False,
    icon=None,
)
