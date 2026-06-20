"""Per-LOCATION verification (PRF review — location-matching standard).

For every FSA location, find the lease/deed/permit that covers THAT location and assign a three-tier
verdict, instead of the per-grid acreage-sufficiency test. Precision: parcel/sub-section where the
instrument lists it (Exhibit A PINs or a section legal), else section (T-R-S).

  MATCHED   = a named instrument demonstrably covers the location's section/parcels
              (insured fee deed; private lease cert whose legal or Exhibit A reaches the section;
               recorded state DNR/WDFW lease; recorded tribal lease).
  LIKELY    = section-level corroboration (lessor/insured parcels in the section per the layer, or
              FSA-CLU operatorship) but no named instrument legal-confirms it.
  EXCEPTION = no instrument and no corroboration — OR federal (BLM/USFS) ground that, per the
              reviewing standard, requires allotment-GIS boundary confirmation not on file.

Writes extracted/location_candidates.json (one record per location) for the agent-verification loop.

  python verify_locations.py account_config.yaml
"""
import os, re, sys, json, pickle, collections, argparse
import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from name_match import OwnerClassifier
from doc_index import DocIndex
import trs_match

FEDERAL = {"US BLM (federal permit)", "US Forest Service (permit)", "Federal (USA)"}
STATE = {"WA DNR (state lease)", "WA WDFW (state lease)"}


def loc_section(legal):
    """Parse (T,R,S) from an FSA legal like '028N-023E-0003' or '029N-023E-IA21' (section may be None)."""
    s = str(legal or "")
    m = trs_match.parse_compact(s)
    if m:
        return m
    mT, mR, mS = re.search(r"(\d+)\s*N", s), re.search(r"(\d+)\s*E", s), re.search(r"(\d+)\D*$", s)
    if mT and mR and mS and mS.group(1).isdigit():
        return (int(mT[1]), int(mR[1]), int(mS[1]))
    return None


