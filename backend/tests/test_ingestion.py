"""
Ingestion Regression Tests — bank statement parsing accuracy
=============================================================
Guards the row accounting fixed in S1.3:

  - Before: bank_icici.pdf held 208 data rows and yielded 175 events (15.9% lost),
    while the pipeline reported `skipped_rows: 0`. The losses came from two places —
    the parser skipped the first row of every page as a "repeated header" when no
    header was repeated, and the generator drew the Date column too narrow for its
    own timestamps, so text extraction returned clipped dates like '0/06/25 21:53:4'.
  - After: every data row is either parsed or counted as skipped, with a reason.

The invariant these tests defend is: parsed + skipped == total. A forensic tool may
fail to read a row; it may not fail to *report* that it failed to read a row.
"""
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from ingestion.bank_parser import _looks_like_repeated_header, parse_bank_pdf
from ingestion.smart_ingest import parse_messy_file

ICICI_PDF = BACKEND_DIR / "data" / "raw" / "bank_icici.pdf"

HEADER = ["S.No", "Account No", "Date", "Description", "Amount", "Type (DR/CR)", "Bal."]


# ============================================================
# Repeated-header detection (content-based, not positional)
# ============================================================
def test_repeated_header_is_detected():
    """The header redrawn at the top of a later page must be recognised as a header."""
    assert _looks_like_repeated_header(list(HEADER), HEADER) is True


def test_transaction_row_is_not_mistaken_for_a_header():
    """A real transaction sitting first on a page must NOT be dropped.

    This is the exact row the old parser deleted once per page — it skipped by
    position (`row_idx == 0`) instead of by content.
    """
    txn_row = ["42", "8644925192", "01/06/25 21:53:47",
               "UPI/500000/advay.contractor@okicici", "500000.00", "CR", "512345.67"]
    assert _looks_like_repeated_header(txn_row, HEADER) is False


def test_header_detection_handles_shape_mismatch():
    """A row with a different column count is not a header (and must not crash)."""
    assert _looks_like_repeated_header(["S.No", "Date"], HEADER) is False
    assert _looks_like_repeated_header(list(HEADER), None) is False


# ============================================================
# Row accounting on the shipped statement
# ============================================================
@pytest.mark.skipif(not ICICI_PDF.exists(), reason="demo dataset not generated")
def test_bank_pdf_row_accounting_is_complete():
    """Every data row in the PDF is either parsed into an event or counted as skipped."""
    stats = {}
    events = parse_bank_pdf(ICICI_PDF, stats=stats)

    total = stats["total_rows"]
    skipped = stats["skipped_rows"]

    assert len(events) == stats["parsed_rows"]
    assert stats["parsed_rows"] + skipped == total, (
        f"row accounting does not balance: {stats['parsed_rows']} parsed "
        f"+ {skipped} skipped != {total} total"
    )


@pytest.mark.skipif(not ICICI_PDF.exists(), reason="demo dataset not generated")
def test_bank_pdf_recovers_essentially_every_row():
    """>=205 of the statement's 208 rows must parse.

    The regression this guards produced 175. The only row expected to fail is the
    blank-amount anomaly the generator injects deliberately.
    """
    stats = {}
    events = parse_bank_pdf(ICICI_PDF, stats=stats)

    assert stats["total_rows"] >= 205
    assert len(events) >= 205, (
        f"only {len(events)} of {stats['total_rows']} rows parsed — "
        f"skip reasons: {stats.get('skip_reasons')}"
    )
    loss_pct = stats["skipped_rows"] / stats["total_rows"] * 100
    assert loss_pct < 2.0, f"{loss_pct:.1f}% of rows lost"


@pytest.mark.skipif(not ICICI_PDF.exists(), reason="demo dataset not generated")
def test_skipped_rows_are_reported_with_a_reason():
    """smart_ingest must surface the parser's real skip count, not a hardcoded 0."""
    events, summary = parse_messy_file(ICICI_PDF)

    assert summary["detected_type"] == "bank"
    assert summary["parsed_rows"] == len(events)
    assert summary["parsed_rows"] + summary["skipped_rows"] == summary["total_rows"]
    # Whatever was skipped must be attributed to a named cause.
    if summary["skipped_rows"]:
        assert summary["skip_reasons"], "rows were skipped but no reason was recorded"
        assert sum(summary["skip_reasons"].values()) == summary["skipped_rows"]


@pytest.mark.skipif(not ICICI_PDF.exists(), reason="demo dataset not generated")
def test_pdf_timestamps_survive_extraction_intact():
    """Dates must come out whole.

    The narrow Date column clipped the leading and trailing character off every
    timestamp, so '01/06/25 21:53:47' extracted as '0/06/25 21:53:4' and failed
    every date format. Parsed events are the proof the text survived.
    """
    events = parse_bank_pdf(ICICI_PDF)
    assert events, "no events parsed from the statement"

    years = {e["timestamp"].year for e in events}
    assert years == {2025}, f"unexpected years parsed from statement: {years}"

    # Seconds resolution is present, i.e. the full "%d/%m/%y %H:%M:%S" was read.
    assert any(e["timestamp"].second for e in events), (
        "no event carries a non-zero seconds value — timestamps were likely truncated"
    )
