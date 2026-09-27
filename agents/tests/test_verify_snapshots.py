"""Snapshot: v1-v4 reports (tests/fixtures/verify_snapshots.json, generated from the pre-v5 code on 27 Sep 2026 and
checked byte-identical against git HEAD) keep their anchored report hash and still recompute in /verify — with the
VALUATION_V5 flag off and on, and after a round-trip through the (extended) SVIResult schema."""
import json
from pathlib import Path

import pytest

from blockid_agents.schemas import SVIResult
from blockid_agents.studio import verify
from blockid_agents.studio.report_hash import canonical_json, report_hash
from blockid_agents.tools import svi

SNAPS = json.loads((Path(__file__).parent / "fixtures" / "verify_snapshots.json").read_text())


def test_fixture_covers_every_formula_version():
    assert {s["formula_version"] for s in SNAPS} >= {"v1", "v2", "v3", "v4"}


@pytest.mark.parametrize("flag", ["0", "1"])
@pytest.mark.parametrize("snap", SNAPS, ids=[s["name"] for s in SNAPS])
def test_old_reports_keep_hash_and_recompute(snap, flag, monkeypatch):
    monkeypatch.setenv("VALUATION_V5", flag)
    rep = snap["report"]
    assert report_hash(rep) == snap["report_hash"]
    rc = verify.recompute(json.loads(canonical_json(rep)))
    assert all(rc["matches_report"].values()), rc["matches_report"]
    assert rc["formula_version"] == snap["formula_version"]
    assert rc["weights_version"] == snap["weights_version"]
    s = rep["svi"]
    assert "analysis" not in s and "weights_profile" not in s


@pytest.mark.parametrize("snap", [s for s in SNAPS if s["formula_version"] in ("v3", "v4")],
                         ids=lambda s: s["name"])
def test_svi_schema_round_trip_is_byte_identical(snap):
    s = snap["report"]["svi"]
    again = SVIResult.model_validate(s).model_dump()
    assert canonical_json(again) == canonical_json(s)
    assert svi.report_hash(SVIResult.model_validate(s)) == s["report_sha256"]
