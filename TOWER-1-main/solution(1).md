# SOLUTION.md — Financial & Telecom Fusion Analyzer (ERH26_PS_03)

## 1. What this actually is
An investigator's tool that ingests three sources that never talk to each other in real life —
bank statements, CDR (call records), IPDR (internet session records) — resolves them onto ONE
entity per suspect, ONE timeline, and automatically surfaces the correlations a human analyst
would otherwise spend hours finding by eye.

This mirrors what Indian cyber cells already do manually via NCRP's Layer 1→2→3→4 fund-trail
method (Layer 1 = account fraud money first lands in, Layer 2 = where that account moves it,
Layer 3/4 = further downstream) and what I4C's Samanvaya platform does at national scale
(interstate case linkage) and Suspect Registry does for mule accounts. We are building a
single-case, deployable version of that same idea.

## 2. Core insight that wins this (say this out loud in your pitch)
"Three institutions — a bank, a telecom operator, an ISP — each hold one-third of the truth.
Nobody currently fuses them automatically. The decisive evidence always lives at the
intersection, not inside any one dataset." Everything you build should visibly prove this
sentence in the live demo.

## 3. What separates a winning build from a generic one
- A generic team: 3 parsers → 3 tables → dashboard. That's a file viewer, not fusion.
- Winning team: entity resolution graph + windowed temporal join + DETERMINISTIC named rules
  + a live "plant the fraud, watch it get found" demo + an explainability trace per flag.
- Judges will ask "how did you get this risk score" in round 2 defense. If your answer is
  "the model said so," you lose. If your answer is "rule TCS-1 fired because a call to this
  number happened 90 seconds before this transfer, here's the exact rows," you win. Build for
  that question from minute one — this is the same lesson MALCORE taught you: linear/black-box
  scoring gets dangerous cases through; named, compound, explainable rules don't.

## 4. Five things to build, in priority order (assume ~5-6 hrs)
1. Canonical schema + entity resolution graph (identity linking across 3 sources)
2. Windowed temporal correlation join (the actual "fusion")
3. Compound rule-based risk scoring with named rule IDs + Isolation Forest as a secondary signal
4. NetworkX money/comms graph + timeline visualization
5. One planted, walkable fraud scenario for the live demo + PDF report export

Skip/cut first if time runs out: NLP query bonus, cross-bank heatmaps, full STR auto-generation.
Never cut: the entity resolution graph and the explainability trace — those are what judges
actually probe in Q&A.

## 5. Judge-defense talking points (memorize these, don't read them off a slide)
- Legal basis: CDR/IPDR requests are made under IT Act S.69 / Telegraph Act, require SP-rank
  sign-off with an FIR number, and are admissible in court under Evidence Act S.65B with proper
  certification — your tool assumes this evidentiary chain is already in place; you're the
  analysis layer, not a surveillance tool. Say this proactively, before anyone asks — it kills
  the "is this tool ethical/legal" question dead in one sentence.
- Real detection logic references: RBI mule-account red flags (unusual frequency, rapid
  in-and-out movement with no balance retention, deposits just under reporting thresholds),
  the NCRP Layer 1-4 fund-trail structure, and I4C's own Suspect Registry / Samanvaya model.
- Local relevance: Gujarat (Ahmedabad/Surat) is consistently among India's highest cyber-fraud
  complaint states, with a cash-intensive trade economy (Surat diamond/textile) that creates
  exactly the structuring/layering risk profile this tool targets. Use this instead of generic
  "cybercrime is rising" filler.

## 6. Research & References (cite these explicitly in your PPT/report — this is what
proves you didn't just wing the approach)
- **Entity resolution / fusion methodology**: MITRE's SEXTANT (arXiv:1906.02686) —
  "Fusion of Mobile Device Signal Data Attributes Enables Multi-Protocol Entity Resolution
  and Enhanced Large-Scale Tracking." This is your direct methodological basis for
  correlation.md Layer 1 — spatio-temporal correlation resolving one device/entity across
  multiple signal types without a shared ID field, tested at ~300,000 devices / 200M+
  observations scale in the original work.
- **CDR/IPDR field-level analysis on real Indian data**: arXiv:1809.09747 — analyzes actual
  Delhi Police CDR/IPDR data, demonstrates extracting app usage (e.g. WhatsApp) via
  destination-port matching from IPDR, and builds subscriber "personas" from telecom
  metadata alone. Cite this directly for your IPDR parsing/app-fingerprinting logic — it's
  the closest real precedent to what your ingestion layer does.
- **Synthetic dataset methodology**: PaySim (Lopez-Rojas et al., 2016) — agent-based mobile
  money simulator built specifically because real financial transaction data is private and
  unpublishable; and IBM AMLSim/AMLworld (arXiv:2306.16424) — purpose-built money-laundering
  pattern simulator modeling the full placement→layering→integration cycle including
  circular/fan-out transfer structures. These are your direct citation for dataset.md's
  generate-ground-truth-then-export-messy-formats approach — you are not inventing a
  methodology, you are following the established one researchers use for this exact
  data-privacy constraint.
- **Real-world institutional grounding**: NCRP's Layer 1→2→3→4 fund-trail investigation
  method (official cyber cell investigation checklist), I4C's Suspect Registry (21.65 lakh+
  suspect identifiers, 26.48 lakh Layer-1 mule accounts shared, ₹9,055+ crore in blocked
  transactions) and Samanvaya platform (interstate case-linkage analytics) as the
  national-scale precedent this prototype scopes down to a single-case tool.

Put these four bullets on one "Research Basis" slide — SEXTANT for the resolution
algorithm, the Delhi CDR/IPDR paper for the parsing layer, PaySim/AMLSim for the dataset,
NCRP/I4C for real-world grounding. That is a complete, defensible research chain covering
every technical claim in your build, not just the cybercrime-is-rising framing everyone else
will use.

## 7. Demo script (what you actually say/click, in order)
1. "Here are three raw files — a bank Excel, a CDR CSV, an IPDR CSV — from three different
   sources with zero shared schema."
2. Run ingestion live → show canonical normalized table.
3. Show entity resolution graph forming — "these five raw IDs are actually one person."
4. Show unified timeline for the flagged entity — call, then IP session, then transfer,
   within minutes.
5. Show risk score breakdown card: "Why This Score?" — name the rules that fired.
6. Show the money-flow graph — circular/layered transfer pattern lighting up.
7. Export the one-click forensic PDF report.
8. Close with the legal-basis sentence from section 5.
