"""
E-Rakshak Synthetic Data Generator
===================================
Generates a ground-truth entity/event graph and exports it into 3 realistically
inconsistent bank statement formats, one CDR CSV, and one IPDR CSV.

Population: 40 normal entities + 5 guilty entities (one per fraud typology).
Target: ~2,000 total events across all entities.

Run: python data/generator/generate_all.py
"""
import os
import sys
import json
import random
import string
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from faker import Faker
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

fake = Faker('en_IN')
Faker.seed(42)
random.seed(42)

# --- Paths ---
BASE_DIR = Path(__file__).resolve().parent.parent  # data/
RAW_DIR = BASE_DIR / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)
GT_PATH = BASE_DIR / "generator" / "ground_truth.json"

# --- Constants ---
REPORTING_THRESHOLD = 50000  # INR 50,000
NUM_NORMAL = 40
NUM_GUILTY = 5  # One per typology: STR-1, LAY-1, MUL-1, IDR-1, LOC-1
BASE_DATE = datetime(2025, 5, 1)
END_DATE = datetime(2025, 6, 15)
DAYS_SPAN = (END_DATE - BASE_DATE).days

# Indian city cell tower IDs (Restricted to Surat only)
CITIES = {
    "Surat": ["SRT-T01", "SRT-T02", "SRT-T03", "SRT-T04", "SRT-T05", "SRT-T06", "SRT-T07", "SRT-T08", "SRT-T09", "SRT-T10"]
}
CITY_NAMES = list(CITIES.keys())

# IP ranges per city (Restricted to Surat only)
CITY_IP_PREFIXES = {
    "Surat": "103.25",
}

BANK_NAMES = ["SBI", "HDFC", "ICICI", "AXIS", "KOTAK", "PNB", "BOB", "CANARA"]
UPI_SUFFIXES = ["@oksbi", "@okhdfcbank", "@okaxis", "@okicici", "@ybl", "@paytm", "@gpay"]
IFSC_PREFIXES = ["SBIN", "HDFC", "ICIC", "UTIB", "KKBK", "PUNB", "BARB", "CNRB"]


def gen_phone():
    return f"9{random.choice(['8','7','6','5'])}{random.randint(10000000, 99999999)}"


def gen_imei():
    return ''.join([str(random.randint(0, 9)) for _ in range(15)])


def gen_account():
    return ''.join([str(random.randint(0, 9)) for _ in range(random.choice([10, 11, 12, 14]))])


def gen_ifsc():
    return f"{random.choice(IFSC_PREFIXES)}0{random.randint(100, 999)}{random.randint(10, 99)}"


def gen_vpa(name):
    clean = name.lower().replace(' ', '.').replace("'", "")
    suffix = random.choice(UPI_SUFFIXES)
    return f"{clean}{suffix}"


def gen_private_ip():
    return f"192.168.{random.randint(1, 254)}.{random.randint(1, 254)}"


def gen_public_ip(city=None):
    if city and city in CITY_IP_PREFIXES:
        prefix = CITY_IP_PREFIXES[city]
    else:
        prefix = f"103.{random.randint(20, 30)}"
    return f"{prefix}.{random.randint(1, 254)}.{random.randint(1, 254)}"


def gen_utr():
    return ''.join([str(random.randint(0, 9)) for _ in range(12)])


def random_datetime(start, end):
    delta = end - start
    seconds = random.randint(0, int(delta.total_seconds()))
    return start + timedelta(seconds=seconds)


def gen_cell_id(city):
    return random.choice(CITIES.get(city, CITIES["Surat"]))


# ============================================================
# ENTITY GENERATION
# ============================================================
class EntityProfile:
    def __init__(self, idx, name, is_guilty=False, typology=None):
        self.idx = idx
        self.entity_id = f"E{idx:03d}"
        self.name = name
        self.is_guilty = is_guilty
        self.typology = typology
        self.city = random.choice(CITY_NAMES)
        self.phones = [gen_phone()]
        self.imeis = [gen_imei()]
        self.accounts = [gen_account()]
        self.vpas = [gen_vpa(name)]
        self.ifsc = gen_ifsc()
        self.bank = random.choice(BANK_NAMES)
        # Normal salary range
        self.salary = random.randint(30000, 80000)
        self.contacts = []  # Filled after all entities created

    def raw_identifiers(self):
        return {
            "phones": self.phones,
            "accounts": self.accounts,
            "imeis": self.imeis,
            "vpas": self.vpas,
            "ips": [],  # Filled dynamically
        }


def create_entities(num_normal=NUM_NORMAL, num_guilty=NUM_GUILTY):
    entities = []
    names_used = set()

    total_count = num_normal + num_guilty
    for i in range(1, total_count + 1):
        name = fake.name()
        while name in names_used:
            name = fake.name()
        names_used.add(name)

        is_guilty = i > num_normal
        typology = None
        if i == num_normal + 1:
            typology = "STR-1"
        elif i == num_normal + 2:
            typology = "LAY-1"
        elif i == num_normal + 3:
            typology = "MUL-1"
        elif i == num_normal + 4:
            typology = "IDR-1"
        elif i == num_normal + 5:
            typology = "LOC-1"

        entities.append(EntityProfile(i, name, is_guilty, typology))

    # Identity fan-out entity (IDR-1): give it 3 phones, 2 extra accounts, 1 IMEI shared
    idr_entities = [e for e in entities if e.typology == "IDR-1"]
    if idr_entities:
        idr_entity = idr_entities[0]
        idr_entity.phones = [gen_phone() for _ in range(3)]
        idr_entity.accounts = [gen_account() for _ in range(3)]
        idr_entity.vpas = [gen_vpa(idr_entity.name) for _ in range(3)]
        # Single IMEI across all 3 phones (SIM swap signature)
        shared_imei = gen_imei()
        idr_entity.imeis = [shared_imei]

    # Assign 5-8 random contacts to each entity (from normal pool)
    normal_entities = [e for e in entities if not e.is_guilty]
    for e in entities:
        contact_pool = [x for x in normal_entities if x.idx != e.idx]
        if contact_pool:
            e.contacts = random.sample(contact_pool, min(random.randint(5, 8), len(contact_pool)))
        else:
            e.contacts = []

    return entities


