"""
Report Chart Renderers
=======================
PNG figures embedded into the forensic .docx: the entity's unified timeline and
its money-flow neighbourhood.

Why matplotlib and not the Plotly figures the dashboard draws
-------------------------------------------------------------
`forensic_report.py` was written to call `fig.to_image()`, which routes through
kaleido. Kaleido works here, but it was measured at **~3.5 s per image and it does
not amortise** — recent versions drive a headless Chrome per render. Reports are
generated inside `run_pipeline(generate_reports=True)` for every HIGH/CRITICAL
entity; at 8 flagged entities x 2 figures that is ~56 s bolted onto a pipeline with
a hard sub-10-second budget.

The same figures render in **~0.1 s each** through matplotlib's Agg backend, in
process, with no browser. The requirement is a chart in the .docx, not Plotly
specifically, so the report path uses matplotlib and the interactive dashboard
keeps its Plotly/vis.js rendering. `generate_forensic_report` still accepts a
Plotly figure and will call `to_image()` on it if one is passed, so nothing is
lost — it simply is not the default.

Palette note: these figures land in a document that gets printed and filed, so
they are drawn light-on-white rather than in the dashboard's dark theme.
"""
import io
import math

import matplotlib

# Must be selected before pyplot is imported — reports are generated inside a
# FastAPI worker thread with no display and no main-thread GUI loop.
matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import FancyArrowPatch  # noqa: E402

# Print palette — dark ink on white, safe in greyscale photocopy.
INK = "#1a1d24"
MUTED = "#6b7280"
GRID = "#e3e6ea"
CREDIT = "#0f7b6c"     # money in
DEBIT = "#b3261e"      # money out
CALL = "#1f5eb8"
SESSION = "#7b3fb8"
WINDOW = "#f5a524"     # correlation band
LAYERING = "#d92d20"

LANE_Y = {"transaction": 2, "call": 1, "ip_session": 0}
LANE_LABEL = {
    "transaction": "Transactions",
    "call": "Calls / SMS",
    "ip_session": "IP Sessions",
}


def _fig_to_png(fig, dpi=150):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def _marker_size(amount, amounts):
    """Scale a transaction marker by amount, log-compressed and bounded."""
    if not amount or amount <= 0:
        return 30.0
    top = max(amounts) if amounts else amount
    if top <= 0:
        return 30.0
    ratio = math.log10(max(amount, 1)) / max(math.log10(max(top, 10)), 1)
    return 28.0 + 170.0 * max(0.0, min(ratio, 1.0))


