"""Public county-assessor (TaxSifter / Aumentum PublicAccess) owner-by-name search.

No login, no API key. Reverse-engineered against the live Okanogan site and reused from the
verified flow in the septic tool:
  1. GET /Disclaimer.aspx, POST "I Agree"      -> establishes a search session
  2. GET /Search/Results.aspx?q=<name>&page=N  -> a list of `div.result` blocks, each carrying
     the owner name, the parcel number (in the Assessor.aspx link), and the DOR land-use.

We read owner + parcel straight off the results list, so one page fetch yields ~20 parcels with
no per-parcel detail request. Polite by design: a real browser UA, a throttle between requests,
and graceful degradation (every failure returns empty, never raises).

This pulls PUBLIC parcel records INBOUND only; no client/insured data is ever sent.
"""
import re
import time
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")


def manual_url(base, query):
    """A URL a person can open to verify a search by hand."""
    return f"{base.rstrip('/')}/Search/Results.aspx?q={quote(str(query))}&page=1"


def _aspnet_fields(soup):
    out = {}
    for name in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"):
        el = soup.find("input", {"name": name})
        if el is not None and el.get("value") is not None:
            out[name] = el["value"]
    return out


def new_session(base, timeout=30):
    """Accept the disclaimer and return a ready-to-search requests.Session (or None on failure)."""
    try:
        s = requests.Session()
        s.headers.update({"User-Agent": UA})
        r = s.get(f"{base}/Disclaimer.aspx", timeout=timeout)
        data = _aspnet_fields(BeautifulSoup(r.text, "html.parser"))
        data["ctl00$cphContent$btnAgree"] = "I Agree"
        s.post(f"{base}/Disclaimer.aspx", data=data, timeout=timeout)
        return s
    except Exception:
        return None


def parse_results(html):
    """Parse a Results.aspx page into [{parcel, owner, landuse}] rows."""
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for div in soup.find_all("div", class_="result"):
        a = div.find("a", href=re.compile(r"Assessor\.aspx", re.I))
        if not a:
            continue
        m = re.search(r"parcelNumber=(\w+)", a["href"])
        if not m:
            continue
        parcel = m.group(1)
        txt = div.get_text(" ", strip=True)
        owner = None
        mo = re.match(r"(.+?)\s*\(Parcel Owner\)", txt)
        if mo:
            owner = mo.group(1).strip()
        mlu = re.search(r"\b(\d{2})\s*-\s*([^|]+?)(?:\s*\||$)", txt)
        landuse = mlu.group(1) if mlu else None
        rows.append({"parcel": parcel, "owner": owner, "landuse": landuse})
    return rows


def search_owner(base, name, session=None, delay=1.5, max_pages=200, timeout=30,
                 progress=lambda m: None):
    """Yield every parcel row owned by `name` across all result pages. Empty on failure."""
    s = session or new_session(base)
    if s is None:
        progress(f"  (could not reach assessor for {name!r})")
        return []
    out, seen = [], set()
    for page in range(1, max_pages + 1):
        try:
            r = s.get(f"{base}/Search/Results.aspx",
                      params={"q": name, "page": str(page)}, timeout=timeout)
        except Exception:
            break
        rows = parse_results(r.text)
        fresh = [row for row in rows if row["parcel"] not in seen]
        if not fresh:
            break
        for row in fresh:
            seen.add(row["parcel"])
        out += fresh
        if len(rows) < 20:          # last page (page size is 20)
            break
        time.sleep(delay)
    return out
