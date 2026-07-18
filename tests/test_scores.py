import unittest

from conglomeraite.loop import parse_critic_evaluation, parse_critic_score


class ScoreParsingTests(unittest.TestCase):
    def test_parses_labeled_fraction(self) -> None:
        self.assertEqual(parse_critic_score("SCORE: 8/10\nNeeds work"), 8.0)

    def test_parses_json_number_and_fraction(self) -> None:
        self.assertEqual(parse_critic_score('{"score": 9, "blocking_issues": []}'), 9.0)
        self.assertEqual(parse_critic_score('{"score": "9.5/10"}'), 9.5)

    def test_rejects_conflicting_scores(self) -> None:
        self.assertIsNone(parse_critic_score("SCORE: 8/10\nFINAL SCORE: 9/10"))
        self.assertIsNone(parse_critic_score('{"score": 8}\nSCORE: 9/10'))

    def test_rejects_out_of_range_or_missing_scores(self) -> None:
        self.assertIsNone(parse_critic_score("SCORE: 11/10"))
        self.assertIsNone(parse_critic_score('{"score": -1}'))
        self.assertIsNone(parse_critic_score("Looks good"))

    def test_ten_with_blockers_cannot_reach_consensus(self) -> None:
        result = parse_critic_evaluation(
            '{"score": 10, "blocking_issues": ["Add authentication"]}'
        )
        self.assertEqual(result.score, 10)
        self.assertFalse(result.can_reach_consensus)

    def test_text_ten_never_reaches_consensus(self) -> None:
        result = parse_critic_evaluation("SCORE: 10/10\nREFINEMENTS:\n- NONE")
        self.assertFalse(result.can_reach_consensus)
        self.assertTrue(result.needs_schema_repair)

    def test_json_ten_requires_explicit_complete_schema(self) -> None:
        valid = parse_critic_evaluation(
            '{"score":10,"ready":true,"blocking_issues":[],"refinements":[],'
            '"rubric_checks":[{"criterion":"correctness","satisfied":true}]}'
        )
        missing_checks = parse_critic_evaluation(
            '{"score":10,"ready":true,"blocking_issues":[],"refinements":[]}'
        )
        unsatisfied = parse_critic_evaluation(
            '{"score":10,"ready":true,"blocking_issues":[],"refinements":[],'
            '"rubric_checks":[{"criterion":"correctness","satisfied":false}]}'
        )
        self.assertTrue(valid.can_reach_consensus)
        self.assertFalse(missing_checks.can_reach_consensus)
        self.assertTrue(missing_checks.needs_schema_repair)
        self.assertFalse(unsatisfied.can_reach_consensus)


if __name__ == "__main__":
    unittest.main()
