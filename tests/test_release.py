import re

import pytest

from open_finance_mcp import release
from conftest import load


def test_earnings_8ks_are_item_2_02_newest_first():
    hits = release.earnings_8ks(load("submissions_AAPL.json"))
    assert hits and all("2.02" in h["items"].split(",") for h in hits)
    assert [h["filingDate"] for h in hits] == sorted((h["filingDate"] for h in hits), reverse=True)


def test_item_codes_are_matched_exactly():
    sub = {"filings": {"recent": {
        "form": ["8-K", "8-K", "10-Q"], "filingDate": ["2026-07-01", "2026-07-02", "2026-07-03"],
        "reportDate": ["", "", ""], "accessionNumber": ["a", "b", "c"],
        "items": ["2.020,9.01", "5.02,2.02", "2.02"], "primaryDocument": ["", "", ""]}}}
    assert [h["accessionNumber"] for h in release.earnings_8ks(sub)] == ["b"]


def test_index_page_lists_typed_documents():
    docs = release.filing_documents(load("release_AAPL_index.htm"))
    types = [d["type"] for d in docs]
    assert "8-K" in types and "EX-99.1" in types
    ex = release.release_exhibits(docs)
    assert ex[0]["type"] == "EX-99.1"
    assert ex[0]["url"].startswith("https://www.sec.gov/Archives/edgar/data/320193/")


def test_exhibits_sort_numerically():
    docs = [{"type": t, "description": None, "url": t} for t in ("EX-99.10", "GRAPHIC", "EX-99.2", "EX-99.1")]
    assert [d["type"] for d in release.release_exhibits(docs)] == ["EX-99.1", "EX-99.2", "EX-99.10"]


def test_apple_release_text_keeps_prose_and_tables():
    text = release.html_to_text(load("release_AAPL_ex991.htm"))
    assert text.startswith("Exhibit 99.1")  # EDGAR envelope lines stripped
    assert "Apple reports" in text
    assert "<" not in text and "&nbsp;" not in text
    # Statement rows come through as "label | value | value" with $ joined to the number.
    rows = [ln for ln in text.splitlines() if ln.startswith("Total net sales")]
    assert any(re.fullmatch(r"Total net sales( \| \$[\d,]+){4}", r) for r in rows)
    assert not any("$ |" in r for r in rows)


@pytest.mark.parametrize("cells, expected", [
    (["Net sales", "$", "94,036", "", "$", "85,777"], "Net sales | $94,036 | $85,777"),
    (["Change", "(", "2.5", ")", "%"], "Change | (2.5)%"),
    (["Margin", "34.9", "%", "34.1", "%"], "Margin | 34.9% | 34.1%"),
    (["Corporate", "37", "(", "256", ")"], "Corporate | 37 | (256)"),
    ([" ", ""], ""),
])
def test_split_alignment_cells_are_rejoined(cells, expected):
    assert release.join_row(cells) == expected


def test_paging_cuts_on_line_boundaries_and_covers_everything():
    text = "\n".join(f"line {i:03d}" for i in range(200))
    out, offset = [], 0
    while offset is not None:
        chunk, offset = release.page(text, offset, 100)
        assert len(chunk) <= 100
        out.append(chunk)
    assert "".join(out) == text
    assert len(out) > 1 and all(c.lstrip("\n").startswith("line") for c in out)
