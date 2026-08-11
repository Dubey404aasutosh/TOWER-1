"""
API Regression Tests — /api/results network payload
====================================================
Guards S1.4 and S1.5.

S1.4: /api/results used to serialise the IDENTITY graph (raw identifiers linked by
KYC ownership, ~1,500 isolated dots, zero money flow) under the key "network", while
the money-flow DiGraph built by build_network_graph — entities joined by weighted
transfer and call edges — was computed every run and thrown away. These tests assert
the default view is the money-flow graph and that the identity graph is still
reachable behind the toggle.

S1.5: rule_severities was dropped when the risk engine assembled its output, so the
UI could never explain why two entities with the same rule list scored differently.
"""
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient

import main


@pytest.fixture(scope="module")
def results():
    """Run the pipeline once through the real API and reuse the payload."""
    with TestClient(main.app) as client:
        resp = client.get("/api/results")
        if resp.status_code == 409:
            run_resp = client.post("/api/run-pipeline")
            if run_resp.status_code != 200:
                pytest.skip("No dataset loaded to test network endpoints")
            resp = client.get("/api/results")
        if resp.status_code != 200 or resp.json().get("metrics", {}).get("total_entities", 0) == 0:
            pytest.skip("No entity dataset loaded to test network endpoints")
        return resp.json()


# ============================================================
# S1.4 — the default network view is the money-flow graph
# ============================================================
def test_both_network_views_are_served(results):
    assert "network_views" in results
    assert set(results["network_views"]) == {"money_flow", "identity"}


def test_default_network_is_money_flow_not_identity(results):
    """The regression: `network` used to be the identity graph."""
    default = results["network"]
    money = results["network_views"]["money_flow"]

    assert default["meta"]["kind"] == "money_flow"
    assert len(default["nodes"]) == len(money["nodes"])

    # Money-flow nodes are resolved entities carrying a risk tier. Identity nodes are
    # bare identifiers (a phone number, an account number) — they have no value flow.
    for node in default["nodes"][:20]:
        assert "risk_tier" in node
        assert "value_in" in node and "value_out" in node


def test_money_flow_edges_carry_direction_and_weight(results):
    edges = results["network_views"]["money_flow"]["edges"]
    assert edges, "money-flow graph has no edges"

    txn = [e for e in edges if e["edge_type"] == "transaction"]
    assert txn, "no transaction edges — this is supposed to be a money-flow graph"

    for e in txn[:20]:
        assert e["arrows"]["to"]["enabled"] is True, "money flow must be directed"
        assert e["amount"] > 0
        assert e["width"] > 0


def test_isolated_entities_are_excluded_not_drawn_as_dots(results):
    """Entities with no edges and no risk are not rendered.

    The identity graph's ~1,200 unconnected identifiers are what made the old view
    unreadable. Every rendered node must either carry an edge or be flagged.
    """
    view = results["network_views"]["money_flow"]
    meta = view["meta"]

    assert meta["rendered_nodes"] < meta["total_nodes"]
    assert meta["hidden_isolated_nodes"] > 0

    endpoints = set()
    for e in view["edges"]:
        endpoints.add(e["from"])
        endpoints.add(e["to"])

    for node in view["nodes"]:
        assert node["id"] in endpoints or node["risk_tier"] != "LOW", (
            f"{node['id']} is an unconnected LOW entity and should not be drawn"
        )


def test_identity_view_is_still_available(results):
    """The identity graph is a genuine second story and must stay reachable."""
    identity = results["network_views"]["identity"]
    assert identity["meta"]["kind"] == "identity"
    assert identity["nodes"], "identity view lost its nodes"
    # Identifier-level nodes, not entity-level.
    assert any(not n["id"].startswith("ENT_") for n in identity["nodes"])


