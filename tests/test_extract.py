"""Tests for the offline document reader (core/extract)."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "core", "extract"))


def test_reader_status_is_offline():
    from core.extract import ingest
    s = ingest.reader_status()
    assert s["parsers"] is True and s["network"] == "none"


def test_ingest_empty_dir_writes_inputs(tmp_path):
    from core.extract import ingest
    out = tmp_path / "extracted"
    r = ingest.ingest([str(tmp_path / "nope")], str(out))
    assert r["pdfs"] == 0
    assert (out / "recorded_grazing_leases.json").exists()
    assert (out / "signed_lease_certs.json").exists()


def test_legals_from_dnr_builds_parseable_strings():
    from core.extract import ingest
    legs = ingest._legals_from_dnr({"townships": ["T30N R24E"], "sections": ["3", "4"]})
    assert "Section 3, Township 30 North, Range 24 East" in legs


def test_parsers_classify_standard_forms():
    import form_templates as T
    dt, res = T.parse("GRAZING LEASE\nLease No. 10-A78830\nLessee: Acme Cattle Ltd.\n"
                      "Section 4; all in Township 30 North, Range 24 East, containing 364.47 acres, more or less.")
    assert "dnr" in dt and res.get("sections")  # recognized a DNR grazing lease with a section
