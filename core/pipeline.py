"""Offline PRF review pipeline orchestrator (no LLM, no network).

Runs the deterministic pipeline the office app exposes:
  - Acreage High Dollar Review  -> per-grid acreage sufficiency folder
  - Location High Dollar Review -> per-location verification at a chosen specificity level

The agent-verification loop (which needs Claude) is intentionally NOT here — the deterministic
matcher + specificity dial + builders produce a complete deliverable on their own, fully offline.
"""
import os, sys, json, glob, shutil, collections, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "scripts"))
import yaml
import build_grid_sufficiency, verify_locations, set_specificity, build_location_verified  # noqa: E402


def _ts():
    return datetime.datetime.now().strftime("%Y-%m-%d_%H%M")


def list_accounts(roots):
    """Find account folders (each contains account_config.yaml) under the given root dirs."""
    out = []
    for root in roots:
        for cfg in glob.glob(os.path.join(root, "**", "account_config.yaml"), recursive=True):
            try:
                c = yaml.safe_load(open(cfg)) or {}
            except Exception:
                continue
            pol = (c.get("policies") or [{}])[0]
            out.append({
                "config_path": cfg,
                "account_dir": os.path.dirname(cfg),
                "name": c.get("account_name") or os.path.basename(os.path.dirname(cfg)),
                "insured": pol.get("insured", ""),
                "policy": pol.get("policy_number", ""),
                "crop_year": c.get("crop_year", ""),
                "county": c.get("county_label", ""),
                "review_mode": c.get("review_mode", "location"),
                "specificity_level": c.get("specificity_level", "instrument"),
            })
    # de-dup by config_path, stable order
    seen, uniq = set(), []
    for a in out:
        if a["config_path"] not in seen:
            seen.add(a["config_path"]); uniq.append(a)
    return uniq


def _candidates_to_verdicts(account_dir):
    cand = json.load(open(os.path.join(account_dir, "extracted", "location_candidates.json")))
    seen = {}
    for o in cand:
        k = "-".join(map(str, o["section"])) if o["section"] else "LEGAL:" + str(o["legal"])
        if k not in seen:
            seen[k] = {"key": k, "status": o["status"], "precision": o["precision"],
                       "instrument": "; ".join(o["instrument"]) or "—", "basis": o["basis"],
                       "confidence": 0.6, "note": "deterministic (offline)"}
    return list(seen.values())


def _stamp(path):
    """Rename a folder to a timestamped name; return the new path."""
    if not os.path.isdir(path):
        return None
    new = f"{path}_v{_ts()}"
    if os.path.exists(new):
        shutil.rmtree(new)
    os.rename(path, new)
    return new


