import gc
import os
import sys
import json
import math
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import List
import pandas as pd
import networkx as nx

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("e-rakshak-api")

# Add backend directory to sys.path to load local modules
BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

# Import E-Rakshak pipeline methods
from pipeline import run_pipeline, sha256_file
from graph.map_builder import CELL_TOWERS

# Investigation Copilot — the LLM layer. Imported at module load so a missing
# dependency fails loudly at startup rather than on the first question asked.
from copilot import CopilotService, GeminiClient, GeminiError, GeminiNotConfigured
from copilot import context as copilot_context
from copilot.service import suggested_questions

app = FastAPI(title="E-Rakshak API", version="2.0.0")

# CORS setup for frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global memory storage for runtime states and pipeline results
STATE = {
    "data_mode": "demo", # "demo" or "upload"
    "pipeline_run": False,
    "last_results": None
}

RAW_DIR = BACKEND_DIR / "data" / "raw"
UPLOAD_DIR = BACKEND_DIR / "data" / "uploaded"
REPORTS_DIR = BACKEND_DIR / "reports"

# Ensure directories exist
RAW_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


#: Reports whose name starts with this are the committed sample deliverables, not
#: output of a run. Wiping them on the first pipeline execution would delete a
#: checked-in artefact from a fresh clone, so every clearing path skips them.
SAMPLE_REPORT_PREFIX = "sample_"


def clear_old_reports():
    """Remove .docx reports from previous pipeline runs, keeping committed samples."""
    if REPORTS_DIR.exists():
        for f in REPORTS_DIR.iterdir():
            if f.is_file() and f.suffix == ".docx" and not f.name.startswith(SAMPLE_REPORT_PREFIX):
                f.unlink()


# ---- Network serialisation ---------------------------------------------------
# Two genuinely different graphs come out of the pipeline and both are worth
# showing, so both are served and the UI toggles between them:
#
#   money_flow  — results["network_graph"]. Nodes are RESOLVED ENTITIES, edges are
#                 actual value movement (transfers, weighted by amount) and contact
#                 (calls, weighted by frequency). This is the graph the problem
#                 statement asks for and the one that shows a layering chain.
#   identity    — results["identity_graph"]. Nodes are RAW IDENTIFIERS (a phone, an
#                 account, an IMEI) and edges are KYC ownership links. It answers
#                 "these five identifiers are one person" — a different question,
#                 and no money flows along any of its edges.
#
# /api/results used to serialise the identity graph under the name "network", which
# is why the money-flow view was missing despite being fully built.

TIER_NODE_SIZE = {"CRITICAL": 30, "HIGH": 24, "MEDIUM": 18, "LOW": 11}


def _fmt_inr(amount):
    """Format a rupee amount for a tooltip (Indian grouping is not worth the noise here)."""
    try:
        return f"₹{float(amount):,.0f}"
    except (TypeError, ValueError):
        return "₹0"


