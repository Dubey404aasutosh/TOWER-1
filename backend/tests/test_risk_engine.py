"""
Unit Tests for Risk Engine Gated Decision Tree
===============================================
Verifies that:
- A lone LOW-severity IDR-1 firing does NOT produce CRITICAL or HIGH tier (returns LOW).
- A lone MEDIUM-severity IDR-1 firing returns MEDIUM tier.
- A lone HIGH-severity IDR-1 firing returns HIGH tier.
- CRITICAL tier requires corroboration (e.g. MUL-1 + TCS-1, LAY-1 + IDR-1, or HIGH IDR-1 + 2nd rule).
"""
import sys
import unittest
from pathlib import Path

# Add backend to path
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scoring.risk_engine import compute_risk_tier


class TestRiskEngine(unittest.TestCase):

    def test_lone_low_idr1_does_not_produce_critical(self):
        """Assert that a lone LOW-severity IDR-1 (routine SIM upgrade) returns LOW tier and NEVER CRITICAL."""
        tier = compute_risk_tier(["IDR-1"], {"IDR-1": "LOW"})
        self.assertNotEqual(tier, "CRITICAL", "Lone LOW-severity IDR-1 must NEVER produce CRITICAL tier.")
        self.assertEqual(tier, "LOW", "Lone LOW-severity IDR-1 should produce LOW tier.")

    def test_lone_medium_idr1_returns_medium(self):
        """Assert that a lone MEDIUM-severity IDR-1 returns MEDIUM tier."""
        tier = compute_risk_tier(["IDR-1"], {"IDR-1": "MEDIUM"})
        self.assertNotEqual(tier, "CRITICAL")
        self.assertEqual(tier, "MEDIUM")

    def test_lone_high_idr1_returns_high(self):
        """Assert that a lone HIGH-severity IDR-1 returns HIGH tier."""
        tier = compute_risk_tier(["IDR-1"], {"IDR-1": "HIGH"})
        self.assertNotEqual(tier, "CRITICAL")
        self.assertEqual(tier, "HIGH")

    def test_corroborated_idr1_returns_critical(self):
        """Assert that LAY-1 + IDR-1 or HIGH IDR-1 + 2nd rule returns CRITICAL tier."""
        tier1 = compute_risk_tier(["LAY-1", "IDR-1"], {"IDR-1": "HIGH"})
        self.assertEqual(tier1, "CRITICAL")

        tier2 = compute_risk_tier(["MUL-1", "TCS-1"])
        self.assertEqual(tier2, "CRITICAL")

    def test_single_money_pattern_returns_high(self):
        """Assert that a single money-pattern rule (MUL-1, LAY-1, STR-1) alone returns HIGH tier."""
        self.assertEqual(compute_risk_tier(["MUL-1"]), "HIGH")
        self.assertEqual(compute_risk_tier(["LAY-1"]), "HIGH")
        self.assertEqual(compute_risk_tier(["STR-1"]), "HIGH")


if __name__ == "__main__":
    unittest.main()
