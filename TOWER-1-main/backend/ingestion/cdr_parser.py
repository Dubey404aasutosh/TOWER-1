"""
CDR (Call Detail Record) Parser
Maps CDR CSV to canonical Event schema.

Expected columns: A_PARTY, B_PARTY, CALL_TYPE, START_TIME, DURATION_SEC, CELL_ID, IMEI
"""
import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd


def parse_cdr(filepath):
    """Parse CDR CSV file into canonical Event list."""
    filepath = Path(filepath)
    df = pd.read_csv(filepath)
    events = []

    for idx, row in df.iterrows():
        # Parse start time
        start_time = None
        st = row.get("START_TIME")
        if pd.notna(st):
            try:
                start_time = datetime.strptime(str(st).strip(), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    start_time = pd.to_datetime(st)
                    if hasattr(start_time, 'to_pydatetime'):
                        start_time = start_time.to_pydatetime()
                except Exception:
                    continue

        if start_time is None:
            continue

        # Compute end time from duration
        duration = row.get("DURATION_SEC", 0)
        if pd.isna(duration):
            duration = 0
        end_time = start_time + timedelta(seconds=int(duration))

        # A-party is the entity, B-party is the counterparty
        a_party = str(row.get("A_PARTY", "")).strip()
        b_party = str(row.get("B_PARTY", "")).strip()
        cell_id = str(row.get("CELL_ID", "")).strip() if pd.notna(row.get("CELL_ID")) else None
        imei = str(row.get("IMEI", "")).strip() if pd.notna(row.get("IMEI")) else None
        call_type = str(row.get("CALL_TYPE", "VOICE")).strip().upper()

        event_type = "sms" if call_type == "SMS" else "call"

        events.append({
            "entity_ref": a_party,
            "event_type": event_type,
            "timestamp": start_time,
            "end_timestamp": end_time,
            "amount": None,
            "counterparty": b_party,
            "location": cell_id,
            "source_file": filepath.name,
            "raw_row_ref": int(idx),
            "utr": None,
            "channel": None,
            "direction": "outgoing",
            "imei": imei,
            "entity_id": None,
        })

    return events


def parse_cdr_file(filepath):
    """Entry point for CDR parsing."""
    print(f"  Parsing CDR file: {Path(filepath).name}")
    events = parse_cdr(filepath)
    print(f"    -> {len(events)} events")
    return events


if __name__ == "__main__":
    raw_dir = Path(__file__).resolve().parent.parent / "data" / "raw"
    cdr_file = raw_dir / "cdr_export.csv"
    if cdr_file.exists():
        events = parse_cdr_file(cdr_file)
        print(f"\nTotal CDR events: {len(events)}")
        if events:
            print(f"Sample: {events[0]}")