def _iso_or_none(value):
    """ISO-8601 string for a timestamp, or None when it is missing/NaT."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return pd.Timestamp(value).isoformat()
    except (TypeError, ValueError):
        return None


def serialize_money_flow_graph(network_graph, scored_entities, entities, max_nodes=600):
    """
    Serialise the money-flow DiGraph into vis.js nodes/edges.

    Only entities that actually participate in the flow are emitted: anything with
    at least one edge, plus every MEDIUM+ entity. The rest are passthrough
    identifiers with no edges — drawing them produces a field of isolated dots that
    hides the structure instead of showing it.

    Edges are classified so the UI can colour them:
      layering    — both endpoints fired LAY-1: a hop on a detected laundering chain
      smoking_gun — an endpoint fired TCS-1/TCS-2, i.e. the transfer sits inside a
                    correlated call/session window (correlation.md calls these the
                    decisive edges)
      transaction — ordinary value movement
      call        — contact only, no money
    """
    meta = {
        "kind": "money_flow",
        "total_nodes": 0, "total_edges": 0,
        "rendered_nodes": 0, "rendered_edges": 0,
        "hidden_isolated_nodes": 0, "truncated": False,
        "transaction_edges": 0, "call_edges": 0,
        "layering_edges": 0, "smoking_gun_edges": 0,
        "total_value": 0.0,
    }
    if network_graph is None or network_graph.number_of_nodes() == 0:
        return {"nodes": [], "edges": [], "meta": meta}

    meta["total_nodes"] = network_graph.number_of_nodes()
    meta["total_edges"] = network_graph.number_of_edges()

    def tier_of(eid):
        return scored_entities.get(eid, {}).get("risk_tier", "LOW")

    def rules_of(eid):
        return scored_entities.get(eid, {}).get("rules_fired", []) or []

    tier_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}

    # Exact hops of every detected layering chain, read from the LAY-1 evidence
    # token the rule emits ("chain:ENT_A>ENT_B>ENT_C"). Highlighting these — rather
    # than every edge between two LAY-1 entities — lights the path that was actually
    # walked, including hops through a chain member that did not itself fire.
    layering_hops = set()
    for eid, sdata in scored_entities.items():
        for token in (sdata.get("evidence", {}) or {}).get("LAY-1", []) or []:
            if isinstance(token, str) and token.startswith("chain:"):
                path = [p for p in token[len("chain:"):].split(">") if p]
                layering_hops.update(zip(path, path[1:]))

    # Which nodes are worth drawing
    connected = {n for n in network_graph.nodes() if network_graph.degree(n) > 0}
    flagged = {n for n in network_graph.nodes() if tier_of(n) in ("CRITICAL", "HIGH", "MEDIUM")}
    visible = connected | flagged
    meta["hidden_isolated_nodes"] = network_graph.number_of_nodes() - len(visible)

    # Guard against a pathological upload: keep the most interesting nodes.
    if len(visible) > max_nodes:
        ranked = sorted(
            visible,
            key=lambda n: (tier_rank.get(tier_of(n), 3), -network_graph.degree(n)),
        )
        visible = set(ranked[:max_nodes])
        meta["truncated"] = True

    nodes = []
    for eid in visible:
        tier = tier_of(eid)
        rules = rules_of(eid)
        ndata = network_graph.nodes[eid]
        edata = entities.get(eid, {})

        value_out = sum(
            d.get("weight", 0) for _, _, d in network_graph.out_edges(eid, data=True)
            if d.get("edge_type") == "transaction"
        )
        value_in = sum(
            d.get("weight", 0) for _, _, d in network_graph.in_edges(eid, data=True)
            if d.get("edge_type") == "transaction"
        )

        title = [f"{eid} — {tier}"]
        if edata.get("name"):
            title.insert(0, str(edata["name"]))
        if rules:
            title.append("Rules: " + ", ".join(rules))
        if scored_entities.get(eid, {}).get("ml_anomaly"):
            title.append("ML anomaly flagged")
        title.append(f"In: {_fmt_inr(value_in)} · Out: {_fmt_inr(value_out)}")
        if ndata.get("institution"):
            title.append(f"Institution: {ndata['institution']}")
        for label, key in (("Phones", "phones"), ("Accounts", "accounts")):
            vals = edata.get(key) or []
            if vals:
                title.append(f"{label}: {', '.join(str(v) for v in vals[:3])}")

        nodes.append({
            "id": eid,
            # Label only the entities worth reading at a glance. With every LOW node
            # labelled, 150 overlapping captions bury the handful that matter; the
            # identity is still on the hover tooltip and in the inspector.
            "label": eid.replace("ENT_", "E") if tier != "LOW" else "",
            "group": tier.lower(),
            "shape": "dot",
            "size": TIER_NODE_SIZE.get(tier, 11),
            "title": "\n".join(title),
            "entity_id": eid,
            "name": edata.get("name", ""),
            "risk_tier": tier,
            "rules_fired": rules,
            "rule_severities": scored_entities.get(eid, {}).get("rule_severities", {}),
            "ml_anomaly": bool(scored_entities.get(eid, {}).get("ml_anomaly")),
            "institution": ndata.get("institution", "Unknown"),
            # Cities this entity was seen operating from, and the identifiers it
            # holds — the fields the network view's location filter and entity
            # search read. Without them those controls have nothing to match on.
            "cities": list(ndata.get("cities", []) or []),
            "phones": [str(p) for p in (edata.get("phones") or [])[:6]],
            "accounts": [str(a) for a in (edata.get("accounts") or [])[:6]],
            "value_in": float(value_in),
            "value_out": float(value_out),
            "font": {"color": "#F2F3F4", "size": 11},
        })

    edges = []
    for u, v, data in network_graph.edges(data=True):
        if u not in visible or v not in visible:
            continue

        edge_type = data.get("edge_type", "transaction")
        weight = float(data.get("weight", 0) or 0)
        count = int(data.get("count", 1) or 1)

        u_rules, v_rules = rules_of(u), rules_of(v)
        is_layering = (u, v) in layering_hops
        is_smoking_gun = any(r in u_rules + v_rules for r in ("TCS-1", "TCS-2"))

        if edge_type == "transaction":
            meta["transaction_edges"] += 1
            meta["total_value"] += weight
            # Width by amount, log-compressed: a 100x range of transfer sizes has to
            # fit in a ~6px range of stroke widths.
            width = 1.4 + min(math.log10(max(weight, 1)) / 1.3, 5.0)
            title = f"{u} → {v}\n{_fmt_inr(weight)} across {count} transfer(s)"
            if not data.get("counted_from_debit", True):
                title += "\n(from the receiving statement — sender's not ingested)"
        else:
            meta["call_edges"] += 1
            freq = int(data.get("call_frequency", count) or 1)
            width = 1.0 + min(freq * 0.25, 2.5)
            title = f"{u} → {v}\n{freq} call(s) / SMS"

        if is_layering:
            meta["layering_edges"] += 1
            edge_class = "layering"
            color = {"color": "#FF3B3B", "highlight": "#FF8A8A", "opacity": 1.0}
            # Deliberately the heaviest stroke on the canvas: in a 600-edge graph the
            # laundering chain has to be findable without hunting for it.
            width = max(width, 7.0)
            title += "\nLAY-1 — hop on a detected layering chain"
        elif is_smoking_gun and edge_type == "transaction":
            meta["smoking_gun_edges"] += 1
            edge_class = "smoking_gun"
            color = {"color": "#FFB020", "highlight": "#FFC961", "opacity": 0.9}
            width = max(width, 2.6)
            title += "\nTCS — transfer inside a correlated call/session window"
        elif edge_type == "transaction":
            edge_class = "transaction"
            color = {"color": "rgba(61,124,255,0.32)", "highlight": "#3D7CFF"}
        else:
            edge_class = "call"
            color = {"color": "rgba(155,161,168,0.16)", "highlight": "#9BA1A8"}

        edges.append({
            "id": f"{u}__{v}",
            "from": u,
            "to": v,
            "title": title,
            "width": round(width, 2),
            "color": color,
            "dashes": edge_type != "transaction",
            "arrows": {"to": {"enabled": True, "scaleFactor": 0.55}},
            "edge_type": edge_type,
            "edge_class": edge_class,
            "amount": weight if edge_type == "transaction" else 0.0,
            "count": count,
            # Span of the underlying events, so the time filter subsets edges on
            # when the money actually moved rather than on nothing at all.
            "t_start": _iso_or_none(data.get("first_ts")),
            "t_end": _iso_or_none(data.get("last_ts")),
        })

    meta["rendered_nodes"] = len(nodes)
    meta["rendered_edges"] = len(edges)

    # Facets: the real ranges and option lists the filter controls are built from,
    # so the UI never offers a city or an amount band the data cannot produce.
    amounts = [e["amount"] for e in edges if e["edge_type"] == "transaction" and e["amount"] > 0]
    stamps = [t for e in edges for t in (e["t_start"], e["t_end"]) if t]
    cities = sorted({c for n in nodes for c in n.get("cities", [])})
    rules = sorted({r for n in nodes for r in (n.get("rules_fired") or [])})
    meta["facets"] = {
        "amount_min": min(amounts) if amounts else 0.0,
        "amount_max": max(amounts) if amounts else 0.0,
        "time_min": min(stamps) if stamps else None,
        "time_max": max(stamps) if stamps else None,
        "cities": cities,
        "rules": rules,
    }
    return {"nodes": nodes, "edges": edges, "meta": meta}


def serialize_identity_graph(identity_graph, id_types, entity_map, scored_entities, network_graph):
    """
    Serialise the identity graph: raw identifiers linked by KYC ownership.

    This is the "these five identifiers are one person" view. It is deliberately
    kept — it is a real second story — but it is not the money-flow graph.
    """
    nodes, edges = [], []
    meta = {"kind": "identity", "total_nodes": 0, "total_edges": 0,
            "rendered_nodes": 0, "rendered_edges": 0}
    if identity_graph is None:
        return {"nodes": nodes, "edges": edges, "meta": meta}

    meta["total_nodes"] = identity_graph.number_of_nodes()
    meta["total_edges"] = identity_graph.number_of_edges()

    for node in identity_graph.nodes():
        node_type = id_types.get(node, "unknown")
        entity_id = entity_map.get(node, "unresolved")
        risk_tier = scored_entities.get(entity_id, {}).get("risk_tier", "LOW")

        node_inst = "Unknown"
        if network_graph is not None and network_graph.has_node(entity_id):
            node_inst = network_graph.nodes[entity_id].get("institution", "Unknown")

        nodes.append({
            "id": node,
            "label": f"{node}\n({node_type})",
            "group": node_type,
            "entity_id": entity_id,
            "risk_tier": risk_tier,
            "institution": node_inst,
        })

    for i, (u, v, data) in enumerate(identity_graph.edges(data=True)):
        edges.append({
            # Stable id so the filter layer can address this edge in the vis.js
            # DataSet. Without one, vis auto-generates an id the client cannot
            # match back to the payload, and hiding an edge becomes impossible.
            "id": f"idl_{i}",
            "from": u,
            "to": v,
            "label": data.get("source", ""),
            "title": f"Link source: {data.get('source', 'unknown')}",
        })

    meta["rendered_nodes"] = len(nodes)
    meta["rendered_edges"] = len(edges)
    # The identity graph has no money and no time on its edges, so it exposes only
    # the facets it can honestly support: identifier type. The UI reads this to
    # decide which filter controls to show — which is why "Critical Only" and an
    # amount slider do not appear here, and "Phones"/"Bank Accounts" do not appear
    # on the money-flow graph whose nodes are entities.
    meta["facets"] = {
        "amount_min": 0.0, "amount_max": 0.0,
        "time_min": None, "time_max": None,
        "cities": [], "rules": [],
        "id_types": sorted({n["group"] for n in nodes if n.get("group")}),
    }
    return {"nodes": nodes, "edges": edges, "meta": meta}


def clean_serializable(obj):
    """Recursively clean objects to make them JSON serializable."""
    import numpy as np

    if isinstance(obj, dict):
        return {str(k): clean_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple, set)):
        return [clean_serializable(i) for i in obj]
    elif isinstance(obj, pd.DataFrame):
        return obj.to_dict(orient="records")
    elif isinstance(obj, pd.Series):
        return obj.to_dict()
    elif isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    elif hasattr(obj, "isoformat"):
        return obj.isoformat()
    elif isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return clean_serializable(obj.tolist())
    elif isinstance(obj, float) and pd.isna(obj):
        return None
    elif isinstance(obj, int) and pd.isna(obj):
        return None
    try:
        return obj
    except Exception:
        return str(obj)


@app.get("/api/status")
def get_status():
    active_dir = UPLOAD_DIR if STATE["data_mode"] == "upload" else RAW_DIR
    files = []
    if active_dir.exists():
        files = [f.name for f in active_dir.iterdir() if f.is_file() and f.name not in ["ground_truth.json"]]

    # Counts come from the last real pipeline run; 0 until one has completed.
    entity_count = 0
    event_count = 0
    if STATE["pipeline_run"] and STATE["last_results"] is not None:
        entity_count = len(STATE["last_results"].get("entities", {}) or {})
        event_count = len(STATE["last_results"].get("all_events", []) or [])

    return {
        "data_mode": STATE["data_mode"],
        "pipeline_run": STATE["pipeline_run"],
        "uploaded_files": files,
        "files_count": len(files),
        "entity_count": entity_count,
        "event_count": event_count
    }


@app.post("/api/toggle-mode")
def toggle_mode(payload: dict):
    mode = payload.get("mode")
    if mode not in ["demo", "upload"]:
        raise HTTPException(status_code=400, detail="Invalid mode. Must be 'demo' or 'upload'.")
    STATE["data_mode"] = mode
    STATE["pipeline_run"] = False
    STATE["last_results"] = None
    clear_old_reports()
    logger.info(f"Data mode changed to: {mode}")
    return {"status": "success", "mode": mode}


@app.post("/api/upload")
async def upload_files(files: List[UploadFile] = File(...)):
    # Auto-switch system to upload mode when user uploads files
    STATE["data_mode"] = "upload"
    STATE["pipeline_run"] = False
    STATE["last_results"] = None
    
    saved_files = []
    for file in files:
        if not file.filename:
            continue
        # Sanitize filename (strip directory paths from browser)
        clean_name = Path(file.filename).name
        target_path = UPLOAD_DIR / clean_name
        try:
            # Stream to disk and digest in the same pass — the SHA-256 returned to
            # the client is computed by hashlib over the exact bytes written, so it
            # is a real chain-of-custody stamp for the received file.
            digest = hashlib.sha256()
            size_bytes = 0
            with open(target_path, "wb") as f:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    size_bytes += len(chunk)
                    f.write(chunk)

            saved_files.append({
                "filename": clean_name,
                "size_bytes": size_bytes,
                "sha256": digest.hexdigest()
            })
            logger.info(f"File uploaded: {clean_name} ({size_bytes} bytes) sha256={digest.hexdigest()}")
        except Exception as e:
            logger.error(f"Error saving file {clean_name}: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to upload {clean_name}: {str(e)}")

    return {
        "status": "success",
        "uploaded": saved_files,
        "filenames": [f["filename"] for f in saved_files],
        "hash_algorithm": "SHA-256",
        "mode": "upload"
    }


def evidence_file_records():
    """
    Chain-of-custody listing for the currently active dataset.

    Every field here is measured, never asserted: byte size from the filesystem,
    SHA-256 recomputed now with hashlib, and parsed/skipped row counts taken from
    the last pipeline run. If a file has not been ingested yet, its row counts are
    returned as null rather than filled in with a plausible-looking number.

    Split out of the endpoint so the copilot can ground provenance answers on the
    same records the Evidence Vault renders, rather than on a second listing that
    could drift from it.
    """
    active_dir = UPLOAD_DIR if STATE["data_mode"] == "upload" else RAW_DIR

    # Per-file parse stats recorded by the pipeline during ingestion
    ingest_stats = {}
    if STATE["last_results"] is not None:
        for rec in STATE["last_results"].get("quality", {}).get("files", []) or []:
            ingest_stats[rec.get("filename")] = rec

    files = []
    if active_dir.exists():
        for f in sorted(active_dir.iterdir(), key=lambda p: p.name):
            if not f.is_file() or f.name == "ground_truth.json":
                continue

            rec = ingest_stats.get(f.name, {})
            current_digest = sha256_file(f)
            ingest_digest = rec.get("sha256")

            if rec:
                status = rec.get("status")
            elif f.suffix.lower() == ".json":
                # KYC / reference maps are consumed by entity resolution, not the
                # event parser, so they legitimately have no parsed-row count.
                status = "REFERENCE"
            else:
                status = "NOT INGESTED"

            files.append({
                "filename": f.name,
                "extension": f.suffix.lower().lstrip("."),
                "size_bytes": f.stat().st_size,
                "sha256": current_digest,
                "sha256_at_ingest": ingest_digest,
                "modified_since_ingest": bool(ingest_digest and current_digest and ingest_digest != current_digest),
                "detected_type": rec.get("detected_type"),
                "total_rows": rec.get("total_rows"),
                "rows_parsed": rec.get("rows_parsed"),
                "rows_skipped": rec.get("rows_skipped"),
                "status": status,
                "error": rec.get("error"),
            })

    return files


@app.get("/api/evidence-files")
def get_evidence_files():
    """Evidence Vault listing — see evidence_file_records() for how each field is measured."""
    files = evidence_file_records()
    return JSONResponse(content=clean_serializable({
        "data_mode": STATE["data_mode"],
        "pipeline_run": STATE["pipeline_run"],
        "hash_algorithm": "SHA-256",
        "hash_source": "python hashlib, streamed over the file on disk",
        "files": files,
        "files_count": len(files)
    }))



@app.post("/api/reset-dataset")
@app.post("/api/clear-uploads")
def reset_dataset():
    """Wipe uploaded/raw files, reports, traces, and pipeline memory state for a new case."""
    for directory in [UPLOAD_DIR, RAW_DIR]:
        if directory.exists():
            for item in directory.iterdir():
                if item.is_file() and item.name != ".gitkeep":
                    try:
                        item.unlink()
                    except Exception as e:
                        logger.error(f"Failed to remove file {item}: {e}")

    clear_old_reports()

    trace_file = BACKEND_DIR / "decision_trace.jsonl"
    if trace_file.exists():
        try:
            trace_file.unlink()
        except Exception as e:
            logger.error(f"Failed to remove trace file: {e}")

    STATE["data_mode"] = "upload"
    STATE["pipeline_run"] = False
    STATE["last_results"] = None
    gc.collect()

    logger.info("Dataset and case state reset cleanly for new investigation.")
    return {
        "status": "success",
        "message": "Dataset, reports, and analysis state reset cleanly. Ready for new case upload.",
        "data_mode": "upload",
        "pipeline_run": False
    }


@app.post("/api/run-pipeline")
def trigger_pipeline(window_minutes: int = Form(10)):
    active_dir = UPLOAD_DIR if STATE["data_mode"] == "upload" else RAW_DIR
    
    # Check if files exist in upload directory
    if STATE["data_mode"] == "upload":
        files = [f for f in active_dir.iterdir() if f.is_file()]
        if not files:
            raise HTTPException(status_code=400, detail="No files uploaded. Please upload Bank, CDR, or IPDR files first.")
            
    logger.info(f"Triggering E-Rakshak pipeline on directory: {active_dir}")
    try:
        # Any .docx still on disk describes the PREVIOUS run. /api/download-report
        # serves a matching file if it finds one, so leaving them would hand a judge
        # last dataset's report for this dataset's entity. Clear first, always.
        clear_old_reports()

        # Release the previous run before building the next one. STATE holds a full
        # events DataFrame, an enriched-transaction frame and two graphs; keeping
        # them alive while a second set is constructed doubles peak footprint for no
        # benefit. It also means a failed re-run cannot leave the API serving the
        # previous dataset's results as if they were current.
        STATE["last_results"] = None
        STATE["pipeline_run"] = False
        gc.collect()

        # Reports are generated on demand by /api/download-report, not in bulk here.
        # Charting all 8 HIGH/CRITICAL entities inline measured ~17 s on top of an
        # 8 s pipeline, against a "runs in seconds" requirement — and nothing reads
        # the pre-generated files, since the UI links straight to the download
        # endpoint. One report costs ~1 s when it is actually asked for.
        results = run_pipeline(
            data_dir=active_dir,
            window_minutes=window_minutes,
            generate_reports=False
        )
        
        # Structure serializable results in memory
        STATE["last_results"] = results
        STATE["pipeline_run"] = True
        
        return {"status": "success", "quality": results.get("quality", {})}
    except Exception as e:
        logger.error(f"Pipeline failure: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Pipeline error: {str(e)}")


@app.on_event("startup")
def startup_event():
    """Start with nothing loaded.

    This used to run the demo dataset through the pipeline at boot so the
    dashboard had something to show. That means every screen — KPIs, persons of
    interest, evidence vault, graphs, reports — is populated with Surat demo
    output before the operator has supplied a single file, and it is not
    obvious on screen which of it came from them. The dashboard now starts
    empty and stays empty until a pipeline run is explicitly requested, so
    everything on it belongs to the dataset actually under investigation.
    """
    logger.info(
        "E-Rakshak API ready. No dataset loaded — upload files and run the "
        "pipeline, or switch to demo mode in Settings."
    )


@app.get("/api/results")
def get_results():
    # Deliberately does NOT kick off a run. A GET that silently executes the
    # whole pipeline meant merely opening the dashboard produced a full set of
    # demo results, which is exactly the pre-populated state this endpoint is
    # supposed to report the absence of. Callers get an explicit "nothing has
    # been run" and the UI renders its empty states.
    if not STATE["pipeline_run"] or STATE["last_results"] is None:
        raise HTTPException(
            status_code=409,
            detail="No analysis has been run yet. Upload files and run the pipeline."
        )

    results = STATE["last_results"]

    # 1. Operational Executive Metrics
    entities = results.get("entities", {})
    scored_entities = results.get("scored_entities", {})
    all_events = results.get("all_events", [])
    
    tier_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    ml_count = 0
    suspects_list = []
    rule_firings = {}

    for eid, score_data in scored_entities.items():
        tier = score_data.get("risk_tier", "LOW")
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        if score_data.get("ml_anomaly", False):
            ml_count += 1

        for rule_id in score_data.get("rules_fired", []):
            rule_firings[rule_id] = rule_firings.get(rule_id, 0) + 1

        # Get identifier collections
        ent_details = entities.get(eid, {})
        
        suspects_list.append({
            "entity_id": eid,
            "name": ent_details.get("name", "Unknown"),
            "risk_tier": tier,
            "rules_fired": score_data.get("rules_fired", []),
            "explanations": score_data.get("explanations", {}),
            "evidence": score_data.get("evidence", {}),
            # Per-rule severity (IDR-1 grades itself HIGH/MEDIUM/LOW) — this is what
            # distinguishes a fraudulent SIM+device swap from a routine handset upgrade.
            "rule_severities": score_data.get("rule_severities", {}),
            "ml_anomaly": score_data.get("ml_anomaly", False),
            "phones": list(ent_details.get("phones", [])),
            "accounts": list(ent_details.get("accounts", [])),
            "imeis": list(ent_details.get("imeis", [])),
            "vpas": list(ent_details.get("vpas", [])),
            "ips": list(ent_details.get("ips", []))
        })
        
    # Sort suspects by tier precedence
    tier_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    suspects_list.sort(key=lambda s: (tier_order.get(s["risk_tier"], 4), s["entity_id"]))
    
    # 2. Geographic Cell Towers Map (Surat Towers)
    towers_map = []
    for tid, info in CELL_TOWERS.items():
        if info.get("city") == "Surat":
            towers_map.append({
                "id": tid,
                "lat": info["lat"],
                "lon": info["lon"],
                "area": info["area"],
                "city": info["city"]
            })

            
    # 3. Vis.js Network Data — money-flow graph (default) + identity graph (toggle)
    identity_graph = results.get("identity_graph")
    network_graph = results.get("network_graph")

    money_flow_view = serialize_money_flow_graph(network_graph, scored_entities, entities)
    identity_view = serialize_identity_graph(
        identity_graph,
        results.get("id_types", {}),
        results.get("entity_map", {}),
        scored_entities,
        network_graph,
    )

    kyc_anchored = sum(1 for e in entities.values() if len(e.get("phones", [])) + len(e.get("accounts", [])) + len(e.get("imeis", [])) + len(e.get("vpas", [])) > 1)
    unmapped_passthrough = len(entities) - kyc_anchored

    # Clean the serialization of all objects
    return JSONResponse(content={
        "metrics": {
            "total_entities": len(entities),
            "kyc_anchored_entities": kyc_anchored,
            "unmapped_passthrough_entities": unmapped_passthrough,
            "total_events": len(all_events),
            "critical_count": tier_counts["CRITICAL"],
            "high_count": tier_counts["HIGH"],
            "medium_count": tier_counts["MEDIUM"],
            "low_count": tier_counts["LOW"],
            "ml_anomalies": ml_count,
            "flagged_suspects": tier_counts["CRITICAL"] + tier_counts["HIGH"] + tier_counts["MEDIUM"],
            "total_rule_firings": sum(rule_firings.values()),
            "rules_fired_count": len(rule_firings)
        },
        "rule_firings": rule_firings,
        "suspects": clean_serializable(suspects_list),
        "map_towers": towers_map,
        # "network" is the default view and is now the MONEY-FLOW graph.
        "network": clean_serializable(money_flow_view),
        "network_views": {
            "money_flow": clean_serializable(money_flow_view),
            "identity": clean_serializable(identity_view),
        },
        "verification": clean_serializable(results.get("verification", {}))
    })


@app.get("/api/institution-risk")
def get_institution_risk():
    """
    Aggregation endpoint that groups flagged entities and rule firings
    by originating institution (e.g., SBI, HDFC, ICICI, Operator-CDR, Operator-IPDR).
    """
    if not STATE["pipeline_run"] or STATE["last_results"] is None:
        raise HTTPException(status_code=400, detail="Pipeline has not been executed yet. Run the pipeline first.")

    results = STATE["last_results"]
    all_events_df = results.get("all_events_df")
    scored_entities = results.get("scored_entities", {})
    entities = results.get("entities", {})

    # Map each entity_id to its institution(s)
    entity_inst_map = {}
    if all_events_df is not None and not all_events_df.empty and 'source_file' in all_events_df.columns:
        for entity_id in entities.keys():
            e_events = all_events_df[all_events_df['entity_id'] == entity_id]
            insts = set()
            for sf in e_events['source_file'].dropna().unique():
                sf_lower = str(sf).lower()
                if "sbi" in sf_lower:
                    insts.add("SBI Bank")
                elif "hdfc" in sf_lower:
                    insts.add("HDFC Bank")
                elif "icici" in sf_lower:
                    insts.add("ICICI Bank")
                elif "cdr" in sf_lower:
                    insts.add("Operator-CDR")
                elif "ipdr" in sf_lower:
                    insts.add("Operator-IPDR")
                else:
                    insts.add("Other Institution")
            entity_inst_map[entity_id] = sorted(list(insts)) if insts else ["Other Institution"]
    else:
        for eid in entities.keys():
            entity_inst_map[eid] = ["Other Institution"]

    all_institutions = ["SBI Bank", "HDFC Bank", "ICICI Bank", "Operator-CDR", "Operator-IPDR"]
    risk_tiers = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    rule_ids = ["STR-1", "LAY-1", "MUL-1", "IDR-1", "LOC-1", "TCS-1", "TCS-2"]

    matrix_risk = {inst: {tier: 0 for tier in risk_tiers} for inst in all_institutions}
    matrix_rules = {inst: {rule: 0 for rule in rule_ids} for inst in all_institutions}
    institution_flagged = {inst: [] for inst in all_institutions}

    for entity_id, data in scored_entities.items():
        tier = data.get("risk_tier", "LOW")
        rules = data.get("rules_fired", [])
        insts = entity_inst_map.get(entity_id, ["Other Institution"])

        for inst in insts:
            if inst not in matrix_risk:
                matrix_risk[inst] = {t: 0 for t in risk_tiers}
                matrix_rules[inst] = {r: 0 for r in rule_ids}
                institution_flagged[inst] = []
                all_institutions.append(inst)

            matrix_risk[inst][tier] += 1
            for r in rules:
                if r in matrix_rules[inst]:
                    matrix_rules[inst][r] += 1
            if tier in ["CRITICAL", "HIGH", "MEDIUM"]:
                entity_info = entities.get(entity_id, {})
                institution_flagged[inst].append({
                    "entity_id": entity_id,
                    "name": entity_info.get("name", entity_id),
                    "risk_tier": tier,
                    "rules_fired": rules
                })

    return JSONResponse(content={
        "institutions": sorted(list(set(all_institutions))),
        "risk_tiers": risk_tiers,
        "rules": rule_ids,
        "matrix_risk": matrix_risk,
        "matrix_rules": matrix_rules,
        "institution_flagged": clean_serializable(institution_flagged)
    })


@app.get("/api/entity/{entity_id}/trace")
def get_entity_trace(entity_id: str):
    """
    Returns the complete decision trace bundle for an entity:
    - Resolved identifiers making up that entity
    - Decision trace entries from decision_trace.jsonl with explanations and evidence row_refs
    - Underlying raw event rows referenced by evidence
    """
    if not STATE["pipeline_run"] or STATE["last_results"] is None:
        raise HTTPException(status_code=400, detail="Pipeline has not been executed yet. Run the pipeline first.")

    results = STATE["last_results"]
    scored_entities = results.get("scored_entities", {})
    entities = results.get("entities", {})
    all_events_df = results.get("all_events_df")
    entity_map = results.get("entity_map", {})

    target_eid = entity_id
    if target_eid not in entities and target_eid in entity_map:
        target_eid = entity_map[target_eid]

    entity_data = entities.get(target_eid)
    if not entity_data:
        raise HTTPException(status_code=404, detail=f"Entity {entity_id} not found in pipeline results.")

    score_info = scored_entities.get(target_eid, {})

    # Read decision_trace.jsonl entries for target_eid
    traces = []
    trace_path = BACKEND_DIR / "decision_trace.jsonl"
    if trace_path.exists():
        with open(trace_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("entity_id") == target_eid:
                        traces.append(entry)
                except Exception:
                    pass

    # Fallback to score_info if trace file entry wasn't found
    if not traces and score_info.get("explanations"):
        for rule_id, explanation in score_info["explanations"].items():
            ev = score_info.get("evidence", {}).get(rule_id, [])
            traces.append({
                "entity_id": target_eid,
                "rule_id": rule_id,
                "explanation": explanation,
                "evidence": ev,
                "timestamp": datetime.now().isoformat()
            })

    # Fetch raw event rows belonging to this entity or referenced by row_refs
    from correlation.temporal_join import _clean_row_ref

    def _text(value):
        """
        A missing field must render as empty, not as the string "nan".

        str(NaN) is "nan", and these values are displayed verbatim beside a row
        reference in the evidence panel — an investigator should not be shown a
        location of "nan" for a bank row that never had one.
        """
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return ""
        text = str(value).strip()
        return "" if text.lower() in ("nan", "none", "nat", "<na>") else text

    raw_events = []
    if all_events_df is not None and not all_events_df.empty:
        entity_events = all_events_df[all_events_df["entity_id"] == target_eid]
        for idx, row in entity_events.iterrows():
            raw_events.append({
                "source_file": _text(row.get("source_file")) or "unknown",
                # Normalised so the UI can match a "row_219" evidence token against
                # the row it cites — and so no reference prints as "219.0".
                "raw_row_ref": _clean_row_ref(row.get("raw_row_ref", idx)) or str(idx),
                "timestamp": _text(row.get("timestamp")),
                "event_type": _text(row.get("event_type")),
                "amount": float(row.get("amount", 0)) if pd.notna(row.get("amount")) else 0.0,
                "counterparty": _text(row.get("counterparty")),
                "location": _text(row.get("location")),
                "direction": _text(row.get("direction")),
            })

    return JSONResponse(content=clean_serializable({
        "entity_id": target_eid,
        "name": entity_data.get("name", target_eid),
        "risk_tier": score_info.get("risk_tier", "LOW"),
        "rules_fired": score_info.get("rules_fired", []),
        "ml_anomaly": score_info.get("ml_anomaly", False),
        "identifiers": {
            "phones": entity_data.get("phones", []),
            "accounts": entity_data.get("accounts", []),
            "vpas": entity_data.get("vpas", []),
            "imeis": entity_data.get("imeis", []),
            "ips": entity_data.get("ips", []),
        },
        "explanations": score_info.get("explanations", {}),
        "evidence": score_info.get("evidence", {}),
        "traces": traces,
        "raw_events": raw_events
    }))


@app.get("/api/entity/{entity_id}/timeline")
def get_entity_timeline(entity_id: str, window_minutes: int = None):
    """
    Unified evidentiary timeline for one entity (FR-II.a).

    Every event the entity appears in, across all three sources, on one time axis
    in three lanes — transactions, telephony, IP sessions — plus the temporal
    correlation windows that made TCS-1/TCS-2 fire.

    This reads the same `build_timeline_payload` the forensic report renders its
    chart from, so the screen and the .docx exhibit cannot disagree.

    `window_minutes` re-computes the correlation window W for **this entity only**,
    so W can be explored interactively (`correlation.md` asks for W to be exposed in
    the UI). Re-joining ~50 events is milliseconds, against ~15s for a full
    re-analysis. The response reports both the requested W and the W the pipeline
    actually ran with: widening W here previews which transfers *would* correlate,
    it does not re-fire the rules, and the payload says so rather than letting the
    screen imply a detection that never happened.
    """
    if not STATE["pipeline_run"] or STATE["last_results"] is None:
        raise HTTPException(status_code=400, detail="Pipeline has not been executed yet. Run the pipeline first.")

    results = STATE["last_results"]
    entities = results.get("entities", {})
    entity_map = results.get("entity_map", {})
    scored_entities = results.get("scored_entities", {})

    target_eid = entity_id
    if target_eid not in entities and target_eid in entity_map:
        target_eid = entity_map[target_eid]
    if target_eid not in entities:
        raise HTTPException(status_code=404, detail=f"Entity {entity_id} not found in pipeline results.")

    score_info = scored_entities.get(target_eid, {})
    pipeline_window = int(results.get("window_minutes", 10) or 10)

    from correlation.temporal_join import build_timeline_payload, temporal_join

    all_events_df = results.get("all_events_df")
    enriched = results.get("enriched_txns")
    effective_window = pipeline_window

    if window_minutes is not None:
        requested = max(1, min(int(window_minutes), 24 * 60))
        if requested != pipeline_window:
            effective_window = requested
            # Re-join this entity's own events at the requested W. Everything else
            # in the response — tiers, rules, evidence — still reflects the run.
            try:
                mine = all_events_df[all_events_df["entity_id"] == target_eid]
                if not mine.empty:
                    enriched = temporal_join(mine.to_dict("records"),
                                             window_minutes=requested)
            except Exception as e:
                logger.warning(f"Timeline re-join at W={requested} failed: {e}")
                effective_window = pipeline_window
                enriched = results.get("enriched_txns")

    payload = build_timeline_payload(
        all_events_df,
        target_eid,
        enriched_txns=enriched,
        window_minutes=effective_window,
        rule_evidence=score_info.get("evidence", {}),
    )
    payload.update({
        "name": entities.get(target_eid, {}).get("name", ""),
        "risk_tier": score_info.get("risk_tier", "LOW"),
        "rules_fired": score_info.get("rules_fired", []),
        "rule_severities": score_info.get("rule_severities", {}),
        "explanations": score_info.get("explanations", {}),
        # The W the rules actually fired at. When this differs from window_minutes
        # above, the UI labels the correlation bands as a preview.
        "pipeline_window_minutes": pipeline_window,
        "is_preview": effective_window != pipeline_window,
    })
    return JSONResponse(content=clean_serializable(payload))


@app.get("/api/download-trace")
def download_trace():
    trace_path = BACKEND_DIR / "decision_trace.jsonl"
    if not trace_path.exists():
        raise HTTPException(status_code=404, detail="Decision trace file not found. Run the pipeline first.")
    return FileResponse(trace_path, filename="decision_trace.jsonl", media_type="application/jsonl")


@app.get("/api/reports")
def get_reports_list():
    reports_dir = BACKEND_DIR / "reports"
    if not reports_dir.exists():
        return []
    reports = []
    for f in reports_dir.iterdir():
        if f.is_file() and f.suffix == ".docx":
            is_str = f.stem.startswith("str_report_")
            stem_prefix = "str_report_" if is_str else "forensic_report_"
            reports.append({
                "filename": f.name,
                "size_bytes": f.stat().st_size,
                "entity_id": f.stem.replace(stem_prefix, "").split("_")[0],
                "report_type": "STR" if is_str else "FORENSIC"
            })
    return reports


@app.get("/api/download-report/{entity_id}")
def download_report(entity_id: str):
    reports_dir = BACKEND_DIR / "reports"
    reports_dir.mkdir(exist_ok=True)
    
    # 1. Search for existing report file for this entity
    matching = list(reports_dir.glob(f"forensic_report_{entity_id}*.docx"))
    if matching:
        latest = max(matching, key=lambda f: f.stat().st_mtime)
        return FileResponse(
            latest,
            filename=f"forensic_report_{entity_id}.docx",
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

    # 2. On-demand report generation if not generated yet
    if not STATE["pipeline_run"] or STATE["last_results"] is None:
        raise HTTPException(status_code=400, detail="Pipeline has not been executed yet. Run the pipeline first.")

    results = STATE["last_results"]
    scored_entities = results.get("scored_entities", {})
    entities = results.get("entities", {})
    all_events_df = results.get("all_events_df", pd.DataFrame())
    network_graph = results.get("network_graph")

    if entity_id not in scored_entities and entity_id not in entities:
        raise HTTPException(status_code=404, detail=f"Entity {entity_id} not found in current analysis.")

    entity_data = entities.get(entity_id, {})
    risk_data = scored_entities.get(entity_id, {"risk_tier": "LOW", "rules_fired": []})

    from report.forensic_report import build_report_figures, generate_forensic_report
    from report.report_charts import extract_layering_hops

    timeline_png, network_png = build_report_figures(
        entity_id, risk_data, all_events_df, scored_entities,
        network_graph=network_graph,
        enriched_txns=results.get("enriched_txns"),
        window_minutes=results.get("window_minutes", 10),
        layering_hops=extract_layering_hops(scored_entities),
    )

    report_path = generate_forensic_report(
        entity_id, entity_data, risk_data, all_events_df,
        timeline_png=timeline_png, network_png=network_png,
    )


    return FileResponse(
        report_path,
        filename=f"forensic_report_{entity_id}.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


@app.get("/api/verification-summary")
def get_verification_summary():
    """
    Runs the ground-truth comparison (backend/verification/verify.py) against the
    CURRENT pipeline run's live scored_entities/entities, so recall/precision/typology
    breakdown always reflect whatever dataset (demo or uploaded) is currently loaded —
    not a cached or static figure.
    """
    if not STATE["pipeline_run"] or STATE["last_results"] is None:
        raise HTTPException(status_code=400, detail="Pipeline has not been executed yet. Run the pipeline first.")

    results = STATE["last_results"]
    scored_entities = results.get("scored_entities", {})
    entities = results.get("entities", {})

    active_dir = UPLOAD_DIR if STATE["data_mode"] == "upload" else RAW_DIR

    # Same ground-truth path resolution fallback used by pipeline.py
    gt_path = active_dir / "ground_truth.json"
    if not gt_path.exists():
        gt_path = active_dir.parent / "generator" / "ground_truth.json"
    if not gt_path.exists():
        gt_path = BACKEND_DIR / "data" / "generator" / "ground_truth.json"

    from verification.verify import verify_against_ground_truth, summarize_by_typology

    try:
        verification = verify_against_ground_truth(
            scored_entities, entities=entities, ground_truth_path=gt_path
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Verification summary error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Verification failed: {str(e)}")

    typology_breakdown = summarize_by_typology(verification)

    return JSONResponse(content=clean_serializable({
        "recall": verification.get("recall", 0.0),
        "precision": verification.get("precision", 0.0),
        "f1": verification.get("f1", 0.0),
        "total_gt_entities": verification.get("total_gt_entities", 0),
        "true_positives": verification.get("true_positives", 0),
        "false_positives": verification.get("false_positives", 0),
        "false_positive_ids": verification.get("false_positive_ids", []),
        "false_negatives": verification.get("false_negatives", 0),
        # Reported with its denominator so the figure cannot be quoted bare.
        "specificity": verification.get("specificity"),
        "clean_entities_evaluated": verification.get("clean_entities_evaluated", 0),
        "threshold": verification.get("threshold", ""),
        "typology_breakdown": typology_breakdown,
        "typology_results": verification.get("typology_results", []),
    }))


@app.get("/api/download-str-report/{entity_id}")
def download_str_report(entity_id: str):
    """
    Generate (or re-fetch) a standalone FIU-IND format Suspicious Transaction
    Report (STR) for a single entity. Distinct deliverable from the full
    forensic investigation report — one-click export mapped to the
    PS bonus requirement "Automated Suspicious Transaction Report (STR) generation".
    """
    if not STATE["pipeline_run"] or STATE["last_results"] is None:
        raise HTTPException(status_code=400, detail="Pipeline has not been executed yet. Run the pipeline first.")

    results = STATE["last_results"]
    scored_entities = results.get("scored_entities", {})
    entities = results.get("entities", {})
    all_events_df = results.get("all_events_df", pd.DataFrame())

    if entity_id not in scored_entities and entity_id not in entities:
        raise HTTPException(status_code=404, detail=f"Entity {entity_id} not found in current analysis.")

    entity_data = entities.get(entity_id, {})
    risk_data = scored_entities.get(entity_id, {"risk_tier": "LOW", "rules_fired": []})

    from report.forensic_report import build_report_figures, generate_str_report

    timeline_png, _ = build_report_figures(
        entity_id, risk_data, all_events_df, scored_entities,
        network_graph=results.get("network_graph"),
        enriched_txns=results.get("enriched_txns"),
        window_minutes=results.get("window_minutes", 10),
    )

    report_path = generate_str_report(entity_id, entity_data, risk_data, all_events_df,
                                       timeline_png=timeline_png)

    return FileResponse(
        report_path,
        filename=f"str_report_{entity_id}.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


# ═══════════════════════════════════════════════════════════════════════════
# INVESTIGATION COPILOT
#
# A Gemini-backed assistant over the *current run only*. Two features: a case
# summary and free-text Q&A. Both are grounded on a digest built by
# copilot/context.py from STATE["last_results"] — the same object /api/results
# serialises — so the copilot and the dashboard cannot disagree about what was
# found.
#
# Three things are deliberately true of every endpoint below:
#
#   * No run, no answer. If the pipeline has not been executed these return 409,
#     exactly as /api/results does. A copilot that will happily discuss a case
#     with no dataset loaded is generating fiction.
#   * The API key is never persisted by this server. It is read from the
#     environment or a .env file, or held in memory after being pasted into
#     Settings — that runtime key dies with the process.
#   * The grounding is inspectable. /api/copilot/context returns the exact digest
#     the model was given, so any answer can be checked against its inputs.
# ═══════════════════════════════════════════════════════════════════════════

GEMINI = GeminiClient()
COPILOT = CopilotService(GEMINI)


class CopilotConfigureRequest(BaseModel):
    api_key: str
    model: str | None = None


class CopilotSummaryRequest(BaseModel):
    entity_id: str | None = None
    stream: bool = True


class CopilotChatRequest(BaseModel):
    question: str
    history: list | None = None
    entity_id: str | None = None
    stream: bool = True


def _require_run():
    """The loaded run, or the same 409 /api/results raises when there isn't one."""
    if not STATE["pipeline_run"] or STATE["last_results"] is None:
        raise HTTPException(
            status_code=409,
            detail="No analysis has been run yet. Upload files and run the pipeline "
                   "before asking the copilot about the case."
        )
    return STATE["last_results"]


