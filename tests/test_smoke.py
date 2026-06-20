"""Gate 1 — logic tests that run BEFORE anything is frozen."""
import os, sys, json, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "core", "scripts"))


def test_app_imports_and_health_route():
    import app
    rules = {r.rule for r in app.app.url_map.iter_rules()}
    assert "/health" in rules                       # the boot self-test depends on this
    assert "/api/accounts" in rules and "/api/run" in rules


def test_pipeline_and_worker_import():
    from core import pipeline
    import run_cli, launcher                          # frozen entry must import cleanly
    assert hasattr(pipeline, "run_review") and hasattr(pipeline, "list_accounts")
    assert hasattr(run_cli, "run")


def test_specificity_levels_known():
    import set_specificity
    assert set_specificity.LEVELS == ["parcel", "section", "instrument"]


def test_specificity_parcel_downgrades_section(tmp_path):
    # parcel level must demote a section-precise MATCH to LIKELY (the dial actually changes verdicts)
    import set_specificity
    vp = tmp_path / "v.json"
    vp.write_text(json.dumps({"verdicts": [
        {"key": "31-24-5", "status": "MATCHED", "precision": "parcel", "basis": ""},
        {"key": "31-24-6", "status": "MATCHED", "precision": "section", "basis": ""},
    ]}))
    set_specificity.apply_level(str(vp), str(tmp_path / "missing_evidence.json"), "parcel")
    out = {v["key"]: v["status"] for v in json.loads(vp.read_text())["verdicts"]}
    assert out["31-24-5"] == "MATCHED" and out["31-24-6"] == "LIKELY"


def test_doc_index_tokenizer_glues_initialisms():
    import doc_index
    assert doc_index._terms("C & M") == doc_index._terms("c&m 1 signed lease cert")  # both -> ['CM']


def test_list_accounts_handles_empty(tmp_path):
    from core import pipeline
    assert pipeline.list_accounts([str(tmp_path)]) == []