def main(config_path):
    cfg = yaml.safe_load(open(config_path)); D = cfg["deliverable"]
    county = cfg.get("county_label") or "the in-scope county"
    oc = OwnerClassifier.from_config(config_path)
    pkl_path = next(iter((cfg.get("data_sources", {}).get("parcel_layers") or {}).values()), "extracted/parcels.pkl")
    if not os.path.exists(pkl_path):
        raise SystemExit(f"parcel layer not found: {pkl_path} (set data_sources.parcel_layers in account_config.yaml)")
    meta = pickle.load(open(pkl_path, "rb"))

    # PIN -> section, and section -> controlled parcels (parcel-precise control side)
    pin2k, sec_ctl = {}, collections.defaultdict(list)
    for a in meta["attrs"]:
        k = trs_match.parse_map(a.get("map")); pin = str(a.get("PIN", ""))
        if k:
            pin2k[pin] = k
            kind, label = oc.classify(a.get("owner") or "")
            if kind != "none":
                sec_ctl[k].append({"pin": pin, "owner": a.get("owner"), "kind": kind, "label": label})

    # recorded permits / state / tribal leases -> section -> instrument file
    pub_trs = {}
    def add_recorded(path):
        if not os.path.exists(path):
            return
        data = json.load(open(path)); items = data if isinstance(data, list) else list(data.values())
        for it in items:
            f = it.get("file", "")
            for leg in (it.get("legal_descriptions") or []):
                for trs in trs_match.parse_prose(leg):
                    if trs and trs[2] is not None and f:
                        pub_trs[trs] = {"file": f, "lessor": it.get("lessor", ""), "term": it.get("term", "")}
    for src in (D.get("recorded_sources") or ["extracted/recorded_grazing_leases.json", "extracted/ctl_leases.json"]):
        add_recorded(src)

    # signed lease certs -> sections they legally reach (by legal text and by Exhibit A PINs)
    cert_sec = collections.defaultdict(set)   # section -> {cert files}
    cert_pin_sec = collections.defaultdict(set)
    certs = json.load(open("extracted/signed_lease_certs.json"))
    for c in certs:
        f = c.get("file", "")
        for leg in (c.get("legal_descriptions") or []):
            for trs in trs_match.parse_prose(str(leg)) or []:
                if trs and trs[2] is not None:
                    cert_sec[trs].add(f)
            m = trs_match.parse_compact(str(leg))
            if m and m[2] is not None:
                cert_sec[m].add(f)
    try:
        exA = json.load(open("extracted/exhibitA_parcels.json"))
        for f, parcels in exA.items():
            blob = json.dumps(parcels)
            for pin in re.findall(r"\b\d{8,11}\b", blob):
                k = pin2k.get(pin)
                if k:
                    cert_pin_sec[k].add(f); cert_sec[k].add(f)
    except FileNotFoundError:
        pass

    di = DocIndex.build([d for d in (x.replace("{PKT}", _pkt(D)) for x in D.get("doc_source_dirs", [])) if os.path.isdir(d)],
                        config=config_path, oc=oc)

    # ---- per-location verdicts -------------------------------------------------------
    import openpyxl
    fv = openpyxl.load_workbook(D["fv_workbook"], data_only=True)[D.get("fv_sheet", "Field Verification")]
    H = [str(c.value) for c in fv[1]]; I = {h: i for i, h in enumerate(H)}
    col = lambda *n: next((I[x] for x in n if x in I), None)
    # account-agnostic header match: prefix-match so e.g. "Lessor (party leasing to <any insured>)" works
    def colstarts(*prefixes):
        for p in prefixes:
            for h, i in I.items():
                if h and str(h).lower().startswith(p.lower()):
                    return i
        return None
    c_fsn, c_fld, c_tr, c_leg = col("FSN"), col("FSA Field #", "Field"), col("Tract"), col("Legal")
    c_grid = col("Assigned To", "Grid")
    c_les = colstarts("Lessor")
    c_ctl = colstarts("Control source")
    c_flag = col("Flag")

    out = []
    for r in fv.iter_rows(min_row=2, values_only=True):
        if r[c_fsn] in (None, ""):
            continue
        k = loc_section(r[c_leg]); les = str(r[c_les] or ""); ctl = str(r[c_ctl] or "")
        ctrl = sec_ctl.get(k, []) if k else []
        kinds = {x["kind"] for x in ctrl}
        owned_pins = [x["pin"] for x in ctrl if x["kind"] == "fee_insured"]
        lessor_parcels = [x for x in ctrl if x["kind"] in ("lessor", "fee_related", "private_tag")]
        certs_here = cert_sec.get(k, set()) if k else set()
        fed = any(lab in FEDERAL for lab in (oc.classify(les)[1],)) or "BLM" in les.upper() or "USFS" in les.upper() or "FOREST" in les.upper()
        gov_state = [x for x in ctrl if x["label"] in STATE]
        tribal = [x for x in ctrl if x["kind"] == "tribal"]

        status, instr, basis = "EXCEPTION", [], "no instrument or corroboration"
        precise = "section"
        if owned_pins:
            status, basis = "MATCHED", "insured fee ownership (deed/assessor parcel)"
            instr = [f"Owned fee PINs: {', '.join(owned_pins[:6])}" + (f" (+{len(owned_pins)-6})" if len(owned_pins) > 6 else "")]
            precise = "parcel"
        elif lessor_parcels and (certs_here or any(di.lookup(x["owner"], trs=k) for x in lessor_parcels)):
            # named lease cert reaches this section (legal/ExhibitA) or the lessor's cert exists
            files = sorted(certs_here) or sorted({d for x in lessor_parcels for d in di.lookup(x["owner"], trs=k)})
            if certs_here:
                status, basis = "MATCHED", "private lease cert covers section (cert legal / Exhibit A)"
                precise = "parcel" if k in cert_pin_sec else "section"
            else:
                status, basis = "LIKELY", "lessor parcels in section per layer; cert not legal-confirmed for section"
            instr = files
        elif k in pub_trs and (("DNR" in pub_trs[k]["lessor"].upper() or "WDFW" in pub_trs[k]["lessor"].upper()
                                or "NATURAL RESOURCES" in pub_trs[k]["lessor"].upper() or "FISH" in pub_trs[k]["lessor"].upper())):
            status, basis, instr = "MATCHED", "recorded state lease covers section", [os.path.basename(pub_trs[k]["file"])]
        elif tribal or (k in pub_trs and "COLVILLE" in (pub_trs[k]["lessor"] + ctl).upper()):
            if k in pub_trs:
                status, basis, instr = "MATCHED", "recorded tribal lease covers section", [os.path.basename(pub_trs[k]["file"])]
            else:
                status, basis = "LIKELY", "tribal/reservation parcels in section; recorded lease not section-confirmed"
        elif fed or "FEDERAL" in les.upper() or any(x["label"] in FEDERAL for x in ctrl):
            status, basis = "EXCEPTION", "federal (BLM/USFS) — allotment GIS boundary confirmation required (not on file)"
        elif gov_state:
            status, basis = "LIKELY", "state-lease parcels in section per layer; recorded lease not section-confirmed"
        elif "CLU operator" in ctl or "operatorship" in ctl.lower():
            status, basis = "LIKELY", "FSA-CLU operatorship; no named instrument confirms the section"
        # corroboration fallback from the AR's own determination (e.g. out-of-county ground not in the layer)
        if status == "EXCEPTION" and basis == "no instrument or corroboration":
            fk = oc.classify(les)[0]
            if fk in ("fee_insured", "fee_related"):
                status, basis = "LIKELY", f"AR determination: insured/related fee ownership ({county}; deed/assessor to confirm)"
            elif fk == "lessor":
                status, basis = "LIKELY", "AR determination: leased from named lessor; cert not section-confirmed"
            elif "owned" in ctl.lower() or "fee" in ctl.lower():
                status, basis = "LIKELY", f"AR determination: owned/fee ground ({county}; deed/assessor to confirm)"
        out.append({
            "fsn": str(r[c_fsn]), "tract": str(r[c_tr]), "field": str(r[c_fld]),
            "grid": str(r[c_grid]).split()[0], "legal": str(r[c_leg]), "section": list(k) if k else None,
            "status": status, "precision": precise, "instrument": instr, "basis": basis,
            "fv_lessor": les[:80], "fv_control": ctl[:80],
        })

    json.dump(out, open("extracted/location_candidates.json", "w"), indent=2)
    # per-section evidence for the agent-verification loop (lightweight; no pkl needed downstream)
    sec_ev = {}
    for o in out:
        if not o["section"]:
            continue
        k = tuple(o["section"]); key = f"{k[0]}-{k[1]}-{k[2]}"
        if key not in sec_ev:
            sec_ev[key] = {"controlled": sec_ctl.get(k, []), "certs": sorted(cert_sec.get(k, set())),
                           "recorded": pub_trs.get(k)}
    json.dump(sec_ev, open("extracted/section_evidence.json", "w"), indent=2)
    # unique section-group keys, in first-seen order — pass these as the agent loop's `keys` arg
    seen = []
    for o in out:
        kk = "-".join(map(str, o["section"])) if o["section"] else "LEGAL:" + str(o["legal"])
        if kk not in seen:
            seen.append(kk)
    json.dump(seen, open("extracted/section_keys.json", "w"), indent=2)
    dist = collections.Counter(o["status"] for o in out)
    prec = collections.Counter(o["precision"] for o in out if o["status"] == "MATCHED")
    secs = {tuple(o["section"]) for o in out if o["section"]}
    print(f"locations: {len(out)} | unique sections: {len(secs)}")
    print(f"status: {dict(dist)}")
    print(f"MATCHED precision: {dict(prec)}")
    print("EXCEPTION breakdown:", dict(collections.Counter(o["basis"] for o in out if o["status"] == "EXCEPTION")))
    print("LIKELY breakdown:", dict(collections.Counter(o["basis"] for o in out if o["status"] == "LIKELY")))
    print("wrote extracted/location_candidates.json")


def _pkt(D):
    import glob
    g = D.get("packet_glob")
    hits = sorted(glob.glob(g)) if g else []
    return hits[-1] if hits else ""


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    a = ap.parse_args()
    main(a.config)
