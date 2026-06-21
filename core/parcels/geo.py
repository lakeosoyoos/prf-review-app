"""Universal Section/Township/Range for a parcel — parcel geometry -> BLM PLSS.

Works for any parcel without knowing the county's parcel-number scheme: look the parcel up in the
public statewide parcel layer to get its geometry, take the centroid, and ask BLM's national PLSS
service which section it falls in. Used to (a) auto-validate the fast parcel-number shortcut for a
new county and (b) decode TRS outright when the shortcut doesn't apply.

Public data IN only. WA-scoped today (the statewide geometry source is WA); returns None elsewhere.
"""
import re
import json
import urllib.parse
import urllib.request

# WA statewide parcels (geometry + ORIG_PARCEL_ID), and BLM's national PLSS "section" layer.
WA_PARCELS = ("https://services.arcgis.com/jsIt88o09Q0r1j8h/arcgis/rest/services/"
              "Current_Parcels/FeatureServer/0/query")
BLM_PLSS_SECTION = ("https://gis.blm.gov/arcgis/rest/services/Cadastral/"
                    "BLM_Natl_PLSS_CadNSDI/MapServer/2/query")


def _get(url, params, timeout=25):
    try:
        return json.load(urllib.request.urlopen(url + "?" + urllib.parse.urlencode(params),
                                                 timeout=timeout))
    except Exception:
        return None


def _centroid(geom):
    ring = (geom.get("rings") or [None])[0]
    if not ring:
        return None
    xs = [p[0] for p in ring]; ys = [p[1] for p in ring]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _decode_plssid(plssid, frstdivno):
    """'WA330310N0230E0' + section 20 -> '31-23-20'."""
    m = re.match(r"[A-Za-z]{2}\d{2}(\d{4})([NS])(\d{4})([EW])", str(plssid or ""))
    if not m:
        return None
    twp = int(m.group(1)) // 10
    rng = int(m.group(3)) // 10
    sec = int(re.sub(r"\D", "", str(frstdivno or "")) or 0)
    if not (1 <= sec <= 36 and twp and rng):
        return None
    return f"{twp}-{rng}-{sec}"


def plss_trs(parcel, state="WA", timeout=25):
    """Resolve a parcel number to 'T-R-S' via statewide geometry + BLM PLSS, or None."""
    if str(state or "WA").upper() != "WA":
        return None                      # geometry source is WA-only for now
    d = _get(WA_PARCELS, {"where": f"ORIG_PARCEL_ID='{parcel}'", "outFields": "ORIG_PARCEL_ID",
                          "returnGeometry": "true", "f": "json", "resultRecordCount": 1}, timeout)
    feats = (d or {}).get("features") or []
    if not feats:
        return None
    c = _centroid(feats[0].get("geometry") or {})
    if not c:
        return None
    sr = (d.get("spatialReference") or {})
    pq = _get(BLM_PLSS_SECTION,
              {"geometry": json.dumps({"x": c[0], "y": c[1], "spatialReference": sr}),
               "geometryType": "esriGeometryPoint", "inSR": sr.get("wkid", 2927),
               "spatialRel": "esriSpatialRelIntersects",
               "outFields": "FRSTDIVNO,PLSSID", "returnGeometry": "false", "f": "json"}, timeout)
    pf = (pq or {}).get("features") or []
    if not pf:
        return None
    a = pf[0].get("attributes") or {}
    return _decode_plssid(a.get("PLSSID"), a.get("FRSTDIVNO"))
