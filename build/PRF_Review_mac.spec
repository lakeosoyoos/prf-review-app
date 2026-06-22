# PyInstaller spec — macOS .app bundle for the PRF Review desktop app.
# Run from the project ROOT:  pyinstaller --clean --noconfirm build/PRF_Review_mac.spec
# Produces dist/"PRF Review.app" (double-clickable). Same launch logic as the Windows build; this
# bundle also ships PyMuPDF so the local vision-model handwriting path can rasterize scanned pages.
import os
from PyInstaller.utils.hooks import collect_all

ROOT = os.getcwd()
if not os.path.exists(os.path.join(ROOT, "launcher.py")):
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(SPECPATH)))
assert os.path.exists(os.path.join(ROOT, "launcher.py")), f"cannot locate launcher.py from ROOT={ROOT}"
block_cipher = None

datas, binaries, hiddenimports = [], [], []
collect_pkgs = ["reportlab", "openpyxl", "flask", "bs4"]
# include PyMuPDF (fitz) when present — it powers PDF->image for the handwriting model
try:
    import fitz  # noqa: F401
    collect_pkgs.append("fitz")
except Exception:
    pass
for pkg in collect_pkgs:
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

hiddenimports += ["pkg_resources", "jaraco.text", "jaraco.functools", "jaraco.context", "jaraco.collections"]

datas += [(os.path.join(ROOT, "web"), "web")]
if os.path.exists(os.path.join(ROOT, "version.txt")):
    datas += [(os.path.join(ROOT, "version.txt"), ".")]
hiddenimports += [
    "name_match", "trs_match", "doc_index", "build_grid_sufficiency", "verify_locations",
    "align_to_prior_aip", "set_specificity", "build_location_verified",
    "form_templates", "local_extract",
    "core.extract.ingest", "core.parcels", "core.parcels.fetch", "core.parcels.assessor",
    "core.parcels.geo",
]

a = Analysis(
    [os.path.join(ROOT, "launcher.py")],
    pathex=[ROOT, os.path.join(ROOT, "core", "scripts"), os.path.join(ROOT, "core", "extract")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["shapely", "pyproj", "shapefile", "matplotlib", "tkinter", "webview"],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="PRF Review",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False,
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name="PRF Review")
app = BUNDLE(
    coll,
    name="PRF Review.app",
    icon=None,
    bundle_identifier="com.fieldoffice.prfreview",
    info_plist={
        "CFBundleName": "PRF Review",
        "CFBundleDisplayName": "PRF High Dollar Review",
        "CFBundleShortVersionString": os.environ.get("APP_VERSION", "1.0.0"),
        "NSHighResolutionCapable": True,
        "LSBackgroundOnly": False,
    },
)
