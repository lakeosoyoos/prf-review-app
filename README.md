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
- `core/updater.py` — fail-closed Ed25519 update check (disabled until a real key is baked in).
- `web/` — the guided UI.
- `tests/` — the gate tests (`test_smoke`, `test_deps_complete`, `test_boot_exe`).
- `build/PRF_Review.spec`, `installer/PRF_Review.iss`, `.github/workflows/windows-release.yml` — packaging.
