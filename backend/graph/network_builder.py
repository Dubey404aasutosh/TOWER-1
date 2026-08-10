"""
Network Graph Builder — Clean Hierarchical Layout
====================================================
- Filters to show only MEDIUM+ risk entities and their direct connections
- Uses radial layout: CRITICAL center, HIGH ring 1, MEDIUM ring 2, connected LOW outer
- Edge bundling: parallel edges merged with weighted thickness
- Interactive Plotly rendering with hover details
"""
import math
import networkx as nx
import pandas as pd
import plotly.graph_objects as go


def _source_file_to_institution(source_file):
    sf = str(source_file).lower()
    if "sbi" in sf:
        return "SBI Bank"
    elif "hdfc" in sf:
        return "HDFC Bank"
    elif "icici" in sf:
        return "ICICI Bank"
    elif "cdr" in sf:
        return "Operator-CDR"
    elif "ipdr" in sf:
        return "Operator-IPDR"
    elif "bank" in sf:
        return "Bank (General)"
    return "Other Institution"


def _location_to_city(location):
    """
    Resolve an event's location field to a city name.

    The two telecom sources record place differently: CDR carries a cell-tower id
    ("SRT-T05"), IPDR carries a city name already ("Chennai"). Both have to land on
    the same label for a city filter to mean anything.
    """
    if location is None:
        return None
    text = str(location).strip()
    if not text or text.lower() in ("nan", "none"):
        return None

    try:
        from graph.map_builder import CELL_TOWERS
    except Exception:
        CELL_TOWERS = {}

    tower = CELL_TOWERS.get(text) or CELL_TOWERS.get(text.upper())
    if tower and tower.get("city"):
        return tower["city"]

    known = {t.get("city") for t in CELL_TOWERS.values() if t.get("city")}
    for city in known:
        if text.lower() == city.lower():
            return city
    return text if len(text) <= 32 else None


def _build_identifier_index(entities):
    """
    Build a single reverse lookup: identifier (phone/account/vpa) -> entity_id.
    O(total identifiers across all entities) instead of an O(entities) scan per event.
    """
    index = {}
    for eid, edata in entities.items():
        for ident in edata.get("phones", []) + edata.get("accounts", []) + edata.get("vpas", []):
            index[ident] = eid
    return index


def _build_phone_index(entities):
    """Reverse lookup restricted to phones, used for call/sms edge resolution."""
    index = {}
    for eid, edata in entities.items():
        for phone in edata.get("phones", []):
            index[phone] = eid
    return index


