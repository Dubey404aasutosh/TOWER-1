"""
Compound Risk Scoring Engine
==============================
GATED decision tree (NOT additive scoring):
- CRITICAL: (MUL-1 AND (TCS-1 or TCS-2)) OR (LAY-1 AND IDR-1)
- HIGH: STR-1 or MUL-1 or LAY-1 fires alone
- MEDIUM: only TCS-1/TCS-2 fires with no money-pattern rule
- LOW: otherwise

Plus IsolationForest as a SEPARATE ML anomaly flag.
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest


RISK_TIERS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
TIER_COLORS = {
    "CRITICAL": "#dc3545",
    "HIGH": "#e67e22",
    "MEDIUM": "#f39c12",
    "LOW": "#27ae60",
}


def compute_risk_tier(rules_fired, rule_severities=None):
    """
    Gated decision tree for risk tier assignment:
    - CRITICAL: (MUL-1 AND (TCS-1 or TCS-2)) OR (LAY-1 AND IDR-1) OR (IDR-1 at HIGH severity AND num_rules >= 2)
    - HIGH: Single money-pattern, velocity, or major rule (STR-1, MUL-1, LAY-1, LOC-1),
            or IDR-1 at HIGH severity alone, or IDR-1 + TCS
    - MEDIUM: Single temporal correlation rule (TCS-1, TCS-2) or IDR-1 at MEDIUM severity alone
    - LOW: No rules fired, or lone LOW-severity IDR-1 (routine SIM upgrade with no financial activity)
    """
    if rule_severities is None:
        rule_severities = {}

    num_rules = len(rules_fired)
    has_mul1 = "MUL-1" in rules_fired
    has_tcs1 = "TCS-1" in rules_fired
    has_tcs2 = "TCS-2" in rules_fired
    has_lay1 = "LAY-1" in rules_fired
    has_idr1 = "IDR-1" in rules_fired
    has_str1 = "STR-1" in rules_fired
    has_loc1 = "LOC-1" in rules_fired

    idr1_severity = rule_severities.get("IDR-1", "LOW") if has_idr1 else "LOW"
    has_tcs = has_tcs1 or has_tcs2

    # CRITICAL: Requires corroboration (MUL-1 + TCS, LAY-1 + IDR-1 or TCS, or HIGH IDR-1 + other rule)
    is_critical = (
        (has_mul1 and has_tcs) or
        (has_lay1 and (has_idr1 or has_tcs)) or
        (has_idr1 and idr1_severity == "HIGH" and num_rules >= 2)
    )
    if is_critical:
        return "CRITICAL"

    # HIGH: Single major typology or velocity rule, or HIGH IDR-1 alone
    is_high = (
        has_mul1 or has_lay1 or has_str1 or has_loc1 or
        (has_idr1 and idr1_severity == "HIGH") or
        (has_idr1 and has_tcs)
    )
    if is_high:
        return "HIGH"

    # MEDIUM: Single temporal correlation rule or MEDIUM IDR-1 alone
    is_medium = (
        has_tcs or
        (has_idr1 and idr1_severity == "MEDIUM")
    )
    if is_medium:
        return "MEDIUM"

    # LOW: No rules fired, or lone LOW-severity IDR-1
    return "LOW"


def compute_ml_anomaly(all_events_df, entities):
    """
    Run IsolationForest on per-entity feature vectors as a SEPARATE anomaly flag.
    Features: txn_velocity, avg_balance_hold_time, in_out_ratio,
              unique_counterparty_count, call_session_frequency.

    Returns dict: {entity_id: bool} — True if flagged as anomaly.
    """
    features = []
    entity_ids = []

    for entity_id in entities.keys():
        entity_events = all_events_df[all_events_df['entity_id'] == entity_id]

        if entity_events.empty:
            continue

        txns = entity_events[entity_events['event_type'] == 'transaction']
        calls = entity_events[entity_events['event_type'].isin(['call', 'sms'])]
        sessions = entity_events[entity_events['event_type'] == 'ip_session']

        # Feature 1: Transaction velocity (txns per day)
        if not txns.empty and len(txns) > 1:
            timestamps = pd.to_datetime(txns['timestamp'])
            time_span = (timestamps.max() - timestamps.min()).total_seconds() / 86400
            txn_velocity = len(txns) / max(time_span, 1)
        else:
            txn_velocity = len(txns)

        # Feature 2: Average balance hold time (proxy: time between consecutive txns)
        if len(txns) > 1:
            timestamps = pd.to_datetime(txns['timestamp']).sort_values()
            gaps = timestamps.diff().dropna().dt.total_seconds() / 3600  # hours
            avg_hold_time = gaps.mean()
        else:
            avg_hold_time = 0

        # Feature 3: In/out amount ratio
        if not txns.empty:
            amounts = txns['amount'].astype(float)
            total_in = amounts[amounts > 0].sum()
            total_out = amounts[amounts < 0].abs().sum()
            in_out_ratio = total_in / max(total_out, 1)
        else:
            in_out_ratio = 1

        # Feature 4: Unique counterparty count
        if not txns.empty:
            unique_cp = txns['counterparty'].dropna().nunique()
        else:
            unique_cp = 0

        # Feature 5: Call/session frequency (per day)
        total_comms = len(calls) + len(sessions)
        all_timestamps = pd.to_datetime(entity_events['timestamp'])
        if len(all_timestamps) > 1:
            total_days = (all_timestamps.max() - all_timestamps.min()).total_seconds() / 86400
            comms_frequency = total_comms / max(total_days, 1)
        else:
            comms_frequency = total_comms

        features.append([txn_velocity, avg_hold_time, in_out_ratio, unique_cp, comms_frequency])
        entity_ids.append(entity_id)

    if len(features) < 5:
        return {eid: False for eid in entities.keys()}

    X = np.array(features)

    # Run IsolationForest
    clf = IsolationForest(
        contamination=0.1,  # Expect ~10% anomalies
        random_state=42,
        n_estimators=100,
    )
    predictions = clf.fit_predict(X)

    ml_flags = {}
    for eid in entities.keys():
        ml_flags[eid] = False

    for eid, pred in zip(entity_ids, predictions):
        ml_flags[eid] = (pred == -1)  # -1 = anomaly in IsolationForest

    return ml_flags


def run_risk_engine(rule_results, all_events_df, entities):
    """
    Full risk scoring pipeline:
    1. Compute deterministic risk tier from named rules
    2. Run IsolationForest ML anomaly detection
    3. Return combined results with both signals kept separate

    Returns:
        dict: {entity_id: {risk_tier, rules_fired, ml_anomaly, explanations, evidence}}
    """
    print("\n[Risk Engine] Computing gated risk tiers...")

    # Step 1: Deterministic risk tiers
    scored = {}
    for entity_id, rule_data in rule_results.items():
        tier = compute_risk_tier(rule_data["rules_fired"], rule_data.get("rule_severities"))
        scored[entity_id] = {
            "risk_tier": tier,
            "rules_fired": rule_data["rules_fired"],
            "explanations": rule_data["explanations"],
            "evidence": rule_data["evidence"],
            "ml_anomaly": False,
        }

    # Step 2: ML anomaly detection
    print("[Risk Engine] Running IsolationForest ML anomaly detection...")
    ml_flags = compute_ml_anomaly(all_events_df, entities)

    for entity_id, is_anomaly in ml_flags.items():
        if entity_id in scored:
            scored[entity_id]["ml_anomaly"] = is_anomaly
        else:
            scored[entity_id] = {
                "risk_tier": "LOW",
                "rules_fired": [],
                "explanations": {},
                "evidence": {},
                "ml_anomaly": is_anomaly,
            }

    # Summary
    tier_counts = {}
    for s in scored.values():
        tier = s["risk_tier"]
        tier_counts[tier] = tier_counts.get(tier, 0) + 1

    ml_flagged = sum(1 for s in scored.values() if s["ml_anomaly"])

    print(f"  Risk tier distribution:")
    for tier in RISK_TIERS:
        print(f"    {tier}: {tier_counts.get(tier, 0)}")
    print(f"  ML anomaly flags: {ml_flagged}")

    return scored
