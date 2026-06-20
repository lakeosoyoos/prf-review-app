"""Set the SPECIFICITY LEVEL of a Location High Dollar Review.

The match-precision tiers form a ladder; this picks how strict "MATCHED" must be. Run on the strict
agent-loop verdicts (precision parcel/section/none + MATCHED/LIKELY/EXCEPTION) to produce the
deliverable verdicts at the chosen level. Higher level = looser = more MATCHED.

LEVELS (strict -> lenient):
  1 parcel      MATCHED only when a specific PIN / Exhibit-A parcel ties the location.
                Section-only, instrument-on-file, federal -> LIKELY/EXCEPTION.
  2 section     MATCHED when an instrument's legal NAMES the section (parcel or section precision).
                Instrument-on-file-but-not-section-confirmed -> LIKELY; federal needing GIS -> EXCEPTION.
                (= the raw strict agent-loop result, no fold.)
  3 instrument  MATCHED when a controlling instrument is on file BY GROUND TYPE — parcel/section, or
                lease cert / state lease / tribal lease / BLM allotment-master-report. Only
                FSA-CLU-operatorship-with-no-instrument stays LIKELY. (= the prior-year AIP standard; default.)
  (grid)        Looser still = the per-grid Acreage High Dollar Review — a different review_mode.

  python set_specificity.py extracted/location_verdicts.json --level instrument
"""
import os, sys, json, argparse, collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import align_to_prior_aip as A

LEVELS = ["parcel", "section", "instrument"]


def apply_level(path, ev_path, level):
    data = json.load(open(path))
    if isinstance(data, list):
        data = {"verdicts": data}
    if level == "instrument":
        json.dump(data, open(path, "w"), indent=2)
        A.main(path, ev_path)                       # fold up to the prior-AIP standard, by ground type
        data = json.load(open(path))
    elif level == "section":
        json.dump(data, open(path, "w"), indent=2)  # strict agent-loop result, unchanged
    elif level == "parcel":
        for v in data["verdicts"]:                  # demand PIN/Exhibit-A precision
            if v.get("status") == "MATCHED" and (v.get("precision") or "").lower() != "parcel":
                v["status"] = "LIKELY"
                v["basis"] = "parcel/sub-section precision required at this specificity level — " + (v.get("basis") or "")
        json.dump(data, open(path, "w"), indent=2)
    else:
        raise SystemExit(f"unknown level {level!r}; choose one of {LEVELS}")
    dist = collections.Counter()
    for v in data["verdicts"]:
        s = v.get("status"); p = (v.get("precision") or "")
        dist["MATCHED (" + p + ")" if (s == "MATCHED" and p not in ("parcel", "section", "")) else s] += 1
    print(f"specificity level = {level} | section-group verdicts: {dict(dist)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("verdicts")
    ap.add_argument("--level", required=True, choices=LEVELS)
    ap.add_argument("--evidence", default="extracted/section_evidence.json")
    a = ap.parse_args()
    apply_level(a.verdicts, a.evidence, a.level)