# ============================================================
# EVENT GENERATION — NORMAL ENTITIES
# ============================================================
def gen_normal_transactions(entity, row_counter):
    """Generate realistic salaried behavior for a normal entity."""
    txns = []
    acct = entity.accounts[0]
    vpa = entity.vpas[0]
    balance = random.uniform(5000, 50000)

    # Monthly salary credit (around 1st or last day)
    for month_offset in [0, 1]:
        salary_date = BASE_DATE.replace(day=random.choice([1, 28, 29, 30])) + timedelta(days=30 * month_offset)
        if salary_date > END_DATE:
            continue
        salary_date = salary_date.replace(hour=random.randint(8, 12), minute=random.randint(0, 59))
        balance += entity.salary
        txns.append({
            "row_id": f"bank_row_{row_counter[0]}",
            "account": acct,
            "vpa": vpa,
            "date": salary_date,
            "amount": entity.salary,
            "direction": "credit",
            "balance": round(balance, 2),
            "counterparty_name": "SALARY",
            "counterparty_acct": f"EMPLOYER-{random.randint(1000, 9999)}",
            "channel": "NEFT",
            "utr": gen_utr(),
            "narration_style": random.choice(["sbi", "hdfc", "icici"]),
            "entity_id": entity.entity_id,
        })
        row_counter[0] += 1

    # Recurring debits: rent, EMI, utilities (3-5 per month)
    for month_offset in [0, 1]:
        num_recurring = random.randint(3, 5)
        for _ in range(num_recurring):
            dt = random_datetime(
                BASE_DATE + timedelta(days=30 * month_offset),
                min(BASE_DATE + timedelta(days=30 * (month_offset + 1)), END_DATE)
            )
            amt = random.choice([
                random.randint(5000, 15000),   # Rent
                random.randint(2000, 8000),    # EMI
                random.randint(200, 3000),     # Utilities
            ])
            balance -= amt
            contact = random.choice(entity.contacts) if entity.contacts else entity
            txns.append({
                "row_id": f"bank_row_{row_counter[0]}",
                "account": acct,
                "vpa": vpa,
                "date": dt,
                "amount": amt,
                "direction": "debit",
                "balance": round(balance, 2),
                "counterparty_name": contact.name,
                "counterparty_acct": contact.accounts[0],
                "counterparty_vpa": contact.vpas[0],
                "channel": random.choice(["UPI", "IMPS", "NEFT"]),
                "utr": gen_utr(),
                "narration_style": random.choice(["sbi", "hdfc", "icici"]),
                "entity_id": entity.entity_id,
            })
            row_counter[0] += 1

    # P2P transfers (3-8 random ones)
    for _ in range(random.randint(3, 8)):
        dt = random_datetime(BASE_DATE, END_DATE)
        amt = random.randint(100, 10000)
        is_credit = random.random() < 0.3
        if is_credit:
            balance += amt
        else:
            balance -= amt
        contact = random.choice(entity.contacts) if entity.contacts else entity
        txns.append({
            "row_id": f"bank_row_{row_counter[0]}",
            "account": acct,
            "vpa": vpa,
            "date": dt,
            "amount": amt,
            "direction": "credit" if is_credit else "debit",
            "balance": round(balance, 2),
            "counterparty_name": contact.name,
            "counterparty_acct": contact.accounts[0],
            "counterparty_vpa": contact.vpas[0],
            "channel": "UPI",
            "utr": gen_utr(),
            "narration_style": random.choice(["sbi", "hdfc", "icici"]),
            "entity_id": entity.entity_id,
        })
        row_counter[0] += 1

    return txns


def gen_normal_calls(entity, row_counter):
    """Generate realistic call patterns for normal entity."""
    calls = []
    num_calls = random.randint(15, 35)
    for _ in range(num_calls):
        dt = random_datetime(BASE_DATE, END_DATE)
        dt = dt.replace(hour=random.randint(7, 22))
        contact = random.choice(entity.contacts) if entity.contacts else entity
        duration = random.choice([
            random.randint(5, 30),     # Quick call
            random.randint(30, 180),   # Normal call
            random.randint(180, 600),  # Long call
        ])
        calls.append({
            "row_id": f"cdr_row_{row_counter[0]}",
            "a_party": entity.phones[0],
            "b_party": contact.phones[0],
            "call_type": random.choice(["VOICE", "VOICE", "VOICE", "SMS"]),
            "start_time": dt,
            "duration_sec": duration,
            "cell_id": gen_cell_id(entity.city),
            "imei": entity.imeis[0],
            "entity_id": entity.entity_id,
        })
        row_counter[0] += 1
    return calls


def gen_normal_sessions(entity, row_counter):
    """Generate realistic IP sessions for normal entity."""
    sessions = []
    num_sessions = random.randint(8, 20)
    for _ in range(num_sessions):
        dt = random_datetime(BASE_DATE, END_DATE)
        duration_min = random.randint(5, 120)
        sessions.append({
            "row_id": f"ipdr_row_{row_counter[0]}",
            "msisdn": entity.phones[0],
            "private_ip": gen_private_ip(),
            "public_ip": gen_public_ip(entity.city),
            "port": random.choice([443, 80, 8080, 8443]),
            "session_start": dt,
            "session_end": dt + timedelta(minutes=duration_min),
            "dest_ip": f"{random.randint(1,223)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}",
            "data_volume_kb": random.randint(100, 50000),
            "entity_id": entity.entity_id,
        })
        row_counter[0] += 1
    return sessions