def _copilot_status_payload():
    return {
        "configured": GEMINI.configured,
        "key_source": GEMINI.key_source(),
        "key_fingerprint": GEMINI.key_fingerprint(),
        "model": GEMINI.model,
        "provider": "Google Gemini",
        "pipeline_run": STATE["pipeline_run"],
        "data_mode": STATE["data_mode"],
        "suggestions": suggested_questions(STATE["last_results"]),
    }


@app.get("/api/copilot/status")
def copilot_status(verify: bool = False):
    """
    Whether the copilot can answer, and why not if it cannot.

    `verify=true` spends one real (tiny) API call to prove the key works. The UI
    polls this endpoint without verification on open and verifies only after a key
    is entered — a round-trip on every panel open would burn free-tier quota to
    tell the operator something the previous call already established.
    """
    payload = _copilot_status_payload()
    if verify and GEMINI.configured:
        try:
            payload["model"] = GEMINI.verify()
            payload["verified"] = True
        except GeminiError as e:
            payload["verified"] = False
            payload["error"] = e.message
    return payload


@app.post("/api/copilot/configure")
def copilot_configure(payload: CopilotConfigureRequest):
    """
    Accept a Gemini API key for this process.

    Held in memory only — never written to .env, never logged, never returned. The
    supported way to configure the key is the environment; this exists so the
    feature can be demonstrated on a machine where setting one is inconvenient.
    """
    key = (payload.api_key or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="No API key supplied.")

    previous = GEMINI._runtime_key
    if payload.model:
        GEMINI._preferred_model = payload.model.strip()
    GEMINI.set_api_key(key)

    try:
        model = GEMINI.verify()
    except GeminiError as e:
        # Reject rather than store: a key that cannot answer should not leave the
        # panel reporting "connected" until the operator's first question fails.
        GEMINI.set_api_key(previous)
        raise HTTPException(status_code=e.status, detail=e.message)

    logger.info(f"Copilot configured with a runtime Gemini key (model={model})")
    return {"status": "success", **_copilot_status_payload(), "verified": True}


