"""
E-Rakshak Pipeline Orchestrator
=================================
End-to-end pipeline: raw files -> parse -> resolve -> correlate -> score -> verify
With progress callbacks for real-time Streamlit status updates.
"""
import sys
import os
import hashlib
from pathlib import Path

import pandas as pd

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from ingestion.smart_ingest import parse_messy_file
from resolution.entity_resolver import run_entity_resolution
from correlation.temporal_join import temporal_join
from correlation.rules import run_all_rules
from scoring.risk_engine import run_risk_engine
from graph.network_builder import build_network_graph, create_network_plotly, create_timeline_plotly
from report.forensic_report import generate_reports_for_flagged
from verification.verify import verify_against_ground_truth


def sha256_file(path, chunk_size=1024 * 1024):
    """
    Compute the real SHA-256 digest of a file by streaming it through hashlib.

    This is the only source of any hash string shown in the UI or written into a
    report — nothing in E-Rakshak fabricates or truncates a digest for display.
    Returns the lowercase hex digest, or None if the file cannot be read.
    """
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def run_pipeline(data_dir=None, window_minutes=10, generate_reports=False, progress_callback=None):
    """
    Run the full E-Rakshak pipeline.

    Args:
        data_dir: path to directory containing raw files
        window_minutes: temporal correlation window in minutes
        generate_reports: whether to generate forensic Word reports
        progress_callback: optional function(step_name, step_num, total_steps, detail_msg)

    Returns:
        dict with all pipeline outputs + quality_summary
    """
    if data_dir is None:
        data_dir = PROJECT_ROOT / "data" / "raw"
    data_dir = Path(data_dir)

    total_steps = 8
    # "files" holds one provenance record per ingested file: real byte size, real
    # hashlib SHA-256 digest and the true parsed/skipped row counts. This is what
    # the Evidence Vault renders — there is no fabricated chain-of-custody data.
    quality = {"steps": [], "errors": [], "warnings": [], "files": []}

    def notify(step_name, step_num, detail=""):
        msg = f"[{step_num}/{total_steps}] {step_name}"
        if detail:
            msg += f" — {detail}"
        print(msg)
        if progress_callback:
            try:
                progress_callback(step_name, step_num, total_steps, detail)
            except Exception:
                pass

    print("=" * 60)
    print("E-RAKSHAK FORENSIC ANALYSIS PIPELINE")
    print("=" * 60)

    # ---- STEP 1: INGESTION ----
    notify("Ingesting raw data files", 1, "Parsing bank/CDR/IPDR files...")
    
    bank_events = []
    cdr_events = []
    ipdr_events = []
    
    try:
        if data_dir.exists():
            for f in data_dir.iterdir():
                if f.is_file() and not f.name.endswith('.json') and f.suffix.lower() in ['.csv', '.xlsx', '.xls', '.pdf']:
                    print(f"  Parsing file: {f.name}")
                    file_events, summary = parse_messy_file(f)

                    record = {
                        "filename": f.name,
                        "extension": f.suffix.lower().lstrip("."),
                        "size_bytes": f.stat().st_size,
                        "sha256": sha256_file(f),
                        "detected_type": summary.get("detected_type"),
                        "confidence": summary.get("confidence"),
                        "total_rows": summary.get("total_rows"),
                        "rows_parsed": summary.get("parsed_rows", len(file_events)),
                        "rows_skipped": summary.get("skipped_rows"),
                        "status": "PARSED",
                        "error": summary.get("error"),
                    }

                    if "error" in summary:
                        record["status"] = "FAILED"
                        quality["files"].append(record)
                        quality["warnings"].append(f"Skipped {f.name}: {summary['error']}")
                        continue

                    det_type = summary.get("detected_type")
                    if det_type == "bank":
                        bank_events.extend(file_events)
                    elif det_type == "cdr":
                        cdr_events.extend(file_events)
                    elif det_type == "ipdr":
                        ipdr_events.extend(file_events)
                    else:
                        record["status"] = "UNRECOGNISED"
                        quality["warnings"].append(f"Skipped {f.name}: Unknown file type")

                    skipped = record.get("rows_skipped")
                    if skipped:
                        quality["warnings"].append(
                            f"{f.name}: {skipped} row(s) could not be parsed and were excluded"
                        )
                    print(f"    -> {record['rows_parsed']} row(s) parsed, {skipped if skipped is not None else 'unknown'} skipped"
                          f" · sha256:{(record['sha256'] or '')[:16]}…")

                    quality["files"].append(record)
    except Exception as e:
        quality["errors"].append(f"Ingestion critical error: {str(e)}")

    print(f"  Bank events: {len(bank_events)}")
    print(f"  CDR events: {len(cdr_events)}")
    print(f"  IPDR events: {len(ipdr_events)}")

    total_parsed = len(bank_events) + len(cdr_events) + len(ipdr_events)
    total_skipped = sum((rec.get("rows_skipped") or 0) for rec in quality["files"])
    print(f"  TOTAL PARSED: {total_parsed}")
    print(f"  TOTAL SKIPPED (unparseable rows): {total_skipped}")
    quality["steps"].append({"name": "Ingestion", "bank": len(bank_events), "cdr": len(cdr_events),
                             "ipdr": len(ipdr_events), "total": total_parsed, "skipped": total_skipped,
                             "files": len(quality["files"])})

    # ---- STEP 2: ENTITY RESOLUTION ----
    notify("Resolving entities", 2, "Building identity graph...")
    try:
        entity_map, entities, identity_graph, id_types, bank_events, cdr_events, ipdr_events = \
            run_entity_resolution(bank_events, cdr_events, ipdr_events, data_dir=data_dir)
        quality["steps"].append({"name": "Entity Resolution", "entities": len(entities), "raw_ids": identity_graph.number_of_nodes()})
    except Exception as e:
        entity_map, entities, identity_graph, id_types = {}, {}, None, {}
        quality["errors"].append(f"Entity resolution error: {str(e)}")

    # ---- COMBINE ALL EVENTS ----
    all_events = bank_events + cdr_events + ipdr_events
    all_events_df = pd.DataFrame(all_events)

    if not all_events_df.empty:
        all_events_df['timestamp'] = pd.to_datetime(all_events_df['timestamp'])
        if 'end_timestamp' in all_events_df.columns:
            all_events_df['end_timestamp'] = pd.to_datetime(all_events_df['end_timestamp'], errors='coerce')

    # ---- STEP 3: TEMPORAL CORRELATION ----
    notify("Running temporal correlation", 3, f"Window = {window_minutes} min")
    try:
        enriched_txns = temporal_join(all_events, window_minutes=window_minutes)
        correlated_count = 0
        if not enriched_txns.empty and 'has_both_correlation' in enriched_txns.columns:
            correlated_count = enriched_txns['has_both_correlation'].sum()
        quality["steps"].append({"name": "Temporal Correlation", "correlated": int(correlated_count)})
    except Exception as e:
        enriched_txns = pd.DataFrame()
        quality["errors"].append(f"Temporal correlation error: {str(e)}")

    # ---- STEP 4: NAMED RULE ENGINE ----
    notify("Running named rules", 4, "7 deterministic forensic rules...")
    try:
        rule_results = run_all_rules(entities, all_events_df, enriched_txns,
                                      entity_map=entity_map, window_minutes=15, data_dir=data_dir)
        fired_count = sum(len(r["rules_fired"]) for r in rule_results.values())
        flagged_count = sum(1 for r in rule_results.values() if r["rules_fired"])
        quality["steps"].append({"name": "Rule Engine", "rules_fired": fired_count, "entities_flagged": flagged_count})
    except Exception as e:
        rule_results = {eid: {"rules_fired": [], "explanations": {}, "evidence": {}} for eid in entities}
        quality["errors"].append(f"Rule engine error: {str(e)}")

    # ---- STEP 5: RISK SCORING ----
    notify("Computing risk scores", 5, "Gated tiers + IsolationForest ML...")
    try:
        scored_entities = run_risk_engine(rule_results, all_events_df, entities)
    except Exception as e:
        scored_entities = {}
        quality["errors"].append(f"Risk scoring error: {str(e)}")

    # ---- STEP 6: GRAPH BUILDING ----
    notify("Building network graph", 6)
    try:
        network_graph = build_network_graph(all_events_df, scored_entities, entities)
        print(f"  Graph: {network_graph.number_of_nodes()} nodes, {network_graph.number_of_edges()} edges")
    except Exception as e:
        network_graph = None
        quality["errors"].append(f"Graph build error: {str(e)}")

    # ---- STEP 7: REPORT GENERATION ----
    reports = []
    if generate_reports:
        notify("Generating forensic reports", 7)
        try:
            # Clear old reports before generating new ones.
            reports_dir = PROJECT_ROOT / "reports"
            if reports_dir.exists():
                for old_report in reports_dir.iterdir():
                    if old_report.is_file() and old_report.suffix == ".docx":
                        old_report.unlink()
                print(f"  Cleared old reports from {reports_dir}")

            reports = generate_reports_for_flagged(
                scored_entities, entities, all_events_df,
                create_timeline_fn=create_timeline_plotly,
                create_network_fn=create_network_plotly,
                network_graph=network_graph,
                # The timeline chart needs the correlation output to shade the TCS
                # windows, and the window it was actually computed with.
                enriched_txns=enriched_txns,
                window_minutes=window_minutes,
            )
            print(f"  Reports generated: {len(reports)}")
        except Exception as e:
            quality["warnings"].append(f"Report generation skipped: {str(e)}")
    else:
        notify("Skipping report generation", 7, "On-demand only")

    # ---- STEP 8: VERIFICATION ----
    notify("Self-verification against ground truth", 8)
    gt_path = data_dir / "ground_truth.json"
    if not gt_path.exists():
        gt_path = data_dir.parent / "generator" / "ground_truth.json"
    if not gt_path.exists():
        gt_path = PROJECT_ROOT / "data" / "generator" / "ground_truth.json"

    try:
        verification = verify_against_ground_truth(
            scored_entities, entities=entities,
            ground_truth_path=gt_path
        )
        if not verification:
            import logging
            err_msg = f"Ground truth verification produced empty results (file missing or invalid at {gt_path})"
            print(f"\033[91m[ERROR] {err_msg}\033[0m")
            logging.error(err_msg)
            verification = {"error": err_msg}
            quality["warnings"].append(err_msg)
    except Exception as e:
        import logging
        err_msg = f"Verification skipped: {str(e)}"
        print(f"\033[91m[ERROR] {err_msg}\033[0m")
        logging.error(err_msg)
        verification = {"error": str(e)}
        quality["warnings"].append(err_msg)

    # ---- FINAL SUMMARY ----
    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    if quality["errors"]:
        print(f"  ⚠ Errors: {len(quality['errors'])}")
        for err in quality["errors"]:
            print(f"    - {err}")
    print("=" * 60)

    return {
        "bank_events": bank_events,
        "cdr_events": cdr_events,
        "ipdr_events": ipdr_events,
        "all_events": all_events,
        "all_events_df": all_events_df,
        "entity_map": entity_map,
        "entities": entities,
        "identity_graph": identity_graph,
        "id_types": id_types,
        "enriched_txns": enriched_txns,
        "rule_results": rule_results,
        "scored_entities": scored_entities,
        "network_graph": network_graph,
        "reports": reports,
        "verification": verification,
        "window_minutes": window_minutes,
        "quality": quality,
    }


if __name__ == "__main__":
    results = run_pipeline()
