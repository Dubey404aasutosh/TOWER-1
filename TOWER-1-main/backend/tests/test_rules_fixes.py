"""
Unit Tests for Rule Engine Bug Fixes (IDR-1 and LOC-1)
=====================================================
Tests:
- IDR-1 Test A: Constant IMEI + Constant IMSI across events -> Must NOT fire IDR-1
- IDR-1 Test B: Consecutive change in IMEI and IMSI (both) on same MSISDN -> MUST fire IDR-1 with HIGH severity
- IDR-1 Test C: Single identifier change (IMEI only) with nearby financial transaction -> MUST fire IDR-1 with MEDIUM severity
- IDR-1 Test D: Single identifier change with no nearby transaction -> MUST fire IDR-1 with LOW severity
- LOC-1 Test A: Same city / 3-5 km apart, 15-60 min gap -> Must NOT fire LOC-1
- LOC-1 Test B: ~230 km apart (Surat to Mumbai), <60 min gap -> MUST fire LOC-1 with km/h speed
- LOC-1 Test C: ~225 km apart, 100+ min gap -> Must NOT fire LOC-1
"""
import sys
import unittest
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

# Add backend to path
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from correlation.rules import check_idr1, check_loc1, haversine_distance_km, load_tower_master


class TestRuleFixes(unittest.TestCase):

    def setUp(self):
        self.tower_map = load_tower_master()

    # -------------------------------------------------------------
    # BUG 1 (IDR-1) TESTS
    # -------------------------------------------------------------
    def test_idr1_constant_identifiers_must_not_fire(self):
        """Test A: Entity with constant IMEI and IMSI across 20 events over 2 weeks must NOT fire IDR-1."""
        base_time = datetime(2025, 8, 1, 10, 0, 0)
        events = []
        for i in range(20):
            events.append({
                "entity_id": "TEST_ENT_001",
                "entity_ref": "9800000001",
                "timestamp": base_time + timedelta(hours=i * 12),
                "event_type": "call",
                "imei": "356000111222333",
                "imsi": "404101234567890",
                "raw_row_ref": i,
            })
        df = pd.DataFrame(events)

        fired, explanation, evidence, severity = check_idr1("TEST_ENT_001", {"phones": ["9800000001"]}, df)
        self.assertFalse(fired, "IDR-1 should NOT fire on constant IMEI and IMSI.")
        self.assertEqual(explanation, "")
        self.assertEqual(severity, "LOW")

    def test_idr1_consecutive_change_must_fire(self):
        """Test B: Entity where both IMEI and IMSI change between consecutive events MUST fire IDR-1 with HIGH severity."""
        base_time = datetime(2025, 8, 10, 10, 0, 0)
        events = [
            {
                "entity_id": "TEST_ENT_002",
                "entity_ref": "9800000002",
                "timestamp": base_time,
                "event_type": "call",
                "imei": "356000111222333",
                "imsi": "404101234567890",
                "raw_row_ref": 101,
            },
            {
                "entity_id": "TEST_ENT_002",
                "entity_ref": "9800000002",
                "timestamp": base_time + timedelta(minutes=10),
                "event_type": "call",
                "imei": "359999888777666",  # IMEI changed!
                "imsi": "404101239999999",  # IMSI changed!
                "raw_row_ref": 102,
            }
        ]
        df = pd.DataFrame(events)

        fired, explanation, evidence, severity = check_idr1("TEST_ENT_002", {"phones": ["9800000002"]}, df)
        self.assertTrue(fired, "IDR-1 MUST fire when IMEI/IMSI changes between consecutive events.")
        self.assertEqual(severity, "HIGH", "Both IMEI and IMSI changing together MUST produce HIGH severity.")
        self.assertIn("IDR-1", explanation)
        self.assertIn("356000111222333", explanation)
        self.assertIn("359999888777666", explanation)

    def test_idr1_single_identifier_change_with_nearby_txn_must_fire_medium(self):
        """Test C: Single identifier change (IMEI only) with a financial transaction nearby MUST fire IDR-1 with MEDIUM severity."""
        base_time = datetime(2025, 8, 10, 10, 0, 0)
        events = [
            {
                "entity_id": "TEST_ENT_003",
                "entity_ref": "9800000003",
                "timestamp": base_time,
                "event_type": "call",
                "imei": "356000111222333",
                "imsi": "404101234567890",
                "raw_row_ref": 103,
            },
            {
                "entity_id": "TEST_ENT_003",
                "entity_ref": "9800000003",
                "timestamp": base_time + timedelta(minutes=10),
                "event_type": "call",
                "imei": "359999888777666",  # IMEI changed!
                "imsi": "404101234567890",  # IMSI constant
                "raw_row_ref": 104,
            },
            {
                "entity_id": "TEST_ENT_003",
                "entity_ref": "9800000003",
                "timestamp": base_time + timedelta(minutes=15),  # 5 min after IMEI change
                "event_type": "transaction",
                "imei": "359999888777666",
                "imsi": "404101234567890",
                "raw_row_ref": 105,
            }
        ]
        df = pd.DataFrame(events)

        fired, explanation, evidence, severity = check_idr1("TEST_ENT_003", {"phones": ["9800000003"]}, df)
        self.assertTrue(fired, "IDR-1 MUST fire on single identifier change.")
        self.assertEqual(severity, "MEDIUM", "Single identifier change near a financial transaction MUST produce MEDIUM severity.")
        self.assertIn("IDR-1", explanation)

    def test_idr1_single_identifier_change_without_nearby_txn_must_fire_low(self):
        """Test D: Single identifier change (IMEI only) with NO nearby financial transaction MUST fire IDR-1 with LOW severity."""
        base_time = datetime(2025, 8, 10, 10, 0, 0)
        events = [
            {
                "entity_id": "TEST_ENT_004",
                "entity_ref": "9800000004",
                "timestamp": base_time,
                "event_type": "call",
                "imei": "356000111222333",
                "imsi": "404101234567890",
                "raw_row_ref": 106,
            },
            {
                "entity_id": "TEST_ENT_004",
                "entity_ref": "9800000004",
                "timestamp": base_time + timedelta(minutes=10),
                "event_type": "call",
                "imei": "359999888777666",  # IMEI changed!
                "imsi": "404101234567890",  # IMSI constant
                "raw_row_ref": 107,
            }
        ]
        df = pd.DataFrame(events)

        fired, explanation, evidence, severity = check_idr1("TEST_ENT_004", {"phones": ["9800000004"]}, df)
        self.assertTrue(fired, "IDR-1 MUST fire on single identifier change even without financial transactions.")
        self.assertEqual(severity, "LOW", "Single identifier change without nearby financial transaction MUST produce LOW severity.")
        self.assertIn("IDR-1", explanation)

    # -------------------------------------------------------------
    # BUG 2 (LOC-1) TESTS
    # -------------------------------------------------------------
    def test_loc1_same_city_towers_must_not_fire(self):
        """Test A: Towers 3-5 km apart, 15-60 min gap -> Must NOT fire LOC-1."""
        base_time = datetime(2025, 8, 1, 12, 0, 0)
        events = [
            {
                "entity_id": "TEST_ENT_LOC_A",
                "timestamp": base_time,
                "event_type": "call",
                "location": "SRT-T01",  # Surat Athwalines
                "raw_row_ref": 201,
            },
            {
                "entity_id": "TEST_ENT_LOC_A",
                "timestamp": base_time + timedelta(minutes=20),  # 20 min gap (~3-4 km)
                "event_type": "call",
                "location": "SRT-T02",  # Surat City Light
                "raw_row_ref": 202,
            }
        ]
        df = pd.DataFrame(events)

        fired, explanation, evidence = check_loc1("TEST_ENT_LOC_A", df, tower_map=self.tower_map)
        self.assertFalse(fired, "LOC-1 must NOT fire on same-city towers 3-5 km apart with 20 min gap.")

    def test_loc1_impossible_travel_must_fire(self):
        """Test B: Towers ~230 km apart (Surat to Mumbai), <60 min gap -> MUST fire LOC-1 with km/h speed."""
        base_time = datetime(2025, 8, 10, 10, 0, 0)
        events = [
            {
                "entity_id": "TEST_ENT_LOC_B",
                "timestamp": base_time,
                "event_type": "call",
                "location": "SRT-T01",  # Surat
                "raw_row_ref": 301,
            },
            {
                "entity_id": "TEST_ENT_LOC_B",
                "timestamp": base_time + timedelta(minutes=15),  # 15 min gap for ~230 km!
                "event_type": "ip_session",
                "_public_ip": "103.21.58.100",  # Mumbai IP
                "location": "BOM-T01",  # Mumbai
                "raw_row_ref": 302,
            }
        ]
        df = pd.DataFrame(events)

        fired, explanation, evidence = check_loc1("TEST_ENT_LOC_B", df, tower_map=self.tower_map)
        self.assertTrue(fired, "LOC-1 MUST fire when traveling ~230 km in 15 minutes.")
        self.assertIn("km/h", explanation)
        self.assertIn("km apart", explanation)

    def test_loc1_plausible_travel_must_not_fire(self):
        """Test C: Towers ~225 km apart, 100+ min gap -> Must NOT fire LOC-1."""
        base_time = datetime(2025, 8, 10, 10, 0, 0)
        events = [
            {
                "entity_id": "TEST_ENT_LOC_C",
                "timestamp": base_time,
                "event_type": "call",
                "location": "SRT-T01",  # Surat
                "raw_row_ref": 401,
            },
            {
                "entity_id": "TEST_ENT_LOC_C",
                "timestamp": base_time + timedelta(minutes=120),  # 120 min gap (2 hrs for ~230 km = ~115 km/h)
                "event_type": "call",
                "location": "BOM-T01",  # Mumbai
                "raw_row_ref": 402,
            }
        ]
        df = pd.DataFrame(events)

        fired, explanation, evidence = check_loc1("TEST_ENT_LOC_C", df, tower_map=self.tower_map)
        self.assertFalse(fired, "LOC-1 must NOT fire for plausible travel (~230 km in 120 mins = ~115 km/h).")


if __name__ == "__main__":
    unittest.main()
