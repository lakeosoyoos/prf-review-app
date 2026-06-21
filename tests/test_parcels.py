"""Tests for the no-file parcel auto-fetch (core/parcels). All offline — network is monkeypatched."""
import os, sys, pickle
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.parcels import assessor, fetch, geo


def test_trs_decodes_from_parcel_number():
    assert fetch._decode_trs_parcelnum("3123202004") == "31-23-20"   # T31 R23 S20
    assert fetch._decode_trs_parcelnum("12") is None                  # too short
    assert fetch._decode_trs_parcelnum("9999990000") is None          # section 99 -> invalid


def test_plss_id_decode():
    assert geo._decode_plssid("WA330310N0230E0", 20) == "31-23-20"
    assert geo._decode_plssid("WA330320N0240E0", "36") == "32-24-36"
    assert geo._decode_plssid("garbage", 5) is None


def test_known_counties_skip_discovery():
    assert fetch.supported("Okanogan") and fetch.supported("FERRY")
    assert fetch.resolve_base("Okanogan").endswith("publicaccessnow.com")
    assert not fetch.supported("Chelan")          # not pre-known -> would be discovered at run


def test_discover_base_probes_url_patterns(monkeypatch):
    import urllib.request
    def fake_open(url, timeout=15):
        class R:
            def read(self_):
                return (b"<input name='btnAgree'/>" if "chelanwa-taxsifter.publicaccessnow.com" in url
                        else b"nope")
        if "chelanwa-taxsifter.publicaccessnow.com" in url:
            return R()
        raise OSError("no such host")
    monkeypatch.setattr(urllib.request, "urlopen", fake_open)
    fetch._DISCOVERY_CACHE.clear()
    base = fetch.discover_base("Chelan")
    assert base == "https://chelanwa-taxsifter.publicaccessnow.com"


def test_parse_results_reads_owner_parcel_landuse():
    html = """
    <div class="result">
      GEBBERS CATTLE LTD (Parcel Owner) | 3123202004 | GEBBERS CATTLE LTD | 83 - Resource - Agriculture Current Use
      <div class="nav"><ul>
        <li><a href="/Assessor.aspx?keyId=1459870&parcelNumber=3123202004&typeID=1">Assessor</a></li>
      </ul></div>
    </div>"""
    rows = assessor.parse_results(html)
    assert len(rows) == 1 and rows[0]["parcel"] == "3123202004"
    assert rows[0]["owner"] == "GEBBERS CATTLE LTD" and rows[0]["landuse"] == "83"


def test_strategy_prefers_fast_decode_when_it_matches_plss(monkeypatch):
    monkeypatch.setattr(geo, "plss_trs", lambda p, state="WA": fetch._decode_trs_parcelnum(p))
    assert fetch._pick_trs_strategy(["3123202004", "3124210004"], "wa") == "parcelnum"


def test_strategy_falls_back_to_plss_when_shortcut_disagrees(monkeypatch):
    monkeypatch.setattr(geo, "plss_trs", lambda p, state="WA": "1-1-1")  # truth != parcelnum decode
    assert fetch._pick_trs_strategy(["3123202004"], "wa") == "plss"


def test_ensure_parcels_writes_matcher_shaped_pickle(tmp_path, monkeypatch):
    monkeypatch.setattr(assessor, "new_session", lambda base, **k: object())
    monkeypatch.setattr(assessor, "search_owner",
                        lambda base, name, **k: [{"parcel": "3123202004", "owner": name, "landuse": "83"},
                                                 {"parcel": "2922010050", "owner": name, "landuse": "83"}])
    monkeypatch.setattr(geo, "plss_trs", lambda p, state="WA": fetch._decode_trs_parcelnum(p))
    out = tmp_path / "extracted" / "parcels.pkl"
    ok, msg = fetch.ensure_parcels("Okanogan", ["GEBBERS CATTLE LTD"], str(out))
    assert ok, msg
    meta = pickle.load(open(out, "rb"))
    assert len(meta["attrs"]) == 2 and meta["_meta"]["trs_method"] == "parcelnum"
    assert meta["attrs"][0]["map"] == "31-23-20"


def test_ensure_parcels_unknown_county_is_graceful(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "discover_base", lambda county, state="wa": None)
    ok, msg = fetch.ensure_parcels("Nowhere", ["X"], str(tmp_path / "p.pkl"))
    assert not ok and "couldn't find a public assessor" in msg