def render_timeline_png(payload, title=None, width_in=7.4, height_in=3.1):
    """
    Draw one entity's unified timeline: three lanes on a shared time axis with the
    temporal correlation windows shaded behind the markers.

    Args:
        payload: output of correlation.temporal_join.build_timeline_payload
        title: optional heading drawn above the axes

    Returns:
        PNG bytes, or None if the entity has nothing to plot.
    """
    events = (payload or {}).get("events") or []
    if not events:
        return None

    fig, ax = plt.subplots(figsize=(width_in, height_in))

    # ---- correlation windows, drawn first so markers sit on top ----
    drawn_window_label = False
    for band in (payload.get("correlations") or [])[:200]:
        try:
            start = pd.Timestamp(band["start"])
            end = pd.Timestamp(band["end"])
        except (TypeError, ValueError, KeyError):
            continue
        is_tcs1 = band.get("kind") == "tcs1"
        ax.axvspan(
            start, end,
            color=WINDOW,
            alpha=0.26 if is_tcs1 else 0.12,
            lw=0,
            zorder=1,
            label=None if drawn_window_label else "_nolegend_",
        )
        if is_tcs1:
            ax.axvline(pd.Timestamp(band["centre"]), color=WINDOW, lw=0.9,
                       alpha=0.75, zorder=2)
        drawn_window_label = True

    txn_amounts = [e["amount"] for e in events
                   if e["lane"] == "transaction" and e.get("amount")]

    lanes_present = set()
    for lane in ("transaction", "call", "ip_session"):
        subset = [e for e in events if e["lane"] == lane]
        if not subset:
            continue
        lanes_present.add(lane)
        xs, ys, sizes, colours, edges, widths = [], [], [], [], [], []
        for event in subset:
            try:
                xs.append(pd.Timestamp(event["t"]))
            except (TypeError, ValueError):
                continue
            ys.append(LANE_Y[lane])
            if lane == "transaction":
                sizes.append(_marker_size(event.get("amount"), txn_amounts))
                colours.append(CREDIT if event.get("direction") == "credit" else DEBIT)
            elif lane == "call":
                sizes.append(46)
                colours.append(CALL)
            else:
                sizes.append(46)
                colours.append(SESSION)
            # A row a rule actually cited gets a dark ring — that is the difference
            # between "an event happened" and "this is the evidence".
            if event.get("cited"):
                edges.append(INK)
                widths.append(1.5)
            else:
                edges.append("white")
                widths.append(0.6)

        ax.scatter(xs, ys, s=sizes, c=colours, edgecolors=edges, linewidths=widths,
                   zorder=4, alpha=0.92)

    # IP sessions have real duration — draw it rather than pretending it is a point.
    for event in events:
        if event["lane"] != "ip_session" or not event.get("t_end"):
            continue
        try:
            start, end = pd.Timestamp(event["t"]), pd.Timestamp(event["t_end"])
        except (TypeError, ValueError):
            continue
        if end > start:
            ax.plot([start, end], [LANE_Y["ip_session"]] * 2,
                    color=SESSION, lw=2.4, alpha=0.45, solid_capstyle="round", zorder=3)

    ordered = [l for l in ("ip_session", "call", "transaction") if l in lanes_present]
    ax.set_yticks([LANE_Y[l] for l in ordered])
    ax.set_yticklabels([LANE_LABEL[l] for l in ordered], fontsize=8.5, color=INK)
    ax.set_ylim(-0.6, 2.6)

    ax.grid(axis="x", color=GRID, lw=0.7, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(axis="x", labelsize=7.5, colors=MUTED, length=3)
    ax.tick_params(axis="y", length=0)

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%H:%M"))
    fig.autofmt_xdate(rotation=0, ha="center")

    legend_items = []
    if "transaction" in lanes_present:
        legend_items += [
            Line2D([], [], marker="o", ls="", color=CREDIT, markersize=6, label="Credit (in)"),
            Line2D([], [], marker="o", ls="", color=DEBIT, markersize=6, label="Debit (out)"),
        ]
    if "call" in lanes_present:
        legend_items.append(Line2D([], [], marker="o", ls="", color=CALL, markersize=6, label="Call / SMS"))
    if "ip_session" in lanes_present:
        legend_items.append(Line2D([], [], marker="o", ls="", color=SESSION, markersize=6, label="IP session"))
    if payload.get("correlations"):
        legend_items.append(
            Line2D([], [], marker="s", ls="", color=WINDOW, alpha=0.5, markersize=7,
                   label=f"±{payload.get('window_minutes', 10)} min correlation window")
        )
    if payload.get("flagged_row_refs"):
        legend_items.append(
            Line2D([], [], marker="o", ls="", markerfacecolor="white", markeredgecolor=INK,
                   markeredgewidth=1.4, markersize=6, label="Cited as evidence")
        )
    if legend_items:
        ax.legend(handles=legend_items, loc="upper left", bbox_to_anchor=(0, -0.30),
                  ncol=3, frameon=False, fontsize=7.2, handletextpad=0.4,
                  columnspacing=1.3, labelcolor=INK)

    if title:
        ax.set_title(title, fontsize=9.5, color=INK, pad=8, loc="left")

    return _fig_to_png(fig)


def _ego_subgraph(network_graph, entity_id, max_neighbours=10):
    """The focus entity plus its heaviest direct counterparties."""
    neighbours = set()
    if network_graph.has_node(entity_id):
        neighbours.update(network_graph.predecessors(entity_id))
        neighbours.update(network_graph.successors(entity_id))
    neighbours.discard(entity_id)

    def edge_weight(other):
        total = 0.0
        for u, v in ((entity_id, other), (other, entity_id)):
            if network_graph.has_edge(u, v):
                total += float(network_graph[u][v].get("weight", 0) or 0)
        return total

    ranked = sorted(neighbours, key=edge_weight, reverse=True)[:max_neighbours]
    return [entity_id] + ranked, len(neighbours) - len(ranked)


def render_money_flow_png(network_graph, scored_entities, entity_id,
                           layering_hops=None, width_in=7.4, height_in=4.3):
    """
    Draw the money-flow neighbourhood around one entity: who paid it, who it paid,
    how much, and which hops sit on a detected layering chain.

    Amounts are taken straight from the de-duplicated graph, so an edge here reads
    the same rupee figure as the bank statement behind it.

    Returns PNG bytes, or None when the entity has no counterparties to draw.
    """
    if network_graph is None or not network_graph.has_node(entity_id):
        return None

    nodes, hidden = _ego_subgraph(network_graph, entity_id)
    if len(nodes) < 2:
        return None

    layering_hops = layering_hops or set()

    # Focus entity centred, counterparties on a ring around it.
    positions = {entity_id: (0.0, 0.0)}
    others = nodes[1:]
    for i, node in enumerate(others):
        angle = 2 * math.pi * i / max(len(others), 1) - math.pi / 2
        positions[node] = (math.cos(angle), math.sin(angle) * 0.82)

    tier_colour = {
        "CRITICAL": "#b3261e", "HIGH": "#c2610a",
        "MEDIUM": "#a37500", "LOW": "#5f6b7a",
    }

    fig, ax = plt.subplots(figsize=(width_in, height_in))
    ax.set_axis_off()

    seen = set()
    for u in nodes:
        for v in nodes:
            if u == v or (u, v) in seen or not network_graph.has_edge(u, v):
                continue
            seen.add((u, v))
            data = network_graph[u][v]
            is_txn = data.get("edge_type") == "transaction"
            weight = float(data.get("weight", 0) or 0)
            on_chain = (u, v) in layering_hops

            if on_chain:
                colour, lw, alpha = LAYERING, 2.6, 0.95
            elif is_txn:
                colour, lw, alpha = "#3d5a8a", 1.5, 0.65
            else:
                colour, lw, alpha = MUTED, 1.0, 0.4

            x0, y0 = positions[u]
            x1, y1 = positions[v]
            ax.add_patch(FancyArrowPatch(
                (x0, y0), (x1, y1),
                connectionstyle="arc3,rad=0.14",
                arrowstyle="-|>", mutation_scale=11,
                color=colour, lw=lw, alpha=alpha,
                linestyle="-" if is_txn else (0, (3, 2)),
                shrinkA=13, shrinkB=13, zorder=2,
            ))

            if is_txn and weight > 0:
                mx, my = (x0 + x1) / 2, (y0 + y1) / 2
                ax.text(mx, my + 0.06, f"₹{weight:,.0f}",
                        fontsize=6.4, ha="center", va="center",
                        color=LAYERING if on_chain else INK,
                        fontweight="bold" if on_chain else "normal",
                        bbox=dict(boxstyle="round,pad=0.16", fc="white",
                                  ec="none", alpha=0.82), zorder=5)

    for node in nodes:
        x, y = positions[node]
        tier = scored_entities.get(node, {}).get("risk_tier", "LOW")
        is_focus = node == entity_id
        ax.scatter([x], [y],
                   s=520 if is_focus else 260,
                   c=tier_colour.get(tier, "#5f6b7a"),
                   edgecolors=INK if is_focus else "white",
                   linewidths=1.8 if is_focus else 0.9,
                   zorder=4)
        ax.text(x, y, node.replace("ENT_", "E"), fontsize=6.8 if is_focus else 6.0,
                ha="center", va="center", color="white",
                fontweight="bold", zorder=6)
        if tier != "LOW":
            ax.text(x, y - (0.17 if is_focus else 0.13), tier,
                    fontsize=5.6, ha="center", va="top", color=tier_colour.get(tier, MUTED),
                    fontweight="bold", zorder=6)

    ax.set_xlim(-1.35, 1.35)
    ax.set_ylim(-1.25, 1.2)

    caption = f"Money-flow neighbourhood of {entity_id} — {len(nodes) - 1} direct counterparties"
    if hidden > 0:
        caption += f" ({hidden} lower-value counterparties not drawn)"
    ax.set_title(caption, fontsize=9, color=INK, pad=6, loc="left")

    legend_items = [
        Line2D([], [], color="#3d5a8a", lw=1.5, label="Transfer (amount labelled)"),
        Line2D([], [], color=MUTED, lw=1.0, ls="--", label="Call / SMS contact"),
    ]
    if any((u, v) in layering_hops for u, v in seen):
        legend_items.append(Line2D([], [], color=LAYERING, lw=2.6, label="LAY-1 layering chain hop"))
    ax.legend(handles=legend_items, loc="lower center", bbox_to_anchor=(0.5, -0.09),
              ncol=3, frameon=False, fontsize=7, labelcolor=INK)

    return _fig_to_png(fig)


def extract_layering_hops(scored_entities):
    """
    Recover the exact hops of every detected layering chain from the LAY-1
    evidence token ("chain:ENT_A>ENT_B>ENT_C").

    Reading the emitted chain — rather than joining every pair of LAY-1 entities —
    lights the path that was actually walked, including hops through a member that
    did not fire the rule itself.
    """
    hops = set()
    for data in (scored_entities or {}).values():
        for token in (data.get("evidence", {}) or {}).get("LAY-1", []) or []:
            if isinstance(token, str) and token.startswith("chain:"):
                path = [p for p in token[len("chain:"):].split(">") if p]
                hops.update(zip(path, path[1:]))
    return hops
