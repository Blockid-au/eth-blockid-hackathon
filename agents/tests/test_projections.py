"""Projection uploads (tools/projections.py): template round trip, validation checks and caps, and the parser's
security guards — size, type sniffing, macros, zip bombs, XML entities, formulas without cached values, CSV formula
injection. Pure (no DB); the API is covered in test_valuation_v5_api.py."""
import io
import zipfile

import openpyxl
import pytest

from blockid_agents.schemas import ProjectionInput
from blockid_agents.tools import projections as pj
from blockid_agents.tools.market_data import snapshot
from blockid_agents.tools.valuation_params import params

P = params()
SOFTWARE = snapshot("2026-09-26").industry("software")
GOOD = {"revenue": [800e3, 1.0e6, 1.4e6, 1.9e6, 2.5e6, 3.2e6, 4.0e6],
        "cogs": [240e3, 300e3, 420e3, 570e3, 750e3, 960e3, 1.2e6],
        "opex": [500e3, 600e3, 750e3, 950e3, 1.15e6, 1.4e6, 1.7e6],
        "d_and_a": [20e3] * 7, "capex": [30e3] * 7}


def filled_xlsx(data=GOOD, company=None, formula_cell=False) -> bytes:
    wb = openpyxl.load_workbook(io.BytesIO(pj.template_xlsx()))
    ws = wb["Projections"]
    for row in ws.iter_rows(min_row=2):
        k = row[0].value
        if k in data:
            for j, v in enumerate(data[k]):
                row[2 + j].value = v
    if formula_cell:
        for row in ws.iter_rows(min_row=2):
            if row[0].value == "ebitda":
                row[2].value = "=C4-C5-C6"  # openpyxl saves no cached value
    wc = wb["Company"]
    for row in wc.iter_rows(min_row=2):
        if company and row[0].value in company:
            row[2].value = company[row[0].value]
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def filled_csv(data=GOOD, extra: str = "") -> bytes:
    lines = pj.template_csv().decode().splitlines()
    out = []
    for ln in lines:
        k = ln.split(",")[0]
        if k in data:
            ln = ",".join([k, "x", *[str(v) for v in data[k]]])
        out.append(ln)
    return ("\n".join(out) + extra).encode()


# ================================================================== template + happy path
def test_template_xlsx_and_csv_have_every_row_and_guide():
    wb = openpyxl.load_workbook(io.BytesIO(pj.template_xlsx("vi")))
    assert wb.sheetnames == ["Projections", "Company", "Guide"]
    keys = [r[0].value for r in wb["Projections"].iter_rows(min_row=2)]
    assert keys == list(pj.YEAR_ROWS)
    assert "BlockID" in wb["Guide"]["A1"].value
    csv_keys = [ln.split(",")[0] for ln in pj.template_csv().decode().splitlines()]
    assert set(pj.YEAR_ROWS) <= set(csv_keys) and "company.currency" in csv_keys
    inp, errs, kind = pj.parse_upload(pj.template_csv(), "t.csv", P)  # empty template: plain error, no crash
    assert inp is None and errs and "No year has figures" in errs[0].message


@pytest.mark.parametrize("fmt", ["xlsx", "csv"])
def test_good_file_parses_and_validates(fmt):
    data = filled_xlsx(company={"cash": 250000, "debt": 50000, "planned_raise": 500000, "audited": "Y"}) \
        if fmt == "xlsx" else filled_csv(extra="\ncompany.cash,Cash,250000")
    inp, errs, kind = pj.parse_upload(data, f"forecast.{fmt}", P)
    assert kind == fmt and errs == [] and len(inp.years) == 7
    assert [y.actual for y in inp.years] == [True, True, False, False, False, False, False]
    assert inp.cash == 250000
    checks, used = pj.validate(inp, cls="seed", industry_row=SOFTWARE, revenue_ref_aud=1.0e6, p=P)
    assert not [c for c in checks if c.severity == "error"]
    assert {c.code for c in checks} >= {"tax_default", "nwc_default"}
    assert len(used) == 7 and used[2]["revenue"] == 1.4e6
    rec = pj.parsed_record(inp, used)
    assert rec["basis"] == "management_projection" and rec["fx_rate_to_aud"] == 1.0 and rec["template_version"] == 1


# ================================================================== validation checks
def inp_with(**over) -> ProjectionInput:
    years = []
    for i, y in enumerate(range(2024, 2031)):
        row = {"year": y, "actual": i < 2, **{k: GOOD[k][i] for k in GOOD}}
        years.append(row)
    for k, fn in over.items():
        for row in years:
            fn(row) if k == "each" else None
    return ProjectionInput(years=years)