# ============================================================
# EVENT GENERATION — GUILTY ENTITIES
# ============================================================
def gen_structuring_events(entity, entities, row_counter):
    """
    STR-1: Large fraud credit followed by 4-6 outgoing transfers just under ₹49,000-49,900
    within 24-48 hours to 2-3 accounts.
    """
    txns, calls, sessions = [], [], []
    acct = entity.accounts[0]
    vpa = entity.vpas[0]
    flagged_rows = []

    # Start with some normal activity
    balance = random.uniform(5000, 30000)
    for _ in range(5):
        dt = random_datetime(BASE_DATE, BASE_DATE + timedelta(days=20))
        amt = random.randint(500, 5000)
        balance -= amt
        contact = random.choice(entity.contacts) if entity.contacts else entities[0]
        txns.append({
            "row_id": f"bank_row_{row_counter[0]}",
            "account": acct, "vpa": vpa, "date": dt, "amount": amt,
            "direction": "debit", "balance": round(balance, 2),
            "counterparty_name": contact.name, "counterparty_acct": contact.accounts[0],
            "counterparty_vpa": contact.vpas[0], "channel": "UPI", "utr": gen_utr(),
            "narration_style": "sbi", "entity_id": entity.entity_id,
        })
        row_counter[0] += 1

    # Fraud credit: ₹2,50,000
    fraud_date = BASE_DATE + timedelta(days=25, hours=random.randint(10, 16))
    fraud_amount = 250000
    balance += fraud_amount
    fraud_row_id = f"bank_row_{row_counter[0]}"
    flagged_rows.append(fraud_row_id)
    txns.append({
        "row_id": fraud_row_id,
        "account": acct, "vpa": vpa, "date": fraud_date, "amount": fraud_amount,
        "direction": "credit", "balance": round(balance, 2),
        "counterparty_name": "UNKNOWN SOURCE", "counterparty_acct": gen_account(),
        "channel": "IMPS", "utr": gen_utr(),
        "narration_style": "sbi", "entity_id": entity.entity_id,
    })
    row_counter[0] += 1

    # 5 structuring transfers just under ₹50k within 36 hours
    target_accounts = random.sample([e for e in entities[:NUM_NORMAL]], 3)
    for i in range(5):
        dt = fraud_date + timedelta(hours=random.randint(2, 36), minutes=random.randint(0, 59))
        amt = random.randint(48500, 49900)
        balance -= amt
        target = target_accounts[i % len(target_accounts)]
        row_id = f"bank_row_{row_counter[0]}"
        flagged_rows.append(row_id)
        txns.append({
            "row_id": row_id,
            "account": acct, "vpa": vpa, "date": dt, "amount": amt,
            "direction": "debit", "balance": round(balance, 2),
            "counterparty_name": target.name, "counterparty_acct": target.accounts[0],
            "counterparty_vpa": target.vpas[0], "channel": "UPI", "utr": gen_utr(),
            "narration_style": "sbi", "entity_id": entity.entity_id,
        })
        row_counter[0] += 1

    # Some normal calls (no suspicious timing)
    calls.extend(gen_normal_calls(entity, row_counter))
    sessions.extend(gen_normal_sessions(entity, row_counter))

    return txns, calls, sessions, flagged_rows


def gen_layering_events(entity, entities, row_counter):
    """
    LAY-1: A→B→C→D→(back to A's cluster) across 3-4 hops within hours,
    5-15% commission skim each hop, with phone call 2-10 min before each transfer
    and overlapping IP session at each transfer timestamp.
    """
    txns, calls, sessions = [], [], []
    flagged_rows = []

    # Pick 3 intermediary entities from normal pool
    intermediaries = random.sample([e for e in entities[:NUM_NORMAL]], 3)
    hop_chain = [entity] + intermediaries  # A → B → C → D

    base_amount = 300000  # ₹3,00,000
    hop_start = BASE_DATE + timedelta(days=28, hours=10)
    current_amount = base_amount

    # Initial credit to entity A
    balance_a = random.uniform(5000, 20000) + base_amount
    init_row_id = f"bank_row_{row_counter[0]}"
    flagged_rows.append(init_row_id)
    txns.append({
        "row_id": init_row_id,
        "account": entity.accounts[0], "vpa": entity.vpas[0],
        "date": hop_start - timedelta(hours=1),
        "amount": base_amount, "direction": "credit",
        "balance": round(balance_a, 2),
        "counterparty_name": "EXTERNAL SOURCE", "counterparty_acct": gen_account(),
        "channel": "NEFT", "utr": gen_utr(),
        "narration_style": "hdfc", "entity_id": entity.entity_id,
    })
    row_counter[0] += 1

    for hop_idx in range(len(hop_chain) - 1):
        sender = hop_chain[hop_idx]
        receiver = hop_chain[hop_idx + 1]
        transfer_time = hop_start + timedelta(hours=hop_idx * 2, minutes=random.randint(10, 40))

        # Commission skim: 5-15%
        commission = random.uniform(0.05, 0.15)
        transfer_amount = int(current_amount * (1 - commission))

        # Phone call 2-10 minutes before transfer (feeds TCS-2)
        call_time = transfer_time - timedelta(minutes=random.randint(2, 10))
        call_row_id = f"cdr_row_{row_counter[0]}"
        flagged_rows.append(call_row_id)
        calls.append({
            "row_id": call_row_id,
            "a_party": sender.phones[0], "b_party": receiver.phones[0],
            "call_type": "VOICE", "start_time": call_time,
            "duration_sec": random.randint(30, 180),
            "cell_id": gen_cell_id(sender.city), "imei": sender.imeis[0],
            "entity_id": sender.entity_id,
        })
        row_counter[0] += 1

        # Overlapping IP session at transfer time (feeds TCS-1)
        session_row_id = f"ipdr_row_{row_counter[0]}"
        flagged_rows.append(session_row_id)
        sessions.append({
            "row_id": session_row_id,
            "msisdn": sender.phones[0],
            "private_ip": gen_private_ip(),
            "public_ip": gen_public_ip(sender.city),
            "port": 443, "session_start": transfer_time - timedelta(minutes=5),
            "session_end": transfer_time + timedelta(minutes=15),
            "dest_ip": gen_public_ip(receiver.city),
            "data_volume_kb": random.randint(500, 5000),
            "entity_id": sender.entity_id,
        })
        row_counter[0] += 1

        # The transfer itself
        txn_row_id = f"bank_row_{row_counter[0]}"
        flagged_rows.append(txn_row_id)
        txns.append({
            "row_id": txn_row_id,
            "account": sender.accounts[0], "vpa": sender.vpas[0],
            "date": transfer_time, "amount": transfer_amount,
            "direction": "debit",
            "balance": round(random.uniform(1000, 10000), 2),
            "counterparty_name": receiver.name,
            "counterparty_acct": receiver.accounts[0],
            "counterparty_vpa": receiver.vpas[0],
            "channel": "UPI", "utr": gen_utr(),
            "narration_style": "hdfc", "entity_id": sender.entity_id,
        })
        row_counter[0] += 1

        # Credit side at receiver
        recv_row_id = f"bank_row_{row_counter[0]}"
        flagged_rows.append(recv_row_id)
        txns.append({
            "row_id": recv_row_id,
            "account": receiver.accounts[0], "vpa": receiver.vpas[0],
            "date": transfer_time + timedelta(seconds=random.randint(5, 60)),
            "amount": transfer_amount, "direction": "credit",
            "balance": round(random.uniform(10000, 50000) + transfer_amount, 2),
            "counterparty_name": sender.name,
            "counterparty_acct": sender.accounts[0],
            "counterparty_vpa": sender.vpas[0],
            "channel": "UPI", "utr": gen_utr(),
            "narration_style": "hdfc", "entity_id": receiver.entity_id,
        })
        row_counter[0] += 1

        current_amount = transfer_amount

    # Final hop: D sends back toward A's cluster (circular)
    final_sender = hop_chain[-1]
    final_receiver = entity  # Back to A
    final_time = hop_start + timedelta(hours=8, minutes=random.randint(0, 30))
    final_amount = int(current_amount * 0.88)

    call_row_id = f"cdr_row_{row_counter[0]}"
    flagged_rows.append(call_row_id)
    calls.append({
        "row_id": call_row_id,
        "a_party": final_sender.phones[0], "b_party": final_receiver.phones[0],
        "call_type": "VOICE", "start_time": final_time - timedelta(minutes=random.randint(3, 8)),
        "duration_sec": random.randint(60, 120),
        "cell_id": gen_cell_id(final_sender.city), "imei": final_sender.imeis[0],
        "entity_id": final_sender.entity_id,
    })
    row_counter[0] += 1

    txn_row_id = f"bank_row_{row_counter[0]}"
    flagged_rows.append(txn_row_id)
    txns.append({
        "row_id": txn_row_id,
        "account": final_sender.accounts[0], "vpa": final_sender.vpas[0],
        "date": final_time, "amount": final_amount, "direction": "debit",
        "balance": round(random.uniform(500, 5000), 2),
        "counterparty_name": final_receiver.name,
        "counterparty_acct": final_receiver.accounts[0],
        "counterparty_vpa": final_receiver.vpas[0],
        "channel": "UPI", "utr": gen_utr(),
        "narration_style": "hdfc", "entity_id": final_sender.entity_id,
    })
    row_counter[0] += 1

    # Normal background calls/sessions for the primary entity
    calls.extend(gen_normal_calls(entity, row_counter))
    sessions.extend(gen_normal_sessions(entity, row_counter))

    return txns, calls, sessions, flagged_rows


