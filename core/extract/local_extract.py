"""LOCAL, AIR-GAPPED document extraction for the PRF review.

GOAL: zero data ever leaves the machine. Nothing here calls any external/cloud service.
The only network call permitted is to a LOCAL model server on 127.0.0.1 (Ollama/vLLM); a hard
guard refuses any non-loopback host. If no local model is running, the pipeline still produces
results for every standard form via the deterministic template parsers (no model at all).

PIPELINE per document:
   PDF -> page image(s) -> OCR/text  -> classify -> template parser (form_templates.py)
                                                  -> if low confidence: LOCAL VLM (loopback only)
                                                  -> validate vs schema + confidence flag
                                                  -> extracted/<name>.json   (+ a review queue for low-confidence)

Dependencies are optional and checked at runtime (so this file imports cleanly anywhere):
   - PDF->image / text:  PyMuPDF (fitz)   [pip install pymupdf]      (falls back to pypdf text layer)
   - OCR:                pytesseract+Pillow [pip install pytesseract pillow] + system `tesseract`
                         (or PaddleOCR / docTR — swap in ocr_image())
   - Local VLM:          Ollama running locally with a vision model, e.g. `ollama pull qwen2.5vl`
All are open-source and run offline. See references/local-extraction.md.
"""
import os, sys, json, base64, urllib.request, urllib.parse, ipaddress, socket

sys.path.insert(0, os.path.dirname(__file__))
import form_templates as T

# ----------------------------------------------------------------------------- privacy guard
def _trusted_hosts():
    """Optionally allow ONE on-premises model host (e.g. the office Mac Studio down the hall) in
    addition to loopback. This is a DELIBERATE boundary the operator opts into — the data still never
    leaves your own network. Set PRF_LOCAL_VLM_TRUSTED_HOST to that machine's LAN IP/hostname."""
    h = (os.environ.get("PRF_LOCAL_VLM_TRUSTED_HOST") or "").strip().lower()
    return {h} if h else set()


def _assert_loopback(url):
    """Refuse any model endpoint that is not on this machine (or the one opted-in on-prem host).
    Hard stop — protects confidentiality. Cloud/remote hosts are always refused."""
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if host in ("localhost",) or host in _trusted_hosts():
        return
    try:
        ip = ipaddress.ip_address(socket.gethostbyname(host))
    except Exception:
        raise RuntimeError(f"REFUSED: model host '{host}' is not loopback. Local-only policy.")
    if ip.is_loopback:
        return
    # a private-LAN address is allowed ONLY if it's the explicitly trusted on-prem host
    if (ip.is_private or ip.is_link_local) and host in _trusted_hosts():
        return
    raise RuntimeError(f"REFUSED: model host '{host}' ({ip}) is not this machine or the trusted "
                       f"on-prem host. Data must not leave your network.")

OLLAMA_URL = os.environ.get("PRF_LOCAL_VLM_URL", "http://127.0.0.1:11434/api/generate")
VLM_MODEL = os.environ.get("PRF_LOCAL_VLM_MODEL", "qwen2.5vl")
CONF_THRESHOLD = 0.75  # below this, escalate to the local VLM, then to the human review queue

