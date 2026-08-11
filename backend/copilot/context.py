"""
Grounding context for the Investigation Copilot.

The copilot answers about *this run and no other*. That guarantee is only worth
something if the model physically cannot see anything else, so this module is the
single place where pipeline state becomes prompt text. Two products:

  build_run_digest()      — the whole case, compressed: provenance, metrics, which
                            rules fired and on whom, the layering chains, the money
                            flow, the ground-truth scores.
  build_entity_dossier()  — one entity in full: identifiers, every rule explanation
                            the engine wrote, the evidence row references, and the
                            actual event rows behind them.

Both are plain dicts, and both have a render_* function that flattens them into the
markdown the model is handed. Keeping the dict separate from its rendering means
GET /api/copilot/context can return the *exact* facts the answer was drawn from —
if the copilot ever says something an investigator disputes, that endpoint settles
it.

Nothing here calls an LLM, and nothing here invents a value. Every figure is read
off `STATE["last_results"]`; anything the pipeline did not produce is rendered as
"not available" rather than filled in with something plausible.
"""

import re
from datetime import datetime

import pandas as pd

# ── Rule reference ──────────────────────────────────────────────────────────
# Verbatim from correlation.md §Rules. The model needs to know what STR-1 *means*
# to answer "why was this flagged"; without it, it either guesses from the name
# ("STR" is not "Suspicious Transaction Report" here, it is "structuring") or
# refuses. Descriptions live here rather than being scraped from the markdown so
# the prompt cannot break when a doc file is edited.
RULE_REFERENCE = {
    "IDR-1": {
        "name": "Identity Fan-out",
        "detail": (
            "One resolved entity's identifiers fan out past a single subscriber's "
            "footprint: one IMEI operating 2+ MSISDNs (HIGH — a handset cycling SIMs), "
            "3+ distinct accounts or 2+ IMEIs (MEDIUM; two limbs together escalate to "
            "HIGH). A SIM/device swap on one number is also caught, graded by whether a "
            "transfer sits near the change."
        ),
    },
    "TCS-1": {
        "name": "Temporal Coincidence",
        "detail": (
            "A call AND an active IP session both fall within the correlation window W "
            "of a transaction — the three data sources agreeing on one moment."
        ),
    },
    "TCS-2": {
        "name": "Call-Then-Transfer",
        "detail": (
            "A call to a specific B-party occurs 1–15 minutes before a transfer to an "
            "account or VPA linked to that same number."
        ),
    },
    "STR-1": {
        "name": "Structuring",
        "detail": (
            "3+ transactions just under a reporting threshold (e.g. ₹49,000 against a "
            "₹50,000 threshold) inside 24–48 hours — deliberate splitting to stay below "
            "a reporting line."
        ),
    },
    "LAY-1": {
        "name": "Layering / Circular Flow",
        "detail": (
            "A→B→C→D and back toward the origin within hours, with the amount shrinking "
            "roughly 5–15% at each hop (a commission skim). The hops are recorded in the "
            "evidence as a 'chain:' token."
        ),
    },
    "MUL-1": {
        "name": "Mule Signature",
        "detail": (
            "An account dormant for 30+ days, then a sudden large inflow, then 80%+ of it "
            "back out within minutes to hours, retaining almost no balance."
        ),
    },
    "LOC-1": {
        "name": "Geo-Improbable Movement",
        "detail": (
            "Two events for the same entity at incompatible cell-tower / IP-geo locations "
            "separated by an impossible travel time."
        ),
    },
}

# The gating logic from backend/scoring/risk_engine.py:compute_risk_tier. Stated to
# the model so "why is this CRITICAL and that one HIGH?" is answered from the actual
# rule, not from an assumption that more rules means a higher tier.
TIER_LOGIC = (
    "CRITICAL — (MUL-1 AND (TCS-1 or TCS-2)) OR (LAY-1 AND (IDR-1 or TCS)) OR "
    "(IDR-1 at HIGH severity AND 2+ rules fired). Corroboration across sources is required.\n"
    "HIGH — a single money-pattern or velocity rule alone (STR-1, MUL-1, LAY-1, LOC-1), "
    "or IDR-1 at HIGH severity alone, or IDR-1 + a TCS rule.\n"
    "MEDIUM — a single temporal correlation rule (TCS-1 or TCS-2) with no money-pattern "
    "rule, or IDR-1 at MEDIUM severity alone.\n"
    "LOW — no rule fired.\n"
    "ML anomaly (IsolationForest) is reported as a SEPARATE signal and never changes the "
    "tier; a LOW entity carrying an ML flag has still not triggered any named rule."
)

