"""
Smart Ingestion Layer for E-Rakshak
===================================
Automatically detects file formats, fuzzy-matches columns, detects encodings,
and normalizes data into the canonical Event schema.
"""
import os
import re
import json
import chardet
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import pdfplumber

COLUMN_MAPS = {
    "date": ["txn date", "date", "transaction date", "trans date", "txn_date", "timestamp", "start_time", "session_start", "date & time", "datetime", "val date", "value date", "value_date", "call_date", "event_date"],
    "time": ["time", "txn_time", "start_time", "session_time", "call_time", "event_time"],
    "narration": ["description", "particulars", "narration", "details", "transaction details", "remarks", "memo"],
    "debit": ["debit", "withdrawal_amt", "withdrawal", "dr_amount", "debit_amount", "dr", "withdrawals"],
    "credit": ["credit", "deposit_amt", "deposit", "cr_amount", "credit_amount", "cr", "deposits"],
    "balance": ["balance", "closing_balance", "running_balance", "bal.", "available balance", "bal"],
    "type": ["type", "type (dr/cr)", "dr/cr", "txn_type", "call_type"],
    "amount": ["amount", "txn_amount", "transaction_amount", "amt", "volume"],
    "account_no": ["account_no", "account no", "account number", "acct_no", "acct no", "card/acc no", "acc_no"],
    # CDR fields
    "a_party": ["a_party", "a party", "a_party_number", "caller", "calling_number", "calling number", "calling_no", "calling_num", "source", "from", "calling", "msisdn", "msisdn_a", "sender", "caller_number", "mobile_a", "phone_a"],
    "b_party": ["b_party", "b party", "b_party_number", "callee", "called_number", "called number", "called_no", "called_num", "destination", "to", "called", "msisdn_b", "receiver", "callee_number", "mobile_b", "phone_b"],
    "duration": ["duration", "duration_sec", "duration sec", "call_duration", "duration_seconds", "sec", "duration_min", "duration min"],
    "cell_id": ["first_cell_id", "last_cell_id", "cell_id", "cell id", "lac", "cgi", "tower", "tower_id", "tower id", "location", "cell_site_address"],
    "imei": ["a_party_imei", "b_party_imei", "imei", "device_imei", "handset_imei", "device_id", "imei_no"],
    "imsi": ["a_party_imsi", "b_party_imsi", "imsi", "sim_imsi", "sim_id", "subscriber_imsi", "imsi_no", "sim_no"],
    # IPDR fields
    "msisdn": ["msisdn", "phone", "mobile", "user_id", "username", "subscriber_id"],
    "public_ip": ["public_ip", "public ip", "ip", "client_ip", "source_ip", "ip_address"],
    "private_ip": ["private_ip", "private ip", "local_ip", "internal_ip"],
    "dest_ip": ["dest_ip", "dest ip", "destination_ip", "destination ip", "target_ip", "ip_dest"],
    "port": ["port", "source_port", "dest_port"],
    "data_volume": ["data_volume", "data_volume_kb", "data volume", "volume_kb", "octets", "bytes", "usage"],
}

def detect_encoding(file_path):
    """Detect encoding of a text file."""
    try:
        with open(file_path, 'rb') as f:
            rawdata = f.read(20000)
            result = chardet.detect(rawdata)
            return result['encoding'] or 'utf-8'
    except Exception:
        return 'utf-8'

def fuzzy_match_columns(df_columns):
    """
    Match DataFrame columns to canonical keys using COLUMN_MAPS.
    Returns: dict mapping canonical_key -> actual_column_name
    """
    mapped = {}
    lower_cols = {str(c).lower().strip(): c for c in df_columns}
    
    for key, candidates in COLUMN_MAPS.items():
        for candidate in candidates:
            if candidate in lower_cols:
                mapped[key] = lower_cols[candidate]
                break
    return mapped

