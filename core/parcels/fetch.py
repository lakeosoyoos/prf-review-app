"""Auto-build the parcel ownership index (extracted/parcels.pkl) WITHOUT a manual file — and
without hardcoding every county.

At run time, for the account's county, we:
  1. RESOLVE the public assessor URL — a known one if we have it, else DISCOVER it by probing the
     standard TaxSifter/PublicAccess URL patterns for that county.
  2. SEARCH the assessor by each roster name and read owner + parcel off the results list.
  3. PICK A TRS STRATEGY automatically: spot-check a few parcels with the fast parcel-number decode
     against the universal geometry->BLM-PLSS truth; if they agree, decode all the fast way; if not,
     fall back to PLSS per parcel; if neither works, record owners without a section.

So a brand-new county works on the first run with no code change. The result is the same
{"attrs":[{PIN,owner,map}]} index the matcher consumes. Public records IN only; cached + reused
offline (default 180-day freshness). Guarded everywhere: failures degrade, never raise.
"""
import os
import time
import pickle

from . import assessor, geo

# Known-good assessor base URLs (skip discovery for these). Discovery handles the rest.
KNOWN_BASES = {
    "OKANOGAN": "https://okanoganwa-taxsifter.publicaccessnow.com",
    "FERRY":    "https://ferrywa-taxsifter.publicaccessnow.com",
    "DOUGLAS":  "https://douglaswa-taxsifter.publicaccessnow.com",
}
_DISCOVERY_CACHE = {}


def _decode_trs_parcelnum(parcel):
    """Fast shortcut: many counties encode TRS in the first 6 digits (TTRRSS...).
    e.g. 3123202004 -> '31-23-20'. Validated per-county against PLSS before it's trusted."""
    s = "".join(ch for ch in str(parcel) if ch.isdigit())
    if len(s) < 6:
        return None
    twp, rng, sec = int(s[0:2]), int(s[2:4]), int(s[4:6])
    if not (1 <= twp <= 99 and 1 <= rng <= 99 and 1 <= sec <= 36):
        return None
    return f"{twp}-{rng}-{sec}"


def discover_base(county, state="wa", timeout=15):
    """Probe the standard public-assessor URL patterns for a county; return a working base or None."""
    key = (str(county).upper(), str(state).upper())
    if key in _DISCOVERY_CACHE:
        return _DISCOVERY_CACHE[key]
    c = "".join(ch for ch in str(county).lower() if ch.isalnum())
    st = str(state).lower()
    candidates = [
        f"https://{c}{st}-taxsifter.publicaccessnow.com",
        f"https://{c}{st}.taxsifter.com",
        f"http://{c}{st}.taxsifter.com",
    ]
    found = None
    for base in candidates:
        try:
            import urllib.request
            html = urllib.request.urlopen(base + "/Disclaimer.aspx", timeout=timeout).read().decode("utf-8", "ignore")
            if "btnAgree" in html or "I Agree" in html or "Disclaimer" in html:
                found = base
                break
        except Exception:
            continue
    _DISCOVERY_CACHE[key] = found
    return found


def resolve_base(county, state="wa"):
    return KNOWN_BASES.get(str(county or "").strip().upper()) or discover_base(county, state)


def supported(county, state="wa"):
    """True if we already know this county's assessor (no network needed to say so)."""
    return str(county or "").strip().upper() in KNOWN_BASES


def _pick_trs_strategy(sample_parcels, state, progress=lambda m: None):
    """Decide how to decode TRS for this county. Returns 'parcelnum', 'plss', or 'none'."""
    agree = checked = plss_ok = 0
    for p in sample_parcels[:4]:
        truth = geo.plss_trs(p, state=state)
        if truth is None:
            continue
        plss_ok += 1
        checked += 1
        if _decode_trs_parcelnum(p) == truth:
            agree += 1
    if checked and agree == checked:
        progress("  (parcel numbers encode section/township/range — using the fast decode)")
        return "parcelnum"
    if plss_ok:
        progress("  (decoding section/township/range from parcel geometry — a bit slower)")
        return "plss"
    if any(_decode_trs_parcelnum(p) for p in sample_parcels[:4]):
        progress("  (no geometry check available — using the parcel-number decode, unvalidated)")
        return "parcelnum"
    return "none"


def _fresh(path, max_age_days):
    if not os.path.exists(path):
        return False
    try:
        if not pickle.load(open(path, "rb")).get("attrs"):
            return False
    except Exception:
        return False
    return (time.time() - os.path.getmtime(path)) / 86400.0 <= max_age_days


def ensure_parcels(county, names, out_path, state="wa", progress=lambda m: None,
                   max_age_days=180, delay=1.5):
    """Make sure out_path holds a fresh parcel index for `county`, built from `names`.
    Returns (ok, message). Discovers the assessor + TRS method at run time for new counties."""
    if _fresh(out_path, max_age_days):
        return True, "using cached parcel index"

    names = list(dict.fromkeys(n.strip() for n in names if n and n.strip()))
    if not names:
        return False, "no owner names to search (check the account roster)"

    base = resolve_base(county, state)
    if not base:
        return False, f"couldn't find a public assessor for county {county!r} (add it to KNOWN_BASES)"

    progress(f"Looking up parcels for {len(names)} owner name(s) on the {county} assessor…")
    session = assessor.new_session(base)
    if session is None:
        return False, f"could not reach the {county} assessor (check internet)"

    rows = []
    for nm in names:
        got = assessor.search_owner(base, nm, session=session, delay=delay, progress=progress)
        rows += got
        progress(f"  {nm}: {len(got)} parcel(s)")
    # dedupe by parcel
    by_pin = {}
    for r in rows:
        by_pin.setdefault(r["parcel"], r)
    rows = list(by_pin.values())
    if not rows:
        return False, "assessor returned no parcels for the roster names"

    method = _pick_trs_strategy([r["parcel"] for r in rows], state, progress)
    attrs, no_trs = [], 0
    for r in rows:
        pin = r["parcel"]
        if method == "parcelnum":
            trs = _decode_trs_parcelnum(pin)
        elif method == "plss":
            trs = geo.plss_trs(pin, state=state)
        else:
            trs = None
        if trs is None:
            no_trs += 1
        attrs.append({"PIN": pin, "owner": r.get("owner"), "map": trs, "landuse": r.get("landuse")})

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    pickle.dump({"attrs": attrs,
                 "_meta": {"source": "assessor:" + base, "county": county, "state": state,
                           "names": names, "fetched": time.time(), "trs_method": method,
                           "parcels": len(attrs), "without_trs": no_trs}},
                open(out_path, "wb"))
    msg = f"built parcel index: {len(attrs)} parcels via {method}"
    if no_trs:
        msg += f" ({no_trs} without a decodable section)"
    progress(msg + ".")
    return True, msg