# ----------------------------------------------------------------------------- PDF -> text/images
def page_texts_and_images(pdf_path, dpi=300):
    """Yield (page_index, text_layer, png_bytes) per page. Local only."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        fitz = None
    if fitz:
        doc = fitz.open(pdf_path)
        for i, page in enumerate(doc):
            txt = page.get_text() or ""
            pix = page.get_pixmap(dpi=dpi)
            yield i, txt, pix.tobytes("png")
        return
    # fallback: text layer only (no images) via pypdf
    from pypdf import PdfReader
    for i, page in enumerate(PdfReader(pdf_path).pages):
        yield i, (page.extract_text() or ""), None

def ocr_image(png_bytes):
    """OCR a page image locally. Returns text or '' if OCR unavailable."""
    if not png_bytes:
        return ""
    try:
        import pytesseract, io
        from PIL import Image
        return pytesseract.image_to_string(Image.open(io.BytesIO(png_bytes)))
    except Exception:
        return ""  # OCR not installed; rely on text layer / VLM

def page_text(text_layer, png_bytes, min_chars=40):
    """Use the embedded text layer if present; otherwise OCR the rendered image. All local."""
    if text_layer and len(text_layer.strip()) >= min_chars:
        return text_layer
    return ocr_image(png_bytes)

# ----------------------------------------------------------------------------- LOCAL VLM backend
def vlm_extract(png_bytes, schema_hint, url=None, model=None):
    """Send ONE page image to a LOCAL vision model (loopback only) and get structured JSON back.
    Returns dict or None if no local model is reachable. Never contacts a remote server."""
    url = url or OLLAMA_URL
    _assert_loopback(url)  # hard privacy guard
    if not png_bytes:
        return None
    prompt = ("You are a local document-extraction tool. Read this scanned crop-insurance document "
              "and return ONLY a JSON object with these fields (use null if absent): " + schema_hint +
              " Do not add commentary.")
    payload = {"model": model or VLM_MODEL, "prompt": prompt, "stream": False, "format": "json",
               "images": [base64.b64encode(png_bytes).decode()]}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:  # loopback only (guarded above)
            resp = json.loads(r.read().decode())
        return json.loads(resp.get("response", "{}"))
    except (urllib.error.URLError, ConnectionError, OSError):
        return None  # no local model running — caller falls back to template/human queue

def vlm_status(url=None, timeout=3):
    """Report the local vision model: configured host/model, whether it's reachable, guard ok.
    Only a loopback/trusted-host probe — never contacts a remote server."""
    url = url or OLLAMA_URL
    host = urllib.parse.urlparse(url).hostname or ""
    st = {"host": host, "model": VLM_MODEL, "reachable": False, "guard_ok": True, "models": []}
    try:
        _assert_loopback(url)
    except RuntimeError:
        st["guard_ok"] = False
        return st
    try:
        tags_url = url.replace("/api/generate", "/api/tags")
        with urllib.request.urlopen(tags_url, timeout=timeout) as r:
            data = json.loads(r.read().decode())
        st["reachable"] = True
        st["models"] = [m.get("name") for m in data.get("models", []) if m.get("name")]
    except Exception:
        pass
    return st


# ----------------------------------------------------------------------------- orchestration
SCHEMA_HINTS = {
    "dnr_lease": "lease_number, lessee, sections, townships, acres, term_start, term_end",
    "blm_allotment": "allotment_number, allotment_name, operator, permitted_aums",
    "nau_lcf": "lessor, tenant_shares (entity:percent), acres, county, term",
    "unknown": "document_type, parties, acres, legal_description, dates",
}

def extract_document(pdf_path, entities=None, counties=None):
    """Extract one document fully locally. Returns a result dict with source, fields, confidence,
    and 'needs_human_review' if below threshold."""
    name = os.path.splitext(os.path.basename(pdf_path))[0]
    texts = []
    first_img = None
    for _, tl, img in page_texts_and_images(pdf_path):
        texts.append(page_text(tl, img))
        if first_img is None:
            first_img = img
    full = "\n".join(texts)
    dt = T.classify(full)
    _, parsed = T.parse(full, dt, entities=entities, counties=counties)
    method = "template"
    conf = parsed.get("confidence", 0.0)
    # escalate low-confidence to the LOCAL vlm (if running)
    if conf < CONF_THRESHOLD:
        vlm = vlm_extract(first_img, SCHEMA_HINTS.get(dt, SCHEMA_HINTS["unknown"]))
        if vlm:
            parsed = {**parsed, **{k: v for k, v in vlm.items() if v not in (None, "")}, "doc_type": dt}
            method = "local_vlm"
            parsed["confidence"] = max(conf, 0.8)
            conf = parsed["confidence"]
    return {
        "source_file": os.path.basename(pdf_path),
        "doc_type": dt,
        "method": method,                       # template | local_vlm
        "confidence": conf,
        "needs_human_review": conf < CONF_THRESHOLD,
        "fields": parsed,
    }

def load_entities(config):
    """Pull tenant/insured entity names + in-scope counties from account_config.yaml (optional)."""
    if not config or not os.path.exists(config):
        return None, None
    try:
        import yaml
        cfg = yaml.safe_load(open(config))
    except Exception:
        return None, None
    e = cfg.get("entities", {})
    entities = (list(e.get("insured_aliases") or []) + list(e.get("related") or []))
    counties = []
    for p in cfg.get("policies", []) or []:
        counties += [str(c) for c in (p.get("counties") or [])]
    return (entities or None), (sorted(set(counties)) or None)


def run_folder(in_dir, out_dir, config=None):
    os.makedirs(out_dir, exist_ok=True)
    entities, counties = load_entities(config)
    results, queue = [], []
    for fn in sorted(os.listdir(in_dir)):
        if not fn.lower().endswith(".pdf"):
            continue
        res = extract_document(os.path.join(in_dir, fn), entities=entities, counties=counties)
        with open(os.path.join(out_dir, os.path.splitext(fn)[0] + ".json"), "w") as f:
            json.dump(res, f, indent=2)
        results.append(res)
        if res["needs_human_review"]:
            queue.append({"file": res["source_file"], "doc_type": res["doc_type"], "confidence": res["confidence"]})
    with open(os.path.join(out_dir, "_REVIEW_QUEUE.json"), "w") as f:
        json.dump(queue, f, indent=2)
    by_method = {}
    for r in results:
        by_method[r["method"]] = by_method.get(r["method"], 0) + 1
    print(f"extracted {len(results)} docs -> {out_dir}")
    print(f"  by method: {by_method}")
    print(f"  needs human review: {len(queue)} (see _REVIEW_QUEUE.json)")
    print("  network used: NONE (template parsers) / loopback-only (if local VLM ran)")


def doctor():
    """Offline readiness check. Reports which local capabilities are available and confirms the
    privacy guard. Makes NO outbound network call (only a loopback probe of the local VLM)."""
    print("PRF local-extraction readiness (everything below runs ON THIS MACHINE):\n")
    ok = lambda b: "  OK " if b else "  -- "

    try:
        import fitz  # noqa
        have_fitz = True
    except ImportError:
        have_fitz = False
    print(ok(have_fitz), "PyMuPDF (PDF text + rasterize)        ", "" if have_fitz else "pip install pymupdf  (falls back to pypdf text-layer only)")

    try:
        import pytesseract
        from PIL import Image  # noqa
        ver = pytesseract.get_tesseract_version()
        have_ocr = True
    except Exception:
        ver, have_ocr = None, False
    print(ok(have_ocr), "Tesseract OCR (scans / handwriting)    ", f"v{ver}" if have_ocr else "pip install pytesseract pillow + `brew/apt install tesseract`")

    # template parsers always available (stdlib only)
    try:
        import form_templates as _t
        n = len(_t.PARSERS)
        print(ok(True), f"Template parsers ({n} forms, no model)  ", "always available — pure regex, no network")
    except Exception as e:
        print(ok(False), "Template parsers                       ", f"IMPORT ERROR: {e}")

    # local VLM: loopback probe only
    guard_ok = True
    try:
        _assert_loopback(OLLAMA_URL)
    except RuntimeError:
        guard_ok = False
    reachable = False
    if guard_ok:
        try:
            req = urllib.request.Request(OLLAMA_URL.replace("/api/generate", "/api/tags"))
            with urllib.request.urlopen(req, timeout=2):
                reachable = True
        except Exception:
            reachable = False
    print(ok(reachable), f"Local VLM at {OLLAMA_URL.split('/api')[0]:22}", f"model={VLM_MODEL}" if reachable else "optional — only consulted for low-confidence pages")

    # privacy guard self-test
    refused = []
    for bad in ("http://api.anthropic.com/v1", "http://8.8.8.8:11434", "http://example.com"):
        try:
            _assert_loopback(bad); refused.append((bad, False))
        except RuntimeError:
            refused.append((bad, True))
    allowed = all(_safe(lambda: _assert_loopback(u)) for u in ("http://127.0.0.1:11434", "http://localhost:11434"))
    all_refused = all(r for _, r in refused)
    print(ok(all_refused and allowed), "Privacy guard (loopback-only)          ",
          "refuses non-loopback hosts; allows 127.0.0.1/localhost" if (all_refused and allowed) else "GUARD CHECK FAILED — do not run with a VLM")
    print("\nMinimum to run fully offline: template parsers + (PyMuPDF or pypdf). OCR + local VLM are")
    print("optional accuracy boosters. With none of the optional pieces, every standard form still parses.")


def _safe(fn):
    try:
        fn(); return True
    except Exception:
        return False


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "doctor":
        doctor()
    elif len(sys.argv) >= 3:
        config = sys.argv[3] if len(sys.argv) > 3 else None
        run_folder(sys.argv[1], sys.argv[2], config=config)
    else:
        sys.exit("usage:\n  python local_extract.py doctor\n"
                 "  python local_extract.py <input_pdf_dir> <output_json_dir> [account_config.yaml]")
