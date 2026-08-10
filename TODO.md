# TODO — 3-Day Submission Sprint (ERH26_PS_03)

**Baseline (measured):** ~70% built · **~48% working** · detection recall 60% / precision 60% (strict) · pipeline 27.3s @ 2,372 events
**Target at submission:** **~80% working** · recall ≥75% / precision ≥70% · pipeline < 8s · zero fabricated data on screen

> **The core problem is not missing code — it is disconnected code.** The money-flow graph, the trace endpoint, the chart renderers, and the progress callback are all already built and simply never called. Most P0 items below are wiring, not algorithms.

---

## Cut line

If you fall behind, **ship P0 + P1 and skip P2 entirely.** P0 alone takes you from 48% → ~62%. P0+P1 → ~78%.
Never cut: `S0.1` (fabricated hashes), `S1.1` (LAY-1), `S1.4` (money-flow graph).

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

- [ ] **S1.3 — Stop the PDF parser silently losing 16% of bank rows** ⏱ 2h 🔴
  - `backend/ingestion/bank_parser.py:187-189` skips the first row of **every** page as a "repeated header" — but reportlab writes no repeated header. **8 transactions deleted outright.**
  - `backend/data/generator/generate_all.py:1054`: `colWidths=[25,55,45,180,50,30,55]` (440pt) is too narrow for A4 (~510pt) → cells shear. Dates extract as `'0/06/25 21:53:4'`, `'1/05/25 20:17:5'`; descriptions carry column bleed (`...advay.contr\n4actor@okicici`). **24 more rows die on date parse.**
  - Fix: remove the page-skip · widen `colWidths` · add `repeatRows=1` · then handle the (now real) repeated header.
  - `backend/ingestion/smart_ingest.py:199` hardcodes `"skipped_rows": 0` for PDFs — return the true count and surface it in `quality["warnings"]`.
  - 📊 **Measured:** 208 data rows → 175 parsed (**15.9% lost**), including the entire planted ₹5,00,000 mule inflow for account `8644925192`. **This — not the rule logic — is why MUL-1 misses E043.**
  - ✅ *Done when:* `bank_icici.pdf` yields ≥205 events **and** the pipeline prints any non-zero skip count.
  - 🏆 Earns: evaluation criterion #1 (parsing accuracy) + likely recovers a full recall point.