TIER_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}

#: Cap on how many flagged entities are described individually. Every CRITICAL and
#: HIGH entity is always included; MEDIUM fills the remainder. On a large upload the
#: alternative is a prompt that is mostly a roster of MEDIUM entities nobody asked
#: about, which crowds out the ones that matter.
MAX_ENTITY_ROWS = 40

#: Explanations are engine-written sentences and are usually one line, but LAY-1 on a
#: long chain can run to several hundred characters. Truncated rather than dropped —
#: a clipped explanation is still evidence, an absent one is a hole.
MAX_EXPLANATION_CHARS = 420


def _f(value, default=0.0):
    """Float or default — pipeline values arrive as numpy scalars, None and NaN."""
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _text(value):
    """Displayable string, with pandas' null sentinels collapsed to empty."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return "" if text.lower() in ("nan", "none", "nat", "<na>") else text


def _inr(amount):
    """Rupee figure for prompt text. Plain grouping — the model reads digits, not lakhs."""
    return f"₹{_f(amount):,.0f}"


def _clip(text, limit=MAX_EXPLANATION_CHARS):
    text = _text(text)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# ── Entity mention detection ────────────────────────────────────────────────

_ENT_PATTERN = re.compile(r"\bENT[\s_\-]?(\d{1,6})\b", re.IGNORECASE)


def detect_entity_mentions(question, entities, limit=3):
    """
    Find which entities a free-text question is about.

    Three ways in, because investigators do not type canonical ids:
      1. "ENT-0043", "ent 43", "ENT_0043"  → normalised to the pipeline's ENT_0043
      2. a KYC name that appears in the question
      3. a phone number, account number, VPA or IMEI that resolves to an entity

    Returns entity ids in the order they were matched, capped — attaching six full
    dossiers to one question buries the question.
    """
    if not question or not entities:
        return []

    found = []

    def add(eid):
        if eid in entities and eid not in found:
            found.append(eid)

    # 1. Explicit ids. The pipeline pads to four digits (ENT_0043); a user typing
    #    "ENT-43" means the same entity and should not get an "unknown entity" reply.
    for raw in _ENT_PATTERN.findall(question):
        digits = raw.lstrip("0") or "0"
        add(f"ENT_{int(digits):04d}")
        add(f"ENT_{raw}")

    lowered = question.lower()

    # 2. Names, longest first so "Yashica Issac" wins over a bare "Issac" that also
    #    matches a different entity.
    named = sorted(
        ((eid, _text(data.get("name"))) for eid, data in entities.items()),
        key=lambda pair: -len(pair[1]),
    )
    for eid, name in named:
        if len(name) >= 4 and name.lower() in lowered:
            add(eid)

    # 3. Raw identifiers. Digits are compared with separators stripped so
    #    "+91 98250-11234" matches the stored 9825011234.
    digits_in_q = set(re.findall(r"\d{6,}", re.sub(r"[\s\-()+]", "", question)))
    if digits_in_q:
        for eid, data in entities.items():
            for key in ("phones", "accounts", "imeis", "vpas"):
                for ident in data.get(key, []) or []:
                    ident_digits = re.sub(r"\D", "", str(ident))
                    if ident_digits and ident_digits in digits_in_q:
                        add(eid)
        for eid, data in entities.items():
            for vpa in data.get("vpas", []) or []:
                if _text(vpa) and _text(vpa).lower() in lowered:
                    add(eid)

    return found[:limit]


# ── Run digest ──────────────────────────────────────────────────────────────


def _layering_chains(scored_entities):
    """Every detected layering path, read from the 'chain:' token LAY-1 emits."""
    chains = []
    seen = set()
    for eid, sdata in scored_entities.items():
        for token in (sdata.get("evidence", {}) or {}).get("LAY-1", []) or []:
            if isinstance(token, str) and token.startswith("chain:"):
                path = [p for p in token[len("chain:") :].split(">") if p]
                key = tuple(path)
                if len(path) >= 2 and key not in seen:
                    seen.add(key)
                    chains.append({"hops": path, "detected_on": eid})
    return chains


def _money_flow_summary(network_graph, scored_entities, top_n=12):
    """Totals and the largest transfers, straight off the money-flow DiGraph."""
    summary = {
        "available": False,
        "entities_in_graph": 0,
        "transfer_edges": 0,
        "call_edges": 0,
        "total_transferred": 0.0,
        "largest_transfers": [],
    }
    if network_graph is None or network_graph.number_of_nodes() == 0:
        return summary

    summary["available"] = True
    summary["entities_in_graph"] = int(network_graph.number_of_nodes())

    transfers = []
    for u, v, data in network_graph.edges(data=True):
        if data.get("edge_type") == "transaction":
            weight = _f(data.get("weight"))
            summary["transfer_edges"] += 1
            summary["total_transferred"] += weight
            transfers.append(
                {
                    "from": u,
                    "to": v,
                    "amount": weight,
                    "count": int(data.get("count", 1) or 1),
                    "from_tier": scored_entities.get(u, {}).get("risk_tier", "LOW"),
                    "to_tier": scored_entities.get(v, {}).get("risk_tier", "LOW"),
                }
            )
        else:
            summary["call_edges"] += 1

    transfers.sort(key=lambda t: -t["amount"])
    summary["largest_transfers"] = transfers[:top_n]
    return summary


def _entity_value_flow(network_graph, eid):
    """(in, out) rupee totals for one entity across transaction edges only."""
    if network_graph is None or not network_graph.has_node(eid):
        return 0.0, 0.0
    value_in = sum(
        _f(d.get("weight"))
        for _, _, d in network_graph.in_edges(eid, data=True)
        if d.get("edge_type") == "transaction"
    )
    value_out = sum(
        _f(d.get("weight"))
        for _, _, d in network_graph.out_edges(eid, data=True)
        if d.get("edge_type") == "transaction"
    )
    return value_in, value_out


def _dataset_span(all_events_df):
    """First and last event timestamps — the period the case actually covers."""
    if all_events_df is None or len(all_events_df) == 0 or "timestamp" not in all_events_df:
        return None, None
    stamps = pd.to_datetime(all_events_df["timestamp"], errors="coerce").dropna()
    if stamps.empty:
        return None, None
    return str(stamps.min()), str(stamps.max())


def build_run_digest(results, data_mode="demo", evidence_files=None,
                     max_entities=MAX_ENTITY_ROWS):
    """
    Compress a completed pipeline run into the facts the copilot may speak from.

    `results` is STATE["last_results"] — the dict pipeline.run_pipeline() returns.
    `evidence_files` is the /api/evidence-files record list, so the copilot can
    answer chain-of-custody questions ("which files is this built on, and do their
    hashes still match?") without a second source of truth.
    """
    entities = results.get("entities", {}) or {}
    scored = results.get("scored_entities", {}) or {}
    all_events = results.get("all_events", []) or []
    all_events_df = results.get("all_events_df")
    network_graph = results.get("network_graph")

    tier_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    rule_firings = {}
    ml_count = 0

    for sdata in scored.values():
        tier = sdata.get("risk_tier", "LOW")
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        if sdata.get("ml_anomaly"):
            ml_count += 1
        for rule_id in sdata.get("rules_fired", []) or []:
            rule_firings[rule_id] = rule_firings.get(rule_id, 0) + 1

    # Entities worth describing: every CRITICAL/HIGH, then MEDIUM until the cap.
    ranked = sorted(
        ((eid, s) for eid, s in scored.items() if s.get("risk_tier") != "LOW"),
        key=lambda pair: (
            TIER_ORDER.get(pair[1].get("risk_tier", "LOW"), 3),
            -len(pair[1].get("rules_fired", []) or []),
            pair[0],
        ),
    )
    included, omitted = ranked[:max_entities], max(0, len(ranked) - max_entities)

    entity_rows = []
    for eid, sdata in included:
        ent = entities.get(eid, {}) or {}
        value_in, value_out = _entity_value_flow(network_graph, eid)
        entity_rows.append(
            {
                "entity_id": eid,
                "name": _text(ent.get("name")) or "Unknown",
                "risk_tier": sdata.get("risk_tier", "LOW"),
                "rules_fired": list(sdata.get("rules_fired", []) or []),
                "rule_severities": dict(sdata.get("rule_severities", {}) or {}),
                "ml_anomaly": bool(sdata.get("ml_anomaly")),
                "explanations": {
                    rid: _clip(text)
                    for rid, text in (sdata.get("explanations", {}) or {}).items()
                },
                "phones": [str(p) for p in (ent.get("phones") or [])[:5]],
                "accounts": [str(a) for a in (ent.get("accounts") or [])[:5]],
                "vpas": [str(v) for v in (ent.get("vpas") or [])[:4]],
                "imeis": [str(i) for i in (ent.get("imeis") or [])[:4]],
                "value_in": value_in,
                "value_out": value_out,
            }
        )

    # An ML flag on an otherwise-clean entity is a real finding and is invisible in
    # the tier counts, so it is listed separately rather than left for the model to
    # dig out of a roster it was never given.
    ml_only = [
        eid
        for eid, s in scored.items()
        if s.get("ml_anomaly") and not (s.get("rules_fired") or [])
    ][:15]

    span_start, span_end = _dataset_span(all_events_df)

    event_type_counts = {}
    if all_events_df is not None and len(all_events_df) and "event_type" in all_events_df:
        event_type_counts = {
            str(k): int(v) for k, v in all_events_df["event_type"].value_counts().items()
        }

    kyc_anchored = sum(
        1
        for e in entities.values()
        if len(e.get("phones", []) or [])
        + len(e.get("accounts", []) or [])
        + len(e.get("imeis", []) or [])
        + len(e.get("vpas", []) or [])
        > 1
    )

    verification = results.get("verification", {}) or {}

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "data_mode": data_mode,
        "window_minutes": int(results.get("window_minutes", 10) or 10),
        "evidence_files": [
            {
                "filename": f.get("filename"),
                "detected_type": f.get("detected_type"),
                "rows_parsed": f.get("rows_parsed"),
                "rows_skipped": f.get("rows_skipped"),
                "sha256": (f.get("sha256") or "")[:16],
                "status": f.get("status"),
                "modified_since_ingest": bool(f.get("modified_since_ingest")),
            }
            for f in (evidence_files or [])
        ],
        "metrics": {
            "total_entities": len(entities),
            "kyc_anchored_entities": kyc_anchored,
            "unmapped_passthrough_entities": len(entities) - kyc_anchored,
            "total_events": len(all_events),
            "event_type_counts": event_type_counts,
            "dataset_start": span_start,
            "dataset_end": span_end,
            "critical_count": tier_counts["CRITICAL"],
            "high_count": tier_counts["HIGH"],
            "medium_count": tier_counts["MEDIUM"],
            "low_count": tier_counts["LOW"],
            "flagged_suspects": tier_counts["CRITICAL"] + tier_counts["HIGH"] + tier_counts["MEDIUM"],
            "ml_anomalies": ml_count,
            "total_rule_firings": sum(rule_firings.values()),
        },
        "rule_firings": rule_firings,
        "entities": entity_rows,
        "entities_omitted": omitted,
        "ml_only_entities": ml_only,
        "layering_chains": _layering_chains(scored),
        "money_flow": _money_flow_summary(network_graph, scored),
        "verification": {
            "recall": verification.get("recall"),
            "precision": verification.get("precision"),
            "f1": verification.get("f1"),
            "true_positives": verification.get("true_positives"),
            "false_positives": verification.get("false_positives"),
            "false_negatives": verification.get("false_negatives"),
            "total_gt_entities": verification.get("total_gt_entities"),
        }
        if verification
        else {},
    }


def render_digest(digest):
    """Flatten a run digest into the markdown block handed to the model."""
    m = digest["metrics"]
    out = []

    out.append("## CASE CONTEXT — current pipeline run")
    out.append(
        f"Dataset mode: **{digest['data_mode']}** "
        f"({'operator-uploaded files' if digest['data_mode'] == 'upload' else 'built-in demo dataset'}). "
        f"Correlation window W = ±{digest['window_minutes']} minutes. "
        f"Digest built {digest['generated_at']}."
    )

    if digest["evidence_files"]:
        out.append("\n### Source files (chain of custody)")
        for f in digest["evidence_files"]:
            parsed = f["rows_parsed"]
            rows = f"{parsed} rows parsed" if parsed is not None else "no row count (reference file)"
            warn = "  ⚠ FILE MODIFIED SINCE INGEST" if f["modified_since_ingest"] else ""
            out.append(
                f"- {f['filename']} — {f.get('detected_type') or f.get('status') or 'unknown type'}, "
                f"{rows}, sha256 {f['sha256']}…{warn}"
            )

    out.append("\n### Totals")
    out.append(
        f"- {m['total_events']:,} events resolved into {m['total_entities']:,} entities "
        f"({m['kyc_anchored_entities']:,} KYC-anchored, {m['unmapped_passthrough_entities']:,} passthrough identifiers)."
    )
    if m["event_type_counts"]:
        out.append(
            "- Events by type: "
            + ", ".join(f"{k} {v:,}" for k, v in sorted(m["event_type_counts"].items()))
            + "."
        )
    if m["dataset_start"]:
        out.append(f"- Period covered: {m['dataset_start']} → {m['dataset_end']}.")
    out.append(
        f"- Risk tiers: CRITICAL {m['critical_count']}, HIGH {m['high_count']}, "
        f"MEDIUM {m['medium_count']}, LOW {m['low_count']}. "
        f"{m['flagged_suspects']} flagged in total."
    )
    out.append(
        f"- {m['total_rule_firings']} rule firings. "
        f"{m['ml_anomalies']} entities carry an IsolationForest ML anomaly flag "
        f"(separate signal — it does not set the tier)."
    )

    if digest["rule_firings"]:
        out.append("\n### Rules fired this run")
        for rid, count in sorted(digest["rule_firings"].items(), key=lambda kv: -kv[1]):
            ref = RULE_REFERENCE.get(rid, {})
            noun = "entity" if count == 1 else "entities"
            out.append(f"- **{rid} ({ref.get('name', 'rule')})** — {count} {noun}. {ref.get('detail', '')}")
    else:
        out.append("\n### Rules fired this run\nNo named rule fired on this dataset.")

    if digest["layering_chains"]:
        out.append("\n### Detected layering chains (LAY-1)")
        for chain in digest["layering_chains"][:10]:
            out.append(f"- {' → '.join(chain['hops'])}  (detected on {chain['detected_on']})")

    mf = digest["money_flow"]
    if mf["available"]:
        out.append("\n### Money flow")
        out.append(
            f"- {mf['entities_in_graph']:,} entities in the money-flow graph; "
            f"{mf['transfer_edges']:,} transfer edges totalling {_inr(mf['total_transferred'])}, "
            f"{mf['call_edges']:,} contact-only edges."
        )
        if mf["largest_transfers"]:
            out.append("- Largest transfer relationships:")
            for t in mf["largest_transfers"]:
                out.append(
                    f"  - {t['from']} ({t['from_tier']}) → {t['to']} ({t['to_tier']}): "
                    f"{_inr(t['amount'])} across {t['count']} transfer(s)"
                )

    if digest["entities"]:
        out.append("\n### Flagged entities (every CRITICAL and HIGH; MEDIUM up to the cap)")
        for e in digest["entities"]:
            rules = ", ".join(
                f"{r}{'(' + e['rule_severities'][r] + ')' if r in e['rule_severities'] else ''}"
                for r in e["rules_fired"]
            ) or "none"
            head = f"\n**{e['entity_id']} — {e['name']} — {e['risk_tier']}**"
            if e["ml_anomaly"]:
                head += " · ML anomaly flagged"
            out.append(head)
            out.append(f"- Rules: {rules}")
            out.append(f"- Money: in {_inr(e['value_in'])}, out {_inr(e['value_out'])}")
            idents = []
            for label, key in (("phones", "phones"), ("accounts", "accounts"),
                               ("VPAs", "vpas"), ("IMEIs", "imeis")):
                if e[key]:
                    idents.append(f"{label} {', '.join(e[key])}")
            if idents:
                out.append(f"- Identifiers: {'; '.join(idents)}")
            for rid, text in e["explanations"].items():
                out.append(f"- {rid} finding: {text}")
        if digest["entities_omitted"]:
            out.append(
                f"\n({digest['entities_omitted']} further MEDIUM-tier entities are not listed "
                f"individually — say so rather than guessing at them.)"
            )
    else:
        out.append("\n### Flagged entities\nNo entity was escalated above LOW on this dataset.")

    if digest["ml_only_entities"]:
        out.append(
            "\n### ML-only flags (anomalous, but no named rule fired)\n"
            + ", ".join(digest["ml_only_entities"])
        )

    v = digest.get("verification") or {}
    if v.get("recall") is not None:
        out.append("\n### Ground-truth verification for this run")
        out.append(
            f"- Recall {_f(v['recall']):.1%}, precision {_f(v.get('precision')):.1%}, "
            f"F1 {_f(v.get('f1')):.2f} against {v.get('total_gt_entities')} labelled entities "
            f"({v.get('true_positives')} true positives, {v.get('false_positives')} false positives, "
            f"{v.get('false_negatives')} missed)."
        )

    return "\n".join(out)


# ── Entity dossier ──────────────────────────────────────────────────────────


def build_entity_dossier(results, entity_id, max_events=60):
    """
    Everything the engine knows about one entity, for entity-scoped questions.

    Rule explanations answer "why", the evidence tokens say which rows were cited,
    and the raw event rows are the rows themselves — so the copilot can quote a
    source line and its file rather than paraphrasing a conclusion.
    """
    entities = results.get("entities", {}) or {}
    entity_map = results.get("entity_map", {}) or {}
    scored = results.get("scored_entities", {}) or {}
    all_events_df = results.get("all_events_df")
    network_graph = results.get("network_graph")

    target = entity_id
    if target not in entities and target in entity_map:
        target = entity_map[target]
    if target not in entities:
        return None

    ent = entities.get(target, {}) or {}
    sdata = scored.get(target, {}) or {}
    value_in, value_out = _entity_value_flow(network_graph, target)

    events = []
    total_events = 0
    if all_events_df is not None and len(all_events_df):
        mine = all_events_df[all_events_df["entity_id"] == target]
        total_events = int(len(mine))
        if "timestamp" in mine.columns:
            mine = mine.sort_values("timestamp")
        for idx, row in mine.head(max_events).iterrows():
            events.append(
                {
                    "timestamp": _text(row.get("timestamp")),
                    "event_type": _text(row.get("event_type")),
                    "amount": _f(row.get("amount")),
                    "direction": _text(row.get("direction")),
                    "counterparty": _text(row.get("counterparty")),
                    "location": _text(row.get("location")),
                    "channel": _text(row.get("channel")),
                    "source_file": _text(row.get("source_file")) or "unknown",
                    "row_ref": _text(row.get("raw_row_ref")) or str(idx),
                }
            )

    counterparties = []
    if network_graph is not None and network_graph.has_node(target):
        for _, dst, data in network_graph.out_edges(target, data=True):
            counterparties.append(
                {
                    "entity_id": dst,
                    "direction": "out",
                    "edge_type": data.get("edge_type", "transaction"),
                    "amount": _f(data.get("weight")),
                    "tier": scored.get(dst, {}).get("risk_tier", "LOW"),
                }
            )
        for src, _, data in network_graph.in_edges(target, data=True):
            counterparties.append(
                {
                    "entity_id": src,
                    "direction": "in",
                    "edge_type": data.get("edge_type", "transaction"),
                    "amount": _f(data.get("weight")),
                    "tier": scored.get(src, {}).get("risk_tier", "LOW"),
                }
            )
        counterparties.sort(key=lambda c: -c["amount"])

    return {
        "entity_id": target,
        "name": _text(ent.get("name")) or "Unknown",
        "risk_tier": sdata.get("risk_tier", "LOW"),
        "rules_fired": list(sdata.get("rules_fired", []) or []),
        "rule_severities": dict(sdata.get("rule_severities", {}) or {}),
        "ml_anomaly": bool(sdata.get("ml_anomaly")),
        "explanations": {
            rid: _clip(text, 900)
            for rid, text in (sdata.get("explanations", {}) or {}).items()
        },
        "evidence": {
            rid: [str(t) for t in (tokens or [])][:25]
            for rid, tokens in (sdata.get("evidence", {}) or {}).items()
        },
        "identifiers": {
            "phones": [str(p) for p in (ent.get("phones") or [])],
            "accounts": [str(a) for a in (ent.get("accounts") or [])],
            "vpas": [str(v) for v in (ent.get("vpas") or [])],
            "imeis": [str(i) for i in (ent.get("imeis") or [])],
            "ips": [str(i) for i in (ent.get("ips") or [])][:10],
        },
        "value_in": value_in,
        "value_out": value_out,
        "counterparties": counterparties[:15],
        "events": events,
        "total_events": total_events,
        "events_truncated": total_events > len(events),
    }


def render_dossier(dossier):
    """Flatten one entity dossier into markdown for the prompt."""
    out = [f"\n## ENTITY DOSSIER — {dossier['entity_id']}"]
    head = f"{dossier['name']} · risk tier **{dossier['risk_tier']}**"
    if dossier["ml_anomaly"]:
        head += " · ML anomaly flagged"
    out.append(head)

    rules = ", ".join(
        f"{r}{'(' + dossier['rule_severities'][r] + ')' if r in dossier['rule_severities'] else ''}"
        for r in dossier["rules_fired"]
    )
    out.append(f"Rules fired: {rules or 'none'}")
    out.append(f"Money: in {_inr(dossier['value_in'])}, out {_inr(dossier['value_out'])}")

    idents = dossier["identifiers"]
    ident_bits = [f"{k} {', '.join(v)}" for k, v in idents.items() if v]
    if ident_bits:
        out.append("Identifiers: " + "; ".join(ident_bits))

    if dossier["explanations"]:
        out.append("\n### Why the engine flagged it")
        for rid, text in dossier["explanations"].items():
            out.append(f"- **{rid}**: {text}")
            tokens = dossier["evidence"].get(rid) or []
            if tokens:
                out.append(f"  - cited evidence: {', '.join(tokens[:12])}")

    if dossier["counterparties"]:
        out.append("\n### Direct counterparties (money-flow graph)")
        for c in dossier["counterparties"]:
            arrow = "→" if c["direction"] == "out" else "←"
            label = _inr(c["amount"]) if c["edge_type"] == "transaction" else "contact only (calls/SMS)"
            out.append(f"- {arrow} {c['entity_id']} ({c['tier']}): {label}")

    if dossier["events"]:
        out.append(
            f"\n### Event rows ({len(dossier['events'])} of {dossier['total_events']} shown"
            + (", truncated" if dossier["events_truncated"] else "")
            + ")"
        )
        for e in dossier["events"]:
            bits = [e["timestamp"], e["event_type"]]
            if e["amount"]:
                bits.append(f"{_inr(e['amount'])} {e['direction']}".strip())
            if e["counterparty"]:
                bits.append(f"cp {e['counterparty']}")
            if e["location"]:
                bits.append(f"@{e['location']}")
            bits.append(f"[{e['source_file']} row {e['row_ref']}]")
            out.append("- " + " · ".join(b for b in bits if b))

    return "\n".join(out)
