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
        all_events: list of event dicts
        entity_id: optional filter for a specific entity

    Returns:
        DataFrame sorted by timestamp with all event types
    """
    df = pd.DataFrame(all_events)
    if df.empty:
        return df

    df['timestamp'] = pd.to_datetime(df['timestamp'])

    if entity_id:
        df = df[df['entity_id'] == entity_id]

    return df.sort_values('timestamp').reset_index(drop=True)


if __name__ == "__main__":
    print("Temporal join module - run via pipeline.py")
