"""
Self-Verification Against Ground Truth
========================================
Compares pipeline detection results against ground_truth.json
and reports recall, precision, and per-typology detection accuracy.
"""
import json
from pathlib import Path


def verify_against_ground_truth(scored_entities, entities=None, ground_truth_path=None):
    """
    Compare flagged entities against planted ground truth.

    Args:
        scored_entities: dict {entity_id: {risk_tier, rules_fired, ...}}
        entities: dict {entity_id: {phones, accounts, imeis, vpas, ips}} from resolution
        ground_truth_path: path to ground_truth.json

    Returns:
        dict with recall, precision, f1, and per-typology results
    """
    if ground_truth_path is None:
        ground_truth_path = Path(__file__).resolve().parent.parent / "data" / "generator" / "ground_truth.json"
    else:
        ground_truth_path = Path(ground_truth_path)

    if not ground_truth_path.exists():
        import logging
        err_msg = f"Ground truth file not found at {ground_truth_path}"
        print(f"\033[91m[ERROR] {err_msg}\033[0m")
        logging.error(err_msg)
        raise FileNotFoundError(err_msg)

    with open(ground_truth_path, 'r', encoding='utf-8') as f:
        gt = json.load(f)

    guilty_ids = set(gt.get("guilty_entity_ids", []))
    gt_entries = {e["entity_id"]: e for e in gt.get("entities", [])}
    total_entities = gt.get("total_entities", 45)
    normal_count = gt.get("normal_entities", 40)

    # Entities that the pipeline flagged as HIGH or CRITICAL
    flagged_entities = set()
    for eid, data in scored_entities.items():
        if data.get("risk_tier") in ["HIGH", "CRITICAL"]:
            flagged_entities.add(eid)

    # --- Match GT entities to pipeline resolved entities ---
    # Best approach: match by identifier overlap using the entities dict
    gt_to_detected = {}
    already_matched = set()  # Prevent double-matching

    for gt_eid, gt_entry in gt_entries.items():
        gt_ids = gt_entry.get("raw_identifiers", {})
        gt_phones = set(gt_ids.get("phones", []))
        gt_accounts = set(gt_ids.get("accounts", []))
        gt_imeis = set(gt_ids.get("imeis", []))
        gt_vpas = set(gt_ids.get("vpas", []))
        gt_all = gt_phones | gt_accounts | gt_imeis | gt_vpas

        matched_detected = None
        best_overlap = 0

        if entities:
            # Match by identifier overlap — the correct approach
            for det_eid, det_data in entities.items():
                if det_eid in already_matched:
                    continue
                det_phones = set(det_data.get("phones", []))
                det_accounts = set(det_data.get("accounts", []))
                det_imeis = set(det_data.get("imeis", []))
                det_vpas = set(det_data.get("vpas", []))
                det_all = det_phones | det_accounts | det_imeis | det_vpas

                overlap = len(gt_all & det_all)
                if overlap > best_overlap:
                    best_overlap = overlap
                    matched_detected = det_eid

        # Fallback: if no identifier overlap found, match by expected typology rule
        if matched_detected is None:
            expected_rule = gt_entry.get("typology")
            for det_eid, det_data in scored_entities.items():
                if det_eid in already_matched:
                    continue
                det_rules = set(det_data.get("rules_fired", []))
                if expected_rule in det_rules:
                    if matched_detected is None:
                        matched_detected = det_eid
                    else:
                        prev_rules = len(scored_entities.get(matched_detected, {}).get("rules_fired", []))
                        curr_rules = len(det_rules)
                        if curr_rules > prev_rules:
                            matched_detected = det_eid

        if matched_detected:
            already_matched.add(matched_detected)
        gt_to_detected[gt_eid] = matched_detected

    # Compute metrics
    true_positives = 0
    false_negatives = 0
    typology_results = []
    detected_entity_ids = set()

    for gt_eid, gt_entry in gt_entries.items():
        detected = gt_to_detected.get(gt_eid)
        typology = gt_entry.get("typology", "?")
        name = gt_entry.get("name", "?")

        if detected and detected in flagged_entities:
            detected_tier = scored_entities.get(detected, {}).get("risk_tier", "LOW")
            detected_rules = scored_entities.get(detected, {}).get("rules_fired", [])
            true_positives += 1
            status = "DETECTED"
            detected_entity_ids.add(detected)
        elif detected:
            # Matched an entity but it wasn't flagged HIGH/CRITICAL
            detected_tier = scored_entities.get(detected, {}).get("risk_tier", "LOW")
            detected_rules = scored_entities.get(detected, {}).get("rules_fired", [])
            # Count as detected if any rules fired, even if tier is LOW/MEDIUM
            if detected_rules:
                true_positives += 1
                status = "DETECTED"
                detected_entity_ids.add(detected)
            else:
                false_negatives += 1
                status = "MISSED"
        else:
            detected_tier = "N/A"
            detected_rules = []
            false_negatives += 1
            status = "MISSED"

        typology_results.append({
            "gt_entity": gt_eid,
            "name": name,
            "typology": typology,
            "status": status,
            "detected_as": detected,
            "detected_tier": detected_tier,
            "detected_rules": detected_rules,
        })

    # False positives: entities flagged HIGH/CRITICAL but not matched to any GT entity
    false_positives = len(flagged_entities - detected_entity_ids)

    # Metrics
    recall = true_positives / max(len(gt_entries), 1)
    precision = true_positives / max(true_positives + false_positives, 1)
    f1 = 2 * precision * recall / max(precision + recall, 0.0001)

    results = {
        "total_gt_entities": len(gt_entries),
        "total_flagged": len(flagged_entities),
        "true_positives": true_positives,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "recall": recall,
        "precision": precision,
        "f1": f1,
        "typology_results": typology_results,
    }

    # Print results
    print("\n" + "=" * 60)
    print("SELF-VERIFICATION AGAINST GROUND TRUTH")
    print("=" * 60)
    print(f"\nPlanted guilty entities: {len(gt_entries)}")
    print(f"Pipeline flagged (HIGH/CRITICAL): {len(flagged_entities)}")
    print(f"\nTrue Positives:  {true_positives}")
    print(f"False Positives: {false_positives}")
    print(f"False Negatives: {false_negatives}")
    print(f"\nRECALL:    {recall:.2%}")
    print(f"PRECISION: {precision:.2%}")
    print(f"F1 SCORE:  {f1:.2%}")

    print(f"\nPer-typology breakdown:")
    for r in typology_results:
        status_icon = "OK" if r["status"] == "DETECTED" else "MISS"
        print(f"  [{status_icon}] {r['gt_entity']} ({r['name']}): "
              f"{r['typology']} -> {r['status']} "
              f"(tier: {r['detected_tier']}, rules: {', '.join(r['detected_rules'])})")

    print("=" * 60)

    return results