def detect_file_type(df_columns):
    """
    Detect type based on matched column counts.
    Returns: type_str ("bank", "cdr", "ipdr", "unknown"), confidence, mapped_cols
    """
    mapped = fuzzy_match_columns(df_columns)
    
    # Calculate scores
    bank_keys = ["debit", "credit", "balance", "narration", "account_no"]
    cdr_keys = ["a_party", "b_party", "duration", "imei", "cell_id"]
    ipdr_keys = ["msisdn", "public_ip", "private_ip", "dest_ip", "data_volume"]
    
    bank_score = sum(1 for k in bank_keys if k in mapped)
    cdr_score = sum(1 for k in cdr_keys if k in mapped)
    ipdr_score = sum(1 for k in ipdr_keys if k in mapped)
    
    scores = {
        "bank": bank_score,
        "cdr": cdr_score,
        "ipdr": ipdr_score
    }
    
    best_type = max(scores, key=scores.get)
    max_score = scores[best_type]
    
    if max_score == 0:
        # Fallback heuristic checks
        col_str = " ".join([str(c).lower() for c in df_columns])
        if "call" in col_str or "caller" in col_str or "callee" in col_str or "sms" in col_str:
            return "cdr", 0.5, mapped
        if "ip" in col_str or "msisdn" in col_str or "port" in col_str:
            return "ipdr", 0.5, mapped
        if "amount" in col_str or "balance" in col_str or "debit" in col_str or "credit" in col_str:
            return "bank", 0.5, mapped
        return "unknown", 0.0, mapped
        
    total_relevant = len(df_columns)
    confidence = max_score / len(bank_keys if best_type == "bank" else (cdr_keys if best_type == "cdr" else ipdr_keys))
    
    return best_type, min(confidence, 1.0), mapped