def build_network_graph(all_events_df, scored_entities, entities):
    """
    Build a directed graph from resolved events.
    Nodes = entities (colored/sized by risk tier and tagged with institution)
    Edges = transactions (weighted by amount) + calls (weighted by frequency)
    """
    G = nx.DiGraph()

    # Track entity -> institutions / source_files mapping via vectorized groupby
    # instead of an iterrows() loop over every event row.
    entity_institutions = {}
    entity_sources = {}
    if not all_events_df.empty and 'source_file' in all_events_df.columns:
        sf_df = all_events_df[['entity_id', 'source_file']].dropna()
        sf_df = sf_df[sf_df['entity_id'] != '']
        if not sf_df.empty:
            sf_df = sf_df.assign(source_file=sf_df['source_file'].astype(str))
            sf_df = sf_df.assign(institution=sf_df['source_file'].map(_source_file_to_institution))
            grouped = sf_df.groupby('entity_id').agg({
                'institution': lambda s: set(s),
                'source_file': lambda s: set(s),
            })
            entity_institutions = grouped['institution'].to_dict()
            entity_sources = grouped['source_file'].to_dict()

    # Add entity nodes
    for entity_id, entity_data in entities.items():
        risk_data = scored_entities.get(entity_id, {})
        risk_tier = risk_data.get("risk_tier", "LOW")
        rules = risk_data.get("rules_fired", [])
        ml_flag = risk_data.get("ml_anomaly", False)

        inst_set = entity_institutions.get(entity_id, {"Unknown"})
        inst_list = sorted(list(inst_set))
        primary_inst = inst_list[0] if inst_list else "Unknown"

        G.add_node(entity_id,
                    risk_tier=risk_tier,
                    rules_fired=rules,
                    ml_anomaly=ml_flag,
                    institution=primary_inst,
                    institutions=inst_list,
                    source_files=sorted(list(entity_sources.get(entity_id, []))),
                    phones=entity_data.get("phones", []),
                    accounts=entity_data.get("accounts", []),
                    imeis=entity_data.get("imeis", []),
                    vpas=entity_data.get("vpas", []))

    if all_events_df.empty:
        return G

    # Build identifier -> entity_id reverse indexes ONCE (O(total identifiers)),
    # replacing the per-event O(entities) linear scan that caused the quadratic blowup.
    id_index = _build_identifier_index(entities)
    phone_index = _build_phone_index(entities)

    # ---- Add transaction edges (vectorized counterparty resolution) ----
    txns = all_events_df[all_events_df['event_type'] == 'transaction'].copy()
    if not txns.empty:
        txns['counterparty'] = txns['counterparty'].astype(str).str.strip()
        txns['amount_abs'] = txns['amount'].abs()
        txns['counterparty_entity'] = txns['counterparty'].map(id_index)
        txns['source_file'] = txns['source_file'].fillna('unknown').astype(str)

        valid = txns[
            txns['entity_id'].notna() & (txns['entity_id'] != '') &
            txns['counterparty_entity'].notna() &
            (txns['amount_abs'] > 0)
        ]

        if not valid.empty:
            # Directed edge: debit (amount < 0) = sender -> counterparty entity,
            # credit (amount >= 0) = counterparty entity -> sender.
            src = valid['entity_id'].where(valid['amount'] < 0, valid['counterparty_entity'])
            dst = valid['counterparty_entity'].where(valid['amount'] < 0, valid['entity_id'])

            edge_df = pd.DataFrame({
                'src': src.values,
                'dst': dst.values,
                'amount_abs': valid['amount_abs'].values,
                'source_file': valid['source_file'].values,
                'is_debit': (valid['amount'] < 0).values,
            })

            # ---- Deduplicate the two sides of one transfer ----
            # When both parties' statements are ingested, a single transfer appears
            # twice: as a debit in the sender's statement and as a credit in the
            # receiver's. They carry different UTRs, so they cannot be matched on a
            # reference — but they are the same movement of money, and summing both
            # doubles the edge weight. (Measured: a real ₹275,659 layering hop was
            # reported as ₹551,318.)
            #
            # Rule: for each (src, dst) pair, count the debit rows — the sender's own
            # record of money leaving. Credit rows are used only when no debit row for
            # that pair was ingested at all, so an edge is never lost, just never
            # counted twice.
            has_debit = edge_df.groupby(['src', 'dst'])['is_debit'].transform('any')
            deduped = edge_df[edge_df['is_debit'] | ~has_debit]

            agg = deduped.groupby(['src', 'dst']).agg(
                weight=('amount_abs', 'sum'),
                count=('amount_abs', 'size'),
                source_file=('source_file', 'first'),
                from_debit=('is_debit', 'any'),
            ).reset_index()

            for row in agg.itertuples(index=False):
                inst = _source_file_to_institution(row.source_file)
                G.add_edge(row.src, row.dst,
                           weight=row.weight, count=int(row.count),
                           edge_type='transaction',
                           source_file=str(row.source_file),
                           institution=inst,
                           # False = only the receiving side's statement was ingested,
                           # so this edge is evidenced by the counterparty's record.
                           counted_from_debit=bool(row.from_debit))

    # ---- Add call edges (vectorized aggregation by frequency) ----
    calls = all_events_df[all_events_df['event_type'].isin(['call', 'sms'])].copy()
    if not calls.empty:
        calls['counterparty'] = calls['counterparty'].astype(str).str.strip()
        calls['callee_entity'] = calls['counterparty'].map(phone_index)
        calls['source_file'] = calls['source_file'].fillna('unknown').astype(str)

        valid_calls = calls[
            calls['entity_id'].notna() & (calls['entity_id'] != '') &
            calls['callee_entity'].notna() &
            (calls['entity_id'] != calls['callee_entity'])
        ]

        if not valid_calls.empty:
            call_agg = valid_calls.groupby(['entity_id', 'callee_entity']).agg(
                freq=('counterparty', 'size'),
                source_file=('source_file', 'first'),
            ).reset_index()

            for row in call_agg.itertuples(index=False):
                caller, callee, freq = row.entity_id, row.callee_entity, int(row.freq)
                inst = _source_file_to_institution(row.source_file)
                if G.has_edge(caller, callee):
                    G[caller][callee]['call_frequency'] = freq
                else:
                    G.add_edge(caller, callee, weight=freq * 100,
                               count=freq, edge_type='call',
                               call_frequency=freq,
                               source_file=row.source_file,
                               institution=inst)

    return G


