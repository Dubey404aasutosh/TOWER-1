# TODO — 3-Day Submission Sprint (ERH26_PS_03)

**Baseline (measured):** ~70% built · **~48% working** · detection recall 60% / precision 60% (strict) · pipeline 27.3s @ 2,372 events
**Target at submission:** **~80% working** · recall ≥75% / precision ≥70% · pipeline < 8s · zero fabricated data on screen

**After Day 0 + Day 1 (measured):** recall **100%** / precision **62.5%** / F1 **76.9%** · **CRITICAL = 4** ·
pipeline **9.1s @ 2,404 events** · PDF parsing **207/208 rows with the 1 loss reported** · money-flow graph live ·
`pytest backend/tests/` **48 passed**.
Precision is the one number still under target — see the Day 1 note below: the shortfall is a
**ground-truth labelling artifact that S3.1 fixes**, not a detection regression.

**After Day 2 (measured):** recall **100%** / precision **62.5%** / F1 **76.9%** · **CRITICAL = 5** ·
**all 7 rules fire — no dead rules** · `pytest backend/tests/` **54 passed** ·
timeline view live · network filters live · evidence drill-down live · `.docx` ships with embedded charts.
**All five Day 2 items are done.** Precision is unchanged and still the S3.1 labelling artifact —
IDR-1 added a firing on an entity that was already flagged, so it could not move the number either way.

> ✅ **Resolved on Day 3 by S3.2 — the pipeline is now ~5.7s.** The note below is kept because
> the methodology is what makes the before/after credible.
>
> ~~⚠️ **Pipeline runtime is ~15s, not the 8–9s previously recorded. The "< 10s" line is NOT met,
> and S3.2 is now mandatory rather than optional.**~~
>
> Controlled measurement — one process, `gc.collect()` between runs, stdout suppressed so print
> I/O is not being timed — gives **14.59 / 15.32 / 14.59 / 15.25 / 14.61 / 15.06 s
> (median 15.09s)**, with RSS flat at ~280 MB across all six: no leak, no degradation, very low
> variance. Over `POST /api/run-pipeline` it is **~19s**, the extra ~4s being log I/O and the
> threadpool hop.
>
> **The earlier 8.2s / 9.1s figures do not reproduce.** They came from ad-hoc runs whose timing
> was contaminated three ways, all of which are worth knowing before Day 3 re-benchmarks: two
> duplicated `uvicorn` processes were competing for CPU; the pipeline prints heavily and the cost
> of that varies wildly by where stdout is pointed; and `autocommit.py` daemons commit during a
> run. **Measure S3.2 the way the block above does, or the before/after slide will be noise.**
>
> **This is not a Day 2 regression.** A step-level profile puts the time in the rule engine
> (3.1–6.7s) and risk/ML scoring (2.2–4.5s) — precisely the two S3.2 names — with ingestion at
> 1.5–3.1s and temporal join at 0.8–2.0s. Graph building, the only step Day 2 touched (it gained
> per-edge timestamps and per-entity cities for the S2.2 filters), costs **0.10–0.39s**.

> **The core problem is not missing code — it is disconnected code.** The money-flow graph, the trace endpoint, the chart renderers, and the progress callback are all already built and simply never called. Most P0 items below are wiring, not algorithms.

---

## Cut line

If you fall behind, **ship P0 + P1 and skip P2 entirely.** P0 alone takes you from 48% → ~62%. P0+P1 → ~78%.
~~Never cut: `S0.1` (fabricated hashes), `S1.1` (LAY-1), `S1.4` (money-flow graph).~~
✅ **All three un-cuttables are shipped.** P0 and Day 0 are done.

~~**Revised cut line for what's left.** Two items are now un-cuttable, for different reasons:~~
~~- **`S1.6` (IDR-1 fires 0×)** — a rule the README advertises does nothing.~~
~~- **`S2.1` (timeline)** — the last named requirement (FR-II.a) with **zero** implementation.~~

✅ **Nothing was cut. All five Day 2 items shipped in the planned order**
(S2.4 → S1.6 → S2.3 → S2.2 → S2.1), including S2.2, which the cut line had marked as the
one to drop.