def gen_mule_events(entity, entities, row_counter):
    """
    MUL-1: 30+ days dormant, then one large inflow, then 80-95% moved out
    within minutes-to-hours, balance returns near-zero.
    """
    txns, calls, sessions = [], [], []
    flagged_rows = []
    acct = entity.accounts[0]
    vpa = entity.vpas[0]

    # Dormant period: only 1-2 tiny transactions early in the dataset
    balance = random.uniform(500, 2000)
    for _ in range(random.randint(1, 2)):
        dt = random_datetime(BASE_DATE, BASE_DATE + timedelta(days=2))
        amt = random.randint(50, 200)
        balance -= amt
        txns.append({
            "row_id": f"bank_row_{row_counter[0]}",
            "account": acct, "vpa": vpa, "date": dt, "amount": amt,
            "direction": "debit", "balance": round(balance, 2),
            "counterparty_name": random.choice(entity.contacts).name if entity.contacts else "SHOP",
            "counterparty_acct": gen_account(),
            "channel": "UPI", "utr": gen_utr(),
            "narration_style": "icici", "entity_id": entity.entity_id,
        })
        row_counter[0] += 1

    # Large inflow after 35 days
    inflow_date = BASE_DATE + timedelta(days=37, hours=random.randint(10, 16))
    inflow_amount = 500000  # ₹5,00,000
    balance += inflow_amount
    inflow_row_id = f"bank_row_{row_counter[0]}"
    flagged_rows.append(inflow_row_id)
    txns.append({
        "row_id": inflow_row_id,
        "account": acct, "vpa": vpa, "date": inflow_date,
        "amount": inflow_amount, "direction": "credit",
        "balance": round(balance, 2),
        "counterparty_name": "SUSPICIOUS CREDIT",
        "counterparty_acct": gen_account(),
        "channel": "RTGS", "utr": gen_utr(),
        "narration_style": "icici", "entity_id": entity.entity_id,
    })
    row_counter[0] += 1

    # 90% outflow within 2 hours: 3-4 transfers
    total_out = 0
    targets = random.sample([e for e in entities[:NUM_NORMAL]], 3)
    for i in range(4):
        dt = inflow_date + timedelta(minutes=random.randint(15, 120))
        if i < 3:
            amt = random.randint(100000, 150000)
        else:
            amt = int(inflow_amount * 0.9) - total_out
            if amt <= 0:
                continue
        total_out += amt
        balance -= amt
        target = targets[i % len(targets)]
        row_id = f"bank_row_{row_counter[0]}"
        flagged_rows.append(row_id)
        txns.append({
            "row_id": row_id,
            "account": acct, "vpa": vpa, "date": dt, "amount": amt,
            "direction": "debit", "balance": round(balance, 2),
            "counterparty_name": target.name,
            "counterparty_acct": target.accounts[0],
            "counterparty_vpa": target.vpas[0],
            "channel": "IMPS", "utr": gen_utr(),
            "narration_style": "icici", "entity_id": entity.entity_id,
        })
        row_counter[0] += 1

    # Add a call during the mule activity (to fire TCS-1/TCS-2 for CRITICAL)
    mule_call_time = inflow_date + timedelta(minutes=random.randint(5, 25))
    call_target = targets[0]
    call_row_id = f"cdr_row_{row_counter[0]}"
    flagged_rows.append(call_row_id)
    calls.append({
        "row_id": call_row_id,
        "a_party": entity.phones[0], "b_party": call_target.phones[0],
        "call_type": "VOICE", "start_time": mule_call_time,
        "duration_sec": random.randint(30, 120),
        "cell_id": gen_cell_id(entity.city), "imei": entity.imeis[0],
        "entity_id": entity.entity_id,
    })
    row_counter[0] += 1

    # IP session overlapping the outflows
    session_row_id = f"ipdr_row_{row_counter[0]}"
    flagged_rows.append(session_row_id)
    sessions.append({
        "row_id": session_row_id,
        "msisdn": entity.phones[0],
        "private_ip": gen_private_ip(),
        "public_ip": gen_public_ip(entity.city),
        "port": 443,
        "session_start": inflow_date - timedelta(minutes=10),
        "session_end": inflow_date + timedelta(hours=3),
        "dest_ip": gen_public_ip(),
        "data_volume_kb": random.randint(1000, 10000),
        "entity_id": entity.entity_id,
    })
    row_counter[0] += 1

    # Normal background activity
    calls.extend(gen_normal_calls(entity, row_counter))
    sessions.extend(gen_normal_sessions(entity, row_counter))

    return txns, calls, sessions, flagged_rows