def _compute_clean_layout(G, scored_entities):
    """
    Compute a clean radial layout:
    - Center: CRITICAL entities
    - Ring 1: HIGH entities
    - Ring 2: MEDIUM entities
    - Outer ring: connected LOW entities only
    """
    tier_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    tiers = {}
    for node in G.nodes():
        tier = scored_entities.get(node, {}).get("risk_tier", "LOW")
        if tier not in tiers:
            tiers[tier] = []
        tiers[tier].append(node)

    pos = {}
    ring_radii = {"CRITICAL": 0.0, "HIGH": 1.5, "MEDIUM": 3.0, "LOW": 5.0}

    for tier in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
        nodes = tiers.get(tier, [])
        if not nodes:
            continue
        radius = ring_radii[tier]

        if tier == "CRITICAL" and len(nodes) == 1:
            pos[nodes[0]] = (0, 0)
        else:
            angle_step = (2 * math.pi) / max(len(nodes), 1)
            for i, node in enumerate(nodes):
                angle = i * angle_step
                # Add small jitter for same-ring overlap avoidance
                jitter = 0.1 * (hash(node) % 10) / 10
                pos[node] = (
                    (radius + jitter) * math.cos(angle),
                    (radius + jitter) * math.sin(angle)
                )

    # Any unpositioned nodes (shouldn't happen)
    for node in G.nodes():
        if node not in pos:
            pos[node] = (6.0 * math.cos(hash(node) % 100),
                         6.0 * math.sin(hash(node) % 100))

    return pos


