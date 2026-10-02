"""Earnings releases: find the Item 2.02 8-K and turn its exhibit into text.

Companies furnish the earnings press release on results day as an exhibit
(usually EX-99.1) to an 8-K tagged Item 2.02, "Results of Operations and
Financial Condition". That is weeks before SEC's XBRL company-facts API
reflects the quarter, so it is the freshest primary source available.

Pure functions, so they can be tested on saved filings.
"""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser

EARNINGS_ITEM = "2.02"

_BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "tr", "section"}
_SKIP = {"style", "script", "head", "title"}


def earnings_8ks(submissions: dict) -> list[dict]:
    """8-K / 8-K/A filings tagged Item 2.02, newest first."""
    r = submissions.get("filings", {}).get("recent", {})
    keys = ("form", "filingDate", "reportDate", "accessionNumber", "items", "primaryDocument")
    rows = [dict(zip(keys, vals)) for vals in zip(*(r.get(k, []) for k in keys))]
    hits = [f for f in rows
            if f["form"] in ("8-K", "8-K/A") and EARNINGS_ITEM in str(f.get("items", "")).split(",")]
    return sorted(hits, key=lambda f: (f["filingDate"], f["accessionNumber"]), reverse=True)


class _IndexParser(HTMLParser):
    """Rows of the "Document Format Files" table on a filing's -index.htm page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[dict] = []
        self._cells: list[str] | None = None
        self._href: str | None = None
        self._text: list[str] = []
        self._in_td = False

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._cells, self._href = [], None
        elif tag == "td" and self._cells is not None:
            self._in_td, self._text = True, []
        elif tag == "a" and self._in_td:
            href = dict(attrs).get("href") or ""
            if "/Archives/edgar/data/" in href and self._href is None:
                self._href = href

    def handle_endtag(self, tag):
        if tag == "td" and self._in_td and self._cells is not None:
            self._cells.append(" ".join("".join(self._text).split()))
            self._in_td = False
        elif tag == "tr" and self._cells is not None:
            # Seq | Description | Document | Type | Size
            if len(self._cells) >= 4 and self._href:
                href = self._href
                if href.startswith("/ix?doc="):
                    href = href[len("/ix?doc="):]
                self.rows.append({
                    "type": self._cells[3],
                    "description": self._cells[1] or None,
                    "url": "https://www.sec.gov" + href if href.startswith("/") else href,
                })
            self._cells = None

    def handle_data(self, data):
        if self._in_td:
            self._text.append(data)


def filing_documents(index_html: str) -> list[dict]:
    p = _IndexParser()
    p.feed(index_html)
    return p.rows


def release_exhibits(docs: list[dict]) -> list[dict]:
    """EX-99.x documents (99.1 first). Graphics and XBRL are excluded."""
    ex = [d for d in docs if re.fullmatch(r"EX-99(\.\d+)?", d["type"].upper())]
    return sorted(ex, key=lambda d: [int(x) for x in re.findall(r"\d+", d["type"])] or [0])


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._skip = 0
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self._skip += 1
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag in _BLOCK and self._row is None:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            line = join_row(self._row)
            if line:
                self.out.append("\n" + line + "\n")
            self._row = None
        elif tag in _BLOCK and self._row is None:
            self.out.append("\n")

    def handle_data(self, data):
        if self._skip:
            return
        if self._cell is not None:
            self._cell.append(data)
        elif self._row is None:
            self.out.append(data)


def join_row(cells: list[str]) -> str:
    """One table row as "label | 13,396 | 12,535", reassembling split cells.

    Filing tables put "$", "(" and ")" / "%" in their own cells for column
    alignment; left alone, "$ | 13,396" and "( | 2.5 | ) %" read as separate
    columns.
    """
    cells = [c for c in (c.strip() for c in cells) if c]
    merged: list[str] = []
    carry = ""
    for c in cells:
        if c in ("$", "(", "$(", "($"):
            carry += c
            continue
        c = carry + c
        carry = ""
        if merged and re.fullmatch(r"\)?\s*%?|\)%|pts?|bps", c):
            merged[-1] += c
        else:
            merged.append(c)
    if carry:
        merged.append(carry)
    return " | ".join(merged)


# EDGAR's document envelope (<TYPE>, <SEQUENCE>, <FILENAME>, <DESCRIPTION>)
# survives in the archived exhibit as bare lines: "EX-99.1", "2", "file.htm".
_ENVELOPE = re.compile(r"(EX-\d+(\.\d+)?|\d{1,3}|[\w.-]+\.(htm|html|txt))", re.I)


def html_to_text(html: str) -> str:
    p = _TextParser()
    p.feed(html)
    text = unescape("".join(p.out)).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    lines = re.sub(r"\n{3,}", "\n\n", text).strip().split("\n")
    while lines and (not lines[0].strip() or _ENVELOPE.fullmatch(lines[0].strip())):
        lines.pop(0)
    return "\n".join(lines)


def page(text: str, offset: int, max_chars: int) -> tuple[str, int | None]:
    """Slice ``text`` at a line boundary; returns (chunk, next_offset or None)."""
    if offset >= len(text):
        return "", None
    end = offset + max_chars
    if end >= len(text):
        return text[offset:], None
    cut = text.rfind("\n", offset, end)
    if cut <= offset:
        cut = end
    return text[offset:cut], cut