def gen_identity_fanout_events(entity, entities, row_counter):
    """
    IDR-1: One IMEI operating 3 phone numbers and 2-3 bank accounts,
    spreading structuring activity across them.
    """
    txns, calls, sessions = [], [], []
    flagged_rows = []

    # Spread structuring across multiple accounts
    fraud_date = BASE_DATE + timedelta(days=30, hours=12)

    for phone_idx, (phone, acct, vpa) in enumerate(zip(entity.phones, entity.accounts, entity.vpas)):
        balance = random.uniform(3000, 15000)

        # Some normal activity on each account
        for _ in range(random.randint(3, 6)):
            dt = random_datetime(BASE_DATE, fraud_date - timedelta(days=5))
            amt = random.randint(200, 5000)
            balance -= amt
            contact = random.choice(entity.contacts) if entity.contacts else entities[0]
            txns.append({
                "row_id": f"bank_row_{row_counter[0]}",
                "account": acct, "vpa": vpa, "date": dt, "amount": amt,
                "direction": "debit", "balance": round(balance, 2),
                "counterparty_name": contact.name,
                "counterparty_acct": contact.accounts[0],
                "channel": "UPI", "utr": gen_utr(),
                "narration_style": random.choice(["sbi", "hdfc", "icici"]),
                "entity_id": entity.entity_id,
            })
            row_counter[0] += 1

        # Fraud credit on each account
        fraud_amt = random.randint(80000, 120000)
        balance += fraud_amt
        row_id = f"bank_row_{row_counter[0]}"
        flagged_rows.append(row_id)
        txns.append({
            "row_id": row_id,
            "account": acct, "vpa": vpa,
            "date": fraud_date + timedelta(hours=phone_idx * 3),
            "amount": fraud_amt, "direction": "credit",
            "balance": round(balance, 2),
            "counterparty_name": "UNKNOWN",
            "counterparty_acct": gen_account(),
            "channel": "IMPS", "utr": gen_utr(),
            "narration_style": random.choice(["sbi", "hdfc", "icici"]),
            "entity_id": entity.entity_id,
        })
        row_counter[0] += 1

        # 2 structuring transfers under threshold from each account
        for j in range(2):
            dt = fraud_date + timedelta(hours=phone_idx * 3 + j + 1, minutes=random.randint(10, 50))
            amt = random.randint(48000, 49800)
            balance -= amt
            target = random.choice([e for e in entities[:NUM_NORMAL]])
            row_id = f"bank_row_{row_counter[0]}"
            flagged_rows.append(row_id)
            txns.append({
                "row_id": row_id,
                "account": acct, "vpa": vpa, "date": dt, "amount": amt,
                "direction": "debit", "balance": round(balance, 2),
                "counterparty_name": target.name,
                "counterparty_acct": target.accounts[0],
                "counterparty_vpa": target.vpas[0],
                "channel": "UPI", "utr": gen_utr(),
                "narration_style": random.choice(["sbi", "hdfc", "icici"]),
                "entity_id": entity.entity_id,
            })
            row_counter[0] += 1

        # CDR from each phone (same IMEI — this is the SIM swap signature)
        for _ in range(random.randint(5, 10)):
            dt = random_datetime(BASE_DATE, END_DATE)
            contact = random.choice(entity.contacts) if entity.contacts else entities[0]
            calls.append({
                "row_id": f"cdr_row_{row_counter[0]}",
                "a_party": phone, "b_party": contact.phones[0],
                "call_type": "VOICE", "start_time": dt,
                "duration_sec": random.randint(10, 300),
                "cell_id": gen_cell_id(entity.city),
                "imei": entity.imeis[0],  # SAME IMEI across all phones
                "entity_id": entity.entity_id,
            })
            row_counter[0] += 1

        # IP sessions from each phone
        for _ in range(random.randint(3, 6)):
            dt = random_datetime(BASE_DATE, END_DATE)
            sessions.append({
                "row_id": f"ipdr_row_{row_counter[0]}",
                "msisdn": phone,
                "private_ip": gen_private_ip(),
                "public_ip": gen_public_ip(entity.city),
                "port": 443,
                "session_start": dt,
                "session_end": dt + timedelta(minutes=random.randint(5, 60)),
                "dest_ip": gen_public_ip(),
                "data_volume_kb": random.randint(100, 5000),
                "entity_id": entity.entity_id,
            })
            row_counter[0] += 1

    return txns, calls, sessions, flagged_rows


def gen_geo_improbable_events(entity, entities, row_counter):
    """
    LOC-1: Call from one city's cell tower and IP session geolocated elsewhere
    within impossible travel time (15 minutes).
    """
    txns, calls, sessions = [], [], []
    flagged_rows = []
    acct = entity.accounts[0]
    vpa = entity.vpas[0]

    # Normal activity
    balance = random.uniform(10000, 50000)
    for _ in range(8):
        dt = random_datetime(BASE_DATE, END_DATE)
        amt = random.randint(500, 8000)
        is_credit = random.random() < 0.3
        if is_credit:
            balance += amt
        else:
            balance -= amt
        contact = random.choice(entity.contacts) if entity.contacts else entities[0]
        txns.append({
            "row_id": f"bank_row_{row_counter[0]}",
            "account": acct, "vpa": vpa, "date": dt, "amount": amt,
            "direction": "credit" if is_credit else "debit",
            "balance": round(balance, 2),
            "counterparty_name": contact.name,
            "counterparty_acct": contact.accounts[0],
            "channel": "UPI", "utr": gen_utr(),
            "narration_style": "icici", "entity_id": entity.entity_id,
        })
        row_counter[0] += 1

    # The geo-improbable event pair
    geo_time = BASE_DATE + timedelta(days=20, hours=14)

    # Call from Mumbai
    call_row_id = f"cdr_row_{row_counter[0]}"
    flagged_rows.append(call_row_id)
    calls.append({
        "row_id": call_row_id,
        "a_party": entity.phones[0],
        "b_party": random.choice(entity.contacts).phones[0] if entity.contacts else gen_phone(),
        "call_type": "VOICE", "start_time": geo_time,
        "duration_sec": 120,
        "cell_id": gen_cell_id("Mumbai"),
        "imei": entity.imeis[0],
        "entity_id": entity.entity_id,
    })
    row_counter[0] += 1

    # IP session from Bangalore 15 minutes later (impossible travel)
    session_row_id = f"ipdr_row_{row_counter[0]}"
    flagged_rows.append(session_row_id)
    sessions.append({
        "row_id": session_row_id,
        "msisdn": entity.phones[0],
        "private_ip": gen_private_ip(),
        "public_ip": gen_public_ip("Bangalore"),  # Different city!
        "port": 443,
        "session_start": geo_time + timedelta(minutes=15),
        "session_end": geo_time + timedelta(minutes=45),
        "dest_ip": gen_public_ip(),
        "data_volume_kb": random.randint(500, 5000),
        "entity_id": entity.entity_id,
    })
    row_counter[0] += 1

    # Normal calls/sessions
    calls.extend(gen_normal_calls(entity, row_counter))
    sessions.extend(gen_normal_sessions(entity, row_counter))

    return txns, calls, sessions, flagged_rows


