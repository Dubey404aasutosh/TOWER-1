"""
Bank Statement Parser — handles 3 different bank layouts (XLSX/CSV/PDF)
and normalizes them into the canonical Event schema.

Supported formats:
  - SBI-style XLSX: Txn Date, Value Date, Description, Debit, Credit, Balance (DD-MM-YYYY)
  - HDFC-style CSV: date, particulars, withdrawal_amt, deposit_amt, closing_balance (YYYY/MM/DD)
  - ICICI-style PDF: S.No, Date, Description, Amount, Type (DR/CR), Balance (DD/MM/YY)
"""
import re
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import pdfplumber


# --- Column name mapping for auto-detection ---
COLUMN_MAPS = {
    "date": ["txn date", "date", "transaction date", "trans date", "txn_date"],
    "narration": ["description", "particulars", "narration", "details", "transaction details"],
    "debit": ["debit", "withdrawal_amt", "withdrawal", "dr_amount", "debit_amount"],
    "credit": ["credit", "deposit_amt", "deposit", "cr_amount", "credit_amount"],
    "balance": ["balance", "closing_balance", "running_balance", "bal.", "available balance"],
    "type": ["type", "type (dr/cr)", "dr/cr", "txn_type"],
    "amount": ["amount", "txn_amount", "transaction_amount"],
    "value_date": ["value date", "value_date", "val date"],
    "account_no": ["account_no", "account no", "account number", "acct_no", "acct no"],
}


def _find_column(df_columns, target_key):
    """Auto-detect column by fuzzy name matching."""
    candidates = COLUMN_MAPS.get(target_key, [])
    lower_cols = {c.lower().strip(): c for c in df_columns}
    for candidate in candidates:
        if candidate in lower_cols:
            return lower_cols[candidate]
    return None