**What remains is Day 3 (P2) only:** S3.1 (metric integrity) · S3.2 (O(N²) hot loop) ·
S3.3 (TCS-2 link check) · S3.4 (MUL-1 false positive) · S3.5 (docs) · S3.6 (rehearse).
Two of those got partly done early as a side effect of Day 2 work — see the notes on
**S3.5** (IDR-1's documented definition now matches the rule) and the P3 float-row-ref item
(fixed, because the evidence panel renders those references to a judge).

---

# ⛑️ DAY 0 — Do these first (45 min, before anything else) — ✅ **DONE**

Four one-liners that are either credibility landmines or silent breakage.

> **Day 0 completed & verified.** `pytest backend/tests/` → 26 passed. API exercised in-process:
> every evidence digest re-verified against `hashlib.sha256(file_bytes)`, the entity-trace fallback
> path returns 200, and a dataset swap (400-row alt CDR + bank csv) moved **all four** KPI tiles
> (1521→367 entities · 10→2 flagged · 5→2 HIGH/CRITICAL · 16→25 ML flags).
> Extra plumbing landed for Day 1: `quality["files"]` now carries per-file size / SHA-256 /
> parsed / skipped counts, and the pipeline prints a `TOTAL SKIPPED` line — so **S1.3** only has
> to fix the parser and return the true count from `smart_ingest.py:199`.
>
> **Rendered and inspected in headless Chrome** (CDP, live DOM read back, not just screenshots):
> KPI tiles, Pipeline Activity, Persons of Interest, Evidence Vault, Decision Trace and the
> staged-upload digest all carry live values; **console is clean — 0 errors, 0 failed requests.**
> Fixed while verifying: `leaflet.css` was also loaded as a `<script>` (MIME error on every load),
> missing favicon (404 on every load), `.ev-hash` double-truncation, and the red `danger` styling
> on the CRITICAL chip when the count is 0. `app.js?v=` bumped so browsers pick up the new bundle.
>
> **Also de-mocked (fabrications the now-honest tiles directly contradicted):**
> `MOCK_ACTIVITY` — announced a CRITICAL entity and rule firings the engine never produced, sitting
> beside a tile reading `0 CRITICAL`. Now built from `/api/results` (`buildActivityFeed`).
> `MOCK_TRACE` — 13 invented firings under a header naming `decision_trace.jsonl`. Now reads the
> real file via `/api/download-trace`, with real explanations and evidence row refs.
> `MOCK_POIS` — invented names, account numbers, and a **fabricated risk percentage** (every HIGH
> entity showed exactly 82%). The engine assigns a *rule-gated tier and no numeric score*, so the
> card now shows the tier plus the rule count. The grid also listed all 1,521 entities; it now
> shows the 10 rule-flagged ones and reports the LOW-tier remainder as a count.
> `MOCK_CASES` — kept, but labelled *"Illustrative workflow · not from this run"* on both the
> dashboard and the registry: there is no case entity in the backend, so this is a scoping
> decision, not a claim. Replacing it properly stays with **S2.3**.

- [x] **S0.1 — Delete the fabricated SHA-256 hashes** ⏱ 20m 🔴 **BLOCKER**
  - `frontend/app.js:1637` generates `'sha256:' + Math.random().toString(36)...` and renders it in green "verified" styling.
  - `frontend/app.js:552-557` `MOCK_EVIDENCE` ships invented digests under a **"Chain of Custody Verified"** header (`dashboard.html:435-436`).
  - **Fix:** compute a real digest in `/api/upload` (`hashlib.sha256` while streaming, ~10 lines) and return it. If short on time, **delete the hash column entirely.**
  - ✅ *Done when:* no string on screen is presented as a cryptographic hash unless it was computed by `hashlib`.
  - ⚠️ This is the only finding that reads as *dishonest* rather than *incomplete*. Fix it first.
  - **✅ Shipped:** `sha256_file()` in `pipeline.py` (streaming `hashlib`) digests every file at ingest;
    `/api/upload` digests the received bytes in the same pass it writes them; new `GET /api/evidence-files`
    returns real size / digest / parsed / skipped per file and flags `modified_since_ingest`.
    `MOCK_EVIDENCE` deleted → `EVIDENCE_FILES` (API-fed, explicit empty state when the backend is down).
    Staged-upload rows now show a **real** WebCrypto SHA-256 of the file bytes, or no chip at all.

- [x] **S0.2 — Add missing `datetime` import** ⏱ 2m
  - `backend/main.py:460` calls `datetime.now()`; `datetime` is never imported → `NameError` → HTTP 500 on the entity-trace fallback path.
  - ✅ *Done when:* `from datetime import datetime` is at the top of `main.py`.
  - **✅ Shipped:** import added; fallback path verified returning HTTP 200 with a real ISO timestamp.

- [x] **S0.3 — Fix the dashboard API contract mismatch** ⏱ 30m 🔴
  - `frontend/app.js:1224-1229` reads `data.entity_count`, `data.high_risk_count`, `data.critical_count`, `data.anomaly_count` — **none exist**. The API returns `data.metrics.total_entities`, `.high_count`, `.critical_count`, `.ml_anomalies`.
  - Same bug at `app.js:1202` (`/api/status` has no `entity_count`).
  - Every KPI tile is therefore frozen on its hardcoded `data-target` in `dashboard.html:183/192/201/210`.
  - ⚠️ *Currently masked:* the hardcoded values (1521, 5, 16) happen to equal today's real values. Load any other dataset and the dashboard displays confidently wrong numbers on stage.
  - ✅ *Done when:* changing the dataset changes the KPI tiles.
  - **✅ Shipped:** `app.js` reads `data.metrics.*`; `/api/status` now returns real `entity_count` /
    `event_count`; `/api/results` gained `metrics.total_rule_firings`, `metrics.rules_fired_count`
    and a `rule_firings` map. All four `data-target`s are `0` in HTML and every chip / sub-line is
    written from live metrics. The rule grid derives fired-state from `rule_firings` instead of the
    hardcoded `MOCK_RULES` (which claimed LAY-1 dead and the other six alive regardless of the data).
    Tile 2 relabelled **Active Cases → Flagged Entities** — "47 active cases" was a number the system
    never computed. Backend unreachable now renders `—`, not a plausible fake.

- [x] **S0.4 — Fix the two tautological tests** ⏱ 10m
  - `backend/tests/test_rules.py:188` and `:204`: `assert fired is True or len(df) > 0` — the right side is always true, so the LAY-1 and LOC-1 tests pass unconditionally. **This is why S1.1 went undetected.**
  - ✅ *Done when:* both assert only `fired is True` (LAY-1 will fail until S1.1 lands — that is correct).
  - **✅ Shipped, with one correction to this TODO:** with the tautologies removed, **LAY-1 passes and
    LOC-1 fails** — the opposite of the prediction above. LAY-1's unit test already hands `check_lay1`
    a multi-entity frame, so it exercises the rule correctly; S1.1 is purely a *caller* bug at
    `rules.py:827`, invisible to this test. LOC-1 failed for a real reason: the fixture put tower ids
    on a `cell_id` field, but `schema.Event` has no such field — `cdr_parser.py:60` maps `CELL_ID` →
    **`location`**, which is what `resolve_event_coordinates()` reads. Fixture moved to `location`
    (Surat→Mumbai, 232 km in 15 min ⇒ ~930 km/h), assertions tightened to check the explanation and
    the `speed_kmh:` evidence token, plus a new negative test (same hop over 5 h must not fire).
    **26 passed.**

---

# 🔴 P0 — DAY 1 · Make the broken things work (~7h) — ✅ **DONE**

Restores advertised functionality. Every item is a defect fix, not a feature.

> **Day 1 completed & verified.** `pytest backend/tests/` → **48 passed** (was 26).
> Measured on the demo dataset, before → after:
>
> | | Before | After |
> |---|---|---|
> | Recall / Precision / F1 | 80% / 66.7% / 72.7% | **100% / 62.5% / 76.9%** |
> | False negatives | 1 (E043 mule missed) | **0 — all 5 typologies detected** |
> | CRITICAL entities | **0 (unreachable)** | **4** |
> | LAY-1 firings | **0** | 3 (+ a closed 4-hop cycle) |
> | `bank_icici.pdf` rows | 175 of 208, reported 0 skipped | **207 of 208, 1 skipped with a reason** |
> | Total events | 2,372 | 2,404 |
> | Pipeline runtime | 17.5s | **9.1s** |
> | Graph served to the UI | identity (300 KYC edges, 0 money) | **money-flow (617 weighted edges, ₹71,15,038)** |
>
> **Rendered and inspected in headless Chrome** (CDP, live DOM read back): money-flow graph
> draws on a real canvas (992×463 — see S1.4 below), all four layering hops highlighted as the
> heaviest strokes, view toggle works both ways leaving exactly one canvas, and clicking
> `ENT_0042` reports *Kashvi Edwin · CRITICAL · TCS-1 MEDIUM, TCS-2 MEDIUM, LAY-1 HIGH ·
> In ₹5,00,829 / Out ₹2,75,659*. **Console clean — 0 errors, 0 failed requests.**
>
> ⚠️ **Two things to know before Day 2:**
> 1. **Precision dipped 66.7% → 62.5%,** and this is expected. LAY-1 now correctly fires on
>    `ENT_0007` and `ENT_0014`, the two accounts the generator plants *as the laundering
>    chain's intermediaries* — but `ground_truth.json` marks only the originator guilty, so
>    they score as false positives. This is the metric artifact **S3.1** exists to fix; the
>    TODO's own S1.2 acceptance criterion ("≤3 clean entities") anticipated exactly this.
>    MUL-1 meanwhile went from 1 firing on the **wrong** entity to 1 firing on the **right** one.
> 2. **IDR-1 still fires 0×** — it is the *second* dead rule, and it is not on any day's list.
>    `E044`, the planted identity-fan-out entity, is caught only incidentally by STR-1. The
>    pre-submission line *"all 7 rules fire at least once"* cannot pass until this is fixed.
>    See the new **S1.6** below.

- [x] **S1.1 — Fix LAY-1 (fires 0× today)** ⏱ 1h 🔴 **HIGHEST IMPACT**
  - `backend/correlation/rules.py:827` passes `entity_df` (this entity's rows only). LAY-1 walks a multi-entity chain A→B→C→D, so `outgoing_by_entity.get(cp_entity)` is always empty and the DFS dies after hop 1.
  - Pass the **global** `all_events_df`.
  - Also replace the cache key at `rules.py:344-356`: `cache_key = id(all_events_df)` is unsound — CPython reuses `id()` after GC, so two entities can collide and silently share the wrong transaction map. Precompute `outgoing_by_entity` **once** in `run_all_rules` and pass it in.
  - ✅ *Verified achievable:* re-running with the global frame produced **10 LAY-1 firings**, e.g. `ENT_0014 → ENT_0007 → ENT_0021 → ENT_0042` in 5.9h.
  - 🏆 Earns: FR-III.a (Layering — a **named** requirement), and unblocks the CRITICAL tier which is currently unreachable.
  - **✅ Shipped:** caller at `rules.py` now passes the global frame. The `id(all_events_df)`
    memo is gone — new `build_outgoing_index()` builds `{entity: [outgoing transfers]}` **once**
    in `run_all_rules` and the same object is handed to every call, so no two entities can
    collide on a recycled `id()`. The index stores 4-field dicts instead of pandas Series
    (the old `iterrows()` build was also the slow path). New test
    `test_lay1_needs_the_global_frame_not_one_entity_slice` fails if the caller ever regresses.

- [x] **S1.2 — Tune LAY-1 so it doesn't over-fire** ⏱ 1h
  - Add a **minimum amount floor** — my test run produced chains on ₹1,417 and ₹8,047 flows.
  - Narrow the shrinkage band from `0.60–0.99` toward the documented 5–15% skim.
  - Cap DFS depth (currently unbounded → worst-case exponential).
  - **Either implement a real cycle check or fix the explanation string** — the emitted text claims *"Commission skim pattern confirmed"* and the docstring claims *"forming a cycle or near-cycle"*, but `if cp_entity in path: continue` makes a cycle structurally unreachable. Do not ship an explanation that asserts something never verified.
  - ✅ *Done when:* LAY-1 fires on E042 (the planted layering entity) and on ≤3 clean entities.
  - **✅ Shipped — and the cycle check is real now, not a claim.** Constants are named and
    documented at the top of the rule: `LAY1_MIN_AMOUNT = ₹50,000` (the reporting threshold the
    layering evades — kills the ₹1,417 and ₹8,047 chains), skim band narrowed `0.60–0.99` →
    **3–20%** around the documented 5–15%, and `LAY1_MAX_DEPTH = 6` bounds the DFS.
    Rather than soften the explanation, the **cycle is now detected**: a hop back to the
    entity the chain started from closes the loop and is ranked above a longer open chain.
    E042's chain is genuinely circular —
    `ENT_0042 → ENT_0014 → ENT_0007 → ENT_0021 → ENT_0042`, 8.2h, **measured** skims
    7.9% / 10.1% / 12.0%. The explanation now reports those measured values and says
    *"no return to X observed"* when the chain does not close. The rule's own unit-test
    fixture was itself a cycle (`A→B→C→A`) the old code could not see.
    **Result: 3 firings** (E042 + the 2 planted intermediaries), well inside the ≤3 budget.

- [x] **S1.3 — Stop the PDF parser silently losing 16% of bank rows** ⏱ 2h 🔴
  - `backend/ingestion/bank_parser.py:187-189` skips the first row of **every** page as a "repeated header" — but reportlab writes no repeated header. **8 transactions deleted outright.**
  - `backend/data/generator/generate_all.py:1054`: `colWidths=[25,55,45,180,50,30,55]` (440pt) is too narrow for A4 (~510pt) → cells shear. Dates extract as `'0/06/25 21:53:4'`, `'1/05/25 20:17:5'`; descriptions carry column bleed (`...advay.contr\n4actor@okicici`). **24 more rows die on date parse.**
  - Fix: remove the page-skip · widen `colWidths` · add `repeatRows=1` · then handle the (now real) repeated header.
  - `backend/ingestion/smart_ingest.py:199` hardcodes `"skipped_rows": 0` for PDFs — return the true count and surface it in `quality["warnings"]`.
  - 📊 **Measured:** 208 data rows → 175 parsed (**15.9% lost**), including the entire planted ₹5,00,000 mule inflow for account `8644925192`. **This — not the rule logic — is why MUL-1 misses E043.**
  - ✅ *Done when:* `bank_icici.pdf` yields ≥205 events **and** the pipeline prints any non-zero skip count.
  - 🏆 Earns: evaluation criterion #1 (parsing accuracy) + likely recovers a full recall point.
  - **✅ Shipped — 175 → 207 of 208 rows (99.5%), and the 1 loss is reported with a cause.**
    Parser: the blind "skip row 0 of every page" is replaced by `_looks_like_repeated_header()`,
    which matches the row's *text* against the header — so a transaction sitting first on a page
    is never deleted, whether or not the header repeats.
    Generator: `colWidths` widened and padding set explicitly. The Date column was 45pt for a
    timestamp that measures ~56pt at 7pt Helvetica, so reportlab drew it past the cell border and
    extraction read back the clipped remains (`'0/06/25 21:53:4'`). Every description is now a
    wrapped `Paragraph`, and `repeatRows=1` draws a real repeated header.
    *Verified by re-extraction:* header reads cleanly as
    `['S.No','Account No','Date','Description','Amount','Type (DR/CR)','Bal.']` (the old
    `'pe ('` / `'r)'` shear artifacts are gone), 9 pages, **zero malformed dates**.
    Accounting: `parse_bank_pdf(stats=...)` and `_parse_bank_df` count every drop by reason;
    `smart_ingest.py` returns the real number instead of the hardcoded `0`. The single skip is
    the generator's *deliberately* injected blank-amount row.
    **The recovered ₹5,00,000 mule inflow makes MUL-1 detect E043 — recall 80% → 100%.**
    New `backend/tests/test_ingestion.py` asserts the invariant `parsed + skipped == total`.
  - ⚠️ *Regenerating the dataset is safe:* the generator is seeded (`random.seed(42)`), and a
    regeneration before any change reproduced byte-identical CSV/XLSX and identical pipeline
    output — only `generated_at` and the PDF layout move.

- [x] **S1.4 — Render the money-flow graph (it's built, just never sent)** ⏱ 2h 🔴
  - `build_network_graph` produces a DiGraph with **613 weighted transaction + call edges**. `backend/main.py:271-298` serializes the **identity graph** instead — KYC ownership links between raw identifiers, with ~1,476 isolated dots and **zero money flow**.
  - Swap the serialization to `results["network_graph"]`: nodes = entities (size/colour by tier), edges = txn (width by amount) + call (width by frequency), arrows on.
  - Highlight edges where **TCS-1/TCS-2** fired — `correlation.md:114` calls these the "smoking gun" edges.
  - Keep the identity graph available behind a toggle ("Identity view / Money-flow view") — it's a genuine second story, just not *the* one the PS asks for.
  - 🏆 Earns: FR-IV.a + evaluation criterion #4. Currently ~30%.
  - **✅ Shipped.** `/api/results` now returns `network` = **money-flow** plus
    `network_views: {money_flow, identity}`; the dashboard has a Money-flow / Identity toggle
    and writes its title, legend and stat line from whichever view is active.
    Nodes are entities sized/coloured by tier; only the 154 that carry an edge or a flag are
    drawn (**1,214 unconnected dots suppressed**, and the count is stated on screen rather than
    hidden). Edges are directed with arrows, transfer width scales log-wise with amount, calls
    are dashed. Labels are drawn only for the 12 flagged entities — 150 overlapping captions
    buried the ones that mattered.
  - **Two defects found and fixed while wiring this up — neither was on any list:**
    1. 🔴 **Edge amounts were doubled.** One transfer appears in *both* statements — a debit at
       the sender and a credit at the receiver, under different UTRs — and `build_network_graph`
       summed both. The ₹275,659 layering hop rendered as **₹551,318**, contradicting the
       statement a judge can open. Now the sender's debit rows are counted, with credit rows
       used only when no debit for that pair was ingested (flagged in the tooltip when so).
       The four chain edges now read ₹275,659 → ₹253,828 → ₹228,215 → ₹200,829 — *exactly* the
       amounts in the LAY-1 explanation. Guarded by `test_transfer_amounts_are_not_double_counted`.
    2. 🔴 **The graph had never been visible.** `dashboard.html` wraps it in `.network-layout`,
       which **has no CSS rule at all**, so `.network-canvas { flex:1 }` resolved against a
       zero-height parent — canvas measured **992×0**. Compounding it, the graph was being built
       by `fetchRealResults()` while the network view was still `display:none`, so vis.js
       measured an invisible container. Layout rule added; construction moved to when the view
       is actually shown; `initNetwork()` re-fits on return. Canvas now measures **992×463**.
  - **Layering highlight is exact, not heuristic.** LAY-1 emits a `chain:A>B>C` evidence token
    and the serializer lights precisely those hops — so hops through `ENT_0021`, which never
    fired LAY-1 itself, are still highlighted. Chain strokes are the heaviest on the canvas
    (7.0 vs 5.61 max), which is what makes the demo's step 4 land.

- [x] **S1.5 — Confirm CRITICAL is reachable end-to-end** ⏱ 30m
  - After S1.1, re-run and check `CRITICAL > 0`. Both paths require LAY-1 or IDR-1, so today it is always 0.
  - Also pass `rule_severities` through — `backend/scoring/risk_engine.py:183-189` drops it, so the IDR-1 HIGH/MEDIUM/LOW sub-levels (good design) never reach the UI.
  - ✅ *Done when:* at least one entity shows CRITICAL with its two corroborating rules named.
  - **✅ Shipped. CRITICAL = 4** (`ENT_0007`, `ENT_0014`, `ENT_0042`, `ENT_0043`), every one of
    them gated on ≥2 corroborating rules — asserted by `test_critical_tier_is_reachable`.
    `rule_severities` now flows `run_all_rules → risk_engine → /api/results → node payload`,
    and the inspector renders the grade beside each rule chip (`LAY-1 HIGH`, `TCS-1 MEDIUM`).
    Note the tier logic was already *reading* severities correctly — what was missing is that
    they never left the backend, so the UI could not explain the difference between two
    entities with the same rule list.

- [x] **S1.6 — IDR-1 fires 0×: the second dead rule** ⏱ ~1h 🔴 **NEW — found on Day 1**
  - Not on the original list. With LAY-1 alive, **IDR-1 is now the only rule that never fires**,
    on any entity, anywhere in the dataset.
  - `E044` is the *planted* identity-fan-out entity and is detected only incidentally, by STR-1.
    The detection is a coincidence, and a rule the README advertises does nothing.
  - Likely the same class of bug as S1.1: `check_idr1` groups by `entity_ref` and looks for a
    **consecutive** IMEI/IMSI change, while `correlation.md:69` documents *"3+ accounts or 2+
    IMEIs"* — which is what the generator plants. **Start by asserting the documented definition
    in a unit test,** the way S0.4's de-tautologised tests exposed LAY-1 and LOC-1.
  - ⚠️ Blocks the pre-submission line **"all 7 rules fire at least once across the dataset"**, and
    leaves the `LAY-1 AND IDR-1` path to CRITICAL still never exercised.
  - 🏆 Earns: honesty on the README's "7 Deterministic Forensic Rules" claim (ties into S3.5).
  - **✅ Shipped — the guess above was right about the cause and understated it.** The rule was
    not merely using a different definition; it was hunting for **the exact opposite** of the
    planted pattern. `generate_all.py:673` plants E044 as *"One IMEI operating 3 phone numbers
    and 2-3 bank accounts"* — one IMEI that **never changes**. `check_idr1` searched for an IMEI
    *changing between consecutive events*, so the single entity the rule exists to catch was
    structurally invisible to it. A second finding: `schema.Event` has **no `imsi` field** and
    `cdr_parser.py` never reads one, so the `imei_changed AND imsi_changed → HIGH` branch could
    not be reached by any real data — the same class of defect as LOC-1's `cell_id` fixture.
  - **Definition, thresholds named and documented** at the top of the rule: one entity is
    "fanned out" if a single IMEI operates ≥2 MSISDNs (**HIGH** — a handset cycling SIMs), or it
    holds ≥3 accounts, or ≥2 IMEIs (**MEDIUM**); two limbs corroborating escalate to HIGH. The
    original SIM-swap logic is kept as a fourth limb rather than deleted — it is a real signal
    with 8 passing tests, it just is not what "fan-out" means.
  - **Thresholds were measured before being chosen, not guessed.** Across all 1,368 resolved
    entities exactly **one** has 3+ accounts, **one** has 3+ phones, **zero** have 2+ IMEIs, and
    exactly **one** IMEI in the entire dataset operates more than one MSISDN — all of them
    `ENT_0044`. Every candidate definition selected that entity and nothing else, so the limb
    thresholds cost **zero false positives**.
  - **Result: IDR-1 fires 1×, on `ENT_0044`, at HIGH.** `DEAD RULES: []` — all seven fire.
    `ENT_0044` was already HIGH via STR-1, so the gate at `risk_engine.py:52`
    (`IDR-1 HIGH AND ≥2 rules`) promotes it to **CRITICAL: 4 → 5**. Recall and precision are
    **unchanged** — the entity was already counted as detected, so this adds a correct reason
    rather than a new flag.
  - Five new tests assert the documented definition limb by limb, plus
    `test_idr1_fires_at_least_once_on_the_demo_dataset`, which fails if **any** of the seven
    rules ever goes dead again. `correlation.md:69` and `README.md:100` rewritten to match the
    rule (part of **S3.5**).

---

# 🟠 P1 — DAY 2 · Fill the rubric holes with zero coverage (~11h) — ✅ **DONE**

> **Day 2 completed & verified.** `pytest backend/tests/` → **54 passed** (was 48).
> Measured, before → after:
>
> | | After Day 1 | After Day 2 |
> |---|---|---|
> | Dead rules | **IDR-1 (fires 0×)** | **none — all 7 fire** |
> | CRITICAL entities | 4 | **5** |
> | Timeline (FR-II.a) | **does not exist** | live view + API + chart in the `.docx` |
> | Network filters (FR-IV.b) | `applyNetworkFilters()` was `{ }` | amount · time · city · rule · tier · search, per view |
> | Evidence drill-down | endpoint called from nowhere | source rows under every rule chip |
> | Charts in the report | `timeline_fig=None, network_fig=None` | 2 figures per forensic `.docx`, 1 per STR |
> | Recall / Precision / F1 | 100% / 62.5% / 76.9% | **unchanged** (precision is still the S3.1 artifact) |
>
> **Rendered and inspected in headless Chrome** (CDP, live DOM read back, not just screenshots):
> the timeline draws 56 markers across 3 lanes for `ENT_0007`; the "Correlation window" preset
> zooms to a 60-minute span; clicking the largest marker on `ENT_0043` reports
> *2025-06-07 11:00:00 · +₹5,00,000 · bank_icici.pdf · row 190* flagged as cited evidence — the
> very row Day 1's PDF fix recovered. Filters verified against live DataSet counts:
> tier=CRITICAL → 5 nodes, rule=LAY-1 → 3 nodes, "Layering chain" → 4 edges, amount ≥₹1,00,200 →
> 165 of 617 edges, search `ENT_0042` → 9 nodes. **Console clean — 0 errors, 0 failed requests.**
>
> ⚠️ **Two scope decisions worth knowing, both measured:**
> 1. **Report charts use matplotlib, not Plotly/kaleido.** Kaleido works, but was measured at
>    **~3.5 s per image and it does not amortise** (it drives a headless Chrome per render). At
>    8 flagged entities × 2 figures that is ~56 s bolted onto the pipeline. The same figures take
>    **~0.1 s each** through matplotlib. The TODO pre-authorised this fallback; the Plotly path is
>    still wired and selectable via `renderer="plotly"` rather than discarded.
> 2. **Reports are generated on demand, not in bulk inside the pipeline.** Charting all 8
>    HIGH/CRITICAL entities inline cost ~17 s on top of an 8 s pipeline, against a "runs in
>    seconds" requirement — and nothing consumed the pre-generated files, since the UI links
>    straight to `/api/download-report/{id}`. One report now costs **1.9 s** when actually asked
>    for. `/api/run-pipeline` clears stale reports first, so a re-run on a new dataset can never
>    serve the previous dataset's `.docx`.
>
> **Also fixed while building these — none were on any list:**
> `MOCK_REPORTS` (invented case numbers, invented "23 Jul 2026" dates, invented "SEALED"
> statuses, and tiers that contradicted the engine — it called `ENT-0042` HIGH when the engine
> says CRITICAL) replaced with the real flagged set. Its download links, and a hardcoded one in
> the case slide-over, pointed at **`ENT-0037` with a hyphen** — an id the API has never issued,
> so **every "Download Report" button 404'd**, which is demo step 8. `vis.js` rejected
> `arrows: 'none'` and logged an options error on every identity-view load. The evidence panel
> rendered missing fields as the literal string **`nan`**. Row references printed as
> **`cdr_row_1018.0`** (the P3 float-ref item — fixed early, because these are now shown to a
> judge as court references). `.gitignore` whitelisted the committed sample `.docx` pair **by two
> specific timestamped filenames that no longer existed**, and `clear_old_reports()` deleted every
> `.docx` including them — so a fresh clone that ran the pipeline destroyed a checked-in
> deliverable. Samples are now `sample_*.docx`, whitelisted by prefix and skipped by both
> clearing paths.

These are requirement lines currently scoring near zero. Backend and frontend tracks are parallelizable.

> **Re-verified against the tree after Day 1** (line numbers moved — `app.js` grew ~195 lines,
> `main.py` ~320). Every "0 references" claim below was re-checked, not carried over.
> Day 1 left three assets that make these cheaper than the original estimates:
> **(a)** money-flow nodes already carry `risk_tier`, `rules_fired`, `rule_severities`,
> `value_in`, `value_out`, `institution`, and edges carry `amount`, `count`, `edge_type`,
> `edge_class` — S2.2 is a filter over fields that already exist, not a new API;
> **(b)** `networkViews` / `activeNetworkView` / `setNetworkView()` already give you a
> per-view render path to hang filters off;
> **(c)** `populateInspector()` already renders real entity data on node click, so S2.3 is
> now only the *evidence rows*, not the whole panel.

- [x] **S2.1 — Unified timeline view** ⏱ 4h 🔴 **PS centrepiece**
  - FR-II.a. Confirmed still true after Day 1: `build_unified_timeline()` is defined at
    `backend/correlation/temporal_join.py:113` and has **0 call sites**;
    `create_timeline_plotly()` is defined at `backend/graph/network_builder.py:444`, imported at
    `pipeline.py:23` and `main.py:904`, and passed as `create_timeline_fn=` at `pipeline.py:228`
    — but **never invoked**, because `forensic_report.py:540` hardcodes `timeline_fig=None`.
    The report's "timeline" is still a plain 6-column table. **No timeline exists in the product.**
  - Build: per-entity, three lanes (transaction / call / IP session) on one time axis, marker size by amount, click → source row.
  - Overlay the correlation window so a TCS-1 firing is *visually obvious* — this is the "decisive evidence lives at the intersection" moment from `solution.md:16`. It is the single most demo-able screen you can build.
  - 💡 **Demo the entity Day 1 proved out:** `ENT_0042` has the full story on one axis —
    call, IP session, then transfer, minutes apart, four times around a closed loop.
  - 🔗 Shares its blocker with **S2.4** (both need a figure past `forensic_report.py:540`); doing
    S2.4's one-line unhardcode first means S2.1's figure lands in the `.docx` for free.
  - 🏆 Earns: FR-II.a + evaluation criterion #4.
  - **✅ Shipped as a new "Unified Timeline" view**, plus `GET /api/entity/{id}/timeline`.
    `build_unified_timeline()` now has call sites: a new `build_timeline_payload()` wraps it and
    is the **single source both the screen and the `.docx` chart read**, so the exhibit and the
    UI cannot disagree about an entity's chronology.
  - **The obvious implementation would have failed, and measuring it is what caught that.** The
    dataset spans six weeks; a ±10-minute correlation window is ~0.02% of that axis. Rendered at
    full range the decisive moment is a literal hairline — the screen the PS calls the centrepiece
    would have shown nothing. Both renderers therefore use focus+context: the UI has a full-range
    strip you can drag plus a **"Correlation window"** preset that walks the windows in order of
    probative weight, and the report chart draws a second zoomed panel underneath the overview.
  - Drawn as hand-written SVG — no library was loaded and the interaction is the point. Three
    lanes, marker radius log-scaled by amount, IP sessions drawn as their real duration rather
    than as points, rows cited by a rule ringed in white, click → the source row.
  - 💡 **The demo lands on `ENT_0043`, not `ENT_0042`.** One 20-minute window on 7 June contains
    an IP session at 10:52, the **₹5,00,000 credit at 11:00**, and a call at 11:08 — three
    separate datasets intersecting, with `bank_icici.pdf row 190` named underneath. That is the
    row Day 1's PDF fix recovered, so steps 2 and 5 of the demo now tell one continuous story.
    `ENT_0042` remains the better *money-flow* story for step 4.
  - ⚠️ The preset deliberately opens on the **most probative** window rather than the earliest.
    Chronological order opened the mule's timeline on a ₹113 transfer; the ranking now matches
    the one the report uses to choose its zoom panel.

- [x] **S2.2 — Filters: amount, time window, location** ⏱ 3h 🔴
  - FR-IV.b is at **~10%**. Re-checked line numbers: `applyNetworkFilters()` is literally `{ }` at
    **`frontend/app.js:1894`**; `applyNetworkFilter(type, btn)` at **`app.js:1889`** only toggles a
    CSS class. The four buttons are at `dashboard.html:487-490`.
  - ⚠️ **Worse than originally recorded:** `app.js:1877` wires a listener to
    `#network-risk-filter`, but **that element does not exist anywhere in `dashboard.html`**. The
    risk dropdown is not a no-op — it was never built. Add the control, don't just wire it.
  - Implement: **amount range** (use `edge.amount`, already on every transaction edge),
    **time-window slider** (the API already accepts `window_minutes` — still no UI control),
    **location/city**, entity search (`#network-search-input` exists and is wired to the no-op).
  - Wire the four network filter buttons to actually subset the vis.js DataSet.
  - ⚠️ **Scope changed by S1.4:** there are now two views, and the buttons are not
    view-agnostic — "Phones" / "Bank Accounts" are meaningless in the money-flow view (its nodes
    are entities), and "Critical Only" is meaningless in the identity view (its nodes are raw
    identifiers with no tier). Give each view its own filter set, or the buttons will lie.
  - 🏆 Earns: FR-IV.b — currently your lowest-scoring line.
  - **✅ Shipped. Every control filters on a field the backend actually emits** — nothing here is
    decorative, and a control is not rendered at all when its facet is empty for the active graph.
  - **Two of the three named filters had nothing to filter on, so the payload was extended first.**
    Money-flow edges are aggregates and carried no time at all, and entity nodes carried no
    location — an "amount, *time window*, *location*" filter over those fields would have been a
    UI with no data behind it. `build_network_graph` now records `first_ts`/`last_ts` per edge
    (**617 of 617 edges carry a span**) and resolves each entity's cities, reconciling the two
    sources that record place differently: CDR gives a tower id (`SRT-T05`), IPDR gives a city
    name (`Chennai`). `/api/results` publishes a `facets` block — real amount range
    (**₹113–₹300,000**), real time range (**2025-05-01 → 2025-06-14**), the cities and rules
    actually present — and the controls are built from it.
  - **Per-view filter sets, so the buttons cannot lie.** The four hardcoded buttons are gone;
    each graph renders its own. Money-flow gets tier / rule / amount / date-range / city;
    identity gets the identifier types actually present (`Account`, `Imei`, `Ip`, `Phone`, `Vpa`)
    and **none** of the money-only controls. Filters reset on a view switch, since a tier filter
    left over from money-flow would silently blank the identity graph.
  - `#network-risk-filter` was wired to an element that did not exist in `dashboard.html`; it is
    now built rather than merely wired. Search subsets on entity id, name, phones and accounts,
    and keeps the hit's **direct counterparties** so a match is not left as one stranded dot.
  - An edge-level filter also hides nodes left with no visible edge — "Layering chain" showed
    154 nodes and 4 edges before that, which buried the answer in stranded dots. Verified live:
    tier=CRITICAL → **5 nodes**, rule=LAY-1 → **3 nodes**, "Layering chain" → **4 nodes / 4 edges**,
    amount ≥₹1,00,200 → **165 of 617 edges**, city=Chennai → **1 node**, identity "Phone" → 47 nodes.
  - **W, the correlation window, is now exposed in the UI** — the one item in this list that was
    missed on the first pass. `/api/run-pipeline` was being POSTed **with no body at all**, so its
    `window_minutes` parameter always fell back to the default and no control could have had any
    effect. Two things were needed, not one:
    **(a)** the pipeline run now sends the selected W; **(b)** `/api/entity/{id}/timeline` accepts
    `?window_minutes=`, which re-joins *that entity's* events at the requested W in milliseconds
    instead of the ~15s a full re-analysis costs — so W is explorable on the screen that actually
    draws it as a shaded band. `correlation.md:55` asks for exactly this and calls it the seed for
    the natural-language-query bonus.
  - ⚠️ **Widening W previews; it does not re-detect.** More coincidences appear, but the rules
    fired at the pipeline's W, so the payload carries `is_preview` and the UI says so in words —
    *"Preview at W = ±30 min — the rules fired at ±10 min, so the tier and rule chips above are
    unchanged"* — with an **Apply to analysis** button that re-runs for real. A widened window
    silently implying a detection that never happened is the same class of dishonesty as the
    fabricated hashes. Measured on `ENT_0043`: W=±5 → **1** window, ±10 → **2**, ±15 → **2**,
    ±30 → **4**, ±60 → **6**; Apply at W=30 re-runs and clears the preview flag.
  - 🐛 **Found via that second re-run: `fetchVerificationSummary()` threw on every call after the
    first.** `#kpi-accuracy-count` is a `<span>` nested *inside* `#kpi-accuracy-sub`, and the
    function wrote to the span and then overwrote the parent's `innerHTML`, destroying it — so
    call 1 worked and call 2 hit a null element. Latent since before Day 2 (running the pipeline
    twice from the UI would have tripped it); only surfaced because Day 2 added a second re-run
    path. The redundant write is gone and the remaining ones are guarded.

- [x] **S2.3 — Drill-down to evidence (endpoint already exists)** ⏱ ~1h *(was 2h — Day 1 did part of it)*
  - `/api/entity/{id}/trace` (now **`backend/main.py:756`**) returns identifiers + real
    `decision_trace` entries + raw evidence rows, and is still called from **nowhere** in the
    frontend (`grep 'api/entity' frontend/app.js` → no hits).
  - ✅ *Already done, don't redo:* **(b)** the Evidence Vault trace log and `MOCK_EVIDENCE` were
    replaced with real data in **Day 0**. **(a)** is half-done — `populateInspector()` now renders
    the real tier, the rules that fired, their severities, value in/out and institution straight
    off the node payload.
  - **What actually remains:** fetch `/api/entity/{id}/trace` on node click and render the
    **evidence rows** — the source lines behind each firing — under the inspector's rule chips.
    That is the click-through that answers *"why this score?"* with a row reference.
  - 💡 LAY-1 evidence already carries structured tokens (`cycle:`, `hops:`, `skim_pct:`,
    `chain:`) alongside its `row_` refs — render the row refs, and treat the rest as metadata.
  - 🏆 Earns: FR-IV.a drill-down.
  - **✅ Shipped.** Clicking a node now fetches `/api/entity/{id}/trace` (cached, with a request
    guard so a slow response for one entity cannot paint under another entity's heading) and
    renders, under each rule chip: the rule's explanation, its structured metadata as chips, and
    **every source row it cited**, resolved to the actual line — timestamp, direction, amount,
    counterparty, location.
  - **This is the screen that answers "why this score?" with a file and a row number.** On
    `ENT_0042`, TCS-1 cites three rows in three different files —
    `bank row 215` (10:12, −₹2,75,659), `cdr row 1016` (10:06, call to 9533357554),
    `ipdr row 545` (10:07, session to 103.25.193.40). LAY-1 renders its `cycle:true`, `hops:4`,
    `skim_pct:7.9,10.1,12.0` and `chain:` tokens as metadata beside the row refs, exactly as the
    note above suggested.
  - A row cited by a rule but belonging to a **counterparty's** file is labelled
    *"referenced — not in this entity's rows"* rather than silently dropped or faked.
  - Two display defects fixed here: references printed as **`cdr_row_1018.0`** (a float artifact
    from `merge_asof`, now normalised at the source in `check_tcs1` so `decision_trace.jsonl`
    itself is clean), and missing fields rendered as the literal string **`nan`**.
  - Also adds an **"Open timeline"** button, so the demo can go from the money-flow chain
    (step 4) straight into that entity's timeline (step 5) without hunting through a dropdown.

- [x] **S2.4 — Embed charts in the forensic report** ⏱ 2h budgeted · likely ~20m of code 🥇 **do this first on Day 2**
  - Re-checked: `backend/report/forensic_report.py:525` accepts `create_timeline_fn` /
    `create_network_fn`, then **`:540` hardcodes `timeline_fig=None, network_fig=None`** — so the
    functions are received and discarded. Every report still prints
    *"[Identity graph visual available in interactive portal]"*.
  - 💡 **The receiving end is already written:** `forensic_report.py:143-146` renders a figure via
    `network_fig.to_image(format="png", ...)` and inserts it. Nothing there needs building — the
    figures just never arrive. This is closer to a one-line unhardcode than a 2h feature, which
    is why it is worth doing before S2.1 rather than after.
  - `kaleido` is already in `requirements.txt` purely for this and is never exercised.
  - ⚠️ **Keep the 2h budget even though the code is ~20m.** `kaleido` has never been run in this
    repo, and recent versions shell out to a headless Chrome for `to_image()`. Smoke-test it on
    its own (`fig.to_image(format="png")`) **before** wiring anything, so a rendering-backend
    problem does not look like a report bug. If it fights back, `matplotlib` → PNG → `add_picture`
    is a legitimate fallback; the requirement is a chart in the `.docx`, not Plotly specifically.
  - FR-IV.c explicitly says *"with charts and the evidentiary timeline"*.
  - ✅ **Day 1 bonus:** `create_network_plotly` now draws off the de-duplicated graph, so an
    embedded money-flow chart will show ₹275,659 for the layering hop — not the doubled
    ₹551,318 it would have printed into a court exhibit yesterday.
  - ✅ *Done when:* the sample `.docx` contains a timeline image and a money-flow image.
  - **✅ Shipped — and the 2h budget was the right call, for exactly the stated reason.**
    Smoke-testing `kaleido` first was what saved this: it *works* (12 KB PNG, no crash), so the
    naive one-line unhardcode would have looked correct — and silently added **~56 s** to the
    pipeline, because kaleido costs **~3.5 s per image and does not amortise**. The failure would
    have surfaced on stage as "why is this taking a minute", not as a report bug. Switched to the
    pre-authorised matplotlib fallback at **~0.1 s per image**; `renderer="plotly"` still selects
    the kaleido path, so the figures are genuinely *received and used*, not received and discarded.
  - The report gained a **timeline section it never had** (FR-IV.c asks for "charts **and the
    evidentiary timeline**"), so each forensic `.docx` now carries 2 figures and the STR carries
    the chronology of its own transaction schedule. Sections renumbered to 7.
  - Both figures are drawn **light-on-white**, not in the dashboard's dark theme — this is a
    document that gets printed and filed.
  - The money-flow figure is the entity's **own neighbourhood**, not the global graph, and its
    labelled amounts read ₹275,659 / ₹200,829 — the same figures as the LAY-1 explanation and the
    bank statement behind them.
  - Two rendering defects caught by actually looking at the output: node captions were white text
    drawn wider than the marker, so everything overhanging the dot fell on white paper and
    vanished (`ENT_0021` rendered as `002`); and edge amount labels collided with node captions on
    near-vertical edges.
  - ⚠️ **Report generation moved out of the pipeline** — see the Day 2 header note. Verified
    end-to-end over HTTP: `GET /api/download-report/ENT_0043` → **200, 195 KB, 1.9 s, 2 embedded
    images**. Committed samples are `backend/reports/sample_*.docx` (forensic: 2 charts,
    STR: 1 chart).

---

# 🟡 P2 — DAY 3 · Metrics integrity, performance, demo prep (~7h) — ✅ **DONE**

> **Day 3 completed & verified.** `pytest backend/tests/` → **57 passed** (was 54).
> Measured with the methodology this file specifies — one process, `gc` between runs, stdout
> captured so print I/O is not being timed:
>
> | | After Day 2 | After Day 3 |
> |---|---|---|
> | Pipeline runtime | ~15s | **5.51 / 5.65 / 5.74 / 5.79 / 6.01 s — median 5.74s** |
> | risk + ML scoring | 2.2–4.5s | **0.52s** |
> | Metric threshold | TP at any tier, FP at HIGH/CRITICAL | **one threshold on both sides** |
> | Specificity | never computed | **92.5%** — 37 of 40 planted clean entities unflagged |
> | TCS-2 firings | 7 (no link check) | **4** (link verified) |
> | Leaflet map | `initMap()` never called — blank div | **live**, 10 towers from the API |
> | Recall / Precision / F1 | 100% / 62.5% / 76.9% | **unchanged** |
>
> **Demo rehearsed twice in headless Chrome** — all 10 beats, **45.7s of walk time, 0 console
> errors**, every step asserted against the live DOM rather than eyeballed.
>
> ⚠️ **Precision stays 62.5%, and that is the number to say out loud.** Unifying the metric did
> not move it, because all three false positives were already HIGH/CRITICAL. Two of them are now
> *proven* labelling artifacts rather than suspected ones — see S3.1.
>
> ⚠️ **Slowest demo beat is step 3**, the identity view: vis.js stabilises 1,508 nodes in ~13.5s.
> Nothing is broken, but it is dead air on stage. Open the network view before you need it.


- [x] **S3.1 — Fix the verification metric (it inflates recall)** ⏱ 1h
  - `backend/verification/verify.py:112-134` counts a TP if **any** rule fired at **any** tier; `:147` counts FPs at **HIGH/CRITICAL only**. Two thresholds on two sides of the same metric.
  - Honest strict numbers today: **recall 60%, precision 60%** (reported: 80% / 66.7%).
  - Unify the threshold, then **add specificity over the 40 clean entities** — `dataset.md:71` calls this the killer demo line and it is never computed.
  - Bonus if time: consume `expected_flagged_rows` from `ground_truth.json` for **row-level** precision. It's generated every run and thrown away — no other team will have this.
  - ⚠️ Fix this *after* S1.1/S1.3 so the number you publish is the improved one.
  - **✅ Shipped. One threshold on both sides.** TP required `flagged OR any rule at any tier`
    while FP required `HIGH/CRITICAL` — a guilty entity at MEDIUM scored as a hit, but a clean
    entity at MEDIUM was not a miss. Both sides are now "HIGH or CRITICAL", and the response
    carries the threshold as a string so the ratio cannot be quoted without it.
  - 📊 **Recall did NOT fall when the metric was tightened** — it stayed 100%, because Days 0–2
    pushed all five planted typologies to HIGH/CRITICAL. The strict number and the flattering
    number now agree, which is the outcome worth having.
  - **Specificity: 92.5% — 37 of 40 planted clean entities left unflagged.** The denominator is
    the whole exercise. My first attempt divided by "KYC-named entities" and returned **99.78%**,
    because the resolver also names ~1,363 passthrough counterparties — any population that
    includes them reports near-perfect specificity for a detector that has done nothing. The
    denominator is now the generator's own `normal_entities: 40`, every FP is charged against it,
    and the count is printed beside the percentage in the CLI, the API and the KPI tile.
  - **Each false positive explains itself, and two are vindicated.** `generate_all.py:421` builds
    the chain as `[guilty] + random.sample(clean_pool, 3)` — the generator routes laundered money
    through three accounts drawn from the CLEAN pool, then marks only the originator guilty.
    `ENT_0007` and `ENT_0014` are those hops. **The score was NOT adjusted for this** — grading a
    detector with its own output is circular. The annotation ships beside the unchanged number.
  - ⏭ **Not done: row-level precision.** Checked, then deliberately skipped — ground truth numbers
    rows in a different index space from the engine's `raw_row_ref` (`bank_row_2127` vs `row_210`
    for the same entity), so it needs a mapping, not an afternoon. A wrong number beats no number
    only if it is right.

- [x] **S3.2 — Kill the O(N²) hot loop** ⏱ 1.5h 🔴 **PROMOTED — no longer optional (Day 2 finding)**
  - 📊 **Re-measured on Day 2 and the target is missed by 50%:** the pipeline is **~15s**, not the
    8–9s on record, so the "< 10s" pre-submission line fails without this. Step profile, 3 trials:
    rule engine **3.1–6.7s**, risk/ML **2.2–4.5s**, ingestion **1.5–3.1s**, temporal join
    **0.8–2.0s**, graph build **0.1–0.4s**. The two steps this item names are the two that dominate.
  - ⚠️ **Benchmark methodology matters more than it looks here.** Timing swung 6s→21s across naive
    runs. Use one process, `gc.collect()` between runs, **stdout redirected to a `StringIO`** (the
    pipeline prints heavily and printing is being timed otherwise), and check no duplicate
    `uvicorn` is running. Done that way the measurement is stable to ±0.4s, which is what a
    before/after slide needs.
  - `backend/scoring/risk_engine.py:92`: `all_events_df[all_events_df['entity_id'] == entity_id]` inside a loop over 1,521 entities = full scan per entity.
  - `run_all_rules` already solved this at `rules.py:769` with `dict(tuple(df.groupby('entity_id')))` — apply the identical pattern.
  - Also skip the 1,476 event-less passthrough entities in the rule loop (the fast-path guard at `rules.py:784` misses them because counterparty accounts populate `entity_data['accounts']`).
  - 📊 **Measured:** risk/ML 5.1s @1× → **236s @25×**. Rule engine 10.8s. Ingestion 8.0s (`df.iterrows()`).
  - 🎯 27.3s → **~5s**. Then re-run `backend/verification/benchmark.py` and put the **before/after table on a slide** — evaluation criterion #5 answered with data, which most teams cannot do.
  - **✅ Shipped — ~15s → 5.74s median (min 5.51, max 6.01 over 5 runs). Target met.**
    The named fix was the whole win: `compute_ml_anomaly` re-scanned all 2,404 rows once per
    entity across 1,368 entities. One `dict(tuple(df.groupby('entity_id')))` plus an early skip
    for the ~1,200 event-less passthrough entities took that step **2.2–4.5s → 0.52s**.
  - ✅ **Provably behaviour-preserving:** recall, precision, tier distribution and every rule
    firing count are identical before and after. A performance change that alters detection is a
    detection change wearing a disguise.
  - 📌 **The second half of this item did not apply.** It says the rule loop's fast path misses
    ~1,476 passthrough entities — profiling shows only **118 entities** ever reach the rules, so
    that guard already works. The remaining cost is real work on real entities, dominated by
    `check_tcs2` (~36% of it), which **S3.3** rewrote with an indexed window scan — so that cost
    fell as a side effect of the correctness fix.

- [x] **S3.3 — TCS-2: implement the missing link check** ⏱ 1h
  - `backend/correlation/rules.py:254` admits it: `# (simplified: any call within the window counts as suspicious)`. The condition is only `if call_party and txn_counterparty:` — both strings non-empty.
  - The documented rule requires the transfer to go **to an account/VPA linked to the called number**. Without it, TCS-2 fires on ordinary background behaviour.
  - ⚠️ This is exactly the *"how did you get this score?"* question from `solution.md:26`. Fix it or explicitly rename the rule to what it actually does.
  - **✅ Fixed, not renamed.** The link is verified two ways, both recorded in evidence:
    **resolved** — called number and beneficiary account/VPA resolve to the same entity via
    `entity_map`; **embedded** — the payee VPA literally contains the called number, which is how
    UPI handles are routinely formed. With no `entity_map` the link is unknowable and the rule
    stays silent rather than reverting to the old behaviour.
  - 📊 **TCS-2: 7 firings → 4.** The three removed are exactly what the old comment admitted to —
    a call and a transfer that merely shared a window. MEDIUM entities dropped 4 → 1. Recall
    unaffected; `E042`'s TCS-2 is genuine and still fires.
  - Three tests added, including the one that would have caught this:
    `test_tcs2_does_not_fire_when_payee_is_unrelated_to_the_called_number`. The pre-existing
    positive test still passes — legitimately, since its fixture pays `ACC_9800000002` after
    calling `9800000002`, which is an embedded link.
  - ⚡ Rewritten with `np.searchsorted` over sorted call times instead of rebuilding a boolean
    mask plus `iterrows()` per transaction — this was the rule engine's single largest cost.

- [x] **S3.4 — MUL-1: stop the false positive** ⏱ 1h
  - `rules.py:475`: `credit_amount < median_credit * 3` lets an ordinary ₹70k salary credit qualify as a "large suspicious inflow" (this produced the ENT_0272 FP).
  - Add an absolute floor; tighten the dormancy test (`len(prior_activity) > 2` currently calls 2 transactions in 30 days "dormant").
  - The explanation asserts *"Balance returned near-zero"* without ever reading a balance column — either read it or delete the claim.
  - **✅ Shipped, thresholds named:** `MUL1_MIN_INFLOW = ₹1,00,000`, `MUL1_MAX_PRIOR_TXNS = 0`,
    `MUL1_MICRO_TXN = ₹10`.
  - The FP came from a test that was an OR in disguise: `credit < 100000 AND credit < median*3`
    admitted any credit on the relative branch alone, so an ordinary salary landing in a quiet
    account read as a "large suspicious inflow". That branch is gone; an absolute floor replaces
    it. Dormancy now means dormant — the old allowance permitted two real transactions inside the
    30-day window and still called the account inactive.
  - **The balance claim is deleted, because it could not be checked.** `balance_col` is mapped in
    both bank parsers and then never written into the event dict, and `schema.Event` has no
    balance field — the sentence was unverifiable from anything the engine had read. The
    explanation now reports the residual it can derive (`inflow − outflow`), and the evidence
    carries `inflow:`, `outflow:`, `retained:` and `prior_txns_in_dormancy:` tokens.
  - 📌 `ENT_0272`, the FP this item names, had already stopped firing before Day 3 — the
    tightening guards against its return rather than fixing a live defect.

- [x] **S3.5 — Reconcile the docs with reality** ⏱ 1h
  - `README.md` currently overstates: "7 Deterministic Forensic Rules" (2 dead pre-S1.1), "Leaflet.js Geo Map" (`initMap()` at `app.js:1397` is **never called** — the map is a blank div), "Word/PDF" reports (Word only), "Hash-stamped audit logging" (**no `hashlib` anywhere in the backend**).
  - `master_prompt.md:131` requires "runs in seconds" — currently 27.3s.
  - IDR-1's documented definition (*"3+ accounts or 2+ IMEIs"*, `correlation.md:69`) does not match the implementation (consecutive IMEI/IMSI change). Pick one and make README + `correlation.md` + the rule agree.
  - ⚠️ Docs that overstate are worse than absent in front of a panel that will click.
  - **✅ Shipped. Every claim was re-checked against the code, not taken from the list above.**
    "Word/PDF" → Word only, stated explicitly (there is no PDF path in `report/`).
    "Hash-stamped audit logging" → rewritten to what exists: `hashlib` SHA-256 over every ingested
    file at ingest, re-verified on request. "7 Deterministic Forensic Rules" → true as of S1.6,
    and asserted by a test.
  - 🗺️ **The Leaflet map was fixed rather than downgraded.** `initMap()` was defined and called
    from nowhere, so a nav item advertised a geo map and opened a blank div. It is now invoked on
    view switch, plots `map_towers` from `/api/results` (the same tower master LOC-1 geolocates
    against) instead of its hardcoded list, calls `invalidateSize()` because the container is
    `display:none` until activated, and states its tower count on screen. Verified live:
    **20 markers, 20 tiles, "10 cell towers from the active tower master"**.
  - **Four rule descriptions contradicted their implementations** and were rewritten: MUL-1
    (≥85% → ≥80% with a ₹1L floor), TCS-2 (now states the link requirement), LOC-1 (documented as
    a KYC-city comparison; it is a >200 km/h Haversine impossible-travel check), LAY-1 (now states
    the 3–20% skim band, ₹50k floor, 6-hop bound and real cycle detection).
  - Added a **Measured Performance & Accuracy** table to the README — runtime, recall, precision,
    specificity, parse rate, test count — every figure recomputed per run, with the 62.5%
    precision explained rather than hidden.

- [x] **S3.6 — Rehearse the demo end-to-end, twice** ⏱ 1.5h 🔴
  - See the script below. Time it. Fix whatever breaks. **Do not skip this** — an untested demo path is how a working system loses.
  - **✅ Rehearsed twice in headless Chrome. All 10 beats, 45.7s of walk time, 0 console errors.**
    Each step asserted against the live DOM: evidence vault lists all 5 sources; KPI reads 1,368
    entities / 2,404 events / 5 CRITICAL / 7-of-7 rules; identity canvas 892×625 over 1,508 nodes;
    money-flow 154 nodes / 617 edges with 4 layering hops at
    ₹228,215 / ₹253,828 / ₹200,829 / ₹275,659; the chain filter isolates 4 of 154; `ENT_0042`
    yields 3 evidence blocks citing `bank row 215` + `cdr row 1016` + `ipdr row 545`; the timeline
    lands on *+₹5,00,000 · bank_icici.pdf · row 190*; the map draws 20 markers; the reports panel
    shows 8 cards / 16 links / **0 broken**.
  - 📌 Run 1 showed three `ERR_CONNECTION_REFUSED` failures that were **not** a product fault: a
    stale headless-Chrome profile served a cached bundle. The endpoints answered 200 in 20–40 ms
    throughout and run 2 was clean. Recorded because it cost real time to chase twice.

---

# ⚪ P3 — Only if you finish early

- [ ] Wire `/api/institution-risk` (80 lines, built, never called) into a cross-institution panel — a genuine differentiator.
- [ ] Call `initMap()` and feed it `map_towers` from `/api/results` instead of the hardcoded tower list at `app.js:1406-1417`.
- [ ] `.txt` ingestion — the UI accepts `.txt` (`dashboard.html:294`) but `backend/pipeline.py:72` only iterates `.csv/.xlsx/.xls/.pdf`, so `.txt` uploads are **silently dropped**.
- [ ] Bank account extraction from statement headers — `bank_parser.py:265-280` collapses every row of a column-less statement into `ACCT_SBI`/`ACCT_UNKNOWN`, merging different customers into one entity.
- [ ] Add amount/volume features to the IsolationForest vector (`risk_engine.py:101-141` has **no amount feature at all**); switch `contamination=0.1` → `'auto'` (0.1 mechanically guarantees exactly 10% flagged regardless of the data).
- [ ] Fix `/api/reports` entity_id: `main.py:519` `.split("_")[0]` returns `"ENT"` for every report.
- [ ] Delete dead weight: `frontend/components/*.jsx` (Next.js files with no build system), `map_builder` plot functions (~290 lines, 0 references), the orphaned dashboard block at `index.html:785` (**12 duplicate IDs**), root `decision_trace.jsonl` (stale), `server_log.txt`.
- [x] ~~Fix float row refs in evidence: `decision_trace.jsonl` contains `"cdr_row_1018.0"`~~ —
  **done on Day 2**, pulled forward because S2.3 now renders these references to a judge as
  court-exhibit citations. Normalised at the source in `check_tcs1` (`_row_ref_text`), so the
  trace file itself is clean, and again on the way out of `/api/entity/{id}/trace`.

---

# 🚫 DO NOT DO (explicitly out of scope for 3 days)

- ❌ Authentication / user accounts — state it as a documented scoping decision instead
- ❌ Database persistence (SQLite/Postgres) — in-memory `STATE` is fine at this scale; `architecture.md:90` already justifies it
- ❌ Migrating the frontend to React/Next.js — delete the orphan `.jsx` files, don't chase them
- ❌ Refactoring `style.css` (3,164 lines, 314 `!important`) — invisible to judges
- ❌ Real-time progress streaming (SSE/WebSocket) — the faked 450ms step animation is fine for a demo
- ❌ XSS hardening — real, but not a rubric line for a local single-user tool
- ❌ Rewriting the entity resolver — it's deliberately conservative and has a passing regression test; **do not touch it under time pressure**
- ❌ New rules beyond the seven — fix the two dead ones instead

---

# 🎬 Demo script (rehearse this exact path)

1. **"Three files, three formats, zero shared schema."** Show `bank_icici.pdf`, `cdr_export.csv`, `ipdr_export.csv` side by side.
2. **Run the pipeline live.** Call out the parse counts *including skipped rows* — post-S1.3 this is a strength, not a weakness ("we report what we couldn't parse; most tools don't").
3. **Entity resolution:** "These 5 raw identifiers are one person." Show the identity view.
4. **Switch to money-flow view** (S1.4) — the layering chain lights up. *This is the money shot.*
5. **Open the flagged entity's timeline** (S2.1) — call, then IP session, then transfer, minutes apart. *"The evidence was never in any one dataset."*
6. **"Why this score?"** — name the rules. Click through to `decision_trace.jsonl` row refs (S2.3). **Never say "the model decided."**
7. **Show the live verification number** (S3.1) — recomputed every run, not a slide constant.
8. **One-click forensic report + STR export** (S2.4) — open the `.docx`, show the embedded charts.
9. **Close on the legal basis** — IT Act S.69 / Telegraph Act, SP-rank sign-off, admissible under BSA S.65B. Say it *before* anyone asks (`solution.md:44-47`).

---

# ✅ Pre-submission checklist

- [x] `python backend/main.py` starts clean from a fresh clone — verified on Day 3 via the exact
      command the README gives: no traceback on stderr, startup pipeline completes, and
      `/`, `/dashboard`, `/api/results`, `/api/verification-summary` and
      `/api/entity/{id}/timeline` all return 200
- [x] Pipeline completes in **< 10s** on the demo dataset — ✅ **5.74s median** (min 5.51, max 6.01
      over 5 controlled runs) after S3.2. Was ~15s at the end of Day 2
- [x] `CRITICAL > 0` and **all 7 rules** fire at least once across the dataset — **CRITICAL = 5,
      zero dead rules**, guarded by `test_idr1_fires_at_least_once_on_the_demo_dataset`
- [~] Recall **≥75%** and precision **≥70%** under a *single* consistent threshold — the threshold
      is now single and consistent (S3.1). Recall **100%** ✅. Precision **62.5%** ❌ — and it stays
      there deliberately: 2 of the 3 false positives are the laundering chain's own intermediaries,
      which `generate_all.py:421` samples from the clean pool and ground truth then labels innocent.
      Verified in the generator, annotated in the output, **not** tuned away. Also now reported:
      **specificity 92.5%** over the 40 planted clean entities
- [x] No number on any screen is hardcoded — the last two holdouts went on Day 3: the cell-tower map
      now plots `map_towers` from the API rather than a built-in list, and the accuracy tile carries
      live specificity with its denominator. A dataset swap moves every tile (verified on Day 0)
- [x] **No fabricated hash, size, or row count anywhere in the UI** — plus the invented case
      numbers, dates and "SEALED" statuses in `MOCK_REPORTS` are gone
- [x] Money-flow graph renders with real edges; clicking a node shows real evidence rows
- [x] Timeline view renders for at least one flagged entity — renders for all 8, demo on `ENT_0043`
- [x] Sample `.docx` (forensic + STR) committed **with charts embedded** —
      `backend/reports/sample_*.docx`, whitelisted by prefix and no longer deleted by a pipeline run
- [x] `README.md` describes only what actually works — every claim re-checked against the code on
      Day 3. Word-only stated, hashing described as what it is, the Leaflet map **fixed** rather than
      downgraded, and four rule descriptions that contradicted their implementations rewritten
- [x] `pytest backend/tests/` passes with the tautologies removed — **57 passed**
- [x] Demo rehearsed twice, end to end, timed — **10 beats, 45.7s, 0 console errors**, every step
      asserted against the live DOM

---

# 📊 Questions that would expose you today

Track these — each should be answerable by submission:

| Question | Status | Fixed by |
|---|---|---|
| "Show me a circular flow." | ✅ `ENT_0042 → ENT_0014 → ENT_0007 → ENT_0021 → ENT_0042`, 8.2h, skims 7.9/10.1/12.0% | S1.1 + S1.2 |
| "That's the money-flow network?" | ✅ 617 weighted edges, ₹71,15,038, arrows on; identity graph behind a toggle | S1.4 |
| "Where does that SHA-256 come from?" | ✅ `hashlib`, streamed over the file | **S0.1** |
| "Why is nothing CRITICAL?" | ✅ 4 CRITICAL, each on ≥2 corroborating rules | S1.1 |
| "Did every PDF row get parsed?" | ✅ 207 of 208 — the 1 skip is named and its cause reported | S1.3 |
| "₹551,318? The statement says ₹275,659." | ✅ edges no longer double-count debit + credit | S1.4 |
| "Do all seven rules work?" | ✅ All 7 fire. IDR-1 catches `ENT_0044` — 1 IMEI running 3 MSISDNs + 3 accounts | **S1.6** |
| "Open this entity's timeline." | ✅ Live view + `/api/entity/{id}/timeline`; `ENT_0043` shows session → ₹5,00,000 → call in 20 min | S2.1 |
| "Filter to transfers over ₹1L, 2–4 PM." | ✅ Amount slider + date range + city + rule + tier + search, per view | S2.2 |
| "Why this score? Show me the row." | ✅ TCS-1 on `ENT_0042` cites `bank row 215`, `cdr row 1016`, `ipdr row 545` | S2.3 |
| "Open the .docx — where are the charts?" | ✅ Timeline + money-flow embedded; 195 KB in 1.9 s on demand | S2.4 |
| "Why are these two clean accounts flagged?" | ⚠️ They are the planted chain's intermediaries; the metric counts them as FPs | S3.1 |
| "How does this scale?" | ❌ 961s @ 48k events | S3.2 |
| "TCS-2 fired — was the transfer actually *to* the person called?" | ❌ Not checked; `rules.py` admits it in a comment | S3.3 |

---

*Findings verified by executing the pipeline and exercising the API in-process. Line references are against the current working tree — re-check after any refactor.*
