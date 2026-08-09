"""
Surat/Gujarat Map Builder for E-Rakshak
=========================================
Interactive Plotly Scattermapbox showing cell tower locations,
event heatmap, call paths, and risk-coded markers.
Uses OpenStreetMap (no API key needed).
"""
import plotly.graph_objects as go
import pandas as pd


# ================================================================
# CELL TOWER COORDINATES (realistic positions across Surat zones)
# ================================================================
CELL_TOWERS = {
    # Surat towers
    "SRT-T01": {"lat": 21.1702, "lon": 72.8311, "area": "Athwa Gate", "city": "Surat"},
    "SRT-T02": {"lat": 21.1860, "lon": 72.7933, "area": "Adajan", "city": "Surat"},
    "SRT-T03": {"lat": 21.2148, "lon": 72.8470, "area": "Katargam", "city": "Surat"},
    "SRT-T04": {"lat": 21.1565, "lon": 72.7710, "area": "Vesu", "city": "Surat"},
    "SRT-T05": {"lat": 21.2050, "lon": 72.8630, "area": "Varachha", "city": "Surat"},
    "SRT-T06": {"lat": 21.1980, "lon": 72.8150, "area": "Ring Road", "city": "Surat"},
    "SRT-T07": {"lat": 21.1690, "lon": 72.7880, "area": "Piplod", "city": "Surat"},
    "SRT-T08": {"lat": 21.1780, "lon": 72.8550, "area": "Udhna", "city": "Surat"},
    "SRT-T09": {"lat": 21.1450, "lon": 72.7650, "area": "Dumas Road", "city": "Surat"},
    "SRT-T10": {"lat": 21.2280, "lon": 72.8380, "area": "Sachin GIDC", "city": "Surat"},
    # Ahmedabad towers
    "AMD-T01": {"lat": 23.0225, "lon": 72.5714, "area": "SG Highway", "city": "Ahmedabad"},
    "AMD-T02": {"lat": 23.0396, "lon": 72.5660, "area": "Vastrapur", "city": "Ahmedabad"},
    "AMD-T03": {"lat": 23.0126, "lon": 72.5827, "area": "Navrangpura", "city": "Ahmedabad"},
    # Mumbai towers
    "MUM-T01": {"lat": 19.0760, "lon": 72.8777, "area": "Andheri", "city": "Mumbai"},
    "MUM-T02": {"lat": 19.0176, "lon": 72.8562, "area": "Dadar", "city": "Mumbai"},
    "MUM-T03": {"lat": 19.0896, "lon": 72.8656, "area": "Goregaon", "city": "Mumbai"},
    "MUM-T04": {"lat": 18.9696, "lon": 72.8199, "area": "Colaba", "city": "Mumbai"},
    # Delhi towers
    "DEL-T01": {"lat": 28.6139, "lon": 77.2090, "area": "Connaught Place", "city": "Delhi"},
    "DEL-T02": {"lat": 28.5672, "lon": 77.2100, "area": "Saket", "city": "Delhi"},
    "DEL-T03": {"lat": 28.6328, "lon": 77.2197, "area": "Karol Bagh", "city": "Delhi"},
    # Bangalore towers
    "BLR-T01": {"lat": 12.9716, "lon": 77.5946, "area": "MG Road", "city": "Bangalore"},
    "BLR-T02": {"lat": 12.9352, "lon": 77.6245, "area": "Koramangala", "city": "Bangalore"},
    "BLR-T03": {"lat": 13.0206, "lon": 77.5650, "area": "Rajajinagar", "city": "Bangalore"},
    # Pune towers
    "PNE-T01": {"lat": 18.5204, "lon": 73.8567, "area": "Shivajinagar", "city": "Pune"},
    "PNE-T02": {"lat": 18.5074, "lon": 73.8077, "area": "Hinjawadi", "city": "Pune"},
    # Hyderabad towers
    "HYD-T01": {"lat": 17.3850, "lon": 78.4867, "area": "HITEC City", "city": "Hyderabad"},
    "HYD-T02": {"lat": 17.4065, "lon": 78.4772, "area": "Banjara Hills", "city": "Hyderabad"},
    # Chennai towers
    "CHE-T01": {"lat": 13.0827, "lon": 80.2707, "area": "T. Nagar", "city": "Chennai"},
    "CHE-T02": {"lat": 13.0569, "lon": 80.2425, "area": "Guindy", "city": "Chennai"},
}