def _parse_date(date_str):
    """Try multiple date formats and return datetime."""
    if isinstance(date_str, datetime):
        return date_str
    if pd.isna(date_str) or not date_str:
        return None
    date_str = str(date_str).strip()
    formats = [
        "%d-%m-%Y %H:%M:%S",  # SBI with time
        "%Y/%m/%d %H:%M:%S",  # HDFC with time
        "%d/%m/%y %H:%M:%S",  # ICICI PDF with time
        "%d/%m/%Y %H:%M:%S",  # DD/MM/YYYY with time
        "%d-%m-%Y",    # DD-MM-YYYY (SBI)
        "%Y/%m/%d",    # YYYY/MM/DD (HDFC)
        "%d/%m/%y",    # DD/MM/YY (ICICI PDF)
        "%d/%m/%Y",    # DD/MM/YYYY
        "%Y-%m-%d",    # ISO
        "%d-%m-%y",    # DD-MM-YY
        "%Y-%m-%d %H:%M:%S",  # ISO with time
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except (ValueError, TypeError):
            continue
    return None


def _extract_narration_fields(narration):
    """
    Extract UTR, counterparty VPA/account, and channel from free-text narration.
    Handles SBI, HDFC, and ICICI narration formats.
    """
    if not narration or pd.isna(narration):
        return None, None, None

    narration = str(narration).strip()
    utr = None
    counterparty = None
    channel = None

    # Extract channel type
    channel_match = re.search(r'(UPI|IMPS|NEFT|RTGS)', narration, re.IGNORECASE)
    if channel_match:
        channel = channel_match.group(1).upper()

    # Extract UTR (12-digit number)
    utr_match = re.search(r'(?:^|[/\-])(\d{12})(?:[/\-]|$)', narration)
    if utr_match:
        utr = utr_match.group(1)

    # Extract counterparty VPA (word@word pattern)
    vpa_match = re.search(r'([a-zA-Z0-9._]+@[a-zA-Z0-9]+)', narration)
    if vpa_match:
        counterparty = vpa_match.group(1)
    else:
        # Try to extract account/name from narration parts
        # SBI style: UPI/DR/UTR/name.vpa/Payment
        # HDFC style: UPI-DEBIT-UTR-name.vpa
        # ICICI style: IMPS-P2A/UTR/NAME/IFSC
        parts = re.split(r'[/\-]', narration)
        if len(parts) >= 4:
            # Try the 4th part (counterparty) if it looks like a name/VPA
            candidate = parts[3].strip() if len(parts) > 3 else ""
            if candidate and not candidate.isdigit() and candidate not in ["Payment", "CREDIT", "DEBIT", "CR", "DR", "P2A", "P2M"]:
                counterparty = candidate

    return utr, counterparty, channel


def _get_direction(row, debit_col, credit_col, type_col, amount_col):
    """Determine transaction direction from available columns."""
    # If we have separate debit/credit columns
    if debit_col and credit_col:
        debit_val = row.get(debit_col)
        credit_val = row.get(credit_col)
        if pd.notna(debit_val) and debit_val != "" and float(str(debit_val).replace(',', '')) > 0:
            return "debit", float(str(debit_val).replace(',', ''))
        elif pd.notna(credit_val) and credit_val != "" and float(str(credit_val).replace(',', '')) > 0:
            return "credit", float(str(credit_val).replace(',', ''))

    # If we have a Type column (DR/CR)
    if type_col and amount_col:
        type_val = str(row.get(type_col, "")).strip().upper()
        amt_val = row.get(amount_col)
        if pd.notna(amt_val) and amt_val != "":
            try:
                amt = float(str(amt_val).replace(',', ''))
            except ValueError:
                return "unknown", 0
            if "DR" in type_val or "DEBIT" in type_val:
                return "debit", amt
            elif "CR" in type_val or "CREDIT" in type_val:
                return "credit", amt

    return "unknown", 0


def parse_bank_xlsx(filepath):
    """Parse SBI-style Excel bank statement."""
    df = pd.read_excel(filepath, engine='openpyxl')
    return _parse_bank_df(df, str(filepath))


def parse_bank_csv(filepath):
    """Parse HDFC-style CSV bank statement."""
    df = pd.read_csv(filepath)
    return _parse_bank_df(df, str(filepath))


def parse_bank_pdf(filepath):
    """Parse ICICI-style PDF bank statement using pdfplumber."""
    events = []
    with pdfplumber.open(filepath) as pdf:
        all_rows = []
        header = None
        for page in pdf.pages:
            table = page.extract_table()
            if table:
                for row_idx, row in enumerate(table):
                    if row_idx == 0 and header is None:
                        # Clean header
                        raw_header = [str(c).strip() if c else f"col_{i}" for i, c in enumerate(row)]
                        # Resolve pdfplumber column-joining artifact
                        header = []
                        for c in raw_header:
                            c_lower = c.lower()
                            if "s.no" in c_lower:
                                header.append("S.No")
                            elif "account" in c_lower:
                                header.append("Account No")
                            elif "date" in c_lower:
                                header.append("Date")
                            elif "desc" in c_lower:
                                header.append("Description")
                            elif "amount" in c_lower:
                                header.append("Amount")
                            elif "type" in c_lower or "dr/cr" in c_lower or "pe (" in c_lower:
                                header.append("Type")
                            elif "bal" in c_lower or "r)" in c_lower:
                                header.append("Balance")
                            else:
                                header.append(c)
                        continue
                    if row_idx == 0 and header is not None:
                        # Skip header on subsequent pages
                        continue
                    if len(row) == len(header):
                        all_rows.append(row)

        if not header or not all_rows:
            return events

        # Build DataFrame
        df = pd.DataFrame(all_rows, columns=header)
        events = _parse_bank_df(df, str(filepath))

    return events


def _parse_bank_df(df, source_file):
    """Generic bank DataFrame parser — auto-detects columns."""
    events = []

    # Auto-detect columns
    date_col = _find_column(df.columns, "date")
    narration_col = _find_column(df.columns, "narration")
    debit_col = _find_column(df.columns, "debit")
    credit_col = _find_column(df.columns, "credit")
    balance_col = _find_column(df.columns, "balance")
    type_col = _find_column(df.columns, "type")
    amount_col = _find_column(df.columns, "amount")
    account_no_col = _find_column(df.columns, "account_no")

    if not date_col:
        print(f"  WARNING: Could not find date column in {source_file}")
        print(f"  Available columns: {list(df.columns)}")
        return events

    for idx, row in df.iterrows():
        # Parse date
        timestamp = _parse_date(row.get(date_col))
        if timestamp is None:
            continue

        # Parse narration
        narration = str(row.get(narration_col, "")) if narration_col else ""
        utr, counterparty, channel = _extract_narration_fields(narration)

        # Determine direction and amount
        direction, amount = _get_direction(row, debit_col, credit_col, type_col, amount_col)
        if amount == 0:
            continue

        # Get account from column if available, else extract from narration/source_file
        if account_no_col:
            account_ref = str(row.get(account_no_col, "")).strip()
            if not account_ref or pd.isna(row.get(account_no_col)):
                account_ref = _extract_account_ref(narration, source_file)
        else:
            account_ref = _extract_account_ref(narration, source_file)

        events.append({
            "entity_ref": account_ref,
            "event_type": "transaction",
            "timestamp": timestamp,
            "end_timestamp": None,
            "amount": amount if direction == "credit" else -amount,
            "counterparty": counterparty,
            "location": None,
            "source_file": os.path.basename(source_file),
            "raw_row_ref": int(idx),
            "utr": utr,
            "channel": channel,
            "direction": direction,
            "imei": None,
            "entity_id": None,
        })

    return events


def _extract_account_ref(narration, source_file):
    """
    Extract the account holder reference from narration.
    For bank statements, every row belongs to the account holder.
    We use the narration to identify WHO they transacted with (counterparty).
    The account_ref is derived from the source file identifier.
    """
    # Use source filename as a base identifier
    basename = os.path.basename(source_file).lower()
    if "sbi" in basename:
        return "ACCT_SBI"
    elif "hdfc" in basename:
        return "ACCT_HDFC"
    elif "icici" in basename:
        return "ACCT_ICICI"
    return "ACCT_UNKNOWN"


def parse_bank_file(filepath):
    """Auto-detect bank file format and parse."""
    filepath = Path(filepath)
    ext = filepath.suffix.lower()

    if ext == '.xlsx' or ext == '.xls':
        return parse_bank_xlsx(filepath)
    elif ext == '.csv':
        return parse_bank_csv(filepath)
    elif ext == '.pdf':
        return parse_bank_pdf(filepath)
    else:
        print(f"  WARNING: Unknown bank file format: {ext}")
        return []


def parse_all_bank_files(directory):
    """Parse all bank files in a directory."""
    all_events = []
    directory = Path(directory)

    bank_files = list(directory.glob("bank_*.*"))
    for f in bank_files:
        print(f"  Parsing bank file: {f.name}")
        events = parse_bank_file(f)
        print(f"    -> {len(events)} events")
        all_events.extend(events)

    return all_events


if __name__ == "__main__":
    # Test parsing
    raw_dir = Path(__file__).resolve().parent.parent / "data" / "raw"
    events = parse_all_bank_files(raw_dir)
    print(f"\nTotal bank events parsed: {len(events)}")
    if events:
        print(f"Sample event: {events[0]}")
