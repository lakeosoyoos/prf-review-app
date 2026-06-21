"""Deterministic template parsers for the standard PRF-review forms.

These run 100% LOCALLY with NO model and NO network — pure regex over OCR/text-layer text.
They handle the consistent-layout documents (DNR grazing leases, BLM Allotment Master Reports,
NAU Lease Certification Forms). Anything they can't confidently parse is handed to the local
VLM backend (see local_extract.py). Each parser returns a dict plus a 'confidence' and the
fields it could not find, so a human gate can review low-confidence extractions.

No imports beyond the standard library — nothing here can phone home.
"""
import re

ACRE = r"([\d,]+(?:\.\d+)?)"


def _num(s):
    try:
        return float(str(s).replace(",", ""))
    except (ValueError, TypeError):
        return None


def classify(text):
    """Best-effort document-type classifier from OCR text (local, no model)."""
    t = text.lower()
    if "allotment master report" in t or re.search(r"\bor\d{5}\b", t):
        return "blm_allotment"
    if "grazing lease" in t and "lease no" in t:
        return "dnr_grazing_lease"
    if "irrigated" in t and "lease no" in t:
        return "dnr_irrigated_lease"
    if "preference grazing permit" in t:
        return "dnr_preference_permit"
    if "lease certification" in t or ("lessor" in t and "tenant" in t and "%" in t):
        return "nau_lcf"
    if "confederated tribes of the colville" in t:
        return "colville_tribal_lease"
    return "unknown"


def parse_dnr_lease(text):
    """WA DNR Grazing/Irrigated Lease header → lessee, legal (T-R-S), acres, term."""
    out = {"doc_type": "dnr_lease", "missing": []}
    m = re.search(r"Lease\s*No\.?\s*([A-Z0-9-]{5,})", text, re.I)
    out["lease_number"] = m.group(1).strip() if m else None
    m = re.search(r"Lessee:?\s*\n?\s*([A-Za-z][A-Za-z .,&'-]+?)(?:\n|P\.?\s*O|PO\s+BOX|\(\d)", text, re.I)
    out["lessee"] = m.group(1).strip().rstrip(",") if m else None
    # legal: collect township/range and sections
    tr = re.findall(r"Township\s+(\d+)\s+North,?\s+Range\s+(\d+)\s+East", text, re.I)
    secs = re.findall(r"Section\s+(\d+)", text, re.I)
    out["townships"] = [f"T{a}N R{b}E" for a, b in tr]
    out["sections"] = sorted(set(secs), key=lambda x: int(x))
    m = re.search(r"containing\s+(?:approximately\s+)?" + ACRE + r"\s+acres", text, re.I)
    out["acres"] = _num(m.group(1)) if m else None
    m = re.search(r"commence\s+on\s+([A-Za-z0-9, ]+?)\s*\(.*?expire\s+on\s+([A-Za-z0-9, ]+?)\s*\(", text, re.I | re.S)
    if m:
        out["term_start"], out["term_end"] = m.group(1).strip(), m.group(2).strip()
    for k in ("lease_number", "lessee", "acres"):
        if not out.get(k):
            out["missing"].append(k)
    out["confidence"] = round(1 - len(out["missing"]) / 5, 2)
    return out


def _entity_alt(entities):
    """Regex alternation from a list of entity names (insured + related), or None."""
    if not entities:
        return None
    parts = [re.escape(e.strip()).replace(r"\ ", r"\s+") for e in entities if e and e.strip()]
    return "|".join(parts) if parts else None


def parse_blm_allotment(text, entities=None):
    """BLM Allotment Master Report → allotment no/name, operator/permittee, AUMs.
    `entities` (insured + related names from the account roster) sharpens operator detection."""
    out = {"doc_type": "blm_allotment", "missing": []}
    m = re.search(r"\b(OR\d{5})\b\s+([A-Z][A-Z .]+?)(?:\n|Office|Distribution)", text)
    if m:
        out["allotment_number"], out["allotment_name"] = m.group(1), m.group(2).strip()
    else:
        m = re.search(r"\b(OR\d{5})\b", text)
        out["allotment_number"] = m.group(1) if m else None
        out["allotment_name"] = None
    # operator: the name under "Operator Name" in the authorization cross-reference
    m = re.search(r"Operator\s*Name.*?\n?\s*([A-Z][A-Z ]{3,}?)\s+\d", text, re.I | re.S)
    if not m:
        alt = _entity_alt(entities)
        if alt:
            m = re.search(r"\b(" + alt + r")\b", text, re.I)
    out["operator"] = m.group(1).strip() if m else None
    m = re.search(r"Permitted\s*\n?\s*Use[\s\S]{0,40}?(\d+)", text, re.I)
    if not m:
        m = re.search(r"Total:\s*\d+\s+(\d+)", text)  # AUMs column on Total row
    out["permitted_aums"] = _num(m.group(1)) if m else None
    for k in ("allotment_number", "operator"):
        if not out.get(k):
            out["missing"].append(k)
    out["confidence"] = round(1 - len(out["missing"]) / 3, 2)
    return out


