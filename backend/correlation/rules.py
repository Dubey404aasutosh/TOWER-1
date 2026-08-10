"""
Named Deterministic Rule Engine
================================
Seven named rules, each returning (bool, explanation, evidence_row_refs).
Every rule firing appends to decision_trace.jsonl.

Rules:
  IDR-1: Identity Fan-out
  TCS-1: Temporal Coincidence
  TCS-2: Call-Then-Transfer
  STR-1: Structuring
  LAY-1: Layering / Circular Flow
  MUL-1: Mule Signature
  LOC-1: Geo-Improbable
"""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

import pandas as pd


# Trace file path
TRACE_FILE = Path(__file__).resolve().parent.parent / "decision_trace.jsonl"


def _append_trace(entity_id, rule_id, evidence_row_refs, explanation):
    """Append one line to decision_trace.jsonl."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "entity_id": entity_id,
        "rule_id": rule_id,
        "evidence_row_refs": evidence_row_refs,
        "explanation": explanation,
    }
    with open(TRACE_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, default=str) + '\n')


def clear_trace():
    """Clear the decision trace file for a fresh pipeline run."""
    if TRACE_FILE.exists():
        TRACE_FILE.unlink()


def _get_entity_df(entity_id, df):
    if df is None or df.empty:
        return pd.DataFrame()
    if 'entity_id' in df.columns:
        if (df['entity_id'] == entity_id).all():
            return df
        return df[df['entity_id'] == entity_id]
    return df


# ============================================================
# RULE IDR-1: Identity Fan-out
# ============================================================
# Documented definition (correlation.md): "One resolved entity linked to 3+ distinct
# accounts or 2+ IMEIs — mule/evasion signature".
#
# The implementation used to look for something else entirely: an IMEI or IMSI
# *changing between consecutive events* on one number. That is a SIM-swap test, not
# a fan-out test, and it is why IDR-1 fired 0x on every entity in the dataset — the
# planted fan-out entity (E044) holds ONE IMEI that never changes, operating three
# MSISDNs and three accounts. The rule was hunting for the opposite of the pattern
# it exists to catch, so the one entity it was written for was invisible to it.
#
# Both readings describe a real identity anomaly, so both are kept as limbs of one
# coherent rule: an identity spread across more identifiers than a single ordinary
# subscriber holds.
#   STATIC  fan-out — one handset driving several numbers, or one person holding an
#                     implausible number of accounts/devices at once.
#   TEMPORAL fan-out — the device or SIM behind a number changes (swap / takeover).
#
# Thresholds are the documented ones, named rather than buried as literals.
IDR1_MIN_ACCOUNTS = 3          # "3+ distinct accounts"
IDR1_MIN_IMEIS = 2             # "2+ IMEIs"
IDR1_MIN_MSISDN_PER_IMEI = 2   # one handset operating 2+ numbers = device fan-out

_SEVERITY_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def _clean_id_set(values):
    """Normalise an identifier collection, dropping blanks and null-ish strings."""
    out = set()
    for value in values or []:
        text = str(value).strip()
        if text and text.lower() not in ("nan", "none", "null", "<na>"):
            out.add(text)
    return out


def _detect_device_fanout(entity_df):
    """
    Find handsets operating more than one MSISDN.

    This is the strongest fan-out signal in telephony evidence: a single IMEI
    cycling SIMs is the standard mule-farm and burner signature, whereas holding
    several accounts can have innocent explanations.

    Returns {imei: {msisdn, ...}} for every IMEI over the threshold.
    """
    if entity_df.empty or 'imei' not in entity_df.columns or 'entity_ref' not in entity_df.columns:
        return {}

    cdr = entity_df[entity_df['imei'].notna()]
    if cdr.empty:
        return {}

    shared = {}
    for imei, group in cdr.groupby('imei'):
        imei_text = str(imei).strip()
        if not imei_text or imei_text.lower() in ("nan", "none"):
            continue
        msisdns = _clean_id_set(group['entity_ref'].dropna().unique())
        if len(msisdns) >= IDR1_MIN_MSISDN_PER_IMEI:
            shared[imei_text] = msisdns
    return shared


def _detect_identifier_swap(entity_df, window_minutes):
    """
    The original temporal limb: an IMEI or IMSI changing between consecutive events
    on the same number, i.e. the device or the SIM behind a number was replaced.

    Returns (severity, description, evidence) or None. Severity is HIGH when device
    and SIM change together, MEDIUM when a single identifier changes near a
    financial transaction, LOW otherwise (a routine handset upgrade).
    """
    has_imei = 'imei' in entity_df.columns
    has_imsi = 'imsi' in entity_df.columns
    if not has_imei and not has_imsi:
        return None

    group_col = 'entity_ref' if 'entity_ref' in entity_df.columns else 'entity_id'

    for phone, group in entity_df.groupby(group_col):
        group_sorted = group.dropna(subset=['timestamp']).sort_values('timestamp')

        last_imei = None
        last_imsi = None
        last_ts = None
        last_row = None

        for idx, row in group_sorted.iterrows():
            curr_imei = str(row['imei']).strip() if has_imei and pd.notna(row.get('imei')) and str(row.get('imei')).strip() not in ['', 'nan', 'None'] else None
            curr_imsi = str(row['imsi']).strip() if has_imsi and pd.notna(row.get('imsi')) and str(row.get('imsi')).strip() not in ['', 'nan', 'None'] else None
            curr_ts = row['timestamp']
            curr_row = row.get('raw_row_ref', idx)

            imei_changed = (last_imei is not None and curr_imei is not None and last_imei != curr_imei)
            imsi_changed = (last_imsi is not None and curr_imsi is not None and last_imsi != curr_imsi)

            if imei_changed or imsi_changed:
                time_gap_mins = (curr_ts - last_ts).total_seconds() / 60.0 if last_ts else 0.0
                time_gap_str = f"{time_gap_mins:.1f} mins" if time_gap_mins < 120 else f"{time_gap_mins/60.0:.1f} hours"

                # Check if any financial transaction occurs near this change window (±60 min)
                start_window = curr_ts - timedelta(minutes=window_minutes)
                end_window = curr_ts + timedelta(minutes=window_minutes)

                nearby_txns = entity_df[
                    (entity_df['event_type'] == 'transaction') &
                    (entity_df['timestamp'] >= start_window) &
                    (entity_df['timestamp'] <= end_window)
                ]
                has_nearby_txn = not nearby_txns.empty

                # Sub-level and severity determination
                if imei_changed and imsi_changed:
                    severity = "HIGH"
                    sub_level = "HIGH Signal (Both SIM + Device Changed)"
                    change_type = "New SIM + New Device (Both Changed - Highest Risk)"
                elif has_nearby_txn:
                    severity = "MEDIUM"
                    sub_level = "MEDIUM Signal (Identifier Changed Near Financial Transaction)"
                    change_type = "SIM/Device Change Near Financial Transfer"
                else:
                    severity = "LOW"
                    sub_level = "LOW Signal (Benign / Informational Identifier Change)"
                    change_type = "Routine Device Upgrade / SIM Replacement (No Financial Activity)"

                evidence = [
                    f"row_{last_row}",
                    f"row_{curr_row}",
                    f"phone:{phone}",
                    f"severity:{severity}",
                    f"sub_level:{sub_level}",
                    f"time_gap:{time_gap_str}",
                    f"nearby_txn:{'yes' if has_nearby_txn else 'no'}",
                ]
                if imei_changed:
                    evidence.extend([f"old_imei:{last_imei}", f"new_imei:{curr_imei}"])
                if imsi_changed:
                    evidence.extend([f"old_imsi:{last_imsi}", f"new_imsi:{curr_imsi}"])

                description = (
                    f"{change_type} on number {phone}. "
                    f"IMEI change: {last_imei or 'N/A'} -> {curr_imei or 'N/A'} | "
                    f"IMSI change: {last_imsi or 'N/A'} -> {curr_imsi or 'N/A'}. "
                    f"Time gap: {time_gap_str}. "
                    f"Financial transaction near change: {'Yes' if has_nearby_txn else 'No'}."
                )
                return severity, description, evidence

            if curr_imei:
                last_imei = curr_imei
            if curr_imsi:
                last_imsi = curr_imsi
            if curr_ts:
                last_ts = curr_ts
            last_row = curr_row

    return None


def check_idr1(entity_id, entity_data, all_events_df=None, window_minutes=60):
    """
    IDR-1: Identity Fan-out.

    Fires when one resolved entity's identifiers fan out past a single ordinary
    subscriber's footprint. Four ways that shows up, checked in order of forensic
    weight:

      HIGH   — one IMEI operating 2+ MSISDNs (a single handset cycling SIMs), or a
               simultaneous device + SIM swap on one number.
      MEDIUM — 3+ distinct accounts, or 2+ distinct IMEIs, on one entity; or a
               single-identifier swap that lands near a financial transaction.
      LOW    — a lone identifier change with no financial activity around it,
               i.e. a routine handset upgrade or store SIM replacement.

    Returns (fired, explanation, evidence, severity).
    """
    entity_data = entity_data or {}

    entity_df = pd.DataFrame()
    if all_events_df is not None and not all_events_df.empty:
        entity_df = _get_entity_df(entity_id, all_events_df)
        if entity_df.empty and entity_data.get('phones') and 'entity_ref' in all_events_df.columns:
            phones = [str(p) for p in entity_data['phones']]
            entity_df = all_events_df[all_events_df['entity_ref'].astype(str).isin(phones)]

    accounts = _clean_id_set(entity_data.get('accounts'))
    imeis = _clean_id_set(entity_data.get('imeis'))

    # Each finding is (severity, description, evidence tokens).
    findings = []

    # ---- LIMB 1: device fan-out — one handset, several numbers ----
    shared_devices = _detect_device_fanout(entity_df)
    for imei, msisdns in shared_devices.items():
        numbers = sorted(msisdns)
        rows = []
        if 'raw_row_ref' in entity_df.columns:
            for msisdn in numbers:
                match = entity_df[
                    (entity_df['imei'].astype(str).str.strip() == imei) &
                    (entity_df['entity_ref'].astype(str).str.strip() == msisdn)
                ]
                if not match.empty:
                    rows.append(f"row_{match.iloc[0].get('raw_row_ref')}")
        findings.append((
            "HIGH",
            f"Device fan-out: a single handset (IMEI {imei}) was used to operate "
            f"{len(numbers)} different mobile numbers — {', '.join(numbers)}.",
            rows + [f"imei:{imei}", f"msisdn_count:{len(numbers)}",
                    f"msisdns:{'|'.join(numbers)}", "limb:device_fanout"],
        ))

    # ---- LIMB 2: account fan-out — the documented "3+ distinct accounts" ----
    if len(accounts) >= IDR1_MIN_ACCOUNTS:
        findings.append((
            "MEDIUM",
            f"Account fan-out: {len(accounts)} distinct bank accounts resolve to this "
            f"single identity (threshold {IDR1_MIN_ACCOUNTS}) — {', '.join(sorted(accounts))}.",
            [f"account_count:{len(accounts)}",
             f"accounts:{'|'.join(sorted(accounts))}", "limb:account_fanout"],
        ))

    # ---- LIMB 3: multiple devices — the documented "2+ IMEIs" ----
    if len(imeis) >= IDR1_MIN_IMEIS:
        findings.append((
            "MEDIUM",
            f"Device multiplicity: {len(imeis)} distinct IMEIs resolve to this single "
            f"identity (threshold {IDR1_MIN_IMEIS}) — {', '.join(sorted(imeis))}.",
            [f"imei_count:{len(imeis)}", f"imeis:{'|'.join(sorted(imeis))}",
             "limb:device_multiplicity"],
        ))

    # ---- LIMB 4: temporal swap — the device or SIM behind a number changed ----
    if not entity_df.empty:
        swap = _detect_identifier_swap(entity_df, window_minutes)
        if swap:
            severity, description, evidence = swap
            findings.append((severity, description, evidence + ["limb:identifier_swap"]))

    if not findings:
        return False, "", [], "LOW"

    # Corroboration across limbs is itself a signal: an entity that is BOTH fanned
    # out across accounts AND running several numbers off one handset is a stronger
    # case than either alone, so two or more limbs escalate to HIGH.
    findings.sort(key=lambda f: _SEVERITY_RANK.get(f[0], 0), reverse=True)
    severity = findings[0][0]
    if len(findings) > 1 and severity == "MEDIUM":
        severity = "HIGH"

    evidence = [f"severity:{severity}", f"limbs:{len(findings)}"]
    for _, _, tokens in findings:
        evidence.extend(tokens)

    explanation = (
        f"Identity Fan-out (IDR-1) [{severity} signal] for entity {entity_id}: "
        + " ".join(description for _, description, _ in findings)
    )
    if len(findings) > 1:
        explanation += (f" {len(findings)} independent fan-out indicators corroborate "
                        f"each other, which is why this is graded {severity}.")

    _append_trace(entity_id, "IDR-1", evidence, explanation)
    return True, explanation, evidence, severity


# ============================================================
# RULE TCS-1: Temporal Coincidence
# ============================================================
def check_tcs1(entity_id, enriched_txns):
    """
    TCS-1: Temporal Coincidence
    Both a call AND an active IP session fall within window W of a transaction.
    """
    if enriched_txns.empty:
        return False, "", []

    flagged = enriched_txns[
        enriched_txns['has_both_correlation'] == True
    ]

    if len(flagged) > 0:
        evidence = []
        details = []
        for _, row in flagged.iterrows():
            # merge_asof promotes an int column to float64 as soon as one row goes
            # unmatched, which is how "cdr_row_1018.0" ended up quoted as a source
            # reference in decision_trace.jsonl. A row number is an integer.
            txn_ref = f"bank_row_{_row_ref_text(row.get('raw_row_ref'))}"
            call_ref = f"cdr_row_{_row_ref_text(row.get('call_row_ref'))}"
            session_ref = f"ipdr_row_{_row_ref_text(row.get('session_row_ref'))}"
            evidence.extend([txn_ref, call_ref, session_ref])

            amt = abs(row.get('amount', 0))
            ts = row.get('timestamp', 'N/A')
            details.append(f"Transaction of {amt:.0f} at {ts}")

        explanation = (
            f"Temporal Coincidence: {len(flagged)} transaction(s) for entity {entity_id} "
            f"had BOTH a phone call AND an active IP session within the correlation window. "
            f"Details: {'; '.join(details[:3])}."
        )
        _append_trace(entity_id, "TCS-1", evidence, explanation)
        return True, explanation, evidence

    return False, "", []


# ============================================================
# RULE TCS-2: Call-Then-Transfer
# ============================================================
def check_tcs2(entity_id, all_events_df, window_minutes=15):
    """
    TCS-2: Call-Then-Transfer
    A phone call to a counterparty followed within 15 minutes by a financial transfer.
    """
    if all_events_df.empty:
        return False, "", []

    entity_events = _get_entity_df(entity_id, all_events_df).copy()
    if entity_events.empty:
        return False, "", []

    entity_events['timestamp'] = pd.to_datetime(entity_events['timestamp'])

    calls = entity_events[entity_events['event_type'].isin(['call', 'sms'])].sort_values('timestamp')
    txns = entity_events[entity_events['event_type'] == 'transaction'].sort_values('timestamp')

    if calls.empty or txns.empty:
        return False, "", []

    evidence = []
    details = []

    for _, txn in txns.iterrows():
        txn_time = txn['timestamp']
        txn_counterparty = str(txn.get('counterparty', '')).strip()

        # Look for calls within 1-15 minutes BEFORE this transaction
        window_start = txn_time - timedelta(minutes=window_minutes)
        window_end = txn_time - timedelta(minutes=1)

        matching_calls = calls[
            (calls['timestamp'] >= window_start) &
            (calls['timestamp'] <= window_end)
        ]

        if not matching_calls.empty:
            for _, call in matching_calls.iterrows():
                call_party = str(call.get('counterparty', '')).strip()
                # Check if the call counterparty is linked to the transaction counterparty
                # (simplified: any call within the window counts as suspicious)
                if call_party and txn_counterparty:
                    txn_ref = f"row_{txn.get('raw_row_ref', 'N/A')}"
                    call_ref = f"row_{call.get('raw_row_ref', 'N/A')}"
                    evidence.extend([txn_ref, call_ref])

                    amt = abs(txn.get('amount', 0))
                    gap = (txn_time - call['timestamp']).total_seconds() / 60
                    details.append(
                        f"Call to {call_party} at {call['timestamp']} ({gap:.0f} min before "
                        f"transfer of {amt:.0f} to {txn_counterparty})"
                    )

    if evidence:
        explanation = (
            f"Call-Then-Transfer pattern: {len(details)} instance(s) for entity {entity_id}. "
            f"A phone call preceded a financial transfer within {window_minutes} minutes. "
            f"Details: {'; '.join(details[:3])}."
        )
        _append_trace(entity_id, "TCS-2", evidence[:20], explanation)
        return True, explanation, evidence

    return False, "", []


# ============================================================
# RULE STR-1: Structuring
# ============================================================
def check_str1(entity_id, all_events_df, threshold=50000, count_min=3, window_hours=48):
    """
    STR-1: Structuring
    3+ outgoing transactions just under a reporting threshold within 24-48 hours.
    """
    if all_events_df.empty:
        return False, "", []

    entity_df = _get_entity_df(entity_id, all_events_df)
    entity_txns = entity_df[entity_df['event_type'] == 'transaction'].copy() if not entity_df.empty else pd.DataFrame()

    if entity_txns.empty:
        return False, "", []

    entity_txns['timestamp'] = pd.to_datetime(entity_txns['timestamp'])

    # Look for outgoing (debit) transactions just under threshold
    lower_bound = threshold * 0.90  # 90% of threshold
    suspicious = entity_txns[
        (entity_txns['amount'] < 0) &  # Debit
        (entity_txns['amount'].abs() >= lower_bound) &
        (entity_txns['amount'].abs() < threshold)
    ].sort_values('timestamp')

    if len(suspicious) < count_min:
        return False, "", []

    # Check sliding windows of exactly count_min consecutive suspicious transactions
    for i in range(len(suspicious) - count_min + 1):
        window = suspicious.iloc[i:i + count_min]
        time_span = (window['timestamp'].max() - window['timestamp'].min()).total_seconds() / 3600

        if time_span <= window_hours:
            evidence = [f"row_{row['raw_row_ref']}" for _, row in window.iterrows()]
            amounts = [f"{abs(row['amount']):.0f}" for _, row in window.iterrows()]

            explanation = (
                f"Structuring detected: {len(window)} outgoing transfers by entity {entity_id} "
                f"each just under the {threshold:.0f} threshold "
                f"(amounts: {', '.join(amounts)}) within {time_span:.1f} hours. "
                f"This pattern is consistent with deliberate threshold evasion."
            )
            _append_trace(entity_id, "STR-1", evidence, explanation)
            return True, explanation, evidence

    return False, "", []



# ============================================================
# RULE LAY-1: Layering / Circular Flow
# ============================================================
# LAY-1 tuning constants. These are the documented thresholds — the explanation
# string reports the measured values against them, it never asserts a pattern
# that was not checked.
LAY1_MIN_AMOUNT = 50000.0   # INR. Matches the CTR reporting threshold the layering
                            # is attempting to evade; below this a shrinking chain of
                            # transfers is ordinary retail behaviour, not layering.
LAY1_MIN_SKIM = 0.03        # Each hop must lose at least 3% (a genuine commission),
LAY1_MAX_SKIM = 0.20        # and at most 20%. Documented typology is a 5-15% skim;
                            # the band carries a small tolerance on either side.
LAY1_MAX_DEPTH = 6          # Hard cap on DFS depth — the search is otherwise
                            # exponential in the branching factor.


def build_outgoing_index(all_events_df):
    """
    Build {entity_id: [outgoing transfer, ...]} once for the whole dataset.

    Each entry is a plain dict holding only the four fields the LAY-1 walk needs,
    which keeps the per-hop scan cheap. Every entity's list is in ascending
    timestamp order, so the walk can stop scanning a list as soon as it passes the
    time window.

    Built once per run and handed to check_lay1 explicitly: the previous
    `id(all_events_df)` memo was unsound, because CPython reuses id() values after
    a garbage collection and two different frames could silently share one map.
    """
    if all_events_df is None or all_events_df.empty:
        return {}
    if 'event_type' not in all_events_df.columns or 'amount' not in all_events_df.columns:
        return {}

    txns = all_events_df[
        (all_events_df['event_type'] == 'transaction') & (all_events_df['amount'] < 0)
    ].copy()
    if txns.empty:
        return {}

    txns['timestamp'] = pd.to_datetime(txns['timestamp'])
    txns = txns.sort_values('timestamp')

    outgoing_by_entity = defaultdict(list)
    for eid, ts, cp, amt, ref in zip(
        txns['entity_id'],
        txns['timestamp'],
        txns['counterparty'] if 'counterparty' in txns.columns else [None] * len(txns),
        txns['amount'].abs(),
        txns['raw_row_ref'] if 'raw_row_ref' in txns.columns else [None] * len(txns),
    ):
        outgoing_by_entity[eid].append({
            "timestamp": ts,
            "counterparty": "" if cp is None or pd.isna(cp) else str(cp).strip(),
            "amount": float(amt),
            "raw_row_ref": ref,
        })

    return dict(outgoing_by_entity)


def check_lay1(entity_id, all_events_df, entity_map=None, min_hops=3, max_hours=12,
               outgoing_by_entity=None, min_amount=LAY1_MIN_AMOUNT,
               min_skim=LAY1_MIN_SKIM, max_skim=LAY1_MAX_SKIM, max_depth=LAY1_MAX_DEPTH):
    """
    LAY-1: Layering / Circular Flow

    Walks the transfer graph outward from `entity_id`, following hops that occur
    within `max_hours` of the previous hop and lose between `min_skim` and
    `max_skim` of their value (the commission the layer takes). A chain qualifies
    at `min_hops` distinct entities.

    A hop that returns to the entity the chain started from closes a **cycle** —
    that is checked for explicitly and reported only when it actually happened.
    Intermediate entities may not be revisited, which is what bounds the walk.

    `outgoing_by_entity` is the shared index from build_outgoing_index(); pass it
    to avoid rebuilding the map per entity. If omitted it is built from
    `all_events_df`, which must therefore be the GLOBAL event frame — a chain
    spans several entities, so a single entity's rows can never contain one.
    """
    if not entity_map:
        return False, "", []

    if outgoing_by_entity is None:
        if all_events_df is None or all_events_df.empty:
            return False, "", []
        outgoing_by_entity = build_outgoing_index(all_events_df)

    # Get outgoing transactions from this entity
    outgoing = outgoing_by_entity.get(entity_id, [])
    if not outgoing:
        return False, "", []

    # Best chain seen so far, ranked by (closes a cycle, number of hops).
    best = {"chain": [], "evidence": [], "amounts": [], "times": [], "cycle": False}

    def consider(path, path_evidence, path_amounts, path_times, closes_cycle):
        if len(path) < min_hops:
            return
        rank = (closes_cycle, len(path))
        best_rank = (best["cycle"], len(best["chain"]))
        if rank > best_rank:
            best.update(chain=list(path), evidence=list(path_evidence),
                        amounts=list(path_amounts), times=list(path_times),
                        cycle=closes_cycle)

    def dfs(curr_entity, curr_time, curr_amount, path, path_evidence, path_amounts, path_times):
        consider(path, path_evidence, path_amounts, path_times, closes_cycle=False)

        if len(path) - 1 >= max_depth:
            return

        # Outgoing transfers from curr_entity, after curr_time, within max_hours.
        # The list is timestamp-ordered, so we can stop at the first one past the window.
        deadline = curr_time + timedelta(hours=max_hours)
        for txn in outgoing_by_entity.get(curr_entity, []):
            t_time = txn["timestamp"]
            if t_time <= curr_time:
                continue
            if t_time > deadline:
                break

            cp = txn["counterparty"]
            if not cp:
                continue
            cp_entity = entity_map.get(cp)
            if not cp_entity:
                continue

            # Commission skim: this hop must give up between min_skim and max_skim
            # of the previous hop's value.
            next_amount = txn["amount"]
            if not (curr_amount * (1 - max_skim) <= next_amount <= curr_amount * (1 - min_skim)):
                continue

            hop_evidence = path_evidence + [f"row_{txn['raw_row_ref']}"]
            hop_amounts = path_amounts + [next_amount]
            hop_times = path_times + [t_time]

            if cp_entity == path[0]:
                # Funds returned to the entity the chain started from: a real cycle.
                # Record it and stop — walking on through the origin would revisit it.
                consider(path + [cp_entity], hop_evidence, hop_amounts, hop_times,
                         closes_cycle=True)
                continue
            if cp_entity in path:
                continue

            dfs(
                curr_entity=cp_entity,
                curr_time=t_time,
                curr_amount=next_amount,
                path=path + [cp_entity],
                path_evidence=hop_evidence,
                path_amounts=hop_amounts,
                path_times=hop_times,
            )

    for txn in outgoing:
        cp = txn["counterparty"]
        if not cp:
            continue
        cp_entity = entity_map.get(cp)
        if not cp_entity or cp_entity == entity_id:
            continue

        # Amount floor: only applied to the head of the chain. Later hops are
        # bounded below by the skim band anyway.
        start_amount = txn["amount"]
        if start_amount < min_amount:
            continue

        dfs(
            curr_entity=cp_entity,
            curr_time=txn["timestamp"],
            curr_amount=start_amount,
            path=[entity_id, cp_entity],
            path_evidence=[f"row_{txn['raw_row_ref']}"],
            path_amounts=[start_amount],
            path_times=[txn["timestamp"]],
        )

    chain = best["chain"]
    if len(chain) < min_hops:
        return False, "", []

    amounts = best["amounts"]
    times = best["times"]
    time_span = (max(times) - min(times)).total_seconds() / 3600 if times else 0

    # Per-hop skim, measured — not assumed.
    skims = [
        (amounts[i] - amounts[i + 1]) / amounts[i] * 100
        for i in range(len(amounts) - 1)
        if amounts[i]
    ]
    skim_text = ", ".join(f"{s:.1f}%" for s in skims) if skims else "n/a"

    if best["cycle"]:
        shape = (
            f"Circular flow confirmed: funds left {chain[0]} and returned to it "
            f"after {len(chain) - 1} hops"
        )
    else:
        shape = (
            f"Layering chain: funds passed through {len(chain)} entities "
            f"(no return to {chain[0]} observed within the {max_hours}h window)"
        )

    explanation = (
        f"{shape} ({' -> '.join(chain)}) over {time_span:.1f} hours. "
        f"Amounts: {', '.join(f'{a:.0f}' for a in amounts)}. "
        f"Value lost per hop: {skim_text} — consistent with a commission skim "
        f"of {min_skim * 100:.0f}-{max_skim * 100:.0f}% at every hop."
    )

    evidence = list(best["evidence"])
    evidence.append(f"cycle:{'true' if best['cycle'] else 'false'}")
    evidence.append(f"hops:{len(chain) - 1}")
    if skims:
        evidence.append("skim_pct:" + ",".join(f"{s:.1f}" for s in skims))
    # The path itself is part of the finding, so it is emitted as structured
    # evidence rather than only inside the prose. The money-flow graph reads this
    # to light up exactly the hops that were walked.
    evidence.append("chain:" + ">".join(chain))

    _append_trace(entity_id, "LAY-1", evidence, explanation)
    return True, explanation, evidence


# ============================================================
# RULE MUL-1: Mule Signature
# ============================================================
def check_mul1(entity_id, all_events_df, dormancy_days=30, outflow_pct=0.80):
    """
    MUL-1: Mule Signature
    30+ days of dormancy, then a large inflow, then 80%+ of it
    outflowing within hours, low retained balance.
    """
    if all_events_df.empty:
        return False, "", []

    entity_df = _get_entity_df(entity_id, all_events_df)
    entity_txns = entity_df[
        (entity_df['event_type'] == 'transaction')
    ].copy() if not entity_df.empty else pd.DataFrame()

    if len(entity_txns) < 3:
        return False, "", []

    entity_txns['timestamp'] = pd.to_datetime(entity_txns['timestamp'])
    entity_txns = entity_txns.sort_values('timestamp')

    # Find large inflows (credits)
    credits = entity_txns[entity_txns['amount'] > 0].copy()
    debits = entity_txns[entity_txns['amount'] < 0].copy()

    for _, credit_row in credits.iterrows():
        credit_amount = credit_row['amount']
        credit_time = credit_row['timestamp']

        # Check if this is a "large" inflow (> 100k or > 5x the entity's typical credit)
        median_credit = credits['amount'].median()
        if credit_amount < 100000 and credit_amount < median_credit * 3:
            continue

        # Check dormancy: look for activity in the 30 days BEFORE this credit
        dormancy_start = credit_time - timedelta(days=dormancy_days)
        prior_activity = entity_txns[
            (entity_txns['timestamp'] >= dormancy_start) &
            (entity_txns['timestamp'] < credit_time) &
            (entity_txns['amount'].abs() > 10)  # Ignore micro transactions < INR 10
        ]

        if len(prior_activity) > 2:
            # Not dormant enough
            continue

        # Check rapid outflow after the credit
        outflow_window = credit_time + timedelta(hours=6)
        subsequent_debits = debits[
            (debits['timestamp'] > credit_time) &
            (debits['timestamp'] <= outflow_window)
        ]

        if subsequent_debits.empty:
            continue

        total_outflow = subsequent_debits['amount'].abs().sum()
        outflow_ratio = total_outflow / credit_amount

        if outflow_ratio >= outflow_pct:
            evidence = [f"row_{credit_row['raw_row_ref']}"]
            evidence.extend([f"row_{r['raw_row_ref']}" for _, r in subsequent_debits.iterrows()])

            explanation = (
                f"Mule Signature detected: entity {entity_id} was dormant for {dormancy_days}+ days, "
                f"received {credit_amount:.0f}, then moved {total_outflow:.0f} "
                f"({outflow_ratio:.0%} of inflow) within "
                f"{(subsequent_debits['timestamp'].max() - credit_time).total_seconds() / 3600:.1f} hours. "
                f"Balance returned near-zero."
            )
            _append_trace(entity_id, "MUL-1", evidence, explanation)
            return True, explanation, evidence

    return False, "", []


# ============================================================
# RULE LOC-1: Geo-Improbable / Impossible Travel Physics Check
# ============================================================
import math

CITY_COORDINATES = {
    "SURAT": (21.1702, 72.8311, "Surat"),
    "MUMBAI": (19.0760, 72.8777, "Mumbai"),
    "DELHI": (28.6139, 77.2090, "Delhi"),
    "BANGALORE": (12.9716, 77.5946, "Bangalore"),
    "AHMEDABAD": (23.0225, 72.5714, "Ahmedabad"),
    "PUNE": (18.5204, 73.8567, "Pune"),
    "HYDERABAD": (17.3850, 78.4867, "Hyderabad"),
    "CHENNAI": (13.0827, 80.2707, "Chennai"),
}

IP_PREFIX_COORDINATES = {
    "103.21": (19.0760, 72.8777, "Mumbai"),
    "103.22": (28.6139, 77.2090, "Delhi"),
    "103.23": (12.9716, 77.5946, "Bangalore"),
    "103.24": (23.0225, 72.5714, "Ahmedabad"),
    "103.25": (21.1702, 72.8311, "Surat"),
    "103.26": (18.5204, 73.8567, "Pune"),
    "103.27": (17.3850, 78.4867, "Hyderabad"),
    "103.28": (13.0827, 80.2707, "Chennai"),
}


def haversine_distance_km(lat1, lon1, lat2, lon2):
    """Calculate Great Circle (Haversine) distance in kilometers between two points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2.0) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


