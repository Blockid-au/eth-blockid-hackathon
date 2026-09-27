"""tools/csv_metrics.py + tools/metrics_calc.py: template CSV -> hand-computed metrics; header aliases; forensics."""
import pytest

from blockid_agents.tools import csv_metrics as cm
from blockid_agents.tools import metrics_calc as mc

HEADER = ("month,revenue_aud,mrr_aud,new_mrr,expansion_mrr,contraction_mrr,churned_mrr,customers,new_customers,"
          "churned_customers,active_users,cash_aud,burn_aud")


def template_csv() -> str:
    rows = [HEADER]
    for i in range(14):  # 2024-09 .. 2025-10
        y, m = (2024, 9 + i) if 9 + i <= 12 else (2025, 9 + i - 12)
        mrr = 9000 if i == 0 else 10000 + 1000 * (i - 1)
        cash = 900_000 - 50_000 * i
        rows.append(f"{y}-{m:02d},{mrr},{mrr},1500,100,50,100,{50 + 2 * i},3,1,{1000 + 50 * i},{cash},50000")
    return "\n".join(rows)


def test_template_csv_hand_computed():
    p = cm.parse(template_csv(), today="2026-09")
    assert p["rows"] == 14 and not p["errors"] and p["months"][-1] == "2025-10"
    m = p["metrics"]
    assert m["mrr_aud"] == 22000 and m["arr_aud"] == 264000
    assert m["yoy_growth_pct"] == pytest.approx(120.0)  # 22000 vs 10000 twelve months earlier
    assert m["nrr_pct"] == pytest.approx(94.0)  # (10000 + 1200 - 600 - 1200) / 10000
    assert m["grr_pct"] == pytest.approx(82.0)  # (10000 - 600 - 1200) / 10000
    assert m["cmgr_pct"] == pytest.approx(((22000 / 16000) ** (1 / 6) - 1) * 100, abs=0.01)
    assert m["burn_multiple"] == pytest.approx(600_000 / 144_000, abs=0.01)
    assert m["runway_months"] == pytest.approx(250_000 / 50_000)
    assert m["paying_customers"] == 76 and m["paying_customers_12m_ago"] == 52
    exp_churn = sum(1 / (50 + 2 * (i - 1)) * 100 for i in range(3, 14)) / 11
    assert m["logo_churn_monthly_pct"] == pytest.approx(exp_churn, abs=0.01)
    assert m["revenue_ttm_aud"] == sum(10000 + 1000 * (i - 1) for i in range(2, 14))
    assert not [f for f in p["flags"] if f["severity"] in ("warning", "high")]


def test_header_aliases_and_formats():
    csv = "Date,MRR ($),Expansion,Churn,Subscribers\nOct 2025,\"$1,000\",0,0,10\n2025-11-01,1100,50,10,11\n"
    p = cm.parse(csv, today="2026-09")
    assert p["mapped_headers"] == {"Date": "month", "MRR ($)": "mrr_aud", "Expansion": "expansion_mrr",
                                   "Churn": "churned_mrr", "Subscribers": "customers"}
    assert p["months"] == ["2025-10", "2025-11"] and p["metrics"]["arr_aud"] == 13200


def test_forensics_flags_smooth_duplicates_future_negative():
    rows = [HEADER] + [f"2025-{m:02d},0,{round(10000 * 1.1 ** m)},0,0,0,0,10,0,0,0,0,0" for m in range(1, 10)]
    rows.append("2025-09,0,999,0,0,0,0,10,0,0,0,0,0")  # duplicated month
    rows.append("2030-01,0,5,0,0,0,0,-3,0,0,0,0,0")  # future + negative
    p = cm.parse("\n".join(rows), today="2026-09")
    codes = {f["code"] for f in p["flags"]}
    assert {"csv_duplicate_rows", "csv_future_months", "csv_smooth_series"} <= codes
    assert "2030-01" not in p["months"]


@pytest.mark.parametrize("bad,msg", [("month,mrr\n", "header row"), ("foo,bar\n1,2\n", "no month column")])
def test_unusable_files(bad, msg):
    with pytest.raises(ValueError, match=msg):
        cm.parse(bad)


def test_row_errors_are_reported_inline():
    p = cm.parse("month,revenue_aud\n2025-01,abc\nnotamonth,5\n2025-02,7\n", today="2026-09")
    assert "row 2: revenue_aud is not a number" in p["errors"] and any("row 3" in e for e in p["errors"])


def test_metrics_calc_edges():
    assert mc.growth_pct(150, 100) == 50 and mc.growth_pct(1, 0) is None
    assert mc.cmgr_pct(121, 100, 2) == pytest.approx(10.0)
    assert mc.burn_multiple(1_000_000, 0) is None and mc.burn_multiple(2e6, 1e6) == 2
    assert mc.runway_months(100, 0) == 60.0 and mc.runway_months(120, 10) == 12
    assert mc.cac_payback_months(1200, 100, 50) == 24
    assert mc.ltv_cac(100, 80, 2, 1000) == 4.0
    assert mc.within(100, 104, 0.05) and mc.within(100, 130, 0.2) is False and mc.within(None, 1, 0.1) is None
    assert cm.benford_p([float(x) for x in range(1, 40)]) is None