# City name -> IP prefix mapping (for location from IPDR)
CITY_FROM_IP = {
    "103.21": "Mumbai",
    "103.22": "Delhi",
    "103.23": "Bangalore",
    "103.24": "Ahmedabad",
    "103.25": "Surat",
    "103.26": "Pune",
    "103.27": "Hyderabad",
    "103.28": "Chennai",
}


def _resolve_tower(cell_id):
    """Return tower info dict if cell_id matches a known tower."""
    if not cell_id or pd.isna(cell_id):
        return None
    cell_str = str(cell_id).strip()
    # Direct match
    if cell_str in CELL_TOWERS:
        return CELL_TOWERS[cell_str]
    # Prefix match (e.g. "SRT" -> pick first SRT tower)
    for tid, info in CELL_TOWERS.items():
        if cell_str.upper().startswith(tid.split("-")[0]):
            return info
    return None


def _resolve_location_to_city(location_str):
    """Resolve a location string (city name or cell ID) to city name."""
    if not location_str or pd.isna(location_str):
        return None
    loc = str(location_str).strip()
    # Direct city name
    for city in ["Mumbai", "Delhi", "Bangalore", "Ahmedabad", "Surat", "Pune", "Hyderabad", "Chennai"]:
        if city.lower() in loc.lower():
            return city
    # Cell ID prefix
    prefix_map = {"MUM": "Mumbai", "DEL": "Delhi", "BLR": "Bangalore", "AMD": "Ahmedabad",
                  "SRT": "Surat", "PNE": "Pune", "HYD": "Hyderabad", "CHE": "Chennai"}
    for prefix, city in prefix_map.items():
        if loc.upper().startswith(prefix):
            return city
    return None


def _get_default_tower_for_city(city):
    """Get the first tower for a given city."""
    for tid, info in CELL_TOWERS.items():
        if info["city"] == city:
            return tid, info
    return None, None