def load_tower_master(data_dir=None):
    """
    Load tower master coordinates map from tower_master.csv and built-in CELL_TOWERS.
    Returns dict mapping Tower ID, Cell ID, and City Names -> {lat, lon, label, city}.
    """
    tower_map = {}

    # Built-in cell towers
    try:
        from graph.map_builder import CELL_TOWERS
        for tid, info in CELL_TOWERS.items():
            label = f"{info.get('area', '')}, {info.get('city', '')}".strip(", ")
            entry = {
                "lat": float(info["lat"]),
                "lon": float(info["lon"]),
                "city": info.get("city", ""),
                "area": info.get("area", ""),
                "label": label,
            }
            tower_map[tid.upper()] = entry
    except Exception as e:
        print(f"  Warning loading CELL_TOWERS: {e}")

    # Search for tower_master.csv
    search_paths = []
    if data_dir:
        search_paths.append(Path(data_dir) / "tower_master.csv")
    backend_dir = Path(__file__).resolve().parent.parent
    search_paths.append(backend_dir / "data" / "uploaded" / "tower_master.csv")
    search_paths.append(backend_dir / "data" / "raw" / "tower_master.csv")

    for path in search_paths:
        if path.exists():
            try:
                df = pd.read_csv(path)
                col_map = {str(c).lower().strip(): c for c in df.columns}
                lat_col = col_map.get("latitude") or col_map.get("lat")
                lon_col = col_map.get("longitude") or col_map.get("lon") or col_map.get("long")
                tower_col = col_map.get("tower id") or col_map.get("tower_id") or col_map.get("tower")
                cell_col = col_map.get("cell id") or col_map.get("cell_id") or col_map.get("cell")
                address_col = col_map.get("address") or col_map.get("area") or col_map.get("city")

                if lat_col and lon_col:
                    for _, row in df.iterrows():
                        try:
                            lat = float(row[lat_col])
                            lon = float(row[lon_col])
                            addr = str(row[address_col]).strip() if address_col and pd.notna(row[address_col]) else ""
                            entry = {"lat": lat, "lon": lon, "label": addr}

                            if tower_col and pd.notna(row[tower_col]):
                                tid = str(row[tower_col]).strip().upper()
                                tower_map[tid] = entry
                            if cell_col and pd.notna(row[cell_col]):
                                cid = str(row[cell_col]).strip()
                                if cid.endswith(".0"):
                                    cid = cid[:-2]
                                tower_map[cid.upper()] = entry
                        except (ValueError, TypeError):
                            continue
            except Exception as e:
                print(f"  Warning reading tower_master.csv at {path}: {e}")
            break

    return tower_map


