"""The 14 companies live on eth.blockid.au (snapshot of the public GET /api/v1/verify/{ticker}, 27 Sep 2026): every
stored report keeps the hash anchored on all three chains and still recomputes with the same formula version — with
VALUATION_V5 off and on (valuation v5 must never change how an existing report verifies)."""
import json
from pathlib import Path

import pytest

from blockid_agents.studio import verify
from blockid_agents.studio.report_hash import canonical_json, report_hash

SNAP = json.loads((Path(__file__).parent / "fixtures" / "onchain_reports_2026-09-27.json").read_text())
REPORTS = SNAP["reports"]


def test_snapshot_has_the_14_live_companies():
    assert len(REPORTS) == 14 and len({r["ticker"] for r in REPORTS}) == 14
    assert all(o["valuationReportHash"] == r["report_hash"] for r in REPORTS for o in r["onchain"])


@pytest.mark.parametrize("flag", ["0", "1"])
@pytest.mark.parametrize("snap", REPORTS, ids=[r["ticker"] for r in REPORTS])
def test_onchain_report_hash_and_recompute_unchanged(snap, flag, monkeypatch):
    monkeypatch.setenv("VALUATION_V5", flag)
    rep = snap["report"]
    assert report_hash(rep) == snap["report_hash"]  # == the hash anchored on BlockID / Hoodi / HashKey
    rc = verify.recompute(json.loads(canonical_json(rep)))
    assert rc["formula_version"] == snap["formula_version"]
    assert rc["matches_report"] == snap["matches"] and all(rc["matches_report"].values())
    assert "methods" not in rc  # per-method v5 output only for v5 reports
