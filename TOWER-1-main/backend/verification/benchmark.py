"""
E-Rakshak Performance & Scalability Benchmark Suite
===================================================
Measures per-stage wall-clock latency and peak memory usage across scale multipliers (scale = 1, 5, 10, 25).
Writes structured results to backend/verification/benchmark_results.json.
"""
import sys
import os
import time
import json
import tracemalloc
from pathlib import Path
import pandas as pd

# Add project root and backend to sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
DATA_DIR = BACKEND_DIR / "data"

from data.generator.generate_all import main as generate_data
from ingestion.smart_ingest import parse_messy_file
from resolution.entity_resolver import run_entity_resolution
from correlation.temporal_join import temporal_join
from correlation.rules import run_all_rules
from scoring.risk_engine import run_risk_engine
from graph.network_builder import build_network_graph


def run_single_benchmark(scale):
    print(f"\n============================================================")
    print(f"BENCHMARKING SCALE: {scale}x")
    print(f"============================================================")
    
    # 1. Generate scaled data
    gt_data = generate_data(scale=scale)
    total_events_generated = gt_data.get("total_events", 0)
    total_entities_generated = gt_data.get("total_entities", 0)

    raw_dir = DATA_DIR / "raw"

    # Start memory tracing
    tracemalloc.start()
    total_start = time.perf_counter()

    # Stage 1: Ingestion
    t0 = time.perf_counter()
    bank_events, cdr_events, ipdr_events = [], [], []
    for f in raw_dir.iterdir():
        if f.is_file() and not f.name.endswith('.json') and f.suffix.lower() in ['.csv', '.xlsx', '.xls', '.pdf']:
            file_events, summary = parse_messy_file(f)
            det_type = summary.get("detected_type")
            if det_type == "bank":
                bank_events.extend(file_events)
            elif det_type == "cdr":
                cdr_events.extend(file_events)
            elif det_type == "ipdr":
                ipdr_events.extend(file_events)
    t_ingestion = time.perf_counter() - t0

    # Stage 2: Entity Resolution
    t0 = time.perf_counter()
    entity_map, entities, identity_graph, id_types, bank_events, cdr_events, ipdr_events = \
        run_entity_resolution(bank_events, cdr_events, ipdr_events, data_dir=raw_dir)
    
    all_events = bank_events + cdr_events + ipdr_events
    all_events_df = pd.DataFrame(all_events)
    if not all_events_df.empty:
        all_events_df['timestamp'] = pd.to_datetime(all_events_df['timestamp'])
        if 'end_timestamp' in all_events_df.columns:
            all_events_df['end_timestamp'] = pd.to_datetime(all_events_df['end_timestamp'], errors='coerce')
    t_resolution = time.perf_counter() - t0

    # Stage 3: Temporal Join / Correlation
    t0 = time.perf_counter()
    enriched_txns = temporal_join(all_events, window_minutes=10)
    t_correlation = time.perf_counter() - t0

    # Stage 4: Rule Engine
    t0 = time.perf_counter()
    rule_results = run_all_rules(entities, all_events_df, enriched_txns,
                                  entity_map=entity_map, window_minutes=15, data_dir=raw_dir)
    t_rule_engine = time.perf_counter() - t0

    # Stage 5: Risk Engine & ML
    t0 = time.perf_counter()
    scored_entities = run_risk_engine(rule_results, all_events_df, entities)
    t_risk_scoring = time.perf_counter() - t0

    # Stage 6: Network Graph
    t0 = time.perf_counter()
    network_graph = build_network_graph(all_events_df, scored_entities, entities)
    t_network_graph = time.perf_counter() - t0

    total_time = time.perf_counter() - total_start
    current_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    peak_mem_mb = round(peak_mem / (1024 * 1024), 2)

    result = {
        "scale": scale,
        "total_entities": total_entities_generated,
        "total_events": total_events_generated,
        "actual_dataframe_rows": len(all_events_df),
        "stage_times_sec": {
            "ingestion": round(t_ingestion, 4),
            "entity_resolution": round(t_resolution, 4),
            "temporal_correlation": round(t_correlation, 4),
            "rule_engine": round(t_rule_engine, 4),
            "risk_scoring": round(t_risk_scoring, 4),
            "network_graph": round(t_network_graph, 4),
            "total_pipeline": round(total_time, 4)
        },
        "peak_memory_mb": peak_mem_mb
    }

    print(f"\n--- SCALE {scale}x BENCHMARK RESULTS ---")
    print(f"Total Events: {len(all_events_df):,} | Total Entities: {len(entities):,}")
    print(f"Ingestion:          {t_ingestion:.3f} s")
    print(f"Entity Resolution:  {t_resolution:.3f} s")
    print(f"Temporal Correlation:{t_correlation:.3f} s")
    print(f"Rule Engine:        {t_rule_engine:.3f} s")
    print(f"Risk Scoring:       {t_risk_scoring:.3f} s")
    print(f"Network Graph:      {t_network_graph:.3f} s")
    print(f"TOTAL PIPELINE TIME:{total_time:.3f} s")
    print(f"PEAK RAM USAGE:     {peak_mem_mb} MB")

    return result


def main():
    scales = [1, 5, 10, 25]
    results = []

    for s in scales:
        res = run_single_benchmark(s)
        results.append(res)

    output_path = BACKEND_DIR / "verification" / "benchmark_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("\n============================================================")
    print("BENCHMARK SUMMARY TABLE")
    print("============================================================")
    print(f"{'Scale':<6} | {'Events':<8} | {'Entities':<8} | {'Ingest(s)':<9} | {'Resolv(s)':<9} | {'Rules(s)':<8} | {'Total(s)':<8} | {'Peak RAM':<8}")
    print("-" * 80)
    for r in results:
        st = r["stage_times_sec"]
        print(f"{r['scale']:<6} | {r['total_events']:<8} | {r['total_entities']:<8} | {st['ingestion']:<9.3f} | {st['entity_resolution']:<9.3f} | {st['rule_engine']:<8.3f} | {st['total_pipeline']:<8.3f} | {r['peak_memory_mb']} MB")

    print("\nRestoring default scale=1.0 dataset...")
    generate_data(scale=1.0)


if __name__ == "__main__":
    main()