def resolve_event_coordinates(event_row, tower_map=None):
    """
    Resolve real Latitude, Longitude, and Location Label for any event.
    Returns (lat, lon, label_name) or None if unresolvable.
    """
    loc_val = str(event_row.get('location', '') or '').strip()
    ip_val = str(event_row.get('_public_ip', '') or event_row.get('public_ip', '') or '').strip()

    # 1. Try resolving via tower_map (from tower_master.csv + CELL_TOWERS)
    if loc_val and tower_map:
        loc_key = loc_val.upper()
        if loc_key in tower_map:
            t = tower_map[loc_key]
            return float(t['lat']), float(t['lon']), t.get('label') or loc_val
        cleaned_loc = loc_val.split('.')[0]
        if cleaned_loc in tower_map:
            t = tower_map[cleaned_loc]
            return float(t['lat']), float(t['lon']), t.get('label') or loc_val

    # 2. Try built-in CELL_TOWERS lookup directly
    try:
        from graph.map_builder import CELL_TOWERS
        if loc_val and loc_val in CELL_TOWERS:
            t = CELL_TOWERS[loc_val]
            label = f"{t.get('area', '')}, {t.get('city', '')}".strip(", ")
            return float(t['lat']), float(t['lon']), label

        if loc_val:
            for tid, t in CELL_TOWERS.items():
                if loc_val.upper().startswith(tid.split('-')[0]):
                    label = f"{t.get('area', '')}, {t.get('city', '')}".strip(", ")
                    return float(t['lat']), float(t['lon']), label
    except Exception:
        pass

    # 3. Try IP prefix resolution
    if ip_val:
        for prefix, (lat, lon, city) in IP_PREFIX_COORDINATES.items():
            if ip_val.startswith(prefix):
                return lat, lon, f"IP-Geo ({city})"

    # 4. Try Direct City Name Match
    if loc_val:
        for city_key, (lat, lon, city_name) in CITY_COORDINATES.items():
            if city_key in loc_val.upper():
                return lat, lon, city_name

    return None


