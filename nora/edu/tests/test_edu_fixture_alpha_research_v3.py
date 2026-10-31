import ast
import hashlib
import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from backend.analys.alpha.code.compile import compile_code


ROOT = Path(__file__).resolve().parents[3]
ALPHA_DIR = ROOT / "nora/edu/data/alpha/user"
BASELINE = ROOT / "nora/check/edu_alpha_baseline_results.json"
MANIFEST = ROOT / "nora/check/candidates/edu_alpha_27_research_v3_20261028.json"


def _stress_bars(size: int = 3000) -> pd.DataFrame:
    rng = np.random.default_rng(20261028)
    returns = rng.normal(0.0, 0.004, size)
    close = 60_000.0 * np.exp(np.cumsum(returns))
    open_price = np.r_[close[0], close[:-1]] * (1.0 + rng.normal(0.0, 0.012, size))
    high = np.maximum(open_price, close) * (1.0 + rng.uniform(0.0, 0.006, size))
    low = np.minimum(open_price, close) * (1.0 - rng.uniform(0.0, 0.006, size))
    return pd.DataFrame(
        {
            "open_time": np.arange(size, dtype="int64") * 3_600_000,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.lognormal(6.0, 1.0, size),
        }
    )


class EduFixtureAlphaResearchV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        cls.target_ids = set(baseline["blocked_records"])
        cls.records = {
            record["id"]: record
            for path in ALPHA_DIR.glob("*.json")
            for record in [json.loads(path.read_text(encoding="utf-8"))]
        }
        cls.targets = [cls.records[alpha_id] for alpha_id in sorted(cls.target_ids)]
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_inventory_compile_and_audit_hashes(self):
        self.assertEqual(len(self.records), 57)
        self.assertEqual(len(self.target_ids), 27)
        self.assertEqual(set(self.manifest["results"][i]["alpha_id"] for i in range(27)), self.target_ids)

        for record in self.records.values():
            program = compile_code(record["code"], register=False)
            if record["id"] not in self.target_ids:
                continue
            self.assertEqual(hashlib.sha256(record["code"].encode()).hexdigest(), record["code_sha256"])
            self.assertEqual(program.code_hash, record["program_hash"])
            self.assertEqual(record["dsl_compile_status"], "PASS")
            self.assertEqual(record["backtest_status"], "NOT_RUN")
            self.assertTrue(record["thesis"])
            self.assertTrue(record["entry_rule"])
            self.assertTrue(record["exit_rule"])
            self.assertTrue(program.has_long)
            self.assertFalse(program.has_short)

            calls = [
                node
                for node in ast.walk(ast.parse(record["code"]))
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"buy", "close"}
            ]
            calls.sort(key=lambda call: call.lineno)
            self.assertEqual([getattr(call.func, "attr", None) for call in calls], ["buy", "close"])
            self.assertLess(calls[0].lineno, calls[1].lineno)

    def test_primary_families_and_sources_are_unique(self):
        families = [record["primary_signal_family"] for record in self.targets]
        hashes = [record["code_sha256"] for record in self.targets]
        self.assertEqual(len(set(families)), 27)
        self.assertEqual(len(set(hashes)), 27)
        self.assertEqual(self.manifest["novelty_gate"], "PASS_RULE_LEVEL")
        self.assertEqual(self.manifest["comparison_count"], 27)
        other_ids = set(self.records) - self.target_ids
        rows_by_id = {row["alpha_id"]: row for row in self.manifest["results"]}
        self.assertEqual(set(rows_by_id), self.target_ids)
        for alpha_id, row in rows_by_id.items():
            self.assertTrue(set(row["closest_existing_alpha_ids"]).issubset(other_ids), alpha_id)
            self.assertTrue(set(row["closest_internal_alpha_ids"]).issubset(self.target_ids - {alpha_id}), alpha_id)
            self.assertTrue(row["comparison_difference"], alpha_id)

    def test_stress_fixture_signals_and_prefix_invariance(self):
        bars = _stress_bars()
        for record in self.targets:
            program = compile_code(record["code"], register=False)
            signals = program.explicit(bars)
            self.assertTrue(np.any(signals == 1.0), record["id"])
            for end in (100, 501, 1500, 2999):
                prefix = program.explicit(bars.iloc[:end])
                np.testing.assert_allclose(prefix, signals[:end], equal_nan=True, err_msg=record["id"])

    def test_harami_waits_for_later_mother_range_break(self):
        record = self.records["bd234070bd7b"]
        program = compile_code(record["code"], register=False)
        bars = pd.DataFrame(
            {
                "open_time": np.arange(3, dtype="int64") * 3_600_000,
                "open": [100.0, 97.0, 99.0],
                "high": [102.0, 99.0, 104.0],
                "low": [95.0, 96.5, 98.5],
                "close": [96.0, 98.0, 103.0],
                "volume": [100.0, 110.0, 120.0],
            }
        )
        signals = program.explicit(bars)
        self.assertTrue(np.isnan(signals[0]))
        self.assertTrue(np.isnan(signals[1]))
        self.assertEqual(signals[2], 1.0)


if __name__ == "__main__":
    unittest.main()
