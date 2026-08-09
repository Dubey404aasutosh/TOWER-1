"""
Entity Resolution Engine — Strict Two-Stage Anchor Resolution
==============================================================
Stage 1 (ownership anchor):
  Build each entity strictly from KYC-verified ownership links only.
  An account number, phone, IMEI, or IP may ONLY be added to an entity
  if the KYC map (or equivalent verified source) explicitly confirms
  that identifier belongs to that same person.

Stage 2 (behavioral linkage):
  Only AFTER stage 1 entities are finalized and validated, temporal and
  behavioral correlation signals (calls, IP sessions, transactions) draw
  relationship edges between distinct entities in the network graph —
  NEVER merging them into one entity.
"""
import re
import json
from collections import defaultdict
from pathlib import Path
import pandas as pd
import networkx as nx


def build_kyc_from_events(bank_events, cdr_events, ipdr_events):
    """
    Auto-generate KYC-like identity links from parsed event data.
    Used when no kyc_map.json is available (user-uploaded data).

    Rules for verified ownership:
    - CDR: entity_ref (phone) <-> imei (same handset during caller's activity)
    - IPDR: entity_ref (phone) <-> _public_ip (session IP for same user)
    - Bank: entity_ref (account) <-> account
    - NEVER link Bank account to narration counterparty VPA/phone!
    - NEVER link CDR caller to callee!
    """
    kyc_map = {}
    phone_data = defaultdict(lambda: {"phones": set(), "accounts": set(), "vpas": set(), "imeis": set(), "ips": set()})

    for event in cdr_events:
        phone = str(event.get("entity_ref", "")).strip()
        imei = str(event.get("imei", "")).strip() if event.get("imei") else None
        if phone and phone not in ["nan", "None", ""]:
            phone_data[phone]["phones"].add(phone)
            if imei and imei not in ["nan", "None", ""]:
                phone_data[phone]["imeis"].add(imei)

    for event in ipdr_events:
        phone = str(event.get("entity_ref", "")).strip()
        pub_ip = str(event.get("_public_ip", "")).strip() if event.get("_public_ip") else None
        if phone and phone not in ["nan", "None", ""]:
            phone_data[phone]["phones"].add(phone)
            if pub_ip and pub_ip not in ["nan", "None", ""]:
                phone_data[phone]["ips"].add(pub_ip)

    for phone, data in phone_data.items():
        kyc_map[phone] = {
            "name": None,
            "phones": list(data["phones"]),
            "accounts": list(data["accounts"]),
            "vpas": list(data["vpas"]),
            "imeis": list(data["imeis"]),
            "ips": list(data["ips"]),
        }

    for event in bank_events:
        acct = str(event.get("entity_ref", "")).strip()
        if acct and acct not in ["nan", "None", ""]:
            if acct not in kyc_map:
                kyc_map[acct] = {
                    "name": None,
                    "phones": [],
                    "accounts": [acct],
                    "vpas": [],
                    "imeis": [],
                    "ips": [],
                }

    return kyc_map


def _normalize_flat_kyc(flat_map):
    """
    Convert a flat KYC map ({identifier: name, ...}) into the structured format
    expected by the resolver ({key: {name, phones, accounts, vpas, imeis, ips}}).

    Heuristics for identifier classification:
    - 10-digit number starting with 6-9: phone
    - Starts with ACCT_ or is alphanumeric with _ and 4+ digits: account
    - Contains @: VPA
    - 15-digit number starting with 35: IMEI
    - Contains dots and all parts are numbers (like IP): IP address
    """
    import re
    name_groups = {}
    for identifier, name in flat_map.items():
        identifier = str(identifier).strip()
        name = str(name).strip()
        if not identifier or not name:
            continue
        if name not in name_groups:
            name_groups[name] = {"name": name, "phones": [], "accounts": [], "vpas": [], "imeis": [], "ips": []}

        # Classify identifier
        if re.match(r'^[6-9]\d{9}$', identifier):
            name_groups[name]["phones"].append(identifier)
        elif identifier.startswith("ACCT_") or re.match(r'^ACC[_\-]', identifier, re.IGNORECASE):
            name_groups[name]["accounts"].append(identifier)
        elif "@" in identifier:
            name_groups[name]["vpas"].append(identifier)
        elif re.match(r'^3[5-9]\d{13}$', identifier):
            name_groups[name]["imeis"].append(identifier)
        elif re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', identifier):
            name_groups[name]["ips"].append(identifier)
        elif re.match(r'^\d{10,}$', identifier):
            # Long digit string: could be phone with different length or IMEI
            if len(identifier) == 15:
                name_groups[name]["imeis"].append(identifier)
            else:
                name_groups[name]["phones"].append(identifier)
        else:
            name_groups[name]["accounts"].append(identifier)

    # Re-key by first phone or first identifier
    structured = {}
    for name, data in name_groups.items():
        key = data["phones"][0] if data["phones"] else (data["accounts"][0] if data["accounts"] else name)
        structured[key] = data

    return structured


