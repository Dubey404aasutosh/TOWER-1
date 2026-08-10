"""
Temporal Correlation Engine
============================
For each resolved entity, sorts events by timestamp and runs windowed joins
using pandas.merge_asof to tag each transaction with its nearest call and
nearest IP session within a configurable window W.

O(n log n) per entity from the sort — no brute-force pairwise comparisons.
"""
import pandas as pd


def temporal_join(all_events, window_minutes=10):
    """
    Run windowed temporal join across event types for each entity.

    For each resolved entity:
    1. Separate events into transactions, calls, and IP sessions
    2. Sort each by timestamp
    3. Use merge_asof to find nearest call and IP session for each transaction

    Args:
        all_events: list of event dicts (already resolved with entity_id)
        window_minutes: correlation window in minutes (default 10)

    Returns:
        DataFrame with transactions enriched with nearest call/session info
    """
    df = pd.DataFrame(all_events)

    if df.empty:
        return pd.DataFrame()

    # Ensure timestamp is datetime
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    if 'end_timestamp' in df.columns:
        df['end_timestamp'] = pd.to_datetime(df['end_timestamp'], errors='coerce')

    tolerance = pd.Timedelta(minutes=window_minutes)

    # Separate by event type
    transactions = df[df['event_type'] == 'transaction'].copy()
    calls = df[df['event_type'].isin(['call', 'sms'])].copy()
    ip_sessions = df[df['event_type'] == 'ip_session'].copy()

    if transactions.empty:
        return transactions

    # Add prefixed columns for join results
    enriched_parts = []

    # Process per entity for accurate merge_asof
    for entity_id in transactions['entity_id'].unique():
        txns_e = transactions[transactions['entity_id'] == entity_id].copy()
        calls_e = calls[calls['entity_id'] == entity_id].copy()
        sessions_e = ip_sessions[ip_sessions['entity_id'] == entity_id].copy()

        # Sort by timestamp (required for merge_asof)
        txns_e = txns_e.sort_values('timestamp').reset_index(drop=True)

        # Join with nearest call
        if not calls_e.empty:
            calls_e = calls_e.sort_values('timestamp').reset_index(drop=True)
            calls_subset = calls_e[['timestamp', 'counterparty', 'location', 'imei', 'raw_row_ref']].copy()
            calls_subset.columns = ['timestamp', 'call_counterparty', 'call_location', 'call_imei', 'call_row_ref']

            txns_e = pd.merge_asof(
                txns_e, calls_subset,
                on='timestamp',
                direction='nearest',
                tolerance=tolerance,
            )
        else:
            txns_e['call_counterparty'] = None
            txns_e['call_location'] = None
            txns_e['call_imei'] = None
            txns_e['call_row_ref'] = None

        # Join with nearest IP session
        if not sessions_e.empty:
            sessions_e = sessions_e.sort_values('timestamp').reset_index(drop=True)
            sessions_subset = sessions_e[['timestamp', 'counterparty', 'location', 'raw_row_ref']].copy()
            sessions_subset.columns = ['timestamp', 'session_dest_ip', 'session_location', 'session_row_ref']

            # Re-sort txns_e since merge_asof may have reordered
            txns_e = txns_e.sort_values('timestamp').reset_index(drop=True)
            txns_e = pd.merge_asof(
                txns_e, sessions_subset,
                on='timestamp',
                direction='nearest',
                tolerance=tolerance,
            )
        else:
            txns_e['session_dest_ip'] = None
            txns_e['session_location'] = None
            txns_e['session_row_ref'] = None

        enriched_parts.append(txns_e)

    if enriched_parts:
        enriched = pd.concat(enriched_parts, ignore_index=True)
    else:
        enriched = transactions

    # Flag transactions that have temporal correlations
    enriched['has_call_correlation'] = enriched['call_counterparty'].notna()
    enriched['has_session_correlation'] = enriched['session_dest_ip'].notna()
    enriched['has_both_correlation'] = enriched['has_call_correlation'] & enriched['has_session_correlation']

    return enriched


