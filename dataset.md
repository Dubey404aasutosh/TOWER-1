# DATASET.md — Synthetic Data Generation Spec (real-working, not toy-demo)

Real bank/CDR/IPDR data is private and unobtainable for a hackathon — same reason PaySim and
IBM AMLSim exist. The fix is not "find real data," it's generate-with-embedded-ground-truth,
the same pattern those tools use. Judges can tell the difference between "obviously random"
and "looks real" instantly — this spec is written to pass that test.

## 1. Build the ground-truth graph FIRST, export messy formats SECOND

Never generate 3 files independently. Generate ONE internal entity/event graph, then
serialize it out into 3 inconsistent formats. This guarantees your correlation engine has
something real to find, and lets you verify detection against `ground_truth.json` afterward.

## 2. Population design (this is what makes it feel real)

- **35-45 "normal" entities** — 90%+ of the dataset, zero embedded fraud pattern:
  - Salaried behavior: monthly credit (salary), recurring debits (rent, utilities, EMI),
    occasional P2P transfers to 5-10 regular contacts, 1-2 stable IPs (home wifi + mobile
    data range), normal call patterns to family/friends, no unusual timing correlation
    between calls and transfers.
  - Add natural noise: occasional late payments, one-off large purchases (electronics,
    travel), varying call durations, weekday/weekend activity skew.
- **4-6 "guilty" entities** — each assigned exactly ONE named fraud typology (below), so you
  can explain each flagged case by name in your demo, not just "the algorithm found something."

## 3. Fraud typologies to embed (pick from real, cited patterns — don't invent your own)

**Typology A — Structuring (maps to rule STR-1)**
Entity receives one large fraud-proceeds credit, then executes 4-6 outgoing transfers each
just under ₹49,000-49,900 (avoiding the ₹50k threshold) within 24-48 hours, to 2-3 different
accounts.

**Typology B — Layering / Circular Flow (maps to rule LAY-1)**
A → B → C → D → back to an account linked to A (via shared UPI VPA or IMEI), across 3-4 hops
within hours, each hop retaining a small "commission" (5-15% skim), amounts shrinking each
hop. Embed a call between adjacent hop-holders 2-10 minutes before each transfer (this feeds
TCS-2) and an active IP session overlapping each transfer (feeds TCS-1).

**Typology C — Mule Signature (maps to rule MUL-1)**
Entity/account dormant (near-zero transactions) for a simulated 30+ day lookback window,
then a single large inflow, then 80-95% of it moved out within minutes to a few hours,
balance returns near-zero. This is the single most cited real-world red flag pattern for
mule accounts.

**Typology D — Identity Fan-out / Evasion (maps to rule IDR-1)**
One physical person (one IMEI) operates 3 different phone numbers (simulate a SIM swap
timeline) and 2-3 different bank accounts, spreading a fraud typology's transactions across
them specifically to look like unrelated actors until entity resolution collapses them into
one node.

**Typology E — Geo-Improbable (maps to rule LOC-1, optional bonus)**
Same entity has a call from a Surat cell tower and, 20 minutes later, an IP session
geolocated to a different city — a physically implausible pattern worth flagging.

## 4. Canonical ground truth file (`ground_truth.json`)
```json
{
  "guilty_entities": [
    {
      "entity_id": "E014",
      "typology": "STR-1",
      "raw_identifiers": {"accounts": ["XXXX1234"], "phones": ["98xxxxxx01"]},
      "expected_flagged_rows": [ "bank_row_101", "bank_row_104", "bank_row_108" ],
      "narrative": "Structuring: 5 transfers under threshold within 36 hours post fraud credit"
    }
  ]
}
```
Use this file after your pipeline runs to auto-check recall/precision of your own detector —
"our tool correctly flagged 5/6 planted typologies with 0 false positives on the 40 clean
entities" is a killer line to say out loud in judging, and you can only say it if you built
this file.

## 5. Format variance — how to make 3 files that don't look hand-matched