def _is_flat_kyc(kyc_data):
    """
    Detect if a loaded KYC map is in flat format ({identifier: name_string})
    vs structured format ({key: {name, phones, accounts, ...}}).
    """
    if not kyc_data or not isinstance(kyc_data, dict):
        return False
    # Check first few values — if they're all strings, it's flat format
    sample_values = list(kyc_data.values())[:5]
    return all(isinstance(v, str) for v in sample_values)


def _find_kyc_file(data_dir):
    """
    Find a KYC map JSON file in the given directory.
    Matches any file containing 'kyc' in the name with .json extension.
    Handles filenames like kyc_map.json, kyc_map(1).json, custom_kyc.json, etc.
    """
    if data_dir is None:
        return None
    data_dir = Path(data_dir)
    if not data_dir.exists():
        return None
    for f in data_dir.iterdir():
        if f.is_file() and f.suffix.lower() == '.json' and 'kyc' in f.name.lower():
            return f
    return None


def build_identity_graph(bank_events, cdr_events, ipdr_events, data_dir=None, kyc_map=None):
    """
    Construct Stage 1 ownership identity graph.

    Edges created ONLY for verified ownership:
    - KYC records: phone <-> account <-> vpa <-> imei <-> ip (from kyc_map.json, passed kyc_map, or auto-generated)
    - Unmapped identifiers exist as standalone nodes (NO EDGES).
    """
    G = nx.Graph()
    id_types = {}
    _kyc_names = {}

    def add_id_node(identifier, id_type):
        if identifier and not pd.isna(identifier):
            identifier = str(identifier).strip()
            if not identifier or identifier in ["nan", "None", ""]:
                return None
            G.add_node(identifier)
            if identifier not in id_types or id_types[identifier] == "unknown":
                id_types[identifier] = id_type
            return identifier
        return None

    def add_identity_edge(id1, id2, source):
        if id1 and id2 and id1 != id2:
            G.add_edge(id1, id2, source=source)

    # 1. Obtain KYC map (passed, file, or auto-generated)
    kyc_path = None

    if kyc_map is None:
        # Try to find a KYC file in the data directory (flexible name matching)
        if data_dir is not None:
            kyc_path = _find_kyc_file(data_dir)

        if kyc_path is None:
            # Fallback: look in the default raw data directory
            default_kyc = Path(__file__).resolve().parent.parent / "data" / "raw" / "kyc_map.json"
            if data_dir is not None and Path(data_dir).resolve() != default_kyc.parent.resolve():
                # We're processing uploaded data, not demo data
                # Try the default raw dir as last resort for KYC
                fallback_kyc = _find_kyc_file(default_kyc.parent)
                if fallback_kyc is None:
                    print("  No KYC map file found. Auto-generating Stage 1 ownership links from event data...")
                    kyc_map = build_kyc_from_events(bank_events, cdr_events, ipdr_events)
                else:
                    # Only use default KYC for demo data path
                    print("  No KYC map file found in upload dir. Auto-generating Stage 1 ownership links from event data...")
                    kyc_map = build_kyc_from_events(bank_events, cdr_events, ipdr_events)
            elif default_kyc.exists():
                kyc_path = default_kyc

        if kyc_map is None and kyc_path is not None and kyc_path.exists():
            try:
                print(f"  Loading KYC map from: {kyc_path.name}")
                with open(kyc_path, 'r', encoding='utf-8') as f:
                    kyc_map = json.load(f)
                # Auto-detect and normalize flat KYC format
                if _is_flat_kyc(kyc_map):
                    print(f"  Detected flat KYC format ({{identifier: name}}). Converting to structured format...")
                    kyc_map = _normalize_flat_kyc(kyc_map)
                    print(f"  Normalized KYC: {len(kyc_map)} identity groups created.")
            except Exception as e:
                print(f"  WARNING: Failed to load KYC map: {str(e)}")
                kyc_map = {}

    if kyc_map is None:
        kyc_map = {}

    # Final safety check: if kyc_map was passed in flat format, normalize it
    if _is_flat_kyc(kyc_map):
        print(f"  Detected flat KYC format. Converting to structured format...")
        kyc_map = _normalize_flat_kyc(kyc_map)
        print(f"  Normalized KYC: {len(kyc_map)} identity groups created.")

    # 2. Add KYC-verified ownership nodes & edges ONLY
    for key, entry in kyc_map.items():
        phones = entry.get("phones", [])
        accounts = entry.get("accounts", [])
        vpas = entry.get("vpas", [])
        imeis = entry.get("imeis", [])
        ips = entry.get("ips", [])
        name = entry.get("name")

        nodes = []
        for p in phones:
            n = add_id_node(p, "phone")
            if n:
                nodes.append(n)
                if name: _kyc_names[n] = name
        for a in accounts:
            n = add_id_node(a, "account")
            if n:
                nodes.append(n)
                if name: _kyc_names[n] = name
        for v in vpas:
            n = add_id_node(v, "vpa")
            if n:
                nodes.append(n)
                if name: _kyc_names[n] = name
        for im in imeis:
            n = add_id_node(im, "imei")
            if n:
                nodes.append(n)
                if name: _kyc_names[n] = name
        for ip in ips:
            n = add_id_node(ip, "ip")
            if n:
                nodes.append(n)
                if name: _kyc_names[n] = name

        # Link identifiers belonging to the SAME verified KYC entry
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                add_identity_edge(nodes[i], nodes[j], "kyc_ownership")

    # 3. Add all unmapped raw identifiers as standalone nodes (NO EDGES)
    for event in bank_events:
        add_id_node(event.get("entity_ref"), "account")
        cp = event.get("counterparty")
        if cp:
            add_id_node(cp, "vpa" if "@" in str(cp) else "account")

    for event in cdr_events:
        add_id_node(event.get("entity_ref"), "phone")
        add_id_node(event.get("counterparty"), "phone")
        add_id_node(event.get("imei"), "imei")

    for event in ipdr_events:
        add_id_node(event.get("entity_ref"), "phone")
        add_id_node(event.get("_public_ip"), "ip")
        cp = event.get("counterparty")
        if cp:
            add_id_node(cp, "ip" if "." in str(cp) else "unknown")

    return G, id_types, _kyc_names, kyc_map


