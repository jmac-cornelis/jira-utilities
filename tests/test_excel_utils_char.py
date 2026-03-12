import csv
from typing import Any, cast

import openpyxl

import excel_utils


def test_convert_from_csv_creates_excel_structure(tmp_path):
    csv_path = tmp_path / "input.csv"
    csv_path.write_text(
        "key,status,priority,summary\n"
        "STL-1,Open,P1-Critical,First row\n"
        "STL-2,Closed,P0-Stopper,Second row\n",
        encoding="utf-8",
    )

    out_path = excel_utils.convert_from_csv(str(csv_path), str(tmp_path / "converted.xlsx"))

    wb = openpyxl.load_workbook(out_path)
    ws = wb[wb.sheetnames[0]]

    assert out_path.endswith("converted.xlsx")
    assert ws.cell(row=1, column=1).value == "key"
    assert ws.cell(row=2, column=1).value == "STL-1"
    assert ws.cell(row=3, column=4).value == "Second row"
    hyperlink = ws.cell(row=2, column=1).hyperlink
    assert hyperlink is not None
    target = hyperlink.target or ""
    assert target.endswith("/browse/STL-1")
    assert ws.freeze_panes == "A2"
    wb.close()


def test_create_dashboard_sheet_adds_countif_formulas():
    wb = openpyxl.Workbook()
    ws = cast(Any, wb.active)
    ws.title = "Tickets"

    headers = ["key", "status", "priority"]
    ws.append(headers)
    ws.append(["STL-1", "Open", "P1-Critical"])
    ws.append(["STL-2", "Open", "P0-Stopper"])
    ws.append(["STL-3", "Closed", "P1-Critical"])

    excel_utils._create_dashboard_sheet(wb, ws, headers, dashboard_columns=["status", "priority"])

    dash = wb["Dashboard"]

    assert dash.cell(row=1, column=1).value == "Dashboard"
    assert dash.cell(row=2, column=1).value == "status"
    assert dash.cell(row=3, column=2).value == "Count"

    formulas = [dash.cell(row=4, column=2).value, dash.cell(row=5, column=2).value]
    assert any(str(formula).startswith("=COUNTIF(") for formula in formulas)

    status_total_formula = dash.cell(row=6, column=2).value
    assert status_total_formula == "=SUM(B4:B5)"


def test_validate_and_repair_csv_repairs_unquoted_comma(tmp_path):
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text(
        "key,summary,status\n"
        "STL-1,Hello, world,Open\n"
        "STL-2,Good row,Closed\n",
        encoding="utf-8",
    )

    repaired, stats = excel_utils._validate_and_repair_csv(str(csv_path))

    assert repaired is True
    assert stats["repaired_rows"] == 1

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))

    assert rows[1] == ["STL-1", "Hello, world", "Open"]
    assert len(rows[1]) == 3


def test_concat_merge_sheet_merges_rows_and_union_columns(temp_excel_file, tmp_path):
    file_a = temp_excel_file(
        "a.xlsx",
        ["key", "status"],
        [["STL-1", "Open"]],
    )
    file_b = temp_excel_file(
        "b.xlsx",
        ["key", "priority"],
        [["STL-2", "P1-Critical"]],
    )

    output_file = tmp_path / "merged.xlsx"
    excel_utils.concat_merge_sheet([str(file_a), str(file_b)], str(output_file))

    wb = openpyxl.load_workbook(output_file)
    ws = wb["Merged"]

    headers = [ws.cell(row=1, column=idx).value for idx in range(1, 4)]
    assert headers == ["key", "status", "priority"]
    assert ws.cell(row=2, column=1).value == "STL-1"
    assert ws.cell(row=3, column=1).value == "STL-2"
    assert ws.cell(row=2, column=3).value in (None, "")
    assert ws.cell(row=3, column=2).value in (None, "")
    wb.close()


def test_concat_add_sheet_creates_one_sheet_per_input(temp_excel_file, tmp_path):
    file_a = temp_excel_file("alpha.xlsx", ["key", "status"], [["STL-1", "Open"]])
    file_b = temp_excel_file("beta.xlsx", ["key", "status"], [["STL-2", "Closed"]])

    output_file = tmp_path / "added.xlsx"
    excel_utils.concat_add_sheet([str(file_a), str(file_b)], str(output_file))

    wb = openpyxl.load_workbook(output_file)

    assert "alpha" in wb.sheetnames
    assert "beta" in wb.sheetnames
    assert wb["alpha"].cell(row=2, column=1).value == "STL-1"
    assert wb["beta"].cell(row=2, column=1).value == "STL-2"

    wb.close()
