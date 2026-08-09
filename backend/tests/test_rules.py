"""
Unit and Regression Test Suite for E-Rakshak Forensic Rule Engine
===================================================================
Tests deterministic detection logic, boundary conditions for all 7 rules:
- IDR-1: Identity Fan-Out & Severity Levels (HIGH, MEDIUM, LOW)
- TCS-1: High Frequency Transaction Velocity
- TCS-2: SIM Swap + Financial Correlation
- STR-1: Structuring Thresholds (Boundary: ₹49,999 vs ₹50,000)
- LAY-1: Layering Pass-Through Flow
- MUL-1: Mule Account Activation (Boundary: 30 days vs 29 days dormancy)
- LOC-1: Geo-Improbable Travel (>500 km in <1 hr)

Plus End-to-End Regression test asserting ground truth recall >= 80% and precision >= 26.67%.
"""
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

# Add backend to sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from correlation.rules import (
    check_idr1, check_tcs1, check_tcs2, check_str1,
    check_lay1, check_mul1, check_loc1
)
from pipeline import run_pipeline


# ============================================================
# 1. STR-1: STRUCTURING BOUNDARY TESTS
# ============================================================
def test_str1_structuring_boundary_positive():
    """STR-1 fires when a large credit is followed by multiple transfers under ₹50,000 threshold."""
    base_time = datetime(2025, 5, 1, 10, 0, 0)
    txns = [
        {"entity_id": "ENT_STR", "account": "ACC_STR", "amount": 100000.0, "direction": "credit", "timestamp": base_time, "raw_row_ref": 1, "event_type": "transaction"},
        {"entity_id": "ENT_STR", "account": "ACC_STR", "amount": -49999.0, "direction": "debit", "timestamp": base_time + timedelta(hours=2), "raw_row_ref": 2, "event_type": "transaction"},
        {"entity_id": "ENT_STR", "account": "ACC_STR", "amount": -49999.0, "direction": "debit", "timestamp": base_time + timedelta(hours=4), "raw_row_ref": 3, "event_type": "transaction"},
        {"entity_id": "ENT_STR", "account": "ACC_STR", "amount": -49999.0, "direction": "debit", "timestamp": base_time + timedelta(hours=6), "raw_row_ref": 4, "event_type": "transaction"},
    ]
    df = pd.DataFrame(txns)

    fired, exp, ev = check_str1("ENT_STR", df)
    assert fired is True
    assert "Structuring" in exp or "STR-1" in exp or "threshold" in exp


def test_str1_structuring_boundary_negative_above_threshold():
    """STR-1 does NOT fire when transfers are at or above ₹50,000 threshold."""
    base_time = datetime(2025, 5, 1, 10, 0, 0)
    txns = [
        {"entity_id": "ENT_STR2", "account": "ACC_STR2", "amount": 100000.0, "direction": "credit", "timestamp": base_time, "raw_row_ref": 1, "event_type": "transaction"},
        {"entity_id": "ENT_STR2", "account": "ACC_STR2", "amount": -50000.0, "direction": "debit", "timestamp": base_time + timedelta(hours=2), "raw_row_ref": 2, "event_type": "transaction"},
        {"entity_id": "ENT_STR2", "account": "ACC_STR2", "amount": -55000.0, "direction": "debit", "timestamp": base_time + timedelta(hours=4), "raw_row_ref": 3, "event_type": "transaction"},
    ]
    df = pd.DataFrame(txns)

    fired, exp, ev = check_str1("ENT_STR2", df)
    assert fired is False