def test_layering_hops_are_highlighted_when_lay1_fires(results):
    """Every hop of a detected LAY-1 chain is marked, including hops through a
    chain member that did not itself fire the rule."""
    view = results["network_views"]["money_flow"]
    suspects = results["suspects"]

    chains = []
    for s in suspects:
        for token in s.get("evidence", {}).get("LAY-1", []) or []:
            if isinstance(token, str) and token.startswith("chain:"):
                chains.append([p for p in token[len("chain:"):].split(">") if p])

    if not chains:
        pytest.skip("LAY-1 did not fire on this dataset")

    expected_hops = set()
    for path in chains:
        expected_hops.update(zip(path, path[1:]))

    highlighted = {(e["from"], e["to"]) for e in view["edges"]
                   if e["edge_class"] == "layering"}
    assert expected_hops <= highlighted, (
        f"hops not highlighted: {expected_hops - highlighted}"
    )

    # And the chain must be the heaviest stroke on the canvas, or it cannot be found.
    lay_widths = [e["width"] for e in view["edges"] if e["edge_class"] == "layering"]
    other_widths = [e["width"] for e in view["edges"] if e["edge_class"] != "layering"]
    assert min(lay_widths) >= max(other_widths)


def test_transfer_amounts_are_not_double_counted(results):
    """One transfer between two ingested statements is one edge weight, not two.

    Both parties' statements record the same movement — the sender as a debit, the
    receiver as a credit, under different UTRs. Summing both doubled every edge where
    both sides had been ingested.
    """
    view = results["network_views"]["money_flow"]
    suspects = {s["entity_id"]: s for s in results["suspects"]}

    lay = [s for s in suspects.values() if "LAY-1" in s.get("rules_fired", [])]
    if not lay:
        pytest.skip("LAY-1 did not fire on this dataset")

    # The LAY-1 explanation lists the amount of each hop, read straight off the
    # transaction rows. The graph edge for that hop must agree.
    longest = max(lay, key=lambda s: len(s["evidence"].get("LAY-1", [])))
    chain_token = next(t for t in longest["evidence"]["LAY-1"] if t.startswith("chain:"))
    path = [p for p in chain_token[len("chain:"):].split(">") if p]

    edge_by_pair = {(e["from"], e["to"]): e for e in view["edges"]}
    hop_amounts = [edge_by_pair[(a, b)]["amount"]
                   for a, b in zip(path, path[1:]) if (a, b) in edge_by_pair]

    assert hop_amounts, "no graph edges found for the detected chain"
    # A layering chain loses value at every hop. Doubling one side's rows breaks that
    # monotonic decrease, so this is a direct check on the de-duplication.
    for earlier, later in zip(hop_amounts, hop_amounts[1:]):
        assert later < earlier, (
            f"chain amounts are not decreasing: {hop_amounts} — "
            f"an edge is likely counting both sides of the same transfer"
        )


# ============================================================
# S1.5 — CRITICAL is reachable, and severities reach the API
# ============================================================
def test_critical_tier_is_reachable(results):
    """CRITICAL requires LAY-1 or MUL-1 corroborated by another rule. Before S1.1
    LAY-1 fired zero times, so the tier was structurally unreachable."""
    assert results["metrics"]["critical_count"] > 0, "no entity reached CRITICAL"

    critical = [s for s in results["suspects"] if s["risk_tier"] == "CRITICAL"]
    assert critical

    for s in critical:
        assert len(s["rules_fired"]) >= 2, (
            f"{s['entity_id']} is CRITICAL on a single rule — the tier is gated on "
            f"corroboration: {s['rules_fired']}"
        )


def test_rule_severities_reach_the_api(results):
    """risk_engine used to drop rule_severities when assembling its output."""
    flagged = [s for s in results["suspects"] if s["rules_fired"]]
    assert flagged

    for s in flagged:
        assert "rule_severities" in s
        # Every fired rule is graded.
        for rule in s["rules_fired"]:
            assert rule in s["rule_severities"], (
                f"{s['entity_id']} fired {rule} with no severity recorded"
            )


def test_every_fired_rule_has_an_explanation(results):
    """A tier is only defensible if each contributing rule can be read back."""
    for s in results["suspects"]:
        for rule in s["rules_fired"]:
            assert s["explanations"].get(rule), f"{s['entity_id']}/{rule} has no explanation"
            assert s["evidence"].get(rule), f"{s['entity_id']}/{rule} has no evidence rows"