def build_unified_timeline(all_events, entity_id=None):
    """
    Build a unified timeline for visualization showing all event types
    interleaved on one axis.

    Args:
        all_events: list of event dicts, or a DataFrame of the same
        entity_id: optional filter for a specific entity

    Returns:
        DataFrame sorted by timestamp with all event types
    """
    df = all_events.copy() if isinstance(all_events, pd.DataFrame) else pd.DataFrame(all_events)
    if df.empty:
        return df

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    if 'end_timestamp' in df.columns:
        df['end_timestamp'] = pd.to_datetime(df['end_timestamp'], errors='coerce')

    if entity_id:
        df = df[df['entity_id'] == entity_id]

    return df.sort_values('timestamp').reset_index(drop=True)


# ---------------------------------------------------------------------------
# Unified timeline payload (FR-II.a)
# ---------------------------------------------------------------------------
# One entity's whole story on a single time axis, in three lanes. This is the
# structure behind both the interactive timeline in the dashboard and the chart
# embedded in the forensic .docx — they render the same numbers because they read
# the same builder, so a judge comparing screen against exhibit sees one dataset.

TIMELINE_LANES = [
    {"key": "transaction", "label": "Transactions", "event_types": ["transaction"]},
    {"key": "call", "label": "Calls / SMS", "event_types": ["call", "sms"]},
    {"key": "ip_session", "label": "IP Sessions", "event_types": ["ip_session"]},
]

_LANE_OF_EVENT_TYPE = {
    et: lane["key"] for lane in TIMELINE_LANES for et in lane["event_types"]
}


def _clean_row_ref(value):
    """
    Render a row reference the way it appears in the source file.

    merge_asof promotes an int column to float64 the moment a row goes unmatched,
    which is how references like "cdr_row_1018.0" end up quoted in a court exhibit.
    A row number is an integer or it is nothing.
    """
    if value is None:
        return None
    if isinstance(value, float):
        if pd.isna(value):
            return None
        if value.is_integer():
            return str(int(value))
    text = str(value).strip()
    if not text or text.lower() in ("nan", "none", "nat"):
        return None
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def _iso(ts):
    if ts is None or pd.isna(ts):
        return None
    return pd.Timestamp(ts).isoformat()