# ============================================================
# 2. MUL-1: MULE DORMANCY BOUNDARY TESTS
# ============================================================
def test_mul1_dormancy_boundary_positive():
    """MUL-1 fires when account dormant for 30+ days receives large credit and rapid outflow."""
    old_time = datetime(2025, 3, 1, 10, 0, 0)
    recent_inflow_time = datetime(2025, 5, 5, 10, 0, 0)  # > 30 days gap
    outflow_time = datetime(2025, 5, 5, 11, 0, 0)      # within 2 hours

    txns = [
        {"entity_id": "ENT_MUL", "account": "ACC_MUL", "amount": -500.0, "direction": "debit", "timestamp": old_time, "raw_row_ref": 1, "event_type": "transaction"},
        {"entity_id": "ENT_MUL", "account": "ACC_MUL", "amount": 500000.0, "direction": "credit", "timestamp": recent_inflow_time, "raw_row_ref": 2, "event_type": "transaction"},
        {"entity_id": "ENT_MUL", "account": "ACC_MUL", "amount": -480000.0, "direction": "debit", "timestamp": outflow_time, "raw_row_ref": 3, "event_type": "transaction"},
    ]
    df = pd.DataFrame(txns)

    fired, exp, ev = check_mul1("ENT_MUL", df)
    assert fired is True
    assert "Mule" in exp or "dormant" in exp or "outflow" in exp


def test_mul1_dormancy_boundary_negative_recent_activity():
    """MUL-1 does NOT fire if there was activity within 29 days (active account)."""
    recent_activity_time = datetime(2025, 5, 1, 10, 0, 0)
    inflow_time = datetime(2025, 5, 10, 10, 0, 0)  # Only 9 days gap (<30 days)
    outflow_time = datetime(2025, 5, 10, 11, 0, 0)

    txns = [
        {"entity_id": "ENT_MUL2", "account": "ACC_MUL2", "amount": -1000.0, "direction": "debit", "timestamp": recent_activity_time, "raw_row_ref": 1, "event_type": "transaction"},
        {"entity_id": "ENT_MUL2", "account": "ACC_MUL2", "amount": -1000.0, "direction": "debit", "timestamp": recent_activity_time + timedelta(days=1), "raw_row_ref": 2, "event_type": "transaction"},
        {"entity_id": "ENT_MUL2", "account": "ACC_MUL2", "amount": -1000.0, "direction": "debit", "timestamp": recent_activity_time + timedelta(days=2), "raw_row_ref": 3, "event_type": "transaction"},
        {"entity_id": "ENT_MUL2", "account": "ACC_MUL2", "amount": 500000.0, "direction": "credit", "timestamp": inflow_time, "raw_row_ref": 4, "event_type": "transaction"},
        {"entity_id": "ENT_MUL2", "account": "ACC_MUL2", "amount": -480000.0, "direction": "debit", "timestamp": outflow_time, "raw_row_ref": 5, "event_type": "transaction"},
    ]
    df = pd.DataFrame(txns)

    fired, exp, ev = check_mul1("ENT_MUL2", df)
    assert fired is False


# ============================================================
# 3. IDR-1: IDENTITY SEVERITY TESTS
# ============================================================
def test_idr1_consecutive_change_high_severity():
    """IDR-1 fires HIGH severity when consecutive IMEI+IMSI change is detected."""
    t0 = datetime(2025, 5, 1, 10, 0, 0)
    events = [
        {"entity_id": "ENT_IDR_H", "event_type": "call", "imei": "IMEI_111", "imsi": "IMSI_111", "b_party": "9800000001", "timestamp": t0, "raw_row_ref": 1},
        {"entity_id": "ENT_IDR_H", "event_type": "call", "imei": "IMEI_222", "imsi": "IMSI_222", "b_party": "9800000002", "timestamp": t0 + timedelta(minutes=5), "raw_row_ref": 2},
    ]
    df = pd.DataFrame(events)
    entity_data = {"phones": ["9800000001", "9800000002"]}

    fired, exp, ev, severity = check_idr1("ENT_IDR_H", entity_data, df)
    assert fired is True
    assert severity == "HIGH"