def check_loc1(entity_id, entity_df, tower_map=None, max_speed_kmh=200.0):
    """
    LOC-1: Geo-Improbable / Impossible Travel Physics Check
    Computes real Haversine distance in km, elapsed time in hours, and implied speed in km/h
    between consecutive events for the entity.

    Fires ONLY when implied speed exceeds realistic max travel threshold (~150-200 km/h).
    """
    if entity_df.empty:
        return False, "", []

    entity_events = entity_df[entity_df['timestamp'].notna()].copy()

    if len(entity_events) < 2:
        return False, "", []

    entity_events['timestamp'] = pd.to_datetime(entity_events['timestamp'])
    entity_events = entity_events.sort_values('timestamp')

    resolved_events = []
    for idx, row in entity_events.iterrows():
        coords = resolve_event_coordinates(row, tower_map=tower_map)
        if coords:
            lat, lon, label = coords
            resolved_events.append({
                "raw_row_ref": row.get('raw_row_ref', idx),
                "timestamp": row['timestamp'],
                "event_type": row.get('event_type', 'event'),
                "lat": lat,
                "lon": lon,
                "label": label,
            })

    if len(resolved_events) < 2:
        return False, "", []

    for i in range(len(resolved_events) - 1):
        e1 = resolved_events[i]
        e2 = resolved_events[i + 1]

        d_km = haversine_distance_km(e1['lat'], e1['lon'], e2['lat'], e2['lon'])

        # Skip if events are at virtually the same spot (< 1.0 km)
        if d_km < 1.0:
            continue

        time_gap_sec = (e2['timestamp'] - e1['timestamp']).total_seconds()
        if time_gap_sec < 0:
            continue

        time_gap_hrs = max(time_gap_sec / 3600.0, 0.00028)  # min 1 second
        implied_speed = d_km / time_gap_hrs

        if implied_speed > max_speed_kmh:
            time_gap_mins = time_gap_sec / 60.0
            evidence = [
                f"row_{e1['raw_row_ref']}",
                f"row_{e2['raw_row_ref']}",
                f"distance_km:{d_km:.1f}",
                f"speed_kmh:{implied_speed:.1f}",
                f"time_mins:{time_gap_mins:.1f}",
            ]

            explanation = (
                f"Geo-Improbable travel (LOC-1) for entity {entity_id}: "
                f"event at {e1['label']} ({e1['event_type']}) and event at {e2['label']} ({e2['event_type']}) "
                f"are {d_km:.1f} km apart with elapsed time of {time_gap_mins:.1f} mins ({time_gap_hrs:.2f} hrs). "
                f"Implied travel speed: {implied_speed:.1f} km/h (exceeds plausible max travel speed threshold of {max_speed_kmh:.0f} km/h)."
            )

            _append_trace(entity_id, "LOC-1", evidence, explanation)
            return True, explanation, evidence

    return False, "", []