# ============================================================
# EXPORT FUNCTIONS — 3 bank formats + CDR + IPDR
# ============================================================
def format_narration_sbi(txn):
    """SBI-style UPI narration: UPI/CR/261234567890/name.vpa/oksbi"""
    direction_tag = "CR" if txn["direction"] == "credit" else "DR"
    utr = txn.get("utr", gen_utr())
    cp_vpa = txn.get("counterparty_vpa", txn.get("counterparty_name", "unknown").lower().replace(' ', '.'))
    channel = txn.get("channel", "UPI")
    if channel == "UPI":
        return f"UPI/{direction_tag}/{utr}/{cp_vpa}/Payment"
    elif channel == "IMPS":
        cp_name = txn.get("counterparty_name", "UNKNOWN")
        return f"IMPS-P2A/{utr}/{cp_name}/{txn.get('counterparty_acct', 'NA')}"
    elif channel == "NEFT":
        return f"NEFT/{direction_tag}/{utr}/{txn.get('counterparty_name', 'UNKNOWN')}"
    else:
        return f"RTGS/{direction_tag}/{utr}/{txn.get('counterparty_name', 'UNKNOWN')}"


def format_narration_hdfc(txn):
    """HDFC-style: UPI-CREDIT-261234567890-GOOGLEPAY or IMPS-261234567890-NAME"""
    direction_tag = "CREDIT" if txn["direction"] == "credit" else "DEBIT"
    utr = txn.get("utr", gen_utr())
    cp_name = txn.get("counterparty_name", "UNKNOWN")
    channel = txn.get("channel", "UPI")
    if channel == "UPI":
        cp_vpa = txn.get("counterparty_vpa", cp_name.lower().replace(' ', '.'))
        return f"UPI-{direction_tag}-{utr}-{cp_vpa}"
    elif channel == "IMPS":
        return f"IMPS-{utr}-{cp_name}"
    else:
        return f"{channel}-{direction_tag}-{utr}-{cp_name}"


def format_narration_icici(txn):
    """ICICI PDF-style IMPS: IMPS-P2A/403318292014/JOHN DOE/HDFC0001234"""
    utr = txn.get("utr", gen_utr())
    cp_name = txn.get("counterparty_name", "UNKNOWN")
    channel = txn.get("channel", "UPI")
    if channel == "UPI":
        cp_vpa = txn.get("counterparty_vpa", cp_name.lower().replace(' ', '.'))
        return f"UPI/P2M/{utr}/{cp_vpa}/Payment"
    elif channel == "IMPS":
        ifsc = txn.get("counterparty_ifsc", gen_ifsc())
        return f"IMPS-P2A/{utr}/{cp_name}/{ifsc}"
    else:
        return f"{channel}/{utr}/{cp_name}"


