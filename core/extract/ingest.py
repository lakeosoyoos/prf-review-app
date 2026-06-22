"""Offline document reader -> pipeline inputs.

Reads a folder of lease / ownership PDFs ENTIRELY ON THIS MACHINE (PDF text layer, optional local
OCR, optional on-PC model) and writes the structured JSONs the matcher consumes. No network: the only
model call local_extract permits is loopback (see local_extract._assert_loopback). Never overwrites a
reviewer-prepared file.
"""
import os, re, sys, json, glob

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import local_extract as LE   # vendored; falls back to text-layer if OCR/VLM absent


def _legals_from_dnr(fields):
    """Build parseable 'Section X, Township T North, Range R East' strings from a parsed DNR lease."""
    out = []
    secs = fields.get("sections") or []
    for tw in (fields.get("townships") or []):
        m = re.search(r"T(\d+)N\s*R(\d+)E", tw)
        if not m:
            continue
        for s in secs:
            out.append(f"Section {s}, Township {m.group(1)} North, Range {m.group(2)} East")
    return out


def reader_status():
    """What offline reading is available on this machine. No outbound probe."""
    st = {"parsers": True, "network": "none", "pdf_render": False, "ocr": False, "local_model": False}
    try:
        import fitz  # noqa: F401  (PyMuPDF)
        st["pdf_render"] = True
    except Exception:
        pass
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        st["ocr"] = True
    except Exception:
        pass
    try:
        vs = LE.vlm_status()
        st["vlm"] = vs
        st["local_model"] = bool(vs.get("reachable"))   # a handwriting model is actually up
    except Exception:
        st["local_model"] = False
    return st


def ingest(doc_dirs, out_dir, entities=None, counties=None, progress=lambda m: None, overwrite=False):
    """Read every PDF under doc_dirs and write recorded_grazing_leases.json + signed_lease_certs.json
    (+ _REVIEW_QUEUE.json) into out_dir. Returns a summary dict. Non-destructive unless overwrite=True."""
    os.makedirs(out_dir, exist_ok=True)
    pdfs = []
    for d in doc_dirs:
        if d and os.path.isdir(d):
            pdfs += glob.glob(os.path.join(d, "**", "*.pdf"), recursive=True)
    pdfs = sorted(set(pdfs))
    progress(f"Reading {len(pdfs)} document(s) on this computer…")
    certs, recorded, queue = [], [], []
    for p in pdfs:
        try:
            res = LE.extract_document(p, entities=entities, counties=counties)
        except Exception:
            continue
        f = os.path.basename(p); dt = res.get("doc_type"); fields = res.get("fields") or {}
        if res.get("needs_human_review"):
            queue.append({"file": f, "doc_type": dt, "confidence": res.get("confidence")})
        if dt in ("dnr_lease", "dnr_grazing_lease", "dnr_irrigated_lease", "dnr_preference_permit"):
            recorded.append({"file": f, "lessor": fields.get("lessee") or "WA DNR (state lease)",
                             "term": f"{fields.get('term_start', '')} - {fields.get('term_end', '')}".strip(" -"),
                             "legal_descriptions": _legals_from_dnr(fields)})
        elif dt == "blm_allotment":
            recorded.append({"file": f, "lessor": "US BLM / " + (fields.get("operator") or ""),
                             "term": "BLM allotment " + (fields.get("allotment_number") or ""), "legal_descriptions": []})
        elif dt == "colville_tribal_lease":
            recorded.append({"file": f, "lessor": "Colville Confederated Tribes",
                             "term": "tribal lease", "legal_descriptions": []})
        elif dt == "nau_lcf":
            certs.append({"file": f, "lessor": fields.get("lessor") or "",
                          "county": fields.get("county") or "",
                          "acres": (fields.get("acres_mentioned") or [None])[0],
                          "legal_descriptions": [], "tract_or_farm_numbers": []})

    written = []
    def _w(name, data):
        path = os.path.join(out_dir, name)
        if os.path.exists(path) and not overwrite:
            return False
        json.dump(data, open(path, "w"), indent=2)
        written.append(name)
        return True
    _w("recorded_grazing_leases.json", recorded)
    _w("signed_lease_certs.json", certs)
    json.dump(queue, open(os.path.join(out_dir, "_REVIEW_QUEUE.json"), "w"), indent=2)
    progress(f"Read {len(pdfs)} document(s) → {len(recorded)} leases/permits, {len(certs)} certs, "
             f"{len(queue)} flagged for human review.")
    return {"pdfs": len(pdfs), "recorded": len(recorded), "certs": len(certs),
            "review_queue": len(queue), "written": written}
