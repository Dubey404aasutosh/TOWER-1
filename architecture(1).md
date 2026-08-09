# ARCHITECTURE.md — Fusion Analyzer System Design

## 1. Tech stack (kept minimal for a 5-6hr build)
- Backend: Python 3.11, FastAPI (single service, no microservices — don't over-engineer)
- Data: Pandas for all transforms, SQLite for persistence (Postgres is overkill for demo scale)
- Parsing: pdfplumber (bank PDFs), openpyxl (bank Excel), pandas.read_csv (CDR/IPDR)
- Correlation: pure Pandas (`merge_asof` for windowed joins) — no Spark/Elastic needed at demo scale
- Anomaly ML: scikit-learn IsolationForest (secondary signal only, not primary decision-maker)
- Graph: NetworkX for computation, vis.js or Plotly for rendering (skip D3/React unless time allows —
  a clean Streamlit or plain HTML+Plotly frontend beats an unfinished React app every time)
- Report export: reportlab or python-docx for the forensic PDF/Word output
- Frontend: Streamlit if time-constrained; React+D3 only if you have a frontend person free to
  burn 2+ hrs on it purely for visual polish — functionality > framework choice here

## 2. Folder structure
```
fusion-analyzer/
├── data/
│   ├── generator/
│   │   ├── generate_entities.py       # ground-truth entity graph
│   │   ├── generate_bank_statements.py
│   │   ├── generate_cdr.py
│   │   ├── generate_ipdr.py
│   │   └── ground_truth.json          # planted fraud pattern, used to verify detection
│   └── raw/
│       ├── bank_hdfc_sample.xlsx
│       ├── bank_sbi_sample.csv
│       ├── bank_icici_sample.pdf
│       ├── cdr_export.csv
│       └── ipdr_export.csv
├── ingestion/
│   ├── bank_parser.py      # handles 3 different bank layouts -> canonical schema
│   ├── cdr_parser.py
│   ├── ipdr_parser.py
│   └── schema.py           # canonical Entity / Event dataclasses
├── resolution/
│   └── entity_resolver.py  # builds identity graph, connected components -> entity IDs
├── correlation/
│   ├── temporal_join.py    # windowed merge_asof join across 3 event streams per entity
│   └── rules.py            # named deterministic rules: TCS-1, STR-1, LAY-1, MUL-1, IDR-1
├── scoring/
│   └── risk_engine.py      # compound scoring (gated, not summed) + IsolationForest secondary pass
├── graph/
│   └── network_builder.py  # NetworkX graph: nodes=entities, edges=comms/txn, weighted by risk
├── report/
│   └── forensic_report.py  # PDF/Word export with charts + evidentiary timeline + rule trace
├── api/
│   └── main.py             # FastAPI endpoints: /ingest /correlate /score /graph /report
├── frontend/
│   └── app.py              # Streamlit dashboard (or React app if time allows)
└── decision_trace.jsonl    # append-only log: every score decision + which rule fired + why
```

## 3. Data flow (top to bottom, this is your literal pipeline order)
```
raw files (xlsx/csv/pdf)
   -> ingestion/*_parser.py -> canonical Event rows (entity_ref, type, timestamp, amount?, ...)
   -> resolution/entity_resolver.py -> canonical Entity IDs (graph connected components)
   -> correlation/temporal_join.py -> per-entity sorted timeline, windowed cross-source join
   -> correlation/rules.py -> tags each transaction/event with fired rule IDs
   -> scoring/risk_engine.py -> compound risk score per entity (deterministic-gated) + ML pass
   -> graph/network_builder.py -> money-flow + comms graph, edges weighted by risk
   -> frontend/app.py -> timeline view, graph view, "Why This Score?" card, filters
   -> report/forensic_report.py -> exportable PDF/Word report
```

## 4. Canonical schema (the contract every parser must output)
```python
# schema.py
@dataclass
class Entity:
    entity_id: str            # resolved, internal — NOT the raw phone/account number
    raw_identifiers: dict      # {"phones": [...], "accounts": [...], "ips": [...], "imeis": [...], "upi_ids": [...]}

@dataclass
class Event:
    entity_id: str
    event_type: str            # "call" | "sms" | "ip_session" | "transaction"
    timestamp: datetime
    end_timestamp: datetime | None   # for ip_session duration / call duration
    amount: float | None             # transactions only
    counterparty: str | None         # B-party number, beneficiary account, or dest IP
    location: str | None             # cell ID / IP-derived location if available
    source_file: str                 # provenance — always keep this, judges will ask "prove it"
    raw_row_ref: int                 # row index in original file, for the audit trail
```
Every parser's ONLY job is to map its messy source format into rows of this shape. Nothing
downstream should ever look at a raw file again.

## 5. Why SQLite not Postgres/Mongo/Elastic for a hackathon
Your dataset is thousands of rows, not millions. Elasticsearch/Neo4j/Postgres setup burns 45+
minutes of your build window for zero visible benefit in a demo. SQLite + Pandas in-memory is
faster to build, faster to demo, and just as fast to query at this scale. Mention in your README
that Postgres/Neo4j/Elastic is the intended production swap-in for scale — that satisfies the
"Suggested Tools" line item on the rubric without actually costing you build time.

## 6. Non-negotiable cross-cutting requirement
Every single risk-relevant decision (a rule firing, a score changing) gets one line appended to
`decision_trace.jsonl`: `{timestamp, entity_id, rule_id, evidence_row_refs, explanation}`. This
is your entire judge-defense strategy in one file. Build it in from step 1, not bolted on later.