def parse_smart_date(date_str):
    """Robust date parser supporting various standard formats."""
    if isinstance(date_str, datetime):
        return date_str
    if pd.isna(date_str) or not date_str:
        return None
        
    date_str = str(date_str).strip()
    
    # Try custom parsing if it has a timestamp
    formats = [
        "%d-%m-%Y %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%d/%m/%y %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%d-%m-%Y %H:%M",
        "%Y/%m/%d %H:%M",
        "%d/%m/%Y %H:%M",
        "%Y-%m-%d %H:%M",
        "%d-%m-%Y",
        "%Y/%m/%d",
        "%d/%m/%y",
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%d-%m-%y",
        "%d-%b-%Y", # e.g. 19-Jul-2026
        "%d-%b-%y",
        "%Y%m%d%H%M%S", # Packed timestamp
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except (ValueError, TypeError):
            continue
            
    # Try pandas to_datetime as fallback
    try:
        dt = pd.to_datetime(date_str)
        if hasattr(dt, 'to_pydatetime'):
            return dt.to_pydatetime()
        return dt
    except Exception:
        return None

def parse_amount(val):
    """Clean and parse amount values (remove commas, currency symbols)."""
    if pd.isna(val) or val == "":
        return 0.0
    val_str = str(val).replace(",", "").replace("$", "").replace("₹", "").strip()
    try:
        return float(val_str)
    except ValueError:
        return 0.0

def parse_messy_file(filepath):
    """
    Reads a file (CSV, XLSX, PDF), detects type, maps columns, parses and
    returns a list of normalized events plus a quality summary.
    """
    filepath = Path(filepath)
    ext = filepath.suffix.lower()
    df = None
    
    # 1. Read file
    if ext == '.csv':
        enc = detect_encoding(filepath)
        try:
            # Try comma first
            df = pd.read_csv(filepath, encoding=enc)
        except Exception:
            try:
                # Try semicolon
                df = pd.read_csv(filepath, sep=';', encoding=enc)
            except Exception:
                try:
                    # Try tab
                    df = pd.read_csv(filepath, sep='\t', encoding=enc)
                except Exception as e:
                    return [], {"error": f"Failed to read CSV: {str(e)}", "file": filepath.name}
    elif ext in ['.xlsx', '.xls']:
        try:
            df = pd.read_excel(filepath)
        except Exception as e:
            return [], {"error": f"Failed to read Excel: {str(e)}", "file": filepath.name}
    elif ext == '.pdf':
        try:
            # Fallback to bank_parser PDF reader logic
            from ingestion.bank_parser import parse_bank_pdf
            events = parse_bank_pdf(filepath)
            return events, {"detected_type": "bank", "confidence": 1.0, "total_rows": len(events), "parsed_rows": len(events), "skipped_rows": 0}
        except Exception as e:
            return [], {"error": f"Failed to read PDF: {str(e)}", "file": filepath.name}
    else:
        return [], {"error": f"Unsupported file extension: {ext}", "file": filepath.name}
        
    if df is None or df.empty:
        return [], {"error": "Empty file or could not parse DataFrame", "file": filepath.name}
        
    # 2. Detect type and map columns
    file_type, confidence, mapped = detect_file_type(df.columns)
    
    events = []
    skipped = 0
    parsed = 0
    
    # 3. Process records based on detected type
    if file_type == "cdr":
        date_col = mapped.get("date")
        a_party_col = mapped.get("a_party")
        b_party_col = mapped.get("b_party")
        duration_col = mapped.get("duration")
        imei_col = mapped.get("imei")
        imsi_col = mapped.get("imsi")
        cell_col = mapped.get("cell_id")
        type_col = mapped.get("type")
        
        time_col = mapped.get("time")
        
        if not date_col or not a_party_col:
            return [], {"error": f"CDR format detected but missing date or A_PARTY column mappings. Mapped: {mapped}", "file": filepath.name}
            
        for idx, row in df.iterrows():
            date_val = row.get(date_col)
            if time_col and date_col != time_col and pd.notna(row.get(time_col)):
                date_val = f"{date_val} {row.get(time_col)}"
            ts = parse_smart_date(date_val)
            if ts is None:
                skipped += 1
                continue
                
            dur_sec = int(parse_amount(row.get(duration_col))) if duration_col else 0
            end_ts = ts + timedelta(seconds=dur_sec)
            
            a_party = str(row.get(a_party_col, "")).strip()
            b_party = str(row.get(b_party_col, "")).strip() if b_party_col else ""
            imei = str(row.get(imei_col, "")).strip() if imei_col else None
            imsi = str(row.get(imsi_col, "")).strip() if imsi_col else None
            cell = str(row.get(cell_col, "")).strip() if cell_col else None
            
            c_type = str(row.get(type_col, "VOICE")).strip().upper() if type_col else "VOICE"
            event_type = "sms" if "SMS" in c_type else "call"
            
            events.append({
                "entity_ref": a_party,
                "event_type": event_type,
                "timestamp": ts,
                "end_timestamp": end_ts,
                "amount": None,
                "counterparty": b_party,
                "location": cell,
                "source_file": filepath.name,
                "raw_row_ref": int(idx),
                "utr": None,
                "channel": None,
                "direction": "outgoing",
                "imei": imei,
                "imsi": imsi,
                "entity_id": None,
            })
            parsed += 1
            
    elif file_type == "ipdr":
        date_col = mapped.get("date")
        msisdn_col = mapped.get("msisdn") or mapped.get("a_party")
        public_ip_col = mapped.get("public_ip")
        private_ip_col = mapped.get("private_ip")
        dest_ip_col = mapped.get("dest_ip") or mapped.get("b_party")
        port_col = mapped.get("port")
        volume_col = mapped.get("data_volume") or mapped.get("amount")
        
        # Location mapping helper
        from ingestion.ipdr_parser import _ip_to_location
        
        if not date_col or not (msisdn_col or public_ip_col):
            return [], {"error": f"IPDR format detected but missing date or MSISDN/IP mappings. Mapped: {mapped}", "file": filepath.name}
            
        for idx, row in df.iterrows():
            ts = parse_smart_date(row.get(date_col))
            if ts is None:
                skipped += 1
                continue
                
            msisdn = str(row.get(msisdn_col, "")).strip() if msisdn_col else ""
            pub_ip = str(row.get(public_ip_col, "")).strip() if public_ip_col else None
            priv_ip = str(row.get(private_ip_col, "")).strip() if private_ip_col else None
            dest_ip = str(row.get(dest_ip_col, "")).strip() if dest_ip_col else None
            port = int(parse_amount(row.get(port_col))) if port_col else None
            vol = parse_amount(row.get(volume_col)) if volume_col else 0
            
            loc = _ip_to_location(pub_ip) if pub_ip else None
            
            events.append({
                "entity_ref": msisdn if msisdn else (pub_ip if pub_ip else "IP_UNKNOWN"),
                "event_type": "ip_session",
                "timestamp": ts,
                "end_timestamp": None,
                "amount": None,
                "counterparty": dest_ip,
                "location": loc,
                "source_file": filepath.name,
                "raw_row_ref": int(idx),
                "utr": None,
                "channel": None,
                "direction": None,
                "imei": None,
                "entity_id": None,
                "_public_ip": pub_ip,
                "_private_ip": priv_ip,
                "_port": port,
                "_data_volume_kb": vol,
            })
            parsed += 1
            
    elif file_type == "bank":
        date_col = mapped.get("date")
        narration_col = mapped.get("narration")
        debit_col = mapped.get("debit")
        credit_col = mapped.get("credit")
        balance_col = mapped.get("balance")
        type_col = mapped.get("type")
        amount_col = mapped.get("amount")
        account_col = mapped.get("account_no")
        
        from ingestion.bank_parser import _extract_narration_fields, _extract_account_ref
        
        if not date_col:
            return [], {"error": f"Bank statement format detected but missing date column mapping. Mapped: {mapped}", "file": filepath.name}
            
        for idx, row in df.iterrows():
            ts = parse_smart_date(row.get(date_col))
            if ts is None:
                skipped += 1
                continue
                
            narration = str(row.get(narration_col, "")) if narration_col else ""
            utr, counterparty, channel = _extract_narration_fields(narration)
            
            # Determine debit/credit & amount
            direction = "unknown"
            amount = 0.0
            
            if debit_col and credit_col:
                debit_val = parse_amount(row.get(debit_col))
                credit_val = parse_amount(row.get(credit_col))
                if debit_val > 0:
                    direction = "debit"
                    amount = debit_val
                elif credit_val > 0:
                    direction = "credit"
                    amount = credit_val
            elif amount_col:
                amt_val = parse_amount(row.get(amount_col))
                if type_col:
                    t_val = str(row.get(type_col, "")).upper()
                    if "DR" in t_val or "DEBIT" in t_val or amt_val < 0:
                        direction = "debit"
                        amount = abs(amt_val)
                    else:
                        direction = "credit"
                        amount = amt_val
                else:
                    if amt_val < 0:
                        direction = "debit"
                        amount = abs(amt_val)
                    else:
                        direction = "credit"
                        amount = amt_val
            
            if amount == 0.0:
                skipped += 1
                continue
                
            if account_col:
                acct = str(row.get(account_col, "")).strip()
            else:
                acct = _extract_account_ref(narration, str(filepath))
                
            events.append({
                "entity_ref": acct,
                "event_type": "transaction",
                "timestamp": ts,
                "end_timestamp": None,
                "amount": amount if direction == "credit" else -amount,
                "counterparty": counterparty,
                "location": None,
                "source_file": filepath.name,
                "raw_row_ref": int(idx),
                "utr": utr,
                "channel": channel,
                "direction": direction,
                "imei": None,
                "entity_id": None,
            })
            parsed += 1
            
    else:
        return [], {"error": "Could not determine statement type from column headers", "file": filepath.name}
        
    quality_summary = {
        "detected_type": file_type,
        "confidence": confidence,
        "total_rows": len(df),
        "parsed_rows": parsed,
        "skipped_rows": skipped,
        "mapped_columns": {k: str(v) for k, v in mapped.items()}
    }
    
    return events, quality_summary