- [ ] **S1.4 — Render the money-flow graph (it's built, just never sent)** ⏱ 2h 🔴
  - `build_network_graph` produces a DiGraph with **613 weighted transaction + call edges**. `backend/main.py:271-298` serializes the **identity graph** instead — KYC ownership links between raw identifiers, with ~1,476 isolated dots and **zero money flow**.
  - Swap the serialization to `results["network_graph"]`: nodes = entities (size/colour by tier), edges = txn (width by amount) + call (width by frequency), arrows on.
  - Highlight edges where **TCS-1/TCS-2** fired — `correlation.md:114` calls these the "smoking gun" edges.
  - Keep the identity graph available behind a toggle ("Identity view / Money-flow view") — it's a genuine second story, just not *the* one the PS asks for.
  - 🏆 Earns: FR-IV.a + evaluation criterion #4. Currently ~30%.

- [ ] **S1.5 — Confirm CRITICAL is reachable end-to-end** ⏱ 30m
  - After S1.1, re-run and check `CRITICAL > 0`. Both paths require LAY-1 or IDR-1, so today it is always 0.
  - Also pass `rule_severities` through — `backend/scoring/risk_engine.py:183-189` drops it, so the IDR-1 HIGH/MEDIUM/LOW sub-levels (good design) never reach the UI.
  - ✅ *Done when:* at least one entity shows CRITICAL with its two corroborating rules named.

---

# 🟠 P1 — DAY 2 · Fill the rubric holes with zero coverage (~11h)

These are requirement lines currently scoring near zero. Backend and frontend tracks are parallelizable.

- [ ] **S2.1 — Unified timeline view** ⏱ 4h 🔴 **PS centrepiece**
  - FR-II.a. Today: `build_unified_timeline()` has **0 references**, `create_timeline_plotly()` is imported and never invoked, and the report's "timeline" is a plain 6-column table. **No timeline exists anywhere in the product.**
  - Build: per-entity, three lanes (transaction / call / IP session) on one time axis, marker size by amount, click → source row.
  - Overlay the correlation window so a TCS-1 firing is *visually obvious* — this is the "decisive evidence lives at the intersection" moment from `solution.md:16`. It is the single most demo-able screen you can build.
  - 🏆 Earns: FR-II.a + evaluation criterion #4.

- [ ] **S2.2 — Filters: amount, time window, location** ⏱ 3h 🔴
  - FR-IV.b is at **~10%**. `frontend/app.js:1560` `applyNetworkFilters()` is literally `{ }`; `app.js:1555` only toggles a CSS class. Four filter buttons, a search box and a risk dropdown are wired to no-ops.
  - Implement: **amount range**, **time-window slider** (the API already accepts `window_minutes` — no UI control exists), **location/city**, entity search.
  - Wire the four network filter buttons to actually subset the vis.js DataSet.
  - 🏆 Earns: FR-IV.b — currently your lowest-scoring line.

- [ ] **S2.3 — Drill-down to evidence (endpoint already exists)** ⏱ 2h
  - `/api/entity/{id}/trace` returns identifiers + real `decision_trace` entries + raw evidence rows — and is **never called**.
  - Wire it into: (a) node click in the network inspector, (b) the Evidence Vault "Decision Trace Log" which currently renders 13 invented `MOCK_TRACE` entries.
  - Also replace `MOCK_EVIDENCE` with the real ingested file list (name, rows parsed, rows skipped, real hash from S0.1).
  - 🏆 Earns: FR-IV.a drill-down + kills the largest remaining block of fake data.

- [ ] **S2.4 — Embed charts in the forensic report** ⏱ 2h
  - `backend/report/forensic_report.py:536-541` accepts `create_timeline_fn` / `create_network_fn` then hardcodes `timeline_fig=None, network_fig=None`. **Every report prints "[Identity graph visual available in interactive portal]"**.
  - `kaleido` is already in `requirements.txt` purely for this and is never exercised.
  - FR-IV.c explicitly says *"with charts and the evidentiary timeline"*.
  - ✅ *Done when:* the sample `.docx` contains a timeline image and a money-flow image.

---

# 🟡 P2 — DAY 3 · Metrics integrity, performance, demo prep (~7h)

- [ ] **S3.1 — Fix the verification metric (it inflates recall)** ⏱ 1h
  - `backend/verification/verify.py:112-134` counts a TP if **any** rule fired at **any** tier; `:147` counts FPs at **HIGH/CRITICAL only**. Two thresholds on two sides of the same metric.
  - Honest strict numbers today: **recall 60%, precision 60%** (reported: 80% / 66.7%).
  - Unify the threshold, then **add specificity over the 40 clean entities** — `dataset.md:71` calls this the killer demo line and it is never computed.
  - Bonus if time: consume `expected_flagged_rows` from `ground_truth.json` for **row-level** precision. It's generated every run and thrown away — no other team will have this.
  - ⚠️ Fix this *after* S1.1/S1.3 so the number you publish is the improved one.

- [ ] **S3.2 — Kill the O(N²) hot loop** ⏱ 1.5h
  - `backend/scoring/risk_engine.py:92`: `all_events_df[all_events_df['entity_id'] == entity_id]` inside a loop over 1,521 entities = full scan per entity.
  - `run_all_rules` already solved this at `rules.py:769` with `dict(tuple(df.groupby('entity_id')))` — apply the identical pattern.
  - Also skip the 1,476 event-less passthrough entities in the rule loop (the fast-path guard at `rules.py:784` misses them because counterparty accounts populate `entity_data['accounts']`).
  - 📊 **Measured:** risk/ML 5.1s @1× → **236s @25×**. Rule engine 10.8s. Ingestion 8.0s (`df.iterrows()`).
  - 🎯 27.3s → **~5s**. Then re-run `backend/verification/benchmark.py` and put the **before/after table on a slide** — evaluation criterion #5 answered with data, which most teams cannot do.

- [ ] **S3.3 — TCS-2: implement the missing link check** ⏱ 1h
  - `backend/correlation/rules.py:254` admits it: `# (simplified: any call within the window counts as suspicious)`. The condition is only `if call_party and txn_counterparty:` — both strings non-empty.
  - The documented rule requires the transfer to go **to an account/VPA linked to the called number**. Without it, TCS-2 fires on ordinary background behaviour.
  - ⚠️ This is exactly the *"how did you get this score?"* question from `solution.md:26`. Fix it or explicitly rename the rule to what it actually does.

- [ ] **S3.4 — MUL-1: stop the false positive** ⏱ 1h
  - `rules.py:475`: `credit_amount < median_credit * 3` lets an ordinary ₹70k salary credit qualify as a "large suspicious inflow" (this produced the ENT_0272 FP).
  - Add an absolute floor; tighten the dormancy test (`len(prior_activity) > 2` currently calls 2 transactions in 30 days "dormant").
  - The explanation asserts *"Balance returned near-zero"* without ever reading a balance column — either read it or delete the claim.

- [ ] **S3.5 — Reconcile the docs with reality** ⏱ 1h
  - `README.md` currently overstates: "7 Deterministic Forensic Rules" (2 dead pre-S1.1), "Leaflet.js Geo Map" (`initMap()` at `app.js:1397` is **never called** — the map is a blank div), "Word/PDF" reports (Word only), "Hash-stamped audit logging" (**no `hashlib` anywhere in the backend**).
  - `master_prompt.md:131` requires "runs in seconds" — currently 27.3s.
  - IDR-1's documented definition (*"3+ accounts or 2+ IMEIs"*, `correlation.md:69`) does not match the implementation (consecutive IMEI/IMSI change). Pick one and make README + `correlation.md` + the rule agree.
  - ⚠️ Docs that overstate are worse than absent in front of a panel that will click.

- [ ] **S3.6 — Rehearse the demo end-to-end, twice** ⏱ 1.5h 🔴
  - See the script below. Time it. Fix whatever breaks. **Do not skip this** — an untested demo path is how a working system loses.

---

# ⚪ P3 — Only if you finish early

- [ ] Wire `/api/institution-risk` (80 lines, built, never called) into a cross-institution panel — a genuine differentiator.
- [ ] Call `initMap()` and feed it `map_towers` from `/api/results` instead of the hardcoded tower list at `app.js:1406-1417`.
- [ ] `.txt` ingestion — the UI accepts `.txt` (`dashboard.html:294`) but `backend/pipeline.py:72` only iterates `.csv/.xlsx/.xls/.pdf`, so `.txt` uploads are **silently dropped**.
- [ ] Bank account extraction from statement headers — `bank_parser.py:265-280` collapses every row of a column-less statement into `ACCT_SBI`/`ACCT_UNKNOWN`, merging different customers into one entity.
- [ ] Add amount/volume features to the IsolationForest vector (`risk_engine.py:101-141` has **no amount feature at all**); switch `contamination=0.1` → `'auto'` (0.1 mechanically guarantees exactly 10% flagged regardless of the data).
- [ ] Fix `/api/reports` entity_id: `main.py:519` `.split("_")[0]` returns `"ENT"` for every report.
- [ ] Delete dead weight: `frontend/components/*.jsx` (Next.js files with no build system), `map_builder` plot functions (~290 lines, 0 references), the orphaned dashboard block at `index.html:785` (**12 duplicate IDs**), root `decision_trace.jsonl` (stale), `server_log.txt`.
- [ ] Fix float row refs in evidence: `decision_trace.jsonl` contains `"cdr_row_1018.0"` — `merge_asof` promotes the column to float64. Cast to nullable `Int64`. Small, but it's a court-exhibit artifact.

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

- [ ] `python backend/main.py` starts clean from a fresh clone
- [ ] Pipeline completes in **< 10s** on the demo dataset
- [ ] `CRITICAL > 0` and **all 7 rules** fire at least once across the dataset
- [ ] Recall **≥75%** and precision **≥70%** under a *single* consistent threshold
- [ ] No number on any screen is hardcoded — swap in a different dataset and verify everything moves
- [ ] **No fabricated hash, size, or row count anywhere in the UI**
- [ ] Money-flow graph renders with real edges; clicking a node shows real evidence rows
- [ ] Timeline view renders for at least one flagged entity
- [ ] Sample `.docx` (forensic + STR) committed **with charts embedded**
- [ ] `README.md` describes only what actually works
- [ ] `pytest backend/tests/` passes with the tautologies removed
- [ ] Demo rehearsed twice, end to end, timed

---

# 📊 Questions that would expose you today

Track these — each should be answerable by submission:

| Question | Today | Fixed by |
|---|---|---|
| "Show me a circular flow." | Structurally impossible | S1.1 + S1.2 |
| "That's the money-flow network?" | It's the identity graph | S1.4 |
| "Where does that SHA-256 come from?" | `Math.random()` | **S0.1** |
| "Open this entity's timeline." | Doesn't exist | S2.1 |
| "Filter to transfers over ₹1L, 2–4 PM." | No filter exists | S2.2 |
| "Why is nothing CRITICAL?" | Two rules are dead | S1.1 |
| "Did every PDF row get parsed?" | 175 of 208; reported 0 skipped | S1.3 |
| "How does this scale?" | 961s @ 48k events | S3.2 |

---

*Findings verified by executing the pipeline and exercising the API in-process. Line references are against the current working tree — re-check after any refactor.*