@app.get("/api/copilot/context")
def copilot_context_dump(entity_id: str = None):
    """
    The exact facts the copilot is grounded on — nothing generated.

    This is the audit surface for the feature. If an answer is disputed, this
    endpoint shows precisely what the model was and was not told.
    """
    results = _require_run()
    digest = copilot_context.build_run_digest(
        results,
        data_mode=STATE["data_mode"],
        evidence_files=evidence_file_records(),
    )
    payload = {"digest": digest, "rendered": copilot_context.render_digest(digest)}
    if entity_id:
        dossier = copilot_context.build_entity_dossier(results, entity_id)
        if dossier is None:
            raise HTTPException(status_code=404, detail=f"Entity {entity_id} not in this run.")
        payload["dossier"] = dossier
        payload["rendered"] += "\n" + copilot_context.render_dossier(dossier)
    return JSONResponse(content=clean_serializable(payload))


def _sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _stream_answer(system_instruction, contents, meta, max_output_tokens):
    """
    SSE generator: meta first, then text deltas, then done — or an error event.

    Errors are streamed rather than raised because the HTTP status is long gone by
    the time Gemini fails mid-answer. The client renders an `error` event as a
    visible failure notice, so a truncated stream can never be mistaken for a
    complete answer.
    """
    yield _sse("meta", {**meta, "model": GEMINI.model})
    try:
        for chunk in COPILOT.run_stream(system_instruction, contents,
                                        max_output_tokens=max_output_tokens):
            yield _sse("delta", {"text": chunk})
    except GeminiError as e:
        yield _sse("error", {"message": e.message, "status": e.status})
        return
    except Exception as e:  # pragma: no cover - defensive
        logger.error(f"Copilot stream failed: {e}", exc_info=True)
        yield _sse("error", {"message": f"Copilot failed: {e}", "status": 500})
        return
    yield _sse("done", {"model": GEMINI.model})


SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    # Without this an intervening proxy can hold the whole stream and deliver it
    # in one lump, which defeats the point of streaming it at all.
    "X-Accel-Buffering": "no",
}


@app.post("/api/copilot/summary")
def copilot_summary(payload: CopilotSummaryRequest):
    """
    AI case summary for the loaded run — or for one entity when entity_id is given.

    This is a briefing aid, not a deliverable. The forensic report and the STR that
    go into a case file are still written by report/forensic_report.py directly from
    the pipeline output; nothing generated here reaches them.
    """
    results = _require_run()
    if not GEMINI.configured:
        raise HTTPException(status_code=503, detail=str(GeminiNotConfigured()))

    try:
        system_instruction, contents, meta = COPILOT.summary_request(
            results,
            data_mode=STATE["data_mode"],
            evidence_files=evidence_file_records(),
            focus_entity=payload.entity_id,
        )
    except GeminiError as e:
        raise HTTPException(status_code=e.status, detail=e.message)

    meta["kind"] = "summary"
    if payload.stream:
        return StreamingResponse(
            _stream_answer(system_instruction, contents, meta, 3072),
            media_type="text/event-stream", headers=SSE_HEADERS,
        )

    try:
        answer = COPILOT.run(system_instruction, contents, max_output_tokens=3072)
    except GeminiError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    return {"answer": answer, "model": GEMINI.model, **meta}