def create_network_plotly(G, scored_entities, show_low=False, min_amount=0, filter_rules=None):
    """
    Create a clean, filtered, interactive Plotly network graph.

    Args:
        G: NetworkX DiGraph
        scored_entities: dict of scoring results
        show_low: whether to show LOW risk nodes (default False — keeps graph clean)
        min_amount: minimum transaction amount to show an edge
        filter_rules: optional list of rule IDs to filter (e.g., ["TCS-1", "MUL-1"])
    """
    if G.number_of_nodes() == 0:
        return go.Figure()

    # ---- FILTER NODES ----
    visible_nodes = set()
    for node in G.nodes():
        tier = scored_entities.get(node, {}).get("risk_tier", "LOW")
        rules = scored_entities.get(node, {}).get("rules_fired", [])

        if tier in ["CRITICAL", "HIGH", "MEDIUM"]:
            if filter_rules:
                if any(r in rules for r in filter_rules):
                    visible_nodes.add(node)
            else:
                visible_nodes.add(node)

    # Add direct neighbors of visible nodes (even if LOW)
    neighbors_to_add = set()
    for node in visible_nodes:
        for neighbor in list(G.predecessors(node)) + list(G.successors(node)):
            neighbors_to_add.add(neighbor)
    if show_low:
        visible_nodes.update(neighbors_to_add)
    else:
        # Only add LOW neighbors that have edges to flagged nodes
        for n in neighbors_to_add:
            if n not in visible_nodes:
                visible_nodes.add(n)

    if not visible_nodes:
        # Fallback: show everything
        visible_nodes = set(G.nodes())

    # Build subgraph
    subG = G.subgraph(visible_nodes).copy()

    # Filter edges by min_amount
    if min_amount > 0:
        edges_to_remove = []
        for u, v, data in subG.edges(data=True):
            if data.get('edge_type') == 'transaction' and data.get('weight', 0) < min_amount:
                edges_to_remove.append((u, v))
        subG.remove_edges_from(edges_to_remove)

    # ---- LAYOUT ----
    pos = _compute_clean_layout(subG, scored_entities)

    # ---- STYLING ----
    tier_colors = {
        "CRITICAL": "#ff2d2d",
        "HIGH": "#ff8c00",
        "MEDIUM": "#ffd700",
        "LOW": "#5a6a5a",
    }
    tier_sizes = {"CRITICAL": 28, "HIGH": 22, "MEDIUM": 16, "LOW": 10}

    # ---- EDGE TRACES ----
    edge_traces = []
    for u, v, data in subG.edges(data=True):
        if u not in pos or v not in pos:
            continue
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        edge_type = data.get('edge_type', 'transaction')
        weight = data.get('weight', 1)

        # Check suspicious edges
        u_rules = scored_entities.get(u, {}).get("rules_fired", [])
        v_rules = scored_entities.get(v, {}).get("rules_fired", [])
        is_suspicious = any(r in u_rules + v_rules for r in ["TCS-1", "TCS-2"])

        if is_suspicious:
            color = "rgba(255, 68, 68, 0.6)"
        elif edge_type == 'transaction':
            color = "rgba(74, 144, 217, 0.35)"
        else:
            color = "rgba(108, 117, 125, 0.25)"

        width = max(1, min(weight / 30000, 6)) if edge_type == 'transaction' else 1.5
        count = data.get('count', 1)

        hover_text = f"{u} → {v}<br>Type: {edge_type}<br>"
        if edge_type == 'transaction':
            hover_text += f"Total: ₹{weight:,.0f}<br>Txns: {count}"
        else:
            hover_text += f"Calls: {data.get('call_frequency', count)}"

        edge_traces.append(go.Scatter(
            x=[x0, x1, None], y=[y0, y1, None],
            mode='lines',
            line=dict(width=width, color=color),
            hovertext=hover_text, hoverinfo='text',
            showlegend=False,
        ))

    # ---- NODE TRACE ----
    node_x, node_y, node_colors, node_sizes, node_text, node_labels = [], [], [], [], [], []
    for node in subG.nodes():
        if node not in pos:
            continue
        x, y = pos[node]
        node_x.append(x)
        node_y.append(y)

        risk_data = scored_entities.get(node, {})
        tier = risk_data.get("risk_tier", "LOW")
        rules = risk_data.get("rules_fired", [])
        ml_flag = risk_data.get("ml_anomaly", False)

        node_colors.append(tier_colors.get(tier, "#5a6a5a"))
        node_sizes.append(tier_sizes.get(tier, 10))

        # Show labels only for MEDIUM+ risk
        if tier in ["CRITICAL", "HIGH", "MEDIUM"]:
            node_labels.append(node)
        else:
            node_labels.append("")

        # Rich hover
        hover = f"<b>{node}</b><br>Risk Tier: {tier}<br>"
        if rules:
            hover += f"Rules: {', '.join(rules)}<br>"
        if ml_flag:
            hover += "🔬 ML Anomaly FLAGGED<br>"

        node_data = subG.nodes[node]
        phones = node_data.get("phones", [])
        accounts = node_data.get("accounts", [])
        if phones:
            hover += f"📱 Phones: {', '.join(phones[:3])}<br>"
        if accounts:
            hover += f"🏦 Accounts: {', '.join(accounts[:3])}<br>"

        node_text.append(hover)

    # Glow effect for CRITICAL nodes via outline
    node_outline_colors = []
    node_outline_widths = []
    for node in subG.nodes():
        if node not in pos:
            continue
        tier = scored_entities.get(node, {}).get("risk_tier", "LOW")
        if tier == "CRITICAL":
            node_outline_colors.append("rgba(255, 45, 45, 0.5)")
            node_outline_widths.append(4)
        elif tier == "HIGH":
            node_outline_colors.append("rgba(255, 140, 0, 0.4)")
            node_outline_widths.append(3)
        else:
            node_outline_colors.append("rgba(42, 45, 53, 0.8)")
            node_outline_widths.append(1)

    node_trace = go.Scatter(
        x=node_x, y=node_y,
        mode='markers+text',
        marker=dict(
            size=node_sizes, color=node_colors,
            line=dict(width=node_outline_widths, color=node_outline_colors),
        ),
        text=node_labels,
        textposition="top center",
        textfont=dict(size=9, color="#d0d0d0"),
        hovertext=node_text,
        hoverinfo='text',
        showlegend=False,
    )

    fig = go.Figure(data=edge_traces + [node_trace])
    fig.update_layout(
        plot_bgcolor='#0c0e12',
        paper_bgcolor='#0c0e12',
        font=dict(color='#c0c0c0'),
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        margin=dict(l=0, r=0, t=30, b=0),
        height=550,
        hovermode='closest',
    )

    return fig


