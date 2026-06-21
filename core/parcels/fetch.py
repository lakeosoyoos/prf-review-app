"""Auto-build the parcel ownership index (extracted/parcels.pkl) WITHOUT a manual file.

For a supported county, we search the public assessor by each roster name (insured + related +
lessors), read the owner + parcel number off the results list, and decode Section/Township/Range
straight from the parcel number (the county's own map convention). The result is the same
{"attrs": [{"PIN", "owner", "map"}...]} structure the matcher already consumes.

Nothing client-related leaves the machine — only public parcel records come in. The built index is
cached on disk and reused offline until it ages out.
"""
import os
import time
import pickle

from . import assessor


def _decode_trs_okanogan(parcel):
    """Okanogan parcel numbers encode TRS in the first 6 digits: TTRRSS....
    e.g. 3123202004 -> T31 R23 S20 -> '31-23-20'. Returns None if it doesn't look like one."""
    s = "".join(ch for ch in str(parcel) if ch.isdigit())
    if len(s) < 6:
        return None
    twp, rng, sec = int(s[0:2]), int(s[2:4]), int(s[4:6])
    if not (1 <= twp <= 99 and 1 <= rng <= 99 and 1 <= sec <= 36):
        return None
    return f"{twp}-{rng}-{sec}"


# county-name (upper) -> how to reach its public assessor + decode TRS
COUNTY_SOURCES = {
    "OKANOGAN": {"base": "https://okanoganwa-taxsifter.publicaccessnow.com",
                 "decode_trs": _decode_trs_okanogan},
    # extensible: add Ferry / Douglas etc. with their base + decoder when needed
    "FERRY":    {"base": "https://ferrywa-taxsifter.publicaccessnow.com",
                 "decode_trs": _decode_trs_okanogan},
}


def supported(county):
    return str(county or "").strip().upper() in COUNTY_SOURCES


def _fresh(path, max_age_days):
    if not os.path.exists(path):
        return False
    try:
        meta = pickle.load(open(path, "rb"))
        if not meta.get("attrs"):
            return False
    except Exception:
        return False
    age_days = (time.time() - os.path.getmtime(path)) / 86400.0
    return age_days <= max_age_days


def ensure_parcels(county, names, out_path, progress=lambda m: None,
                   max_age_days=180, delay=1.5):
    """Make sure out_path holds a fresh parcel index for `county`, built from `names`.
    Returns (ok: bool, message: str). Non-destructive: skips if a fresh file already exists."""
    src = COUNTY_SOURCES.get(str(county or "").strip().upper())
    if not src:
        return False, f"no automatic parcel source configured for county {county!r}"
    if _fresh(out_path, max_age_days):
        return True, "using cached parcel index"

    names = [n for n in dict.fromkeys(n.strip() for n in names if n and n.strip())]
    if not names:
        return False, "no owner names to search (check the account roster)"

    progress(f"Looking up parcels for {len(names)} owner name(s) on the {county} assessor…")
    session = assessor.new_session(src["base"])
    if session is None:
        return False, f"could not reach the {county} assessor (check internet)"

    attrs, seen = [], set()
    no_trs = 0
    for nm in names:
        rows = assessor.search_owner(src["base"], nm, session=session, delay=delay,
                                     progress=progress)
        for row in rows:
            pin = row["parcel"]
            if pin in seen:
                continue
            seen.add(pin)
            trs = src["decode_trs"](pin)
            if trs is None:
                no_trs += 1
            attrs.append({"PIN": pin, "owner": row.get("owner") or nm, "map": trs,
                          "landuse": row.get("landuse")})
        progress(f"  {nm}: {len(rows)} parcel(s)  (running total {len(attrs)})")

    if not attrs:
        return False, "assessor returned no parcels for the roster names"

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    pickle.dump({"attrs": attrs,
                 "_meta": {"source": "assessor:" + src["base"], "county": county,
                           "names": names, "fetched": time.time(),
                           "parcels": len(attrs), "without_trs": no_trs}},
                open(out_path, "wb"))
    msg = f"built parcel index: {len(attrs)} parcels"
    if no_trs:
        msg += f" ({no_trs} without a decodable section)"
    progress(msg + ".")
    return True, msg