- **Bank source 1 — SBI-style (xlsx)**: columns `Txn Date, Value Date, Description, Debit,
  Credit, Balance`, date format `DD-MM-YYYY`. Real SBI UPI narration format:
  `UPI/CR/261234567890/GOOGLEPAY/oksbi` (credit) or `UPI/DR/261234567891/ramesh.k/okaxis`
  (debit) — the 12-digit number right after `CR`/`DR` is the UTR (unique transaction
  reference), always keep this as a distinctly extractable field since it's the standard
  real-world cross-reference number banks and NPCI use to trace a payment end-to-end.
- **Bank source 2 — HDFC-style (csv)**: columns `date, particulars, withdrawal_amt,
  deposit_amt, closing_balance`, date format `YYYY/MM/DD`. Real HDFC narration formats
  differ from SBI's slash-delimited style — either `UPI-CREDIT-261234567890-GOOGLEPAY`
  (hyphen-delimited) or `UPI/P2M/261234567890/ramesh.k@okhdfcbank/Payment` depending on
  channel (NetBanking CSV vs CMS export). Use the hyphen style here to maximize the format
  contrast with source 1 — this is exactly the kind of real inconsistency that makes
  "multi-format ingestion" a provable claim instead of a checkbox.
- **Bank source 3 (pdf, generate via reportlab as a real table)**: columns
  `S.No | Date | Description | Amount | Type | Balance`, `Type` is `DR`/`CR` in a separate
  column instead of separate debit/credit columns, date format `DD/MM/YY`, narration mixes
  IMPS style: `IMPS-P2A/403318292014/JOHN DOE/HDFC0001234` (IMPS reference is 12 digits too,
  positioned right after the channel tag, same extraction logic as UTR).
- **CDR (csv)**: columns `A_PARTY, B_PARTY, CALL_TYPE, START_TIME, DURATION_SEC, CELL_ID, IMEI`.
- **IPDR (csv)**: columns `MSISDN, PRIVATE_IP, PUBLIC_IP, PORT, SESSION_START, SESSION_END,
  DEST_IP, DATA_VOLUME_KB`.

Deliberately inject: 2-3 missing values per file, one duplicate row, one header-row anomaly
in the PDF export (merged cell/misaligned column), inconsistent casing in narration text.
This is what makes "multi-format ingestion" a real claim instead of "I read 3 clean CSVs with
the same column names."

**Narration parser must extract 3 distinct sub-fields from one messy string, not just the
counterparty**: (1) the UTR/reference number (the 12-digit code, position varies by bank —
right after `CR`/`DR`/channel tag), (2) the counterparty VPA or account/IFSC if present, and
(3) the channel type (UPI/IMPS/NEFT/RTGS). Keep the UTR as its own field on the canonical
`Event` even though it isn't used for cross-dataset correlation directly (CDR/IPDR have no
UTR) — real investigators use UTR to cross-check with the beneficiary bank's own ledger, and
having it demonstrates your parser does genuine field-level extraction, not just narration
pass-through.

## 6. Build order for the generator script
```
generate_entities.py       -> creates 40-46 entities + relationships graph, writes ground_truth.json
generate_events.py         -> for each entity, generates calls/sessions/transactions per its
                               profile (normal or one of typologies A-E), writes one master
                               internal event table
export_bank_formats.py     -> takes master events, filters transaction-type events, writes out
                               3 differently-formatted bank files (xlsx/csv/pdf)
export_cdr.py               -> filters call-type events -> cdr_export.csv
export_ipdr.py               -> filters session-type events -> ipdr_export.csv
```
Libraries: `pandas`, `openpyxl`, `reportlab` (for PDF table), `faker` (Indian locale for
names — `Faker('en_IN')`) for realistic names/addresses without using real people.

## 7. Scale target for the demo
1,500-3,000 total events across ~40 entities is enough to look substantial in a live demo
and still runs the whole pipeline in under a few seconds — don't over-generate just to claim
a bigger number, it buys you nothing and risks slow demo reruns.