def validate_and_sanitize_entities(entities, entity_map, kyc_map):
    """
    Validation check (Requirement 3):
    No single entity should ever contain more than one phone number,
    more than one IMEI, or more than one account number UNLESS the KYC map
    explicitly lists multiple values under the same verified identity.
    """
    kyc_entries = list(kyc_map.values()) if kyc_map else []

    sanitized_entities = {}
    new_entity_map = dict(entity_map)

    for eid, edata in list(entities.items()):
        phones = edata.get("phones", [])
        accounts = edata.get("accounts", [])
        imeis = edata.get("imeis", [])

        is_multi = len(phones) > 1 or len(accounts) > 1 or len(imeis) > 1

        if is_multi:
            # Check if this exact set of multi-values is explicitly authorized by a single KYC record
            allowed = False
            for kentry in kyc_entries:
                k_phones = set(kentry.get("phones", []))
                k_accounts = set(kentry.get("accounts", []))
                k_imeis = set(kentry.get("imeis", []))

                if set(phones).issubset(k_phones) and \
                   set(accounts).issubset(k_accounts) and \
                   set(imeis).issubset(k_imeis):
                    allowed = True
                    break

            if not allowed:
                # Conflicting unverified ownership detected! Split this entity into single-ownership entities
                print(f"  [Validation Warning] Splitting unverified multi-identifier entity {eid}")
                all_ids = phones + accounts + imeis + edata.get("vpas", []) + edata.get("ips", [])
                sub_count = 1
                for item in all_ids:
                    sub_eid = f"{eid}_{sub_count}"
                    sub_count += 1
                    sub_data = {
                        "entity_id": sub_eid,
                        "name": edata.get("name"),
                        "phones": [item] if item in phones else [],
                        "accounts": [item] if item in accounts else [],
                        "vpas": [item] if item in edata.get("vpas", []) else [],
                        "imeis": [item] if item in imeis else [],
                        "ips": [item] if item in edata.get("ips", []) else [],
                    }
                    sanitized_entities[sub_eid] = sub_data
                    new_entity_map[item] = sub_eid
                continue

        sanitized_entities[eid] = edata

    return sanitized_entities, new_entity_map


