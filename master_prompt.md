# MASTER_PROMPT.md — Feed this whole thing to Antigravity

---

You are a senior cybersecurity engineer and financial-crime forensics developer. Build a
complete, working prototype for a hackathon problem statement: an AI-powered tool that fuses
bank statements, Call Detail Records (CDR), and Internet Protocol Detail Records (IPDR) into
one unified investigation timeline, resolves identities across all three sources, detects
fraud patterns using deterministic named rules (not black-box scoring), and produces an
investigation-ready forensic report. This mirrors how real Indian cyber cells trace fund
trails via the NCRP Layer 1→2→3→4 model, and how I4C's Suspect Registry/Samanvaya platform
link mule accounts and cases nationally — you are building a single-case, deployable version
of that same idea. Think like an investigator who needs to defend every number you produce
to a skeptical panel, not like someone optimizing a leaderboard metric.

## Build in this exact order. Do not skip or reorder steps.

### STEP 1 — Synthetic Data Generation (build and run this first, verify output before continuing)
Generate one internal ground-truth entity/event graph, then export it into 3 realistically
inconsistent formats simulating 3 different institutions:
- 35-45 "normal" entities with realistic salaried/consumer transaction and call/session
  behavior, natural noise, no embedded anomaly.
- 4-6 "guilty" entities, each assigned exactly ONE of these fraud typologies:
  - **Structuring**: large fraud credit followed by 4-6 outgoing transfers just under
    ₹49,000-49,900 within 24-48 hours to 2-3 accounts.
  - **Layering/Circular Flow**: A→B→C→D→(back to A's cluster) across 3-4 hops within
    hours, 5-15% commission skim each hop, with a phone call 2-10 minutes before each
    transfer and an overlapping IP session at each transfer timestamp.
  - **Mule Signature**: 30+ days dormant, then one large inflow, then 80-95% moved out
    within minutes-to-hours, balance returns near-zero.
  - **Identity Fan-out**: one IMEI operating 3 phone numbers (simulated SIM swaps) and
    2-3 bank accounts, spreading one typology's activity across them to look unrelated
    until identity resolution collapses them.
  - **Geo-Improbable** (optional): a call from one city's cell tower and an IP session
    geolocated elsewhere within an impossible travel time.
- Write `ground_truth.json` listing every guilty entity, its typology, its resolved
  identifiers, and the exact rows that should later be flagged — you will use this file to
  self-verify detection recall/precision after building the pipeline.
- Export to 3 inconsistent bank formats (xlsx with `Txn Date/Value Date/Description/
  Debit/Credit/Balance` columns and DD-MM-YYYY dates and UPI-style narration; csv with
  different column names and YYYY/MM/DD dates and IMPS-style narration; pdf table via
  reportlab with a DR/CR type column and DD/MM/YY dates), plus one CDR csv
  (`A_PARTY,B_PARTY,CALL_TYPE,START_TIME,DURATION_SEC,CELL_ID,IMEI`) and one IPDR csv
  (`MSISDN,PRIVATE_IP,PUBLIC_IP,PORT,SESSION_START,SESSION_END,DEST_IP,DATA_VOLUME_KB`).
  Deliberately inject a few missing values, one duplicate row, and one header/column
  anomaly in the PDF export. Use Faker with `en_IN` locale for names. Target 1,500-3,000
  total events across all entities — enough to look substantial, small enough to run in
  seconds.

### STEP 2 — Ingestion Layer
Build three parsers (`bank_parser.py`, `cdr_parser.py`, `ipdr_parser.py`) that each take one
of the messy source formats and output rows conforming to ONE canonical `Event` schema:
`entity_ref, event_type (call|sms|ip_session|transaction), timestamp, end_timestamp,
amount, counterparty, location, source_file, raw_row_ref`. The bank parser must handle all
3 different bank layouts (auto-detect columns, don't hardcode one schema), extract UPI VPA /
beneficiary references out of free-text narration via regex, and normalize all 3 different
date formats. Use `pdfplumber` for the PDF bank statement, `openpyxl`/`pandas` for xlsx/csv.

### STEP 3 — Entity Resolution
Build `entity_resolver.py`: construct a graph where nodes are every raw identifier seen
(phone, IMEI, IP, account number, UPI VPA) and edges connect identifiers that co-occur as
the same person in any source record (phone↔IMEI from CDR, account↔UPI VPA from bank
narration, IP↔account if simulated login sessions exist, IMEI↔multiple phones for SIM-swap
linkage). Run connected-components (NetworkX) to produce one resolved `entity_id` per
component. All downstream processing operates on resolved `entity_id`, never on raw
identifiers directly.

### STEP 4 — Temporal Correlation Engine
Build `temporal_join.py`: for each resolved entity, sort its call/session/transaction events
by timestamp and run a windowed join using `pandas.merge_asof(direction='nearest',
tolerance=pd.Timedelta(minutes=W))` where W is a configurable parameter (default 10,
exposed as a UI slider). This tags each transaction with its nearest call and nearest IP
session, if any exist within the window. This must be O(n log n) per entity, not a nested
loop — do not write brute-force pairwise comparisons.

### STEP 5 — Named Rule Engine (deterministic, this is the explainability backbone)
Build `rules.py` implementing these exact named rules, each returning a boolean plus a
human-readable explanation string and the specific row references that caused it to fire:
- `IDR-1` Identity Fan-out: entity linked to 3+ accounts or 2+ IMEIs.
- `TCS-1` Temporal Coincidence: both a call and an active IP session fall within window W
  of a transaction.
- `TCS-2` Call-Then-Transfer: a call to a specific number occurs 1-15 minutes before a
  transfer to an account/VPA linked to that number.
- `STR-1` Structuring: 3+ transactions just under a reporting threshold within 24-48 hours.
- `LAY-1` Layering: a chain of transfers across 3+ entities within hours, amounts shrinking
  5-15% per hop, forming a cycle or near-cycle.
- `MUL-1` Mule Signature: 30+ days of dormancy, then a large inflow, then 80%+ of it
  outflowing within hours, low retained balance.
- `LOC-1` Geo-Improbable (optional): incompatible locations within impossible travel time.

Every rule firing must append one line to `decision_trace.jsonl`:
`{timestamp, entity_id, rule_id, evidence_row_refs, explanation}`. This file is
non-negotiable — build it in from the start, not as an afterthought.

### STEP 6 — Compound Risk Scoring (gated, never a linear sum)
Build `risk_engine.py` implementing a GATED decision tree, not additive scoring:
- CRITICAL if (`MUL-1` fires AND (`TCS-1` or `TCS-2` fires)), OR (`LAY-1` fires AND `IDR-1` fires).
- HIGH if `STR-1` or `MUL-1` or `LAY-1` fires alone.
- MEDIUM if only `TCS-1`/`TCS-2` fires with no anomalous money pattern.
- LOW otherwise.
Additionally run `sklearn.ensemble.IsolationForest` on a per-entity feature vector (txn
velocity, average balance-hold time, in/out amount ratio, unique counterparty count,
call/session frequency) as a SEPARATE, clearly-labeled secondary "ML anomaly" flag — never
blend its output into the deterministic tier. The UI must show both independently: e.g.
"Rule-based tier: HIGH | ML anomaly: also flagged" or "Rule-based tier: LOW | ML anomaly:
flagged" so the two detection mechanisms are always visually distinguishable.

### STEP 7 — Graph + Timeline Visualization
Build `network_builder.py` using NetworkX: nodes = resolved entities (colored/sized by risk
tier), directed edges = transactions (weighted by amount) and calls (weighted by frequency).
Highlight edges where `TCS-1`/`TCS-2` fired. Build a per-entity unified timeline view showing
calls, IP sessions, and transactions interleaved on one axis. Use Streamlit with Plotly for
fastest working build; only use React+D3 if there is dedicated frontend time available beyond
the core pipeline. Every node/edge must be clickable to drill down into the underlying rows
and the relevant `decision_trace.jsonl` entries.

### STEP 8 — Forensic Report Export
Build `forensic_report.py` producing a PDF (via `reportlab`) or Word (via `python-docx`)
report per flagged entity containing: resolved identity summary, risk tier and which rules
fired with plain-English explanations, the unified timeline (as an embedded chart image),
the money-flow graph (as an embedded image), and a table of underlying evidence rows with
source file references. This must be a one-click export from the UI.

### STEP 9 — Self-Verification Against Ground Truth
After the full pipeline runs, write a small script that compares flagged entities against
`ground_truth.json` and prints recall/precision (how many planted typologies were correctly
flagged, how many false positives among the 35-45 clean entities). This number becomes your
strongest live-demo claim and must be genuinely computed, not hardcoded.

## Non-functional requirements
- All processing must run locally in seconds on a dataset of 1,500-3,000 events — do not
  introduce Spark/Elasticsearch/Neo4j infrastructure for this scale; use SQLite/Pandas and
  note in documentation that Postgres/Neo4j/Elasticsearch is the intended production
  swap-in for scale, without actually building it in the prototype.
- Every risk decision must be traceable to a named rule and specific source rows — no
  unexplained scores anywhere in the system.
- Provide a README documenting: legal/evidentiary basis (CDR/IPDR obtained under IT Act
  S.69/Telegraph Act with SP-rank sign-off and FIR number, admissible under Evidence Act
  S.65B), the NCRP Layer 1-4 fund-trail model this tool automates, and I4C's Suspect
  Registry/Samanvaya as the national-scale precedent this prototype scopes down to a
  single-case tool.

## Deliverables to produce
1. Working end-to-end pipeline: raw multi-format files → parsed → resolved → correlated →
   scored → visualized → exported as a forensic report.
2. `ground_truth.json` and the self-verification recall/precision output.
3. `decision_trace.jsonl` populated from a full pipeline run.
4. One sample exported forensic PDF/Word report for a flagged entity.
5. README with architecture summary, legal/real-world grounding, and setup instructions.

Build now. Confirm each step's output before moving to the next step so the pipeline is
verifiable at every stage rather than only at the end.
