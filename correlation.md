# CORRELATION.md — Entity Resolution + Temporal Fusion + Rule Engine

This is the actual differentiator of the whole project. Everything else is plumbing around this.

## 1. Layer 1 — Entity Resolution (who is actually who)

Real accounts/numbers/IPs never come with a "this is the same person" flag. You build that
yourself as a graph problem, the same way MITRE's SEXTANT approach does spatio-temporal
multi-protocol entity resolution, and the same way real mule-ring detection works (shared
identifiers linking multiple accounts).

**Algorithm:**
1. Create one graph node per RAW identifier seen anywhere: every phone number, IMEI, IP,
   account number, UPI VPA.
2. Add an edge between two identifiers whenever they co-occur as the "same person" in a
   source record:
   - phone ↔ IMEI (same handset, from CDR)
   - phone ↔ account (KYC linkage / narration text mentions the phone)
   - IP ↔ account (net-banking/session login IP, if simulated)
   - account ↔ UPI VPA (extracted from bank narration text)
   - IMEI ↔ multiple phones (SIM swap detection — same device, different SIM over time)
3. Run connected-components (networkx.connected_components) on this graph.
4. Each connected component = one resolved `entity_id`. This is what lets you say "this
   suspect used 3 SIMs and 2 bank accounts but it's the same person" — that's a real,
   demo-able "wow" moment.

**Why this matters for scoring:** all events from all identifiers in one component get
attributed to ONE entity before you do anything else. Skipping this step means your
correlation will silently miss mule rings that intentionally spread activity across
multiple numbers/accounts — which is exactly how real mule networks try to evade detection.

## 2. Layer 2 — Temporal Correlation (the actual "fusion")

For each resolved entity, build three separate timestamp-sorted event lists: calls, IP
sessions, transactions. Then run a windowed join — NOT a nested loop, use
`pandas.merge_asof(..., direction='nearest', tolerance=pd.Timedelta(minutes=W))` per entity,
sorted by timestamp. This is O(n log n) per entity from the sort, so it scales to thousands
of rows without any special infrastructure.

```python
# pseudocode, this is close to literal implementation
for entity_id, txns in transactions.groupby('entity_id'):
    calls_e = calls[calls.entity_id == entity_id].sort_values('timestamp')
    sessions_e = ip_sessions[ip_sessions.entity_id == entity_id].sort_values('timestamp')
    txns = txns.sort_values('timestamp')

    joined_calls = pd.merge_asof(txns, calls_e, on='timestamp',
                                  direction='nearest', tolerance=pd.Timedelta(minutes=10),
                                  suffixes=('', '_call'))
    joined_sessions = pd.merge_asof(txns, sessions_e, on='timestamp',
                                     direction='nearest', tolerance=pd.Timedelta(minutes=10),
                                     suffixes=('', '_session'))
    # a transaction row now has a matched call and/or matched ip session, or neither
```

Make the window (`W`) a configurable parameter exposed in the UI — this doubles as your
"natural language query" bonus feature seed ("show every transfer within 10 minutes of a
call to X" is just this join with a counterparty filter and a slider for W).

## 3. Layer 3 — Named Deterministic Rules (your explainability backbone)

Never sum scores linearly. Gate on named rules so every flag has a one-line human reason —
this is the exact lesson from the MALCORE audit: linear independent scoring let critically
dangerous cases slip through with low scores. Same failure mode applies here if you just
add up "risk points."

| Rule ID | Name | Fires when |
|---|---|---|
| **IDR-1** | Identity Fan-out | One resolved entity's identifiers fan out past a single subscriber's footprint: one IMEI operating 2+ MSISDNs (**HIGH** — a handset cycling SIMs), 3+ distinct accounts, or 2+ IMEIs (**MEDIUM**; two limbs together escalate to HIGH). A device/SIM swap on one number is also caught, graded by whether a transfer sits near the change — mule/evasion signature |
| **TCS-1** | Temporal Coincidence | A call AND an active IP session both fall within window W of a transaction |
| **TCS-2** | Call-Then-Transfer | A call to a specific B-party occurs 1-15 min before a transfer to a linked account/VPA of that number |
| **STR-1** | Structuring | 3+ transactions just under a reporting threshold (e.g. ₹49,000 near ₹50,000) within 24-48 hrs |
| **LAY-1** | Layering/Circular Flow | A→B→C→D→(back toward A or a related entity) within hours, amounts shrinking ~5-15% each hop (commission skim) |
| **MUL-1** | Mule Signature | Account dormant (near-zero activity) for 30+ days, then sudden large inflow, then 80%+ outflow within minutes-to-hours, low balance retention |
| **LOC-1** | Geo-Improbable | Two events for the same entity in incompatible cell-tower/IP-geo locations within an impossible travel time |

**Scoring gate logic (not a sum):**
```
if MUL-1 fires AND (TCS-1 or TCS-2 fires):
    risk_tier = CRITICAL   # corroborated mule behavior — highest confidence
elif LAY-1 fires AND IDR-1 fires:
    risk_tier = CRITICAL   # organized layering across a fan-out identity cluster
elif STR-1 fires OR MUL-1 fires OR LAY-1 fires:
    risk_tier = HIGH
elif TCS-1 or TCS-2 fires alone:
    risk_tier = MEDIUM     # corroborating signal but no anomalous money pattern yet
else:
    risk_tier = LOW
```
The point: a single rule firing alone should rarely mean CRITICAL. Corroboration across
independent rule categories (identity + timing + money-pattern) is what should escalate —
this is what makes your scoring defensible when a judge asks "why isn't every big transfer
flagged critical."

## 4. Layer 4 — ML as a secondary net, not the primary decision

Run `sklearn.ensemble.IsolationForest` on a per-entity feature vector (txn velocity, avg
balance-hold time, in/out amount ratio, unique-counterparty count, call/session frequency)
purely to catch entities that don't match any named rule but still look statistically
unusual. Tag these as `ML-FLAG` separately from rule-tier — never let the ML score silently
override or blend into the deterministic tier. Keep them visually and logically separate in
the UI ("Rule-based: HIGH | ML anomaly: also flagged") — that separation IS your
explainability story.

## 5. Graph construction (money-flow + comms network)

```python
G = nx.DiGraph()
# nodes = entity_id, attrs = {risk_tier, resolved_identifiers}
# edges:
#   transaction edges: G.add_edge(sender, receiver, type='txn', amount=..., timestamp=...)
#   comms edges: G.add_edge(caller, callee, type='call', timestamp=..., duration=...)
# edge weight = amount for txn edges, frequency count for call edges
# color/highlight edges where a TCS-1/TCS-2 rule fired (the "smoking gun" edges)
```
Drill-down = clicking a node/edge in the frontend shows the underlying rows + which rule
fired + link to `decision_trace.jsonl` entry. This satisfies "clarity of visualization" and
"quality of correlation" rubric lines simultaneously.

## 6. What to say if a judge asks "how does this scale to real data volume"
Windowed `merge_asof` per entity is O(n log n) in events-per-entity, and entities process
independently — this parallelizes trivially (multiprocessing pool over entity_id groups) and
maps directly onto a Spark/Elastic backend at production scale without changing the
correlation logic itself, only the execution engine. Say exactly this — it shows you
understand the scale question without needing to have actually built the Spark version.