def export_bank_xlsx(txns, filepath):
    """SBI-style Excel: Account No, Txn Date, Value Date, Description, Debit, Credit, Balance (DD-MM-YYYY)"""
    rows = []
    for txn in txns:
        if txn.get("narration_style") != "sbi":
            continue
        date_str = txn["date"].strftime("%d-%m-%Y %H:%M:%S")
        value_date_str = (txn["date"] + timedelta(days=random.choice([0, 0, 1]))).strftime("%d-%m-%Y %H:%M:%S")
        narration = format_narration_sbi(txn)
        debit = txn["amount"] if txn["direction"] == "debit" else ""
        credit = txn["amount"] if txn["direction"] == "credit" else ""
        rows.append({
            "Account No": txn.get("account", ""),
            "Txn Date": date_str,
            "Value Date": value_date_str,
            "Description": narration,
            "Debit": debit,
            "Credit": credit,
            "Balance": txn["balance"],
        })

    if not rows:
        for txn in txns[:max(len(txns) // 3, 10)]:
            date_str = txn["date"].strftime("%d-%m-%Y %H:%M:%S")
            value_date_str = (txn["date"] + timedelta(days=random.choice([0, 0, 1]))).strftime("%d-%m-%Y %H:%M:%S")
            narration = format_narration_sbi(txn)
            debit = txn["amount"] if txn["direction"] == "debit" else ""
            credit = txn["amount"] if txn["direction"] == "credit" else ""
            rows.append({
                "Account No": txn.get("account", ""),
                "Txn Date": date_str,
                "Value Date": value_date_str,
                "Description": narration,
                "Debit": debit,
                "Credit": credit,
                "Balance": txn["balance"],
            })

    df = pd.DataFrame(rows)
    if len(df) > 5:
        df.loc[3, "Balance"] = None
    df.to_excel(filepath, index=False, engine='openpyxl')
    print(f"  [XLSX] Exported {len(df)} rows to {filepath}")


def export_bank_csv(txns, filepath):
    """HDFC-style CSV: account_no, date, particulars, withdrawal_amt, deposit_amt, closing_balance (YYYY/MM/DD)"""
    rows = []
    for txn in txns:
        if txn.get("narration_style") != "hdfc":
            continue
        date_str = txn["date"].strftime("%Y/%m/%d %H:%M:%S")
        narration = format_narration_hdfc(txn)
        withdrawal = txn["amount"] if txn["direction"] == "debit" else ""
        deposit = txn["amount"] if txn["direction"] == "credit" else ""
        rows.append({
            "account_no": txn.get("account", ""),
            "date": date_str,
            "particulars": narration,
            "withdrawal_amt": withdrawal,
            "deposit_amt": deposit,
            "closing_balance": txn["balance"],
        })

    if not rows:
        for txn in txns[max(len(txns) // 3, 10):max(2 * len(txns) // 3, 20)]:
            date_str = txn["date"].strftime("%Y/%m/%d %H:%M:%S")
            narration = format_narration_hdfc(txn)
            withdrawal = txn["amount"] if txn["direction"] == "debit" else ""
            deposit = txn["amount"] if txn["direction"] == "credit" else ""
            rows.append({
                "account_no": txn.get("account", ""),
                "date": date_str,
                "particulars": narration,
                "withdrawal_amt": withdrawal,
                "deposit_amt": deposit,
                "closing_balance": txn["balance"],
            })

    df = pd.DataFrame(rows)
    # Inject missing value and a duplicate row
    if len(df) > 5:
        df.loc[2, "closing_balance"] = None
        df = pd.concat([df, df.iloc[[4]]], ignore_index=True)  # Duplicate row
    df.to_csv(filepath, index=False)
    print(f"  [CSV]  Exported {len(df)} rows to {filepath}")


def export_bank_pdf(txns, filepath):
    """ICICI-style PDF: S.No, Account No, Date, Description, Amount, Type (DR/CR), Balance (DD/MM/YY)"""
    rows_data = []
    for txn in txns:
        if txn.get("narration_style") != "icici":
            continue
        date_str = txn["date"].strftime("%d/%m/%y %H:%M:%S")
        narration = format_narration_icici(txn)
        dr_cr = "DR" if txn["direction"] == "debit" else "CR"
        rows_data.append([
            len(rows_data) + 1,
            txn.get("account", ""),
            date_str,
            narration,
            f"{txn['amount']:.2f}",
            dr_cr,
            f"{txn['balance']:.2f}",
        ])

    if not rows_data:
        for txn in txns[max(2 * len(txns) // 3, 20):]:
            date_str = txn["date"].strftime("%d/%m/%y %H:%M:%S")
            narration = format_narration_icici(txn)
            dr_cr = "DR" if txn["direction"] == "debit" else "CR"
            rows_data.append([
                len(rows_data) + 1,
                txn.get("account", ""),
                date_str,
                narration,
                f"{txn['amount']:.2f}",
                dr_cr,
                f"{txn['balance']:.2f}",
            ])

    # Inject anomalies
    if len(rows_data) > 3:
        rows_data[1][4] = ""  # Missing amount
        header = ["S.No", "Account No", "Date", "Description", "Amount", "Type (DR/CR)", "Bal."]
    else:
        header = ["S.No", "Account No", "Date", "Description", "Amount", "Type", "Balance"]

    table_data = [header] + rows_data

    doc = SimpleDocTemplate(str(filepath), pagesize=A4,
                            leftMargin=15*mm, rightMargin=15*mm,
                            topMargin=20*mm, bottomMargin=20*mm)
    styles = getSampleStyleSheet()

    elements = []
    elements.append(Paragraph("ICICI Bank — Account Statement", styles['Title']))
    elements.append(Spacer(1, 10*mm))

    # Wrap the narration column so long text flows onto extra lines instead of
    # overrunning its cell. reportlab does not wrap bare strings in a table cell —
    # it draws them past the cell border, and a text extractor then reads the
    # clipped remains. Every description goes through a Paragraph for that reason.
    wrapped_data = []
    for row in table_data:
        wrapped_row = []
        for i, cell in enumerate(row):
            if i == 3:
                wrapped_row.append(Paragraph(str(cell), styles['Normal']))
            else:
                wrapped_row.append(str(cell))
        wrapped_data.append(wrapped_row)

    # Column widths, in points. A4 is 595.3pt wide; 15mm margins leave 510.2pt of
    # usable width, so these must sum to less than that.
    #
    # Each width is set from the widest string the column actually carries at 7pt
    # Helvetica plus the 3pt padding set below. The Date column is the one that
    # matters: "01/06/25 21:53:47" measures ~56pt, so the old 45pt width clipped
    # the first and last character off every timestamp on the page — dates came
    # out as '0/06/25 21:53:4' and failed to parse, silently deleting the row.
    col_widths = [
        26,   # S.No
        64,   # Account No
        66,   # Date        <- 56pt of text + padding
        178,  # Description (wrapped Paragraph)
        52,   # Amount
        54,   # Type (DR/CR) — sized for the header, which is wider than "DR"/"CR"
        50,   # Bal.
    ]

    # repeatRows=1 redraws the header at the top of every page, which is what a
    # real bank statement does. The parser detects and skips those repeats by
    # matching the text, rather than assuming the first row of each page is one.
    table = Table(wrapped_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a1d24')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
    ]))
    elements.append(table)
    doc.build(elements)
    print(f"  [PDF]  Exported {len(rows_data)} rows to {filepath}")


def export_cdr_csv(all_calls, filepath):
    """CDR CSV: A_PARTY,B_PARTY,CALL_TYPE,START_TIME,DURATION_SEC,CELL_ID,IMEI"""
    rows = []
    for call in all_calls:
        rows.append({
            "A_PARTY": call["a_party"],
            "B_PARTY": call["b_party"],
            "CALL_TYPE": call["call_type"],
            "START_TIME": call["start_time"].strftime("%Y-%m-%d %H:%M:%S"),
            "DURATION_SEC": call["duration_sec"],
            "CELL_ID": call["cell_id"],
            "IMEI": call["imei"],
        })
    df = pd.DataFrame(rows)
    # Inject missing values
    if len(df) > 10:
        df.loc[7, "CELL_ID"] = None
        df.loc[12, "DURATION_SEC"] = None
    df.to_csv(filepath, index=False)
    print(f"  [CDR]  Exported {len(df)} rows to {filepath}")


def export_ipdr_csv(all_sessions, filepath):
    """IPDR CSV: MSISDN,PRIVATE_IP,PUBLIC_IP,PORT,SESSION_START,SESSION_END,DEST_IP,DATA_VOLUME_KB"""
    rows = []
    for sess in all_sessions:
        rows.append({
            "MSISDN": sess["msisdn"],
            "PRIVATE_IP": sess["private_ip"],
            "PUBLIC_IP": sess["public_ip"],
            "PORT": sess["port"],
            "SESSION_START": sess["session_start"].strftime("%Y-%m-%d %H:%M:%S"),
            "SESSION_END": sess["session_end"].strftime("%Y-%m-%d %H:%M:%S"),
            "DEST_IP": sess["dest_ip"],
            "DATA_VOLUME_KB": sess["data_volume_kb"],
        })
    df = pd.DataFrame(rows)
    if len(df) > 5:
        df.loc[4, "DEST_IP"] = None
    df.to_csv(filepath, index=False)
    print(f"  [IPDR] Exported {len(df)} rows to {filepath}")


# ============================================================
# MAIN GENERATION PIPELINE
# ============================================================
def main(scale=1.0):
    print("=" * 60)
    print(f"E-Rakshak — Synthetic Data Generator (Scale: {scale}x)")
    print("=" * 60)

    num_normal = max(1, int(NUM_NORMAL * scale))
    num_guilty = NUM_GUILTY

    # 1. Create entities
    print("\n[STEP 1] Creating entities...")
    entities = create_entities(num_normal=num_normal, num_guilty=num_guilty)
    print(f"  Created {len(entities)} entities ({num_normal} normal, {num_guilty} guilty)")

    for e in entities:
        if e.is_guilty:
            print(f"  GUILTY: {e.entity_id} ({e.name}) — {e.typology}")

    # 2. Generate events
    print("\n[STEP 2] Generating events...")
    all_txns = []
    all_calls = []
    all_sessions = []
    ground_truth_entries = []
    row_counter = [1]  # Mutable counter

    for entity in entities:
        if not entity.is_guilty:
            # Normal entity
            txns = gen_normal_transactions(entity, row_counter)
            calls = gen_normal_calls(entity, row_counter)
            sessions = gen_normal_sessions(entity, row_counter)
            all_txns.extend(txns)
            all_calls.extend(calls)
            all_sessions.extend(sessions)
        else:
            # Guilty entity
            if entity.typology == "STR-1":
                txns, calls, sessions, flagged = gen_structuring_events(entity, entities, row_counter)
            elif entity.typology == "LAY-1":
                txns, calls, sessions, flagged = gen_layering_events(entity, entities, row_counter)
            elif entity.typology == "MUL-1":
                txns, calls, sessions, flagged = gen_mule_events(entity, entities, row_counter)
            elif entity.typology == "IDR-1":
                txns, calls, sessions, flagged = gen_identity_fanout_events(entity, entities, row_counter)
            elif entity.typology == "LOC-1":
                txns, calls, sessions, flagged = gen_geo_improbable_events(entity, entities, row_counter)
            else:
                continue

            all_txns.extend(txns)
            all_calls.extend(calls)
            all_sessions.extend(sessions)

            ground_truth_entries.append({
                "entity_id": entity.entity_id,
                "typology": entity.typology,
                "name": entity.name,
                "raw_identifiers": entity.raw_identifiers(),
                "expected_flagged_rows": flagged,
                "narrative": _get_narrative(entity.typology),
            })

    print(f"  Transactions: {len(all_txns)}")
    print(f"  Calls:        {len(all_calls)}")
    print(f"  IP Sessions:  {len(all_sessions)}")
    print(f"  TOTAL EVENTS: {len(all_txns) + len(all_calls) + len(all_sessions)}")

    # 3. Distribute transactions across 3 bank formats
    print("\n[STEP 3] Assigning bank statement formats...")
    styles = ["sbi", "hdfc", "icici"]
    for i, txn in enumerate(all_txns):
        if "narration_style" not in txn or not txn.get("narration_style"):
            txn["narration_style"] = styles[i % 3]

    style_counts = {}
    for txn in all_txns:
        s = txn.get("narration_style", "sbi")
        style_counts[s] = style_counts.get(s, 0) + 1

    for s, c in sorted(style_counts.items()):
        print(f"  {s.upper()}: {c} transactions")

    # 4. Export files
    print("\n[STEP 4] Exporting files...")
    export_bank_xlsx(all_txns, RAW_DIR / "bank_sbi.xlsx")
    export_bank_csv(all_txns, RAW_DIR / "bank_hdfc.csv")
    export_bank_pdf(all_txns, RAW_DIR / "bank_icici.pdf")
    export_cdr_csv(all_calls, RAW_DIR / "cdr_export.csv")
    export_ipdr_csv(all_sessions, RAW_DIR / "ipdr_export.csv")

    # 5. Write ground truth
    print("\n[STEP 5] Writing ground truth...")
    ground_truth = {
        "generated_at": datetime.now().isoformat(),
        "scale": scale,
        "total_entities": len(entities),
        "normal_entities": num_normal,
        "guilty_entities": num_guilty,
        "total_events": len(all_txns) + len(all_calls) + len(all_sessions),
        "guilty_entity_ids": [e["entity_id"] for e in ground_truth_entries],
        "entities": ground_truth_entries,
    }
    with open(GT_PATH, 'w') as f:
        json.dump(ground_truth, f, indent=2, default=str)
    print(f"  Written to {GT_PATH}")

    # 6. Generate KYC map
    print("\n[STEP 6] Generating KYC map...")
    kyc_map = {}
    for entity in entities:
        for phone in entity.phones:
            kyc_map[phone] = {
                "name": entity.name,
                "phones": entity.phones,
                "accounts": entity.accounts,
                "vpas": entity.vpas,
                "imeis": entity.imeis,
            }
        for acct in entity.accounts:
            kyc_map[acct] = {
                "name": entity.name,
                "phones": entity.phones,
                "accounts": entity.accounts,
                "vpas": entity.vpas,
                "imeis": entity.imeis,
            }

    kyc_path = RAW_DIR / "kyc_map.json"
    with open(kyc_path, 'w') as f:
        json.dump(kyc_map, f, indent=2, default=str)
    print(f"  Written {len(kyc_map)} KYC entries to {kyc_path}")

    print("\n" + "=" * 60)
    print("GENERATION COMPLETE")
    print("=" * 60)
    return ground_truth


def _get_narrative(typology):
    narratives = {
        "STR-1": "Structuring: large fraud credit followed by 5 transfers under INR 50k threshold within 36 hours",
        "LAY-1": "Layering: A->B->C->D circular flow with 5-15% commission skim, calls before each transfer",
        "MUL-1": "Mule Signature: 35 days dormant, INR 5L inflow, 90% outflow within 2 hours",
        "IDR-1": "Identity Fan-out: 1 IMEI across 3 phones + 3 accounts, structuring spread across them",
        "LOC-1": "Geo-Improbable: call from Mumbai tower, IP session from Bangalore 15 minutes later",
    }
    return narratives.get(typology, "Unknown typology")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate synthetic data for E-Rakshak")
    parser.add_argument("--scale", type=float, default=1.0, help="Scale multiplier (e.g., 1.0, 5.0, 10.0, 50.0)")
    args = parser.parse_args()
    main(scale=args.scale)