# Human-readable labels for each planted fraud typology (keyed by the rule ID
# used as the ground-truth "typology" tag in ground_truth.json).
TYPOLOGY_LABELS = {
    "STR-1": "Structuring / Smurfing",
    "LAY-1": "Layering / Circular Flow",
    "MUL-1": "Mule Account Signature",
    "IDR-1": "Identity Fan-out / SIM Swap",
    "LOC-1": "Geo-Improbable Location",
}


def summarize_by_typology(verification_results):
    """
    Aggregate the flat per-entity typology_results list from
    verify_against_ground_truth() into per-typology recall/precision counts.

    Args:
        verification_results: dict returned by verify_against_ground_truth()

    Returns:
        list of dicts, one per typology present in ground truth:
        {typology, label, planted, detected, missed, recall}
    """
    typology_results = verification_results.get("typology_results", [])

    buckets = {}
    for r in typology_results:
        typology = r.get("typology", "?")
        bucket = buckets.setdefault(typology, {"planted": 0, "detected": 0, "missed": 0})
        bucket["planted"] += 1
        if r.get("status") == "DETECTED":
            bucket["detected"] += 1
        else:
            bucket["missed"] += 1

    breakdown = []
    for typology, counts in sorted(buckets.items()):
        planted = counts["planted"]
        detected = counts["detected"]
        breakdown.append({
            "typology": typology,
            "label": TYPOLOGY_LABELS.get(typology, typology),
            "planted": planted,
            "detected": detected,
            "missed": counts["missed"],
            "recall": (detected / planted) if planted else 0.0,
        })

    return breakdown


if __name__ == "__main__":
    print("Verification module - run via pipeline.py")