def parse_nau_lcf(text, entities=None, counties=None):
    """NAU Lease Certification Form → lessor, tenant entities + shares, acres, county.
    `entities` (tenant entity names from the roster) and `counties` (in-scope county names) make
    share/county capture account-specific; both fall back to generic patterns when not supplied."""
    out = {"doc_type": "nau_lcf", "missing": []}
    # entity shares e.g. "Cass Gebbers 33.3%", "Gebbers Cattle 40%"
    shares = {}
    alt = _entity_alt(entities)
    share_re = (r"(" + alt + r")\s*[: ]?\s*(\d{1,3}(?:\.\d)?)\s*%") if alt else \
               r"([A-Z][A-Za-z.&'-]+(?:\s+[A-Z][A-Za-z.&'-]+){0,3})\s*[: ]?\s*(\d{1,3}(?:\.\d)?)\s*%"
    for ent, pct in re.findall(share_re, text, re.I):
        shares[re.sub(r"\s+", " ", ent).strip().title()] = float(pct)
    out["tenant_shares"] = shares
    m = re.search(r"Lessor\s*\(?(?:Landlord)?\)?\s*[: ]\s*([A-Za-z][A-Za-z .,&'-]+?)(?:\n|Lessee|Tenant)", text, re.I)
    out["lessor"] = m.group(1).strip() if m else None
    acres = re.findall(ACRE + r"\s*(?:ac\b|acres)", text, re.I)
    out["acres_mentioned"] = [_num(a) for a in acres][:6]
    county_alt = "|".join(re.escape(c) for c in counties) if counties else \
        "Okanogan|Chelan|Douglas|Ferry|Grant|Benton|Stevens|Lincoln|Kittitas|Yakima|Adams"
    m = re.search(r"\b(" + county_alt + r")\b", text, re.I)
    out["county"] = m.group(1).title() if m else None
    if not shares:
        out["missing"].append("tenant_shares")
    if not out["lessor"]:
        out["missing"].append("lessor")
    out["confidence"] = round(1 - len(out["missing"]) / 3, 2)
    return out


PARSERS = {
    "blm_allotment": parse_blm_allotment,
    "dnr_grazing_lease": parse_dnr_lease,
    "dnr_irrigated_lease": parse_dnr_lease,
    "dnr_preference_permit": parse_dnr_lease,
    "nau_lcf": parse_nau_lcf,
}


def parse(text, doc_type=None, entities=None, counties=None):
    """Route text to the right template parser. Returns (doc_type, result-dict).
    entities/counties (from account_config.yaml) are passed to the parsers that use them."""
    dt = doc_type or classify(text)
    fn = PARSERS.get(dt)
    if not fn:
        return dt, {"doc_type": dt, "confidence": 0.0, "missing": ["(no template — route to local VLM)"]}
    if dt == "nau_lcf":
        return dt, fn(text, entities=entities, counties=counties)
    if dt == "blm_allotment":
        return dt, fn(text, entities=entities)
    return dt, fn(text)


if __name__ == "__main__":
    # self-test against representative text (the kind OCR yields from these forms) — no network, no model
    DNR = ("GRAZING LEASE\nLease No. 10-A78830\nLessee: Gebbers Cattle Ltd.\nP.O. Box 1448\n"
           "1.01 Property Description. State hereby leases to Lessee the following described property: "
           "Government Lots 3 & 4, Section 3; Section 4; all in Township 30 North, Range 24 East, W.M., "
           "Okanogan County, Washington, containing 364.47 acres, more or less.")
    BLM = ("ALLOTMENT MASTER REPORT\nOR00734 CHILIWIST BUTTE\nOffice: WENATCHEE RA\n"
           "Authorization Cross Reference\nOperator Name\nGEBBERS CATTLE 124 0 0 124\nPermitted Use 124")
    LCF = ("NAU LEASE CERTIFICATION FORM\nLessor (Landlord): Tracie Carter\nLessee (Tenant): "
           "Cass Gebbers 33.3% Ruby Range 33.3% Gebbers Cattle 33.3%\n831.16 acres  Okanogan County")
    for name, txt in [("DNR", DNR), ("BLM", BLM), ("LCF", LCF)]:
        dt, res = parse(txt)
        print(f"\n[{name}] classified={dt}")
        for k, v in res.items():
            print(f"    {k}: {v}")