def _safe_float(value):
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_timeline_payload(all_events_df, entity_id, enriched_txns=None,
                            window_minutes=10, rule_evidence=None, max_events=1500):
    """
    Assemble one entity's unified timeline: every event on a shared time axis,
    split into transaction / call / IP-session lanes, with the temporal
    correlation windows that made TCS-1 and TCS-2 fire drawn over the top.

    The correlation band is the literal search window of the rule — [t - W, t + W]
    around a transaction — so "the call, the session and the transfer all fall
    inside this box" stops being a claim in a paragraph and becomes something
    visible on an axis.

    Args:
        all_events_df: DataFrame of all resolved events
        entity_id: the entity to build the timeline for
        enriched_txns: output of temporal_join(), used to locate correlated transfers
        window_minutes: the correlation window W the pipeline ran with
        rule_evidence: {rule_id: [evidence tokens]} — used to mark rows a rule cited
        max_events: hard cap so a pathological entity cannot stall the browser

    Returns:
        dict, JSON-serialisable, ready for both the API and the report renderer
    """
    payload = {
        "entity_id": entity_id,
        "window_minutes": window_minutes,
        "lanes": [{"key": l["key"], "label": l["label"], "count": 0} for l in TIMELINE_LANES],
        "events": [],
        "correlations": [],
        "start": None,
        "end": None,
        "total_events": 0,
        "truncated": False,
        "flagged_row_refs": [],
    }

    if all_events_df is None or len(all_events_df) == 0:
        return payload

    timeline = build_unified_timeline(all_events_df, entity_id=entity_id)
    if timeline.empty:
        return payload

    timeline = timeline[timeline['timestamp'].notna()]
    if timeline.empty:
        return payload

    payload["total_events"] = int(len(timeline))
    if len(timeline) > max_events:
        timeline = timeline.head(max_events)
        payload["truncated"] = True

    # Row references cited by any rule that fired — these get emphasised in both
    # renderers so "why this score?" has an answer you can point at.
    flagged_refs = set()
    for tokens in (rule_evidence or {}).values():
        for token in tokens or []:
            text = str(token)
            if text.startswith("row_"):
                ref = _clean_row_ref(text[len("row_"):])
                if ref:
                    flagged_refs.add(ref)
    payload["flagged_row_refs"] = sorted(flagged_refs)

    lane_counts = {lane["key"]: 0 for lane in TIMELINE_LANES}

    for idx, row in timeline.iterrows():
        event_type = str(row.get('event_type', '') or '')
        lane = _LANE_OF_EVENT_TYPE.get(event_type)
        if lane is None:
            continue

        row_ref = _clean_row_ref(row.get('raw_row_ref', idx))
        amount = _safe_float(row.get('amount'))
        counterparty = row.get('counterparty')
        counterparty = None if counterparty is None or pd.isna(counterparty) else str(counterparty)
        location = row.get('location')
        location = None if location is None or pd.isna(location) else str(location)

        direction = None
        if lane == "transaction" and amount is not None:
            direction = "credit" if amount >= 0 else "debit"

        if lane == "transaction" and amount is not None:
            label = f"{'+' if direction == 'credit' else '-'}₹{abs(amount):,.0f}"
        elif lane == "call":
            label = event_type.upper()
        else:
            label = "SESSION"

        lane_counts[lane] += 1
        payload["events"].append({
            "id": f"{lane}-{len(payload['events'])}",
            "lane": lane,
            "event_type": event_type,
            "t": _iso(row.get('timestamp')),
            "t_end": _iso(row.get('end_timestamp')) if 'end_timestamp' in timeline.columns else None,
            "amount": abs(amount) if amount is not None else None,
            "direction": direction,
            "counterparty": counterparty,
            "location": location,
            "source_file": str(row.get('source_file', '') or ''),
            "row_ref": row_ref,
            "label": label,
            "cited": bool(row_ref and row_ref in flagged_refs),
        })

    for lane_entry in payload["lanes"]:
        lane_entry["count"] = lane_counts.get(lane_entry["key"], 0)

    stamps = [e["t"] for e in payload["events"] if e["t"]]
    if stamps:
        payload["start"] = min(stamps)
        payload["end"] = max(stamps)

    # ---- Correlation windows (the TCS overlay) ----
    if enriched_txns is not None and len(enriched_txns) > 0 and 'entity_id' in enriched_txns.columns:
        mine = enriched_txns[enriched_txns['entity_id'] == entity_id]
        tolerance = pd.Timedelta(minutes=window_minutes)
        for _, txn in mine.iterrows():
            has_call = bool(txn.get('has_call_correlation', False))
            has_session = bool(txn.get('has_session_correlation', False))
            if not (has_call or has_session):
                continue
            centre = txn.get('timestamp')
            if centre is None or pd.isna(centre):
                continue
            centre = pd.Timestamp(centre)

            if has_call and has_session:
                kind, note = "tcs1", "Call AND IP session both inside the window — TCS-1"
            elif has_call:
                kind, note = "call", "Call inside the window"
            else:
                kind, note = "session", "IP session inside the window"

            amount = _safe_float(txn.get('amount'))
            payload["correlations"].append({
                "kind": kind,
                "note": note,
                "start": _iso(centre - tolerance),
                "end": _iso(centre + tolerance),
                "centre": _iso(centre),
                "amount": abs(amount) if amount is not None else None,
                "row_ref": _clean_row_ref(txn.get('raw_row_ref')),
                "call_row_ref": _clean_row_ref(txn.get('call_row_ref')),
                "session_row_ref": _clean_row_ref(txn.get('session_row_ref')),
            })

    return payload


if __name__ == "__main__":
    print("Temporal join module - run via pipeline.py")
