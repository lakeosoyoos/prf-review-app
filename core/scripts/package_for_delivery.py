"""Package a built Location/Acreage deliverable for friction-free hand-off.

Fixes the field-reported delivery pain (Windows 260-char path errors, OneDrive folder re-zipping):
  * FLAT layout — workbook + every PDF at one level (links resolve after a plain extract)
  * SHORT names — short folder + short ASCII filenames so the total path stays well under 260 chars
  * ONE pre-made .zip — hand your boss a single file; OneDrive serves it as-is (no account/re-zip)
  * READ_ME_FIRST.txt — download → Extract All → open the workbook

Lossless: PDFs are copied byte-for-byte (never recompressed). Excel hyperlinks are rewritten to the
short flat names. The source deliverable is left untouched.

    python package_for_delivery.py <built_deliverable_folder> <dest_short_name>
    # e.g. python package_for_delivery.py ~/Desktop/_LV_Gebbers_CORRECTED_build Gebbers_CY26
"""
import os, re, sys, glob, shutil, zipfile
from urllib.parse import unquote
import openpyxl

_SUB = [
    (r"Location_Verification[_-]+", ""), (r"Grid_Acreage_Sufficiency[_-]+", ""),
    (r"signed[_-]?lease[_-]?cert(ification)?", "cert"), (r"_?LCF(_?26)?", "_cert"),
    (r"Signature_Authority", "sig"), (r"Grazing_Lease", "lease"), (r"_?bundle", ""),
    (r"Permits?", "permit"), (r"State_Leases?", "DNR"), (r"Owned_fee_parcel_records[_-]*", "fee_"),
    (r"Gebbers_?(Cattle|Farms)?_?(LP|LTD)?", "GC"), (r"_+", "_"),
]


def _short(stem, ext, used):
    s = stem
    for pat, rep in _SUB:
        s = re.sub(pat, rep, s, flags=re.I)
    s = re.sub(r"[^A-Za-z0-9._-]", "", s).strip("_-").lower()[:28] or "doc"
    name = s + ext
    i = 1
    while name.lower() in used:
        name = f"{s[:25]}_{i}{ext}"; i += 1
    used.add(name.lower())
    return name


def main(src, short):
    src = os.path.abspath(src)
    parent = os.path.dirname(src)
    dest = os.path.join(parent, short)
    if os.path.exists(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)

    # gather PDFs (flat + any Supporting_Documents subfolder)
    pdfs = glob.glob(os.path.join(src, "*.pdf")) + glob.glob(os.path.join(src, "**", "*.pdf"), recursive=True)
    pdfs = sorted(set(pdfs))
    used = set()
    namemap = {}                      # original basename -> short name
    for p in pdfs:
        base = os.path.basename(p)
        stem, ext = os.path.splitext(base)
        namemap[base] = _short(stem, ext, used)
        shutil.copy2(p, os.path.join(dest, namemap[base]))   # byte-for-byte, lossless

    # the workbook: short name, rewrite hyperlinks to the flat short names
    xlsx = glob.glob(os.path.join(src, "*.xlsx"))[0]
    wb = openpyxl.load_workbook(xlsx)
    fixed = 0
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if c.hyperlink and c.hyperlink.target:
                    tgt = unquote(c.hyperlink.target)
                    b = os.path.basename(tgt.replace("\\", "/"))
                    if b in namemap:
                        c.hyperlink.target = namemap[b]     # flat, same folder
                        fixed += 1
    wbname = short + "_LocationReview.xlsx"
    wb.save(os.path.join(dest, wbname))

    # README: if the source folder ships a curated READ_ME_FIRST.txt, preserve it verbatim (so
    # account-specific delivery notes survive re-packaging); else write the field-hardened default.
    src_readme = os.path.join(src, "READ_ME_FIRST.txt")
    dest_readme = os.path.join(dest, "READ_ME_FIRST.txt")
    if os.path.exists(src_readme):
        shutil.copy2(src_readme, dest_readme)
    else:
        with open(dest_readme, "w") as f:
            f.write("PRF High Dollar Review — how to open\n"
                    "====================================\n\n"
                    "1. Download the single .zip file. No OneDrive account needed.\n"
                    "   No need to rename it - just download it as-is.\n"
                    "2. Right-click it -> Extract All (Windows) / double-click (Mac).\n"
                    f"3. Open {wbname}.\n"
                    "4. If Excel shows a yellow \"PROTECTED VIEW\" bar, click \"Enable Editing\".\n"
                    "   The clickable links won't work until you do.\n"
                    "   (Optional: before extracting, right-click the .zip -> Properties ->\n"
                    "   check \"Unblock\" -> OK, and the yellow bar never appears.)\n\n"
                    "Everything is in ONE flat folder with short names, so the clickable links work\n"
                    "as soon as it's extracted. Keep the .xlsx in the same folder as the PDFs. If your\n"
                    "Downloads folder syncs to OneDrive, you can extract to any local folder instead.\n\n"
                    "The big agency bundles (DNR / BLM-USFS / WDFW) open with a clickable CONTENTS page\n"
                    "and bookmarks (\"tabs\") - DNR leases by number, BLM ground by allotment name.\n")

    # ONE pre-made zip (short name -> short extract path)
    zpath = os.path.join(parent, short + ".zip")
    if os.path.exists(zpath):
        os.remove(zpath)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for fn in sorted(os.listdir(dest)):
            z.write(os.path.join(dest, fn), os.path.join(short, fn))

    longest = max((len(short) * 2 + len(fn) for fn in os.listdir(dest)), default=0)
    print(f"packaged -> {dest}")
    print(f"  files: {len(os.listdir(dest))} | hyperlinks rewritten: {fixed}")
    print(f"  single zip: {zpath}  ({os.path.getsize(zpath)/1048576:.0f} MB)")
    print(f"  worst-case internal path (doubled short folder + longest file): {longest} chars (<260 OK)")
    return dest, zpath


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: package_for_delivery.py <built_deliverable_folder> <dest_short_name>")
    main(sys.argv[1], sys.argv[2])