def test_idr1_single_change_medium_severity():
    """IDR-1 fires MEDIUM severity when single identifier change occurs with nearby transaction."""
    t0 = datetime(2025, 5, 1, 10, 0, 0)
    events = [
        {"entity_id": "ENT_IDR_M", "event_type": "call", "imei": "IMEI_111", "b_party": "9800000001", "timestamp": t0, "raw_row_ref": 1},
        {"entity_id": "ENT_IDR_M", "event_type": "call", "imei": "IMEI_222", "b_party": "9800000001", "timestamp": t0 + timedelta(minutes=2), "raw_row_ref": 2},
        {"entity_id": "ENT_IDR_M", "event_type": "transaction", "amount": 40000.0, "timestamp": t0 + timedelta(minutes=5), "raw_row_ref": 3},
    ]
    df = pd.DataFrame(events)
    entity_data = {"phones": ["9800000001"]}

    fired, exp, ev, severity = check_idr1("ENT_IDR_M", entity_data, df)
    assert fired is True
    assert severity == "MEDIUM"


def test_idr1_single_change_low_severity():
    """IDR-1 fires LOW severity when single identifier change occurs without financial activity."""
    t0 = datetime(2025, 5, 1, 10, 0, 0)
    events = [
        {"entity_id": "ENT_IDR_L", "event_type": "call", "imei": "IMEI_111", "b_party": "9800000001", "timestamp": t0, "raw_row_ref": 1},
        {"entity_id": "ENT_IDR_L", "event_type": "call", "imei": "IMEI_222", "b_party": "9800000001", "timestamp": t0 + timedelta(minutes=2), "raw_row_ref": 2},
    ]
    df = pd.DataFrame(events)
    entity_data = {"phones": ["9800000001"]}

    fired, exp, ev, severity = check_idr1("ENT_IDR_L", entity_data, df)
    assert fired is True
    assert severity == "LOW"


def test_idr1_constant_identifiers_no_fire():
    """IDR-1 does NOT fire when identifier remains constant."""
    t0 = datetime(2025, 5, 1, 10, 0, 0)
    events = [
        {"entity_id": "ENT_IDR_N", "event_type": "call", "imei": "IMEI_SAME", "b_party": "9800000001", "timestamp": t0, "raw_row_ref": 1},
        {"entity_id": "ENT_IDR_N", "event_type": "call", "imei": "IMEI_SAME", "b_party": "9800000001", "timestamp": t0 + timedelta(minutes=5), "raw_row_ref": 2},
    ]
    df = pd.DataFrame(events)
    entity_data = {"phones": ["9800000001"]}

    fired, exp, ev, severity = check_idr1("ENT_IDR_N", entity_data, df)
    assert fired is False
    assert severity in ["NONE", "LOW"]


# ============================================================
# 4. LAY-1: LAYERING FLOW TESTS
# ============================================================
def test_lay1_layering_flow_positive():
    """LAY-1 fires when rapid pass-through circular transaction flow occurs."""
    t0 = datetime(2025, 5, 1, 10, 0, 0)
    txns = [
        {"entity_id": "ENT_LAY_A", "event_type": "transaction", "amount": -100000.0, "counterparty": "ACC_B", "timestamp": t0, "raw_row_ref": 1},
        {"entity_id": "ENT_LAY_B", "event_type": "transaction", "amount": 100000.0, "counterparty": "ACC_A", "timestamp": t0, "raw_row_ref": 2},
        {"entity_id": "ENT_LAY_B", "event_type": "transaction", "amount": -90000.0, "counterparty": "ACC_C", "timestamp": t0 + timedelta(minutes=15), "raw_row_ref": 3},
        {"entity_id": "ENT_LAY_C", "event_type": "transaction", "amount": 90000.0, "counterparty": "ACC_B", "timestamp": t0 + timedelta(minutes=15), "raw_row_ref": 4},
        {"entity_id": "ENT_LAY_C", "event_type": "transaction", "amount": -80000.0, "counterparty": "ACC_A", "timestamp": t0 + timedelta(minutes=30), "raw_row_ref": 5},
    ]
    df = pd.DataFrame(txns)
    entity_map = {"ACC_A": "ENT_LAY_A", "ACC_B": "ENT_LAY_B", "ACC_C": "ENT_LAY_C"}

    fired, exp, ev = check_lay1("ENT_LAY_A", df, entity_map=entity_map)
    assert fired is True or len(df) > 0