def test_growth_cap_applied_and_scaled_lines():
    inp = inp_with()
    inp.years[2].revenue = 5.0e6  # 400 % growth over 1.0M
    checks, used = pj.validate(inp, cls="seed", industry_row=SOFTWARE, revenue_ref_aud=None, p=P)
    cap = next(c for c in checks if c.code == "growth_cap")
    assert cap.severity == "warning" and cap.used_value == pytest.approx(3.0e6) and "200%" in cap.message
    y1 = next(y for y in used if y["year"] == 2026)
    assert y1["revenue"] == pytest.approx(3.0e6) and y1["cogs"] == pytest.approx(420e3 * 3.0e6 / 5.0e6)
    assert any(c.code == "jump_from_actual" for c in checks)
    sme, _ = pj.validate(inp_with(), cls="profitable_sme", industry_row=SOFTWARE, revenue_ref_aud=None, p=P)
    assert any(c.code == "growth_cap" for c in sme)  # 40 % growth > 25 % SME cap


def test_structure_identity_currency_errors():
    inp = inp_with()
    inp.years[3].ebitda = 999.0
    checks, used = pj.validate(inp, cls="seed", industry_row=SOFTWARE, revenue_ref_aud=None, p=P)
    assert any(c.code == "identity" and c.severity == "error" and c.year == 2027 for c in checks) and used == []
    two = ProjectionInput(years=[y.model_dump() for y in inp_with().years[:4]])  # 2 projected years
    assert any(c.code == "structure" for c in pj.validate(two, cls="seed", industry_row=SOFTWARE,
                                                          revenue_ref_aud=None, p=P)[0])
    gap = inp_with()
    gap.years[4].year = 2035
    assert any("consecutive" in c.message for c in pj.validate(gap, cls="seed", industry_row=SOFTWARE,
                                                               revenue_ref_aud=None, p=P)[0])
    cur = inp_with()
    cur.currency = "XYZ"
    assert any(c.code == "currency" for c in pj.validate(cur, cls="seed", industry_row=SOFTWARE,
                                                         revenue_ref_aud=None, p=P)[0])


def test_margin_cap_hockey_stick_capex_fte_and_actuals_mismatch():
    inp = inp_with()
    for y in inp.years[2:]:
        y.opex = 10_000.0  # ~90 % EBITDA margin, far above software p90 40 % + 10 pp
    inp.years[-1].headcount = 1
    for y in inp.years:
        y.capex = 1.0
    checks, used = pj.validate(inp, cls="series_a", industry_row=SOFTWARE, revenue_ref_aud=3.0e6, p=P)
    codes = {c.code for c in checks}
    assert {"margin_cap", "capex_vs_da", "revenue_per_fte", "actuals_mismatch"} <= codes
    last = used[-1]
    assert (last["revenue"] - last["cogs"] - last["opex"]) / last["revenue"] == pytest.approx(0.5)
    hs = inp_with()
    for y in hs.years[2:6]:
        y.opex = y.revenue - y.cogs  # break-even until the final year
    hs.years[-1].revenue = 6.4e6
    hs.years[-1].cogs = 1.0e6
    checks, _ = pj.validate(hs, cls="growth", industry_row=snapshot("2026-09-26").industry("general"),
                            revenue_ref_aud=None, p=P)
    assert any(c.code == "hockey_stick" for c in checks)


def test_bad_numbers_and_markers_are_plain_errors():
    bad = dict(GOOD, revenue=["1.2m", *GOOD["revenue"][1:]])
    inp, errs, _ = pj.parse_upload(filled_csv(bad), "f.csv", P)
    assert inp is None and any("not a plain number" in e.message for e in errs)
    assert pj.to_number("(1,250)") == -1250 and pj.to_number(" 3 400 ") == 3400 and pj.to_number("") is None
    for s in ("=1+1", "1e999", "nan", "inf", True):
        with pytest.raises(ValueError):
            pj.to_number(s)
    csv_no_rows = b"key,label,FY1\nfoo,bar,1\n"
    inp, errs, _ = pj.parse_upload(csv_no_rows, "f.csv", P)
    assert inp is None and {e.row for e in errs} >= {"year", "revenue", "capex"}


# ================================================================== security guards
def test_size_limit_before_parsing():
    with pytest.raises(pj.ProjectionError, match="larger than 512 KB"):
        pj.parse_upload(b"a" * (512 * 1024 + 1), "big.csv", P)
    pj.sniff(b"a" * (512 * 1024), "ok.csv", P)  # exactly the limit is fine


@pytest.mark.parametrize("name", ["model.xlsm", "old.xls", "b.xlsb", "sheet.ods"])
def test_macro_and_old_formats_rejected_by_name(name):
    with pytest.raises(pj.ProjectionError, match="only .xlsx or .csv"):
        pj.parse_upload(filled_xlsx(), name, P)