def create_surat_map(all_events_df, scored_entities, entities, selected_entities=None):
    """
    Create an interactive Surat-focused map with cell towers and event markers.

    Args:
        all_events_df: DataFrame of all events
        scored_entities: risk scoring results
        entities: resolved entity dict
        selected_entities: optional list of entity IDs to filter

    Returns:
        plotly Figure
    """
    fig = go.Figure()

    tier_colors = {
        "CRITICAL": "#ff2d2d",
        "HIGH": "#ff8c00",
        "MEDIUM": "#ffd700",
        "LOW": "#2ecc71",
    }

    # ---- 1. PLOT ALL CELL TOWERS ----
    tower_lats = []
    tower_lons = []
    tower_texts = []
    tower_ids = []

    for tid, info in CELL_TOWERS.items():
        if info["city"] == "Surat":
            tower_lats.append(info["lat"])
            tower_lons.append(info["lon"])
            tower_texts.append(f"🗼 {tid}<br>{info['area']}, {info['city']}")
            tower_ids.append(tid)

    # Tower markers
    fig.add_trace(go.Scattermapbox(
        lat=tower_lats, lon=tower_lons,
        mode='markers+text',
        marker=dict(size=14, color="#4a90d9", symbol="circle",
                    opacity=0.9),
        text=[t.split("<br>")[1] for t in tower_texts],
        textposition="top center",
        textfont=dict(size=9, color="#c0c0c0"),
        hovertext=tower_texts, hoverinfo='text',
        name='📡 Cell Towers',
    ))

    # Tower range circles (approximate 1.5km radius as ~0.013 deg) - BUNDLED into 1 trace for performance
    import math
    circle_lats = []
    circle_lons = []
    for tid, info in CELL_TOWERS.items():
        if info["city"] != "Surat":
            continue
        for angle in range(0, 361, 15):
            rad = math.radians(angle)
            circle_lats.append(info["lat"] + 0.012 * math.sin(rad))
            circle_lons.append(info["lon"] + 0.012 * math.cos(rad))
        circle_lats.append(None)
        circle_lons.append(None)

    fig.add_trace(go.Scattermapbox(
        lat=circle_lats, lon=circle_lons,
        mode='lines',
        line=dict(width=1, color="rgba(74, 144, 217, 0.18)"),
        hoverinfo='skip',
        showlegend=False,
    ))

    # ---- 2. PLOT EVENTS ON TOWERS ----
    if not all_events_df.empty:
        events_to_plot = all_events_df.copy()
        if selected_entities:
            events_to_plot = events_to_plot[events_to_plot['entity_id'].isin(selected_entities)]

        # Group events by location -> tower
        event_markers = {}  # tower_id -> list of event info
        call_paths = []     # (tower1_id, tower2_id, entity_id, tier)

        for _, row in events_to_plot.iterrows():
            loc = row.get('location')
            if pd.isna(loc) or not loc:
                continue

            tower_info = _resolve_tower(loc)
            if not tower_info:
                city = _resolve_location_to_city(loc)
                if city:
                    _, tower_info = _get_default_tower_for_city(city)

            if not tower_info:
                continue

            eid = row.get('entity_id', '')
            tier = scored_entities.get(eid, {}).get('risk_tier', 'LOW')
            evt_type = row.get('event_type', '')

            tid_key = f"{tower_info['lat']}_{tower_info['lon']}"
            if tid_key not in event_markers:
                event_markers[tid_key] = {
                    "lat": tower_info["lat"], "lon": tower_info["lon"],
                    "area": tower_info.get("area", ""),
                    "events": [], "highest_tier": "LOW", "tiers": {}
                }

            event_markers[tid_key]["events"].append({
                "entity": eid, "type": evt_type, "tier": tier,
                "time": str(row.get('timestamp', '')),
            })
            event_markers[tid_key]["tiers"][tier] = event_markers[tid_key]["tiers"].get(tier, 0) + 1

            # Track highest tier
            tier_rank = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
            if tier_rank.get(tier, 0) > tier_rank.get(event_markers[tid_key]["highest_tier"], 0):
                event_markers[tid_key]["highest_tier"] = tier

            # Build call paths for CDR events
            if evt_type in ['call', 'sms']:
                cp = str(row.get('counterparty', '')).strip()
                if cp:
                    for cp_eid, cp_data in entities.items():
                        if cp in cp_data.get("phones", []):
                            # Find counterparty's events to get their tower
                            cp_events = all_events_df[
                                (all_events_df['entity_id'] == cp_eid) &
                                (all_events_df['location'].notna())
                            ]
                            if not cp_events.empty:
                                cp_loc = cp_events.iloc[0]['location']
                                cp_tower = _resolve_tower(cp_loc)
                                if not cp_tower:
                                    cp_city = _resolve_location_to_city(cp_loc)
                                    if cp_city:
                                        _, cp_tower = _get_default_tower_for_city(cp_city)
                                if cp_tower and cp_tower != tower_info:
                                    call_paths.append((tower_info, cp_tower, eid, tier))
                            break

        # Plot event heatmap dots on towers (with jitter for density)
        for tid_key, mdata in event_markers.items():
            count = len(mdata["events"])
            tier = mdata["highest_tier"]
            color = tier_colors.get(tier, "#2ecc71")

            tier_summary = " | ".join([f"{t}: {c}" for t, c in mdata["tiers"].items()])
            hover = (f"📍 {mdata['area']}<br>"
                     f"Events: {count}<br>"
                     f"Risk: {tier_summary}<br>"
                     f"Entities: {len(set(e['entity'] for e in mdata['events']))}")

            fig.add_trace(go.Scattermapbox(
                lat=[mdata["lat"] + 0.002],
                lon=[mdata["lon"] + 0.002],
                mode='markers',
                marker=dict(
                    size=max(10, min(count * 2, 30)),
                    color=color,
                    opacity=0.7,
                ),
                hovertext=hover, hoverinfo='text',
                showlegend=False,
            ))

        # ---- 3. CALL PATH LINES (Bundled by tier color to avoid Plotly lag) ----
        paths_by_tier = {t: {"lats": [], "lons": []} for t in tier_colors}
        seen_paths = set()
        for t1, t2, eid, tier in call_paths:
            path_key = (t1["lat"], t1["lon"], t2["lat"], t2["lon"])
            if path_key in seen_paths:
                continue
            seen_paths.add(path_key)

            paths_by_tier[tier]["lats"].extend([t1["lat"], t2["lat"], None])
            paths_by_tier[tier]["lons"].extend([t1["lon"], t2["lon"], None])

        for tier, coords in paths_by_tier.items():
            if not coords["lats"]:
                continue
            fig.add_trace(go.Scattermapbox(
                lat=coords["lats"], lon=coords["lons"],
                mode='lines',
                line=dict(width=2, color=tier_colors[tier]),
                opacity=0.5,
                hoverinfo='skip',
                showlegend=False,
            ))

    # ---- LAYOUT ----
    fig.update_layout(
        mapbox=dict(
            style="carto-darkmatter",
            center=dict(lat=21.1800, lon=72.8300),  # Surat center
            zoom=12,
        ),
        paper_bgcolor='#0c0e12',
        plot_bgcolor='#0c0e12',
        font=dict(color='#c0c0c0'),
        margin=dict(l=0, r=0, t=0, b=0),
        height=600,
        legend=dict(
            bgcolor='rgba(20, 23, 30, 0.9)',
            bordercolor='#1e222a',
            borderwidth=1,
            font=dict(size=11, color='#c0c0c0'),
            x=0.01, y=0.99,
        ),
        showlegend=True,
    )

    return fig