# ============================================================
# RUN ALL RULES
# ============================================================
def run_all_rules(entities, all_events_df, enriched_txns, entity_map=None, window_minutes=15, data_dir=None):
    """
    Run all named rules for all entities.
    Returns dict: {entity_id: {rules_fired: [...], explanations: {...}, evidence: {...}}}
    """
    print("\n[Rule Engine] Running deterministic rules...")
    clear_trace()

    # Pre-load tower master coordinate map for LOC-1
    tower_map = load_tower_master(data_dir=data_dir)

    results = {}

    # Pre-group events by entity_id to avoid O(E * N) dataframe scans
    events_by_entity = dict(tuple(all_events_df.groupby('entity_id'))) if not all_events_df.empty and 'entity_id' in all_events_df.columns else {}
    enriched_by_entity = dict(tuple(enriched_txns.groupby('entity_id'))) if not enriched_txns.empty and 'entity_id' in enriched_txns.columns else {}

    # LAY-1 walks a chain ACROSS entities (A -> B -> C -> D), so it needs the whole
    # transfer graph, not one entity's slice. Build that index once here and hand the
    # same object to every call.
    outgoing_by_entity = build_outgoing_index(all_events_df)

    for entity_id, entity_data in entities.items():
        entity_results = {
            "rules_fired": [],
            "explanations": {},
            "evidence": {},
            "rule_severities": {},
        }

        entity_df = events_by_entity.get(entity_id, pd.DataFrame())
        entity_enriched = enriched_by_entity.get(entity_id, pd.DataFrame())

        # Fast path: skip entities with zero events and no phone/acct data
        if entity_df.empty and not entity_data.get('phones') and not entity_data.get('accounts'):
            results[entity_id] = entity_results
            continue

        # IDR-1: Identity Fan-out (SIM Swap / Device Upgrade Check with Sub-levels)
        res_idr1 = check_idr1(entity_id, entity_data, entity_df)
        if len(res_idr1) == 4:
            fired, explanation, evidence, severity = res_idr1
        else:
            fired, explanation, evidence = res_idr1
            severity = "MEDIUM"

        if fired:
            entity_results["rules_fired"].append("IDR-1")
            entity_results["explanations"]["IDR-1"] = explanation
            entity_results["evidence"]["IDR-1"] = evidence
            entity_results["rule_severities"]["IDR-1"] = severity

        # TCS-1: Temporal Coincidence
        fired, explanation, evidence = check_tcs1(entity_id, entity_enriched)
        if fired:
            entity_results["rules_fired"].append("TCS-1")
            entity_results["explanations"]["TCS-1"] = explanation
            entity_results["evidence"]["TCS-1"] = evidence
            entity_results["rule_severities"]["TCS-1"] = "MEDIUM"

        # TCS-2: Call-Then-Transfer
        fired, explanation, evidence = check_tcs2(entity_id, entity_df, window_minutes)
        if fired:
            entity_results["rules_fired"].append("TCS-2")
            entity_results["explanations"]["TCS-2"] = explanation
            entity_results["evidence"]["TCS-2"] = evidence
            entity_results["rule_severities"]["TCS-2"] = "MEDIUM"

        # STR-1: Structuring
        fired, explanation, evidence = check_str1(entity_id, entity_df)
        if fired:
            entity_results["rules_fired"].append("STR-1")
            entity_results["explanations"]["STR-1"] = explanation
            entity_results["evidence"]["STR-1"] = evidence
            entity_results["rule_severities"]["STR-1"] = "HIGH"

        # LAY-1: Layering — driven by the global transfer index, not entity_df
        fired, explanation, evidence = check_lay1(
            entity_id, all_events_df, entity_map,
            outgoing_by_entity=outgoing_by_entity,
        )
        if fired:
            entity_results["rules_fired"].append("LAY-1")
            entity_results["explanations"]["LAY-1"] = explanation
            entity_results["evidence"]["LAY-1"] = evidence
            entity_results["rule_severities"]["LAY-1"] = "HIGH"

        # MUL-1: Mule Signature
        fired, explanation, evidence = check_mul1(entity_id, entity_df)
        if fired:
            entity_results["rules_fired"].append("MUL-1")
            entity_results["explanations"]["MUL-1"] = explanation
            entity_results["evidence"]["MUL-1"] = evidence
            entity_results["rule_severities"]["MUL-1"] = "HIGH"

        # LOC-1: Geo-Improbable Physics Check
        fired, explanation, evidence = check_loc1(entity_id, entity_df, tower_map=tower_map)
        if fired:
            entity_results["rules_fired"].append("LOC-1")
            entity_results["explanations"]["LOC-1"] = explanation
            entity_results["evidence"]["LOC-1"] = evidence
            entity_results["rule_severities"]["LOC-1"] = "HIGH"

        results[entity_id] = entity_results

    # Summary
    total_fired = sum(len(r["rules_fired"]) for r in results.values())
    entities_flagged = sum(1 for r in results.values() if r["rules_fired"])
    print(f"  Total rule firings: {total_fired}")
    print(f"  Entities flagged: {entities_flagged}")

    for eid, r in results.items():
        if r["rules_fired"]:
            print(f"    {eid}: {', '.join(r['rules_fired'])}")

    return results
