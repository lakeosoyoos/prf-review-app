# PRF High Dollar Review — desktop app

A click‑to‑run front‑end over the PRF review tooling, for **non‑technical office staff**. Runs
**entirely on the computer** — no internet, no cloud, nothing leaves the machine.

It produces the same deliverables as the command‑line tooling: the **Location High Dollar Review**
(per‑location, tiered, with a follow‑up list) or the **Acreage High Dollar Review** (per‑grid). The
optional agent re‑verification (which needs Claude) is **not** in this app — the offline deterministic
matcher produces a complete deliverable on its own.

## For office staff — how to use it
1. Double‑click **PRF Review.exe**. A window opens.
2. **Choose an account** → **choose the review** (Location or Acreage) and, for Location, **how
   specific** (Standard / Section / Strict) → **Run review**.
3. When it finishes (a few seconds), click **Open folder** to get the deliverable. The **FLAT** folder
   is best for emailing/uploading; the other is best kept on this PC.

## Setting up an account (done once, by the reviewer)
An "account" is a folder that contains **`account_config.yaml`**. Put account folders either in the
`accounts` folder next to the app, in your **Documents**, or anywhere listed in `settings.json`
(next to the app):
```json
{ "accounts_roots": ["D:\\PRF Accounts", "\\\\server\\share\\PRF"] }
```
Each account folder needs (paths set inside `account_config.yaml`):
- `account_config.yaml` — entities roster, parcel layer, `review_mode`, `specificity_level`, and the
  `deliverable:` block (input workbook, supporting‑document folders, output folder).
- `extracted/parcels.pkl` — the county owner‑tagged parcel index.
- the FSA acreage workbook + the supporting‑document folders the config points to.

See the `/prf-review` skill (`references/review-modes.md`, `location-hd-review.md`) for what each
config field means.

## Building the Windows installer — a 6-gate pipeline (a DOA build can never be published)
This Mac can't build a Windows `.exe`, so CI does it. The workflow `.github/workflows/windows-release.yml`
runs six gates **in order and stops on the first failure**, so the installer and the published download
only exist if the app actually launched:
1. **pytest (logic)** — before anything is frozen.
2. **dependency-completeness** — AST-scans the source for third-party imports and asserts each is pinned
   in `requirements-desktop.txt` (catches "works on my machine, dies on a clean Windows box").
3. **PyInstaller build** → `dist/PRF Review.exe`.
4. **BOOT SELF-TEST** — launches the actual `.exe --server-only` and polls `/health` for up to 90s;
   **fails the whole build if it doesn't come up**. The hard guarantee.
5. **Inno Setup installer** — only runs after Gate 4 passes.
6. **Publish** — uploads the installer / makes a GitHub Release only after every gate is green.

To ship: push this folder to a GitHub repo → Actions → **Windows release (6 gates)** → Run workflow
(or push a tag like `v1.0` to also cut a Release). Download **PRF‑Review‑Setup** and hand it to the boss.

**De-risk locally first** so CI is never where a packaging break is first found:
- Windows: `build.bat` (runs Gates 1–5).
- macOS: `bash build.sh` (Gates 1–2 + a *mac* freeze + boot test — same launch logic, proxy target).

Pins are hard requirements: **Python 3.11** (not 3.12), PyInstaller + Inno Setup, everything pinned in
`requirements-desktop.txt` (incl. `setuptools==65.5.1` + `jaraco.*` for a known vendoring crash).

## Delivery — one permanent link that always serves the latest verified build
Distribution is a GitHub Release on a **single rolling tag, `windows-build`**, whose assets CI
**overwrites (`--clobber`) on every green build**. The tag never changes, so:
- the download URL is **permanent** — techs bookmark it once;
- it always points at the **newest** build (CI replaced the file in place); no version hunting;
- it can **never serve a broken build** — the publish step (Gate 6) only runs after the boot
  self‑test (Gate 4) passes, so a build that didn't launch never reaches the link.

Permanent links (public repo → no login needed):
- Installer: `https://github.com/lakeosoyoos/prf-review-app/releases/download/windows-build/PRF-Review-Setup.exe`
- Portable ZIP: `…/releases/download/windows-build/PRF-Review-Windows.zip`

Updates reach techs by **manual re‑download** from the same link (the installer upgrades in place).
Each build is stamped with the CI run number and shown in the app header (“Build ####”) so a tech can
report exactly which build they're on. Tech‑facing instructions: **`TECH_DOWNLOAD.md`**.

## Developing on this Mac
```
pip install -r requirements-desktop.txt
python3 launcher.py            # runs the server + opens your browser
# headless (what the boot test uses):  PRF_SERVER_ONLY=1 PORT=8765 python3 launcher.py --server-only
```

## What's inside
- `launcher.py` — frozen entry point. Dispatches the `--run-worker` sentinel first (self-invoke when
  frozen), then runs Flask headless and opens the browser. `--server-only` = the boot-test mode.
- `app.py` — local Flask backend (UI + `/health` + runs reviews as an isolated subprocess).
- `run_cli.py` — the subprocess worker (keeps heavy PDF work off the UI; emits clean JSON progress).
- `core/pipeline.py` + `core/scripts/` — the offline review pipeline (vendored from the `/prf-review` skill).
- `core/extract/` — the **offline document reader** (deterministic form parsers + optional local OCR +
  loopback‑only on‑PC model). The pipeline auto‑reads the lease/ownership PDFs into the matcher's inputs
  when they haven't been prepared yet — entirely on the machine, no network (`/api/reader-status` reports
  what's available). Reads digital PDFs out of the box; scanned docs need the optional OCR pack installed.
  Note: the county **parcel layer** (`extracted/parcels.pkl`) is still a one‑time GIS build — it can't come
  from the PDFs.
- `core/parcels/` — **no-file parcel ownership auto-fetch.** When `extracted/parcels.pkl` is missing
  or stale for a supported county, the Location pipeline builds it automatically by searching the
  public county assessor (TaxSifter) for each roster name, reading owner + parcel off the results list,
  and decoding Section/Township/Range from the parcel number. Cached and reused offline (default 180-day
  freshness). Only public records come in — no client data goes out. Coverage depends on the account
  roster being complete (same dependency the matcher already has); unsupported counties fall back to the
  usual "parcel layer not found" message. Toggle with `data_sources.auto_fetch_parcels` (default on).
- `web/` — the guided UI.
- `tests/` — the gate tests (`test_smoke`, `test_deps_complete`, `test_boot_exe`).
- `build/PRF_Review.spec`, `installer/PRF_Review.iss`, `.github/workflows/windows-release.yml` — packaging.
