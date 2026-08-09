"""
Regression Tests for Two-Stage Entity Resolution Engine
==========================================================
Verifies that entity resolution strictly anchors entities to verified KYC ownership
and does NOT merge distinct people based on temporal or behavioral interactions
(transfers, calls, IP sessions).
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

from resolution.entity_resolver import run_entity_resolution, build_identity_graph, resolve_entities, validate_and_sanitize_entities
from graph.network_builder import build_network_graph


class TestEntityResolutionRegression(unittest.TestCase):

    def setUp(self):
        self.base_time = datetime(2025, 5, 10, 10, 0, 0)

    def test_regression_scenarios(self):
        # Identifiers
        suspect_phone = "9900000001"
        suspect_acct = "ACC_SUSPECT_01"
        suspect_imei = "350000000000001"
        suspect_ip = "103.25.1.1"

        cp_b_phone = "9900000002"
        cp_c_phone = "9900000003"
        cp_d_phone = "9900000004"

        family_phone = "9900000005"
        family_acct = "ACC_FAMILY_05"

        # 1. Synthetic KYC map confirming Suspect (phone A, account A, IMEI A, IP A) and Family (phone E, account E)
        kyc_map = {
            suspect_phone: {
                "name": "Suspect A",
                "phones": [suspect_phone],
                "accounts": [suspect_acct],
                "vpas": ["suspecta@ybl"],
                "imeis": [suspect_imei],
                "ips": [suspect_ip],
            },
            family_phone: {
                "name": "Family Member E",
                "phones": [family_phone],
                "accounts": [family_acct],
                "vpas": ["familye@paytm"],
                "imeis": ["350000000000005"],
                "ips": ["103.25.1.5"],
            }
        }

        # 2. Bank events: Suspect transfers funds to B, C, D and family member E
        bank_events = [
            {
                "entity_ref": suspect_acct,
                "event_type": "transaction",
                "timestamp": self.base_time + timedelta(minutes=10),
                "amount": -5000.0,
                "counterparty": cp_b_phone,
                "direction": "debit",
                "source_file": "test_bank.csv",
                "raw_row_ref": 1,
            },
            {
                "entity_ref": suspect_acct,
                "event_type": "transaction",
                "timestamp": self.base_time + timedelta(minutes=20),
                "amount": -7000.0,
                "counterparty": cp_c_phone,
                "direction": "debit",
                "source_file": "test_bank.csv",
                "raw_row_ref": 2,
            },
            {
                "entity_ref": suspect_acct,
                "event_type": "transaction",
                "timestamp": self.base_time + timedelta(minutes=30),
                "amount": -4000.0,
                "counterparty": cp_d_phone,
                "direction": "debit",
                "source_file": "test_bank.csv",
                "raw_row_ref": 3,
            },
            {
                "entity_ref": suspect_acct,
                "event_type": "transaction",
                "timestamp": self.base_time + timedelta(minutes=45),
                "amount": -1000.0,
                "counterparty": family_acct,
                "direction": "debit",
                "source_file": "test_bank.csv",
                "raw_row_ref": 4,
            },
        ]

        # 3. CDR events: Suspect calls family member E 5 minutes before transfer
        cdr_events = [
            {
                "entity_ref": suspect_phone,
                "event_type": "call",
                "timestamp": self.base_time + timedelta(minutes=40),
                "end_timestamp": self.base_time + timedelta(minutes=42),
                "counterparty": family_phone,
                "imei": suspect_imei,
                "location": "SRT-T01",
                "source_file": "test_cdr.csv",
                "raw_row_ref": 1,
            }
        ]

        # 4. IPDR events: Suspect active session on IP A
        ipdr_events = [
            {
                "entity_ref": suspect_phone,
                "event_type": "ip_session",
                "timestamp": self.base_time + timedelta(minutes=5),
                "_public_ip": suspect_ip,
                "counterparty": "198.51.100.1",
                "location": "SRT-T01",
                "source_file": "test_ipdr.csv",
                "raw_row_ref": 1,
            }
        ]

        # --- RUN STAGE 1 RESOLUTION ---
        # Build identity graph using explicit KYC map
        G, id_types, kyc_names, _ = build_identity_graph(bank_events, cdr_events, ipdr_events, kyc_map=kyc_map)
        
        entity_map, entities = resolve_entities(G, id_types, kyc_names)
        entities, entity_map = validate_and_sanitize_entities(entities, entity_map, kyc_map)

        # Map entity_id for suspect and family member
        suspect_eid = entity_map.get(suspect_phone)
        family_eid = entity_map.get(family_phone)
        b_eid = entity_map.get(cp_b_phone)
        c_eid = entity_map.get(cp_c_phone)
        d_eid = entity_map.get(cp_d_phone)

        # --- VERIFICATION SCENARIO 3: Suspect's own identity is consolidated into ONE entity ---
        self.assertIsNotNone(suspect_eid, "Suspect must have a resolved entity_id")
        suspect_entity = entities[suspect_eid]
        self.assertIn(suspect_phone, suspect_entity["phones"])
        self.assertIn(suspect_acct, suspect_entity["accounts"])
        self.assertIn(suspect_imei, suspect_entity["imeis"])
        self.assertIn(suspect_ip, suspect_entity["ips"])
        print(f"\n[OK] Scenario 3 Passed: Suspect entity {suspect_eid} correctly consolidated phone A, account A, IMEI A, IP A into ONE entity.")

        # --- VERIFICATION SCENARIO 1: Counterparties B, C, D do NOT merge into suspect's entity ---
        self.assertNotEqual(suspect_eid, b_eid, "Counterparty B must NOT be merged into suspect entity")
        self.assertNotEqual(suspect_eid, c_eid, "Counterparty C must NOT be merged into suspect entity")
        self.assertNotEqual(suspect_eid, d_eid, "Counterparty D must NOT be merged into suspect entity")
        self.assertNotIn(cp_b_phone, suspect_entity["phones"])
        self.assertNotIn(cp_c_phone, suspect_entity["phones"])
        self.assertNotIn(cp_d_phone, suspect_entity["phones"])
        print(f"[OK] Scenario 1 Passed: Counterparties B ({b_eid}), C ({c_eid}), D ({d_eid}) remain distinct entities from suspect ({suspect_eid}).")

        # --- VERIFICATION SCENARIO 2: Suspect and Family Member remain TWO separate entities ---
        self.assertIsNotNone(family_eid, "Family member must have a resolved entity_id")
        self.assertNotEqual(suspect_eid, family_eid, "Suspect and Family member must NOT be merged despite call and transfer")
        self.assertNotIn(family_phone, suspect_entity["phones"])
        self.assertNotIn(family_acct, suspect_entity["accounts"])
        print(f"[OK] Scenario 2 Passed: Suspect ({suspect_eid}) and Family Member ({family_eid}) remain TWO separate entities.")

        # --- VERIFICATION STAGE 2: Network Graph relationship edges ---
        # Apply resolution to events
        from resolution.entity_resolver import apply_entity_resolution
        bank_events = apply_entity_resolution(bank_events, entity_map)
        cdr_events = apply_entity_resolution(cdr_events, entity_map)
        ipdr_events = apply_entity_resolution(ipdr_events, entity_map)
        all_events_df = pd.DataFrame(bank_events + cdr_events + ipdr_events)

        scored_entities = {
            suspect_eid: {"risk_tier": "HIGH", "rules_fired": ["TCS-2"]},
            family_eid: {"risk_tier": "LOW", "rules_fired": []},
        }

        netG = build_network_graph(all_events_df, scored_entities, entities)
        self.assertTrue(netG.has_edge(suspect_eid, family_eid), "Stage 2 relationship edge must exist between suspect and family member in network graph")
        print(f"[OK] Stage 2 Relationship Edge Passed: Edge exists between {suspect_eid} and {family_eid} in network graph.")


if __name__ == "__main__":
    unittest.main()
