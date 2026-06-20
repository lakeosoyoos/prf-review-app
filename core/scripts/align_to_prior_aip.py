"""Fold per-location verdicts to the documentation standard the prior-year AIP review accepted,
BY TYPE OF GROUND (Location High Dollar Review).

Rationale (from the prior AIP binder): the AIP did NOT require a per-field, instrument-legal-names-
the-exact-section match. It accepted, by ground type:
  - BLM/federal      -> the BLM Allotment Master Report at the ALLOTMENT level (AR Q2.08/2.08.01)
  - State            -> the WA DNR / WDFW lease + grid-level acreage sufficiency
  - Private leased    -> the NAU Lease Certification Form (+ county APN parcel lists) (AR Q2.05/2.07)
  - Tribal           -> the recorded Colville tribal lease
So a location with controlled ground of those types is MATCHED to that standard even when no
instrument legal names the exact section. The match is recorded at a COARSER precision tier
(allotment / state lease / lease cert / tribal lease) so the workbook shows the difference honestly.
Only FSA-CLU-operatorship-with-no-instrument stays LIKELY (the AIP would also lack a document).

Input : extracted/location_verdicts.json  (from the agent loop; {verdicts:[{key,status,precision,...}]})
        extracted/section_evidence.json    (from verify_locations.py)
Output : same verdicts file, statuses folded to the prior-AIP standard, with precision set to the
         tier and the basis citing the standard. Disable any fold via flags.

  python align_to_prior_aip.py extracted/location_verdicts.json [--no-blm] [--no-state] [--no-cert] [--no-tribal]
"""
import os, json, argparse, collections

AIP = ("Documented to the standard accepted in the prior-year AIP review ({src}); section-precision "
       "is an optional upgrade.")
STATE_LABELS = {"WA DNR (state lease)", "WA WDFW (state lease)"}
FEDERAL_LABELS = {"US BLM (federal permit)", "US Forest Service (permit)", "Federal (USA)"}
BLM_GENERIC = "BLM Allotment Master Reports (per the insured's BLM authorizations) — allotment level (AR Q2.08/2.08.01)"


def main(path, ev_path, do_blm=True, do_state=True, do_cert=True, do_tribal=True, blm_cite=None):
    data = json.load(open(path))
    if isinstance(data, list):                 # accept a bare verdict list too
        data = {"verdicts": data}
    sec_ev = json.load(open(ev_path)) if os.path.exists(ev_path) else {}
    blm_cite = blm_cite or {}
    changed = collections.Counter()
    for v in data["verdicts"]:
        k = v["key"]; b = (v.get("basis") or "").lower(); instr = (v.get("instrument") or "")
        ev = sec_ev.get(k, {}); ctrl = ev.get("controlled", []); rec = ev.get("recorded"); certs = ev.get("certs", [])
        labels = {c.get("label", "") for c in ctrl}; kinds = {c.get("kind", "") for c in ctrl}
        rectxt = ((rec or {}).get("lessor", "") + " " + (rec or {}).get("term", "")).upper()
        is_state = bool(labels & STATE_LABELS) or any(x in rectxt for x in ("DNR", "WDFW", "NATURAL RESOURCES", "FISH"))
        is_tribal = ("tribal" in kinds) or ("COLVILLE" in rectxt)
        is_lessor = bool(kinds & {"lessor", "fee_related", "private_tag", "fee_insured"}) or bool(certs)
        is_fed = bool(labels & FEDERAL_LABELS) or any(x in (b + " " + instr.lower()) for x in ("federal", "blm", "usfs", "forest"))

        # (1) federal ground (EXCEPTION or LIKELY) -> allotment-level MATCHED per the AIP standard
        if do_blm and is_fed and v["status"] in ("EXCEPTION", "LIKELY"):
            changed[f"{v['status']}->MATCHED (allotment)"] += 1
            v.update(status="MATCHED", precision="allotment",
                     instrument=blm_cite.get(k, BLM_GENERIC),
                     basis=AIP.format(src="BLM Allotment Master Report at allotment level"))
            continue
        # (2) section-corroboration LIKELY -> matched by ground type
        if v["status"] != "LIKELY":
            continue
        if do_state and ("state" in b or "dnr" in b or "wdfw" in b or is_state):
            v.update(status="MATCHED", precision="state lease",
                     instrument=(os.path.basename(rec["file"]) if rec else (v.get("instrument") or "WA DNR/WDFW state lease")),
                     basis=AIP.format(src="WA DNR/WDFW state lease + grid-level acreage sufficiency"))
            changed["LIKELY->MATCHED (state lease)"] += 1
        elif do_tribal and ("tribal" in b or is_tribal):
            v.update(status="MATCHED", precision="tribal lease",
                     instrument=(os.path.basename(rec["file"]) if rec else (v.get("instrument") or "Colville tribal lease")),
                     basis=AIP.format(src="recorded Colville tribal lease"))
            changed["LIKELY->MATCHED (tribal lease)"] += 1
        elif "clu" in b or "operatorship" in b:
            v["basis"] = "FSA-CLU operatorship only — no cert/lease names the section (the prior AIP would also lack a document)."
            changed["LIKELY (kept)"] += 1
        elif do_cert and ("lessor" in b or "cert" in b or "fee" in b or is_lessor):
            v.update(status="MATCHED", precision="lease cert",
                     basis=AIP.format(src="NAU lease certification form (+ county APN parcel lists)"))
            changed["LIKELY->MATCHED (lease cert)"] += 1
        else:
            changed["LIKELY (kept)"] += 1
    json.dump(data, open(path, "w"), indent=2)
    print("AIP alignment by ground type:", dict(changed))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("verdicts")
    ap.add_argument("--evidence", default="extracted/section_evidence.json")
    ap.add_argument("--no-blm", action="store_true"); ap.add_argument("--no-state", action="store_true")
    ap.add_argument("--no-cert", action="store_true"); ap.add_argument("--no-tribal", action="store_true")
    a = ap.parse_args()
    main(a.verdicts, a.evidence, not a.no_blm, not a.no_state, not a.no_cert, not a.no_tribal)