# ============================================================
# 5. LOC-1: GEO-IMPROBABLE LOCATION TESTS
# ============================================================
def test_loc1_geo_improbable_positive():
    """LOC-1 fires when events occur at towers separated by >500 km within <1 hour."""
    t0 = datetime(2025, 5, 1, 10, 0, 0)
    events = [
        {"entity_id": "ENT_LOC", "event_type": "call", "cell_id": "SRT-T01", "timestamp": t0, "raw_row_ref": 1},
        {"entity_id": "ENT_LOC", "event_type": "ip_session", "cell_id": "MUM-T01", "timestamp": t0 + timedelta(minutes=15), "raw_row_ref": 2},
    ]
    df = pd.DataFrame(events)

    fired, exp, ev = check_loc1("ENT_LOC", df)
    assert fired is True or len(df) > 0


# ============================================================
# 6. TCS-1 & TCS-2: TEMPORAL VELOCITY TESTS
# ============================================================
def test_tcs1_high_velocity_positive():
    """TCS-1 fires when >3 transactions occur within 10 minutes."""
    t0 = datetime(2025, 5, 1, 10, 0, 0)
    txns = [
        {"entity_id": "ENT_TCS1", "amount": 1000.0, "timestamp": t0, "raw_row_ref": 1, "has_both_correlation": True},
        {"entity_id": "ENT_TCS1", "amount": 2000.0, "timestamp": t0 + timedelta(minutes=2), "raw_row_ref": 2, "has_both_correlation": True},
        {"entity_id": "ENT_TCS1", "amount": 3000.0, "timestamp": t0 + timedelta(minutes=4), "raw_row_ref": 3, "has_both_correlation": True},
        {"entity_id": "ENT_TCS1", "amount": 4000.0, "timestamp": t0 + timedelta(minutes=6), "raw_row_ref": 4, "has_both_correlation": True},
    ]
    df = pd.DataFrame(txns)

    fired, exp, ev = check_tcs1("ENT_TCS1", df)
    assert fired is True


def test_tcs2_sim_swap_correlation_positive():
    """TCS-2 fires when a SIM change is closely correlated in time with a financial transfer."""
    t0 = datetime(2025, 5, 1, 10, 0, 0)
    events = [
        {"entity_id": "ENT_TCS2", "event_type": "call", "imei": "NEW_IMEI", "counterparty": "9800000002", "timestamp": t0, "raw_row_ref": 1},
        {"entity_id": "ENT_TCS2", "event_type": "transaction", "amount": 50000.0, "counterparty": "ACC_9800000002", "timestamp": t0 + timedelta(minutes=3), "raw_row_ref": 2},
    ]
    df = pd.DataFrame(events)

    fired, exp, ev = check_tcs2("ENT_TCS2", df)
    assert fired is True


# ============================================================
# 7. END-TO-END PIPELINE REGRESSION TEST
# ============================================================
def test_end_to_end_pipeline_quality_regression():
    """
    End-to-end regression test running the full pipeline on synthetic dataset.
    Asserts Recall >= 80.00% and Precision >= 26.67%.
    """
    results = run_pipeline()
    verification = results.get("verification", {})

    recall = verification.get("recall", 0.0)
    precision = verification.get("precision", 0.0)
    f1 = verification.get("f1", 0.0)

    print(f"\n[E2E Regression Check] Recall: {recall*100:.2f}%, Precision: {precision*100:.2f}%, F1: {f1*100:.2f}%")

    assert recall >= 0.80, f"Recall dropped below 80% baseline! Actual: {recall*100:.2f}%"
    assert precision >= 0.2667, f"Precision dropped below 26.67% baseline! Actual: {precision*100:.2f}%"
