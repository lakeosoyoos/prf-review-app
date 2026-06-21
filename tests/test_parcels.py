"""Tests for the no-file parcel auto-fetch (core/parcels). All offline — no live network."""
import os, sys, pickle
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.parcels import assessor, fetch


def test_trs_decodes_from_okanogan_parcel_number():
    assert fetch._decode_trs_okanogan("3123202004") == "31-23-20"   # T31 R23 S20
    assert fetch._decode_trs_okanogan("12") is None                  # too short
    assert fetch._decode_trs_okanogan("9999990000") is None          # section 99 -> invalid


def test_supported_counties():
    assert fetch.supported("Okanogan") and fetch.supported("OKANOGAN")
    assert not fetch.supported("Nowhere")


def test_parse_results_reads_owner_parcel_landuse():
    html = """
    <div class="result">
      GEBBERS CATTLE LTD (Parcel Owner) | 3123202004 | GEBBERS CATTLE LTD | 83 - Resource - Agriculture Current Use
      <div class="nav"><ul>
        <li><a href="/Assessor.aspx?keyId=1459870&parcelNumber=3123202004&typeID=1">Assessor</a></li>
      </ul></div>
    </div>"""
    rows = assessor.parse_results(html)
    assert len(rows) == 1
    assert rows[0]["parcel"] == "3123202004"
    assert rows[0]["owner"] == "GEBBERS CATTLE LTD"
    assert rows[0]["landuse"] == "83"


def test_ensure_parcels_writes_matcher_shaped_pickle(tmp_path, monkeypatch):
    # stub the network: one owner -> two parcels
    monkeypatch.setattr(assessor, "new_session", lambda base, **k: object())
    monkeypatch.setattr(assessor, "search_owner",
                        lambda base, name, **k: [{"parcel": "3123202004", "owner": name, "landuse": "83"},
                                                 {"parcel": "2922010050", "owner": name, "landuse": "83"}])
    out = tmp_path / "extracted" / "parcels.pkl"
    ok, msg = fetch.ensure_parcels("Okanogan", ["GEBBERS CATTLE LTD"], str(out))
    assert ok, msg
    meta = pickle.load(open(out, "rb"))
    assert len(meta["attrs"]) == 2
    a = meta["attrs"][0]
    assert set(a) >= {"PIN", "owner", "map"} and a["map"] == "31-23-20"


def test_ensure_parcels_unsupported_county_is_graceful(tmp_path):
    ok, msg = fetch.ensure_parcels("Nowhere", ["X"], str(tmp_path / "p.pkl"))
    assert not ok and "no automatic parcel source" in msg