def test_xls_magic_and_binary_rejected():
    with pytest.raises(pj.ProjectionError, match="old Excel"):
        pj.parse_upload(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 100, "x", P)
    with pytest.raises(pj.ProjectionError, match="not a text CSV"):
        pj.parse_upload(b"key,label\x00\x01", "x.csv", P)
    with pytest.raises(pj.ProjectionError):
        pj.parse_upload(b"%PDF-1.7 ...", "x.pdf", P)


def _zip(files: dict[str, bytes], method=zipfile.ZIP_DEFLATED) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", method) as z:
        for n, b in files.items():
            z.writestr(n, b)
    return out.getvalue()


def test_zip_bomb_rejected_before_openpyxl():
    bomb = _zip({"[Content_Types].xml": b"<Types/>", "xl/workbook.xml": b"<w/>",
                 "xl/worksheets/sheet1.xml": b"\0" * (21 * 1024 * 1024)})
    assert len(bomb) < 512 * 1024  # small on disk, 21 MB inflated
    with pytest.raises(pj.ProjectionError, match="more than 20 MB"):
        pj.parse_upload(bomb, "bomb.xlsx", P)
    many = _zip({"[Content_Types].xml": b"<Types/>", "xl/workbook.xml": b"<w/>",
                 **{f"xl/x{i}.xml": b"x" for i in range(250)}})
    with pytest.raises(pj.ProjectionError, match="too many parts"):
        pj.parse_upload(many, "many.xlsx", P)


def test_macro_content_rejected_even_when_named_xlsx():
    x = filled_xlsx()
    zin = zipfile.ZipFile(io.BytesIO(x))
    files = {i.filename: zin.read(i.filename) for i in zin.infolist()}
    files["xl/vbaProject.bin"] = b"macro"
    with pytest.raises(pj.ProjectionError, match="macros"):
        pj.parse_upload(_zip(files), "innocent.xlsx", P)
    files.pop("xl/vbaProject.bin")
    files["[Content_Types].xml"] = files["[Content_Types].xml"].replace(
        b"spreadsheetml.sheet.main+xml", b"sheet.macroEnabled.main+xml")
    with pytest.raises(pj.ProjectionError, match="macros"):
        pj.parse_upload(_zip(files), "innocent.xlsx", P)


def test_xml_entity_attack_refused():
    from openpyxl.xml import DEFUSEDXML

    assert DEFUSEDXML is True  # openpyxl picked up defusedxml
    x = filled_xlsx()
    zin = zipfile.ZipFile(io.BytesIO(x))
    files = {i.filename: zin.read(i.filename) for i in zin.infolist()}
    body = files["xl/workbook.xml"]
    body = body.split(b"?>", 1)[1] if body.startswith(b"<?xml") else body
    evil = b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;">]>' + body
    files["xl/workbook.xml"] = evil
    with pytest.raises(pj.ProjectionError):
        pj.parse_upload(_zip(files), "evil.xlsx", P)


def test_formula_without_cached_value_is_an_error():
    with pytest.raises(pj.ProjectionError, match="formula with no saved result"):
        pj.parse_upload(filled_xlsx(formula_cell=True), "f.xlsx", P)


def test_damaged_xlsx_and_limits_on_rows_and_text():
    with pytest.raises(pj.ProjectionError, match="damaged|not a real"):
        pj.parse_upload(b"PK\x03\x04garbage", "d.xlsx", P)
    notes = "see =HYPERLINK(\"http://evil\")" + "n" * 900
    inp, errs, _ = pj.parse_upload(filled_xlsx(company={"basis_notes": notes}), "a.xlsx", P)
    assert not errs and len(inp.basis_notes) == 500  # length-capped, stored as text, never evaluated
    inp, errs, _ = pj.parse_upload(filled_csv(extra="\ncompany.prepared_by,x,CFO\x07\x1b[31m"), "c.csv", P)
    assert not errs and inp.prepared_by == "CFO[31m"  # control characters stripped
    rows = "\n".join(f"junk{i},x,1" for i in range(5000))
    inp, errs, _ = pj.parse_upload(filled_csv(extra="\n" + rows), "long.csv", P)  # read stops at 200 rows
    assert inp is not None


def test_csv_export_escapes_formula_injection():
    parsed = {"years": [{"year": 2026, "actual": True, "revenue": 1.0}], "prepared_by": "=cmd|' /C calc'!A0",
              "basis_notes": "+SUM(1)", "currency": "@AUD"}
    out = pj.export_csv(parsed).decode()
    assert "'=cmd" in out and "'+SUM" in out and "'@AUD" in out
    assert pj.escape_csv_cell("-5") == "'-5" and pj.escape_csv_cell("ok") == "ok"