@app.post("/api/copilot/chat")
def copilot_chat(payload: CopilotChatRequest):
    """
    Free-text Q&A over the loaded run.

    `history` is the conversation so far, sent by the client — this server keeps no
    session state. `entity_id` pins the entity the operator currently has open so
    "why did this one fire?" resolves without them retyping the id; any entity the
    question itself names is attached on top of that.
    """
    results = _require_run()
    if not GEMINI.configured:
        raise HTTPException(status_code=503, detail=str(GeminiNotConfigured()))

    try:
        system_instruction, contents, meta = COPILOT.chat_request(
            payload.question,
            history=payload.history,
            results=results,
            data_mode=STATE["data_mode"],
            evidence_files=evidence_file_records(),
            focus_entity=payload.entity_id,
        )
    except GeminiError as e:
        raise HTTPException(status_code=e.status, detail=e.message)

    meta["kind"] = "chat"
    if payload.stream:
        return StreamingResponse(
            _stream_answer(system_instruction, contents, meta, 2048),
            media_type="text/event-stream", headers=SSE_HEADERS,
        )

    try:
        answer = COPILOT.run(system_instruction, contents, max_output_tokens=2048)
    except GeminiError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    return {"answer": answer, "model": GEMINI.model, **meta}


# Mount the frontend static files at the root
# Register / route for index.html explicitly
@app.get("/")
def read_index():
    index_path = BACKEND_DIR.parent / "frontend" / "index.html"
    if not index_path.exists():
        return {"message": "Welcome to E-Rakshak API. Frontend index.html not found."}
    return FileResponse(index_path)

# Register /dashboard route for clean URL access
@app.get("/dashboard")
def read_dashboard():
    dash_path = BACKEND_DIR.parent / "frontend" / "dashboard.html"
    if not dash_path.exists():
        return {"message": "Welcome to E-Rakshak API. Frontend dashboard.html not found."}
    return FileResponse(dash_path)

# Mount frontend folder
app.mount("/", StaticFiles(directory=str(BACKEND_DIR.parent / "frontend")), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