def create_india_overview_map(all_events_df, scored_entities, entities):
    """
    Create a broader India-level map showing inter-city connections.
    """
    fig = go.Figure()

    tier_colors = {
        "CRITICAL": "#ff2d2d", "HIGH": "#ff8c00",
        "MEDIUM": "#ffd700", "LOW": "#2ecc71",
    }

    # City-level event aggregation
    city_events = {}
    if not all_events_df.empty:
        for _, row in all_events_df.iterrows():
            loc = row.get('location')
            if pd.isna(loc) or not loc:
                continue
            city = _resolve_location_to_city(loc)
            if not city:
                continue
            if city not in city_events:
                city_events[city] = {"count": 0, "highest_tier": "LOW", "entities": set()}

            eid = row.get('entity_id', '')
            tier = scored_entities.get(eid, {}).get('risk_tier', 'LOW')
            city_events[city]["count"] += 1
            city_events[city]["entities"].add(eid)

            tier_rank = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
            if tier_rank.get(tier, 0) > tier_rank.get(city_events[city]["highest_tier"], 0):
                city_events[city]["highest_tier"] = tier

    # Plot city markers
    for city, data in city_events.items():
        tid, info = _get_default_tower_for_city(city)
        if not info:
            continue

        color = tier_colors.get(data["highest_tier"], "#2ecc71")
        fig.add_trace(go.Scattermapbox(
            lat=[info["lat"]], lon=[info["lon"]],
            mode='markers+text',
            marker=dict(
                size=max(12, min(data["count"], 40)),
                color=color, opacity=0.8,
            ),
            text=[city],
            textposition="top center",
            textfont=dict(size=11, color="#e0e0e0"),
            hovertext=f"🏙️ {city}<br>Events: {data['count']}<br>Entities: {len(data['entities'])}<br>Risk: {data['highest_tier']}",
            hoverinfo='text',
            name=city,
            showlegend=False,
        ))

    fig.update_layout(
        mapbox=dict(
            style="carto-darkmatter",
            center=dict(lat=21.5, lon=76.0),  # India center
            zoom=4.5,
        ),
        paper_bgcolor='#0c0e12',
        plot_bgcolor='#0c0e12',
        font=dict(color='#c0c0c0'),
        margin=dict(l=0, r=0, t=0, b=0),
        height=450,
        showlegend=False,
    )

    return fig