def resolve_entities(G, id_types, kyc_names=None):
    """
    Run connected components on Stage 1 ownership identity graph.
    Returns:
    - entity_map: {raw_identifier: entity_id}
    - entities: {entity_id: {phones, accounts, imeis, ips, vpas, name}}
    """
    if kyc_names is None:
        kyc_names = {}

    components = list(nx.connected_components(G))
    entity_map = {}
    entities = {}

    for comp_idx, component in enumerate(components):
        entity_id = f"ENT_{comp_idx + 1:04d}"

        entity_data = {
            "entity_id": entity_id,
            "name": None,
            "phones": [],
            "accounts": [],
            "imeis": [],
            "ips": [],
            "vpas": [],
        }

        for node in component:
            entity_map[node] = entity_id
            node_type = id_types.get(node, "unknown")
            if node_type == "phone":
                entity_data["phones"].append(node)
            elif node_type == "imei":
                entity_data["imeis"].append(node)
            elif node_type == "ip":
                entity_data["ips"].append(node)
            elif node_type == "account":
                entity_data["accounts"].append(node)
            elif node_type == "vpa":
                entity_data["vpas"].append(node)

            if entity_data["name"] is None and node in kyc_names:
                entity_data["name"] = kyc_names[node]

        if entity_data["name"] is None:
            if entity_data["phones"]:
                entity_data["name"] = f"Phone {entity_data['phones'][0]}"
            elif entity_data["accounts"]:
                entity_data["name"] = f"Acct {entity_data['accounts'][0]}"
            elif entity_data["vpas"]:
                entity_data["name"] = f"VPA {entity_data['vpas'][0]}"
            elif entity_data["ips"]:
                entity_data["name"] = f"IP {entity_data['ips'][0]}"
            else:
                entity_data["name"] = entity_id

        entities[entity_id] = entity_data

    return entity_map, entities


def apply_entity_resolution(events, entity_map):
    """
    Apply resolved entity_id to all events.
    Maps each event's entity_ref (raw identifier) to a resolved entity_id.
    """
    for event in events:
        raw_ref = str(event.get("entity_ref", "")).strip()
        if raw_ref in entity_map:
            event["entity_id"] = entity_map[raw_ref]
        else:
            event["entity_id"] = entity_map.get(raw_ref, f"UNRESOLVED_{raw_ref}")

    return events


def run_entity_resolution(bank_events, cdr_events, ipdr_events, data_dir=None, kyc_map=None):
    """
    Full two-stage entity resolution pipeline.
    Stage 1: Ownership Anchor (KYC-verified identity graph) + Validation Check
    Stage 2: Behavioral Linkage (handled downstream by relationship graph / rules)
    """
    print("\n[Entity Resolution] Stage 1: Building ownership identity graph...")
    G, id_types, kyc_names, kyc_map = build_identity_graph(bank_events, cdr_events, ipdr_events, data_dir=data_dir, kyc_map=kyc_map)
    print(f"  Ownership Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    print("[Entity Resolution] Stage 1: Running connected components...")
    entity_map, entities = resolve_entities(G, id_types, kyc_names)
    print(f"  Initial Resolved Entities: {len(entities)} from {G.number_of_nodes()} raw identifiers")

    print("[Entity Resolution] Stage 1 Validation: Verifying multi-identifier ownership constraints...")
    entities, entity_map = validate_and_sanitize_entities(entities, entity_map, kyc_map)
    print(f"  Final Validated Entities: {len(entities)}")

    multi_id = sum(1 for e in entities.values()
                   if len(e["phones"]) + len(e["accounts"]) + len(e["imeis"]) + len(e["vpas"]) > 1)
    singleton_id = len(entities) - multi_id

    # Compute KYC identifier coverage breakdown
    graph_nodes = set(G.nodes())
    kyc_mapped_nodes = set()
    if kyc_map:
        for entry in kyc_map.values():
            for k in ["phones", "accounts", "vpas", "imeis", "ips"]:
                for val in entry.get(k, []):
                    if val and str(val).strip() in graph_nodes:
                        kyc_mapped_nodes.add(str(val).strip())
    unmapped_nodes = graph_nodes - kyc_mapped_nodes

    print(f"  Identifier Breakdown:")
    print(f"    - Total raw identifiers in graph: {len(graph_nodes)}")
    print(f"    - Identifiers with verified KYC entry: {len(kyc_mapped_nodes)}")
    print(f"    - Unmapped identifiers (counterparties/IPs): {len(unmapped_nodes)}")
    print(f"  Entity Resolution Breakdown:")
    print(f"    - KYC-Anchored Multi-identifier Entities: {multi_id}")
    print(f"    - Singleton Passthrough Entities (Unmapped Counterparties): {singleton_id}")

    print("[Entity Resolution] Applying entity IDs to events...")
    bank_events = apply_entity_resolution(bank_events, entity_map)
    cdr_events = apply_entity_resolution(cdr_events, entity_map)
    ipdr_events = apply_entity_resolution(ipdr_events, entity_map)

    return entity_map, entities, G, id_types, bank_events, cdr_events, ipdr_events


if __name__ == "__main__":
    print("Entity resolver module - run via pipeline.py")
