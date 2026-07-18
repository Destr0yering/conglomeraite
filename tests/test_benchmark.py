import unittest

from conglomeraite.benchmark import _summarize


class BenchmarkSummaryTests(unittest.TestCase):
    def test_reports_noninferior_efficiency_rates(self) -> None:
        records = [
            {
                "status": "ok",
                "comparison": {
                    "swarm_vs_one_shot": {"quality_score_gain": 1.0},
                    "swarm_vs_budget_matched": {
                        "quality_score_gain": 0.0,
                        "latency_ratio_swarm_over_baseline": 0.8,
                        "call_ratio_swarm_over_baseline": 1.0,
                        "output_token_ratio_swarm_over_baseline": 0.7,
                    },
                },
            },
            {
                "status": "ok",
                "comparison": {
                    "swarm_vs_one_shot": {"quality_score_gain": 0.0},
                    "swarm_vs_budget_matched": {
                        "quality_score_gain": -1.0,
                        "latency_ratio_swarm_over_baseline": 0.7,
                        "call_ratio_swarm_over_baseline": 1.0,
                        "output_token_ratio_swarm_over_baseline": 0.6,
                    },
                },
            },
        ]
        summary = _summarize(records)
        self.assertEqual(summary["budget_matched_quality_noninferior_rate"], 0.5)
        self.assertEqual(
            summary["budget_matched_quality_noninferior_and_faster_rate"], 0.5
        )
        self.assertEqual(
            summary[
                "budget_matched_quality_noninferior_and_fewer_output_tokens_rate"
            ],
            0.5,
        )


if __name__ == "__main__":
    unittest.main()