def create_timeline_plotly(all_events_df, entity_id):
    """Create an interactive timeline for a single entity showing all event types."""
    entity_events = all_events_df[all_events_df['entity_id'] == entity_id].copy()

    if entity_events.empty:
        return go.Figure()

    entity_events['timestamp'] = pd.to_datetime(entity_events['timestamp'])
    entity_events = entity_events.sort_values('timestamp')

    event_colors = {
        "transaction": "#4a90d9",
        "call": "#27ae60",
        "sms": "#2ecc71",
        "ip_session": "#9b59b6",
    }

    fig = go.Figure()

    for event_type in ["transaction", "call", "sms", "ip_session"]:
        subset = entity_events[entity_events['event_type'] == event_type]
        if subset.empty:
            continue

        y_pos = {"transaction": 3, "call": 2, "sms": 1.5, "ip_session": 1}

        hover_texts = []
        sizes = []
        for _, row in subset.iterrows():
            if event_type == "transaction":
                amt = row.get('amount', 0)
                direction = "Credit" if amt > 0 else "Debit"
                hover = f"{direction}: ₹{abs(amt):,.0f}<br>To: {row.get('counterparty', 'N/A')}"
                sizes.append(max(5, min(abs(amt) / 5000, 20)))
            elif event_type in ["call", "sms"]:
                hover = f"To: {row.get('counterparty', 'N/A')}<br>Location: {row.get('location', 'N/A')}"
                sizes.append(8)
            else:
                hover = f"Location: {row.get('location', 'N/A')}<br>Dest: {row.get('counterparty', 'N/A')}"
                sizes.append(8)
            hover_texts.append(hover)

        fig.add_trace(go.Scatter(
            x=subset['timestamp'],
            y=[y_pos.get(event_type, 0)] * len(subset),
            mode='markers',
            marker=dict(size=sizes, color=event_colors.get(event_type, '#666'),
                        symbol='circle', line=dict(width=0.5, color='#2a2d35')),
            name=event_type.replace('_', ' ').title(),
            hovertext=hover_texts,
            hoverinfo='text+x',
        ))

    fig.update_layout(
        plot_bgcolor='#0c0e12',
        paper_bgcolor='#0c0e12',
        font=dict(color='#c0c0c0', size=11),
        xaxis=dict(title="Time", gridcolor='#1e222a', showgrid=True),
        yaxis=dict(
            tickvals=[1, 1.5, 2, 3],
            ticktext=["IP Session", "SMS", "Call", "Transaction"],
            gridcolor='#1e222a', showgrid=True,
        ),
        margin=dict(l=80, r=20, t=30, b=40),
        height=300,
        legend=dict(bgcolor='rgba(0,0,0,0)', font=dict(size=10)),
        hovermode='closest',
    )

    return fig
