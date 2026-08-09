"""
IPDR (Internet Protocol Detail Record) Parser
Maps IPDR CSV to canonical Event schema.

Expected columns: MSISDN, PRIVATE_IP, PUBLIC_IP, PORT, SESSION_START, SESSION_END, DEST_IP, DATA_VOLUME_KB
"""
import os
from datetime import datetime
from pathlib import Path

import pandas as pd


def parse_ipdr(filepath):
    """Parse IPDR CSV file into canonical Event list."""
    filepath = Path(filepath)
    df = pd.read_csv(filepath)
    events = []

    for idx, row in df.iterrows():
        # Parse session start
        session_start = None
        ss = row.get("SESSION_START")
        if pd.notna(ss):
            try:
                session_start = datetime.strptime(str(ss).strip(), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    session_start = pd.to_datetime(ss)
                    if hasattr(session_start, 'to_pydatetime'):
                        session_start = session_start.to_pydatetime()
                except Exception:
                    continue

        if session_start is None:
            continue

        # Parse session end
        session_end = None
        se = row.get("SESSION_END")
        if pd.notna(se):
            try:
                session_end = datetime.strptime(str(se).strip(), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    session_end = pd.to_datetime(se)
                    if hasattr(session_end, 'to_pydatetime'):
                        session_end = session_end.to_pydatetime()
                except Exception:
                    session_end = None

        msisdn = str(row.get("MSISDN", "")).strip()
        public_ip = str(row.get("PUBLIC_IP", "")).strip() if pd.notna(row.get("PUBLIC_IP")) else None
        private_ip = str(row.get("PRIVATE_IP", "")).strip() if pd.notna(row.get("PRIVATE_IP")) else None
        dest_ip = str(row.get("DEST_IP", "")).strip() if pd.notna(row.get("DEST_IP")) else None
        port = row.get("PORT")
        data_kb = row.get("DATA_VOLUME_KB")

        # Location derived from public IP prefix (simulated geolocation)
        location = _ip_to_location(public_ip) if public_ip else None

        events.append({
            "entity_ref": msisdn,
            "event_type": "ip_session",
            "timestamp": session_start,
            "end_timestamp": session_end,
            "amount": None,
            "counterparty": dest_ip,
            "location": location,
            "source_file": filepath.name,
            "raw_row_ref": int(idx),
            "utr": None,
            "channel": None,
            "direction": None,
            "imei": None,
            "entity_id": None,
            # Extra IPDR fields stored for downstream use
            "_public_ip": public_ip,
            "_private_ip": private_ip,
            "_port": port,
            "_data_volume_kb": data_kb,
        })

    return events


def _ip_to_location(ip):
    """Simulated IP geolocation based on prefix (matches generator's CITY_IP_PREFIXES)."""
    if not ip:
        return None
    prefix_map = {
        "103.21": "Mumbai",
        "103.22": "Delhi",
        "103.23": "Bangalore",
        "103.24": "Ahmedabad",
        "103.25": "Surat",
        "103.26": "Pune",
        "103.27": "Hyderabad",
        "103.28": "Chennai",
    }
    for prefix, city in prefix_map.items():
        if ip.startswith(prefix):
            return city
    return None


def parse_ipdr_file(filepath):
    """Entry point for IPDR parsing."""
    print(f"  Parsing IPDR file: {Path(filepath).name}")
    events = parse_ipdr(filepath)
    print(f"    -> {len(events)} events")
    return events


if __name__ == "__main__":
    raw_dir = Path(__file__).resolve().parent.parent / "data" / "raw"
    ipdr_file = raw_dir / "ipdr_export.csv"
    if ipdr_file.exists():
        events = parse_ipdr_file(ipdr_file)
        print(f"\nTotal IPDR events: {len(events)}")
        if events:
            print(f"Sample: {events[0]}")