def run_review(config_path, mode=None, level=None, progress=lambda m: None):
    """Run the offline review. Returns {folders:[...], summary:{...}}."""
    config_path = os.path.abspath(config_path)
    account_dir = os.path.dirname(config_path)
    cfg = yaml.safe_load(open(config_path)) or {}
    mode = (mode or cfg.get("review_mode") or "location").lower()
    level = (level or cfg.get("specificity_level") or "instrument").lower()
    D = cfg.get("deliverable") or {}
    out_base = D.get("output_folder")
    if not out_base:
        raise ValueError("account_config.yaml deliverable.output_folder is not set")

    cwd0 = os.getcwd()
    os.chdir(account_dir)                      # the vendored scripts use relative extracted/ paths
    try:
        progress("Building the supporting-document index and linked folder…")
        build_grid_sufficiency.main(config_path)               # subfolder base
        build_grid_sufficiency.main(config_path, flat=True)    # flat base
        base, base_flat = out_base, out_base + "_FLAT"

        if mode == "acreage":
            folders = [_stamp(base), _stamp(base_flat)]
            progress("Acreage High Dollar Review complete.")
            return {"folders": [f for f in folders if f], "mode": mode, "summary": _grid_summary(base if False else folders[0])}

        # ---- Location High Dollar Review ----
        # Parcel ownership: auto-build the index from the public county assessor if it's missing or
        # stale (no file to feed, no login). Only public records come in; guarded so it can't crash
        # the run. Supported counties only; otherwise verify_locations gives its usual clear error.
        try:
            ds = cfg.get("data_sources") or {}
            pkl = next(iter((ds.get("parcel_layers") or {}).values()), "extracted/parcels.pkl")
            pkl_abs = pkl if os.path.isabs(pkl) else os.path.join(account_dir, pkl)
            ent0 = cfg.get("entities") or {}
            county = cfg.get("county_label") or next(
                (str(c) for p2 in (cfg.get("policies") or []) for c in (p2.get("counties") or [])), "")
            if ds.get("auto_fetch_parcels", True) and county:
                from core.parcels import fetch as _pf
                names = []
                for key in ("insured_aliases", "related", "lessors", "roster"):
                    names += list(ent0.get(key) or [])
                state = cfg.get("state") or ds.get("state") or "wa"
                # known counties skip discovery; unknown ones are discovered at run time
                ok, msg = _pf.ensure_parcels(county, names, pkl_abs, state=state, progress=progress)
                if not ok:
                    progress(f"(parcel auto-fetch: {msg})")
        except Exception as e:
            progress(f"(parcel auto-fetch skipped: {e})")

        # Offline reader: if the lease/ownership documents haven't been turned into data yet, read them
        # ON THIS MACHINE now (never clobbers reviewer-prepared files; guarded so it can't break the run).
        try:
            if not os.path.exists(os.path.join(account_dir, "extracted", "recorded_grazing_leases.json")):
                from core.extract import ingest as _ingest
                ent = cfg.get("entities") or {}
                ents = list(ent.get("insured_aliases") or []) + list(ent.get("related") or [])
                counties = [str(c) for p2 in (cfg.get("policies") or []) for c in (p2.get("counties") or [])]
                ddirs = []
                for d in (D.get("doc_source_dirs") or []):
                    if "{PKT}" in d:
                        hits = sorted(glob.glob(D.get("packet_glob"))) if D.get("packet_glob") else []
                        d = d.replace("{PKT}", hits[-1]) if hits else None
                    if d:
                        ddirs.append(d)
                progress("Reading lease/ownership documents on this computer (offline)…")
                _ingest.ingest(ddirs, os.path.join(account_dir, "extracted"),
                               entities=ents, counties=counties, progress=progress)
        except Exception as e:
            progress(f"(offline reader skipped: {e})")

        progress("Matching every location to the instrument that covers it…")
        verify_locations.main(config_path)
        vpath = os.path.join(account_dir, "extracted", "location_verdicts.json")
        json.dump({"verdicts": _candidates_to_verdicts(account_dir)}, open(vpath, "w"), indent=2)

        progress(f"Applying specificity level: {level}…")
        set_specificity.apply_level(vpath, os.path.join(account_dir, "extracted", "section_evidence.json"), level)

        progress("Rendering the verified workbook (this keeps every supporting-document link)…")
        pol = (cfg.get("policies") or [{}])[0]
        title = f"Location Verification — {pol.get('insured', cfg.get('account_name', 'Insured'))}, CY{cfg.get('crop_year', '')}"
        county = cfg.get("county_label", "")
        if county:
            title += f" ({county.split(',')[0]})"
        dest = out_base.replace("Grid_Acreage_Sufficiency", "Location_Verification") + f"_v{_ts()}"
        build_location_verified.main(base, vpath, dest, title)
        build_location_verified.main(base_flat, vpath, dest + "_FLAT", title)
        # remove the intermediate grid base folders to avoid clutter
        for b in (base, base_flat):
            if os.path.isdir(b):
                shutil.rmtree(b, ignore_errors=True)
        progress("Location High Dollar Review complete.")
        return {"folders": [dest + "_FLAT", dest], "mode": mode, "level": level,
                "summary": _location_summary(vpath, account_dir)}
    finally:
        os.chdir(cwd0)


def _location_summary(vpath, account_dir):
    V = {v["key"]: v for v in json.load(open(vpath))["verdicts"]}
    cand = json.load(open(os.path.join(account_dir, "extracted", "location_candidates.json")))
    dist = collections.Counter()
    for o in cand:
        k = "-".join(map(str, o["section"])) if o["section"] else "LEGAL:" + str(o["legal"])
        v = V.get(k)
        if not v:
            continue
        s = v["status"]; p = (v.get("precision") or "")
        dist["MATCHED (" + p + ")" if (s == "MATCHED" and p not in ("parcel", "section", "")) else s] += 1
    matched = sum(c for k, c in dist.items() if k.startswith("MATCHED"))
    return {"locations": sum(dist.values()), "matched": matched, "by_status": dict(dist)}


def _grid_summary(folder):
    try:
        import openpyxl
        x = [f for f in glob.glob(os.path.join(folder, "*.xlsx")) if "~$" not in f][0]
        ws = openpyxl.load_workbook(x)["Grid Sufficiency"]
        return {"grids": ws.max_row - 2}
    except Exception:
        return {}
