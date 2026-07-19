import unittest

from conglomeraite.config import LoopConfig, MemoryConfig
from conglomeraite.loop import RefinementLoop
from conglomeraite.memory import MemoryGuard, MemorySnapshot
from conglomeraite.providers import Completion, FailoverRouter


class SafeProbe:
    def __init__(self, used: float = 1000) -> None:
        self.used = used

    def snapshot(self):
        return MemorySnapshot("test", 8000, self.used)

    def close(self):
        pass


class ScriptedProvider:
    name = "local"

    def __init__(self, values):
        self.values = list(values)
        self.messages = []

    def complete(self, messages, *, temperature, timeout_s=None):
        self.messages.append(messages)
        value = self.values.pop(0)
        if isinstance(value, Completion):
            return value
        text = value
        return Completion(
            text,
            self.name,
            5.0,
            input_tokens=10,
            output_tokens=5,
            providers_attempted=(self.name,),
        )


def make_loop(provider, *, loop_config=None, probe=None):
    return RefinementLoop(
        FailoverRouter(None, provider),
        MemoryGuard(probe or SafeProbe(), MemoryConfig()),
        loop_config or LoopConfig(),
    )


VALID_TEN = (
    '{"score":10,"ready":true,"blocking_issues":[],"refinements":[],'
    '"rubric_checks":[{"criterion":"correctness","satisfied":true,'
    '"evidence":"all requirements met"}],"verdict":"ready"}'
)


class LoopTests(unittest.TestCase):
    def test_generator_receives_the_rubric_on_first_call(self) -> None:
        provider = ScriptedProvider(["draft", VALID_TEN])
        loop = RefinementLoop(
            FailoverRouter(None, provider),
            MemoryGuard(SafeProbe(), MemoryConfig()),
            LoopConfig(),
            rubric="Require a rollback trigger.",
        )
        result = loop.run("design a system")
        self.assertEqual(result.status, "consensus")
        self.assertIn("RUBRIC:", provider.messages[0][1].content)
        self.assertIn("Require a rollback trigger.", provider.messages[0][1].content)

    def test_truncated_generator_output_cannot_reach_consensus(self) -> None:
        provider = ScriptedProvider(
            [
                Completion(
                    "partial draft",
                    "local",
                    5.0,
                    input_tokens=10,
                    output_tokens=5,
                    providers_attempted=("local",),
                    finish_reason="length",
                ),
                VALID_TEN,
                "complete concise draft",
                VALID_TEN,
            ]
        )
        result = make_loop(provider).run("design a system")
        self.assertEqual(result.status, "consensus")
        self.assertEqual(len(result.iterations), 2)
        self.assertEqual(result.calls[0].finish_reason, "length")
        self.assertIn("output-token limit", provider.messages[2][1].content)

    def test_truncated_generator_is_not_returned_at_terminal_boundary(self) -> None:
        provider = ScriptedProvider(
            [
                Completion(
                    "partial draft",
                    "local",
                    5.0,
                    input_tokens=10,
                    output_tokens=5,
                    providers_attempted=("local",),
                    finish_reason="length",
                ),
                "SCORE: 9/10\nREFINEMENTS: complete the answer",
            ]
        )
        result = make_loop(
            provider,
            loop_config=LoopConfig(max_iterations=1, max_stagnant_iterations=0),
        ).run("design a system")
        self.assertEqual(result.status, "max_iterations")
        self.assertIsNone(result.final_draft)
        self.assertIsNone(result.final_score)

    def test_iterates_feedback_until_ten(self) -> None:
        provider = ScriptedProvider(
            [
                "draft one",
                "SCORE: 8/10\nREFINEMENTS:\n- Add fallback",
                "draft two with fallback",
                VALID_TEN,
            ]
        )
        result = make_loop(provider).run("design a system")
        self.assertEqual(result.status, "consensus")
        self.assertEqual(result.final_score, 10)
        self.assertEqual(result.final_draft, "draft two with fallback")
        self.assertEqual(result.model_calls, 4)
        self.assertEqual(result.output_tokens, 20)
        second_generator_prompt = provider.messages[2][1].content
        self.assertIn("draft one", second_generator_prompt)
        self.assertIn("Add fallback", second_generator_prompt)
        second_critic_prompt = provider.messages[3][1].content
        self.assertIn("PRIOR CRITIC JUDGMENT", second_critic_prompt)
        self.assertIn("SCORE: 8/10", second_critic_prompt)

    def test_repairs_malformed_critic_score(self) -> None:
        provider = ScriptedProvider(
            [
                "draft",
                "Everything seems ready",
                VALID_TEN,
            ]
        )
        result = make_loop(provider).run("task")
        self.assertEqual(result.status, "consensus")
        self.assertEqual(result.iterations[0].parse_repairs, 1)
        self.assertEqual([call.role for call in result.calls], ["generator", "critic", "critic_repair"])

    def test_returns_best_draft_when_later_iteration_regresses(self) -> None:
        provider = ScriptedProvider(
            [
                "best draft",
                "SCORE: 8/10\nREFINEMENTS: improve",
                "worse draft",
                "SCORE: 7/10\nREFINEMENTS: regress",
            ]
        )
        result = make_loop(
            provider,
            loop_config=LoopConfig(max_iterations=2, max_stagnant_iterations=0),
        ).run("task")
        self.assertEqual(result.status, "max_iterations")
        self.assertEqual(result.final_draft, "best draft")
        self.assertEqual(result.final_score, 8)
        self.assertEqual(result.best_iteration, 1)

    def test_hardware_guard_stops_before_first_model_call(self) -> None:
        provider = ScriptedProvider(["must not run"])
        result = make_loop(provider, probe=SafeProbe(7600)).run("task")
        self.assertEqual(result.status, "circuit_breaker")
        self.assertEqual(result.model_calls, 0)
        self.assertEqual(len(provider.messages), 0)

    def test_ten_with_blocking_issue_does_not_pass(self) -> None:
        provider = ScriptedProvider(
            [
                "draft",
                '{"score":10,"ready":false,"blocking_issues":["missing tests"],'
                '"refinements":["add tests"],"rubric_checks":[{"criterion":"tests",'
                '"satisfied":false}],"verdict":"not ready"}',
                "revised",
                VALID_TEN,
            ]
        )
        result = make_loop(provider).run("task")
        self.assertEqual(result.status, "consensus")
        self.assertEqual(len(result.iterations), 2)

    def test_text_ten_requires_bounded_json_schema_repair(self) -> None:
        provider = ScriptedProvider(["draft", "SCORE: 10/10", VALID_TEN])
        result = make_loop(provider).run("task")
        self.assertEqual(result.status, "consensus")
        self.assertEqual(result.iterations[0].parse_repairs, 1)

    def test_identical_rejected_candidate_cannot_later_reach_consensus(self) -> None:
        provider = ScriptedProvider(
            [
                "unchanged",
                "SCORE: 8/10",
                "unchanged",
                VALID_TEN,
            ]
        )
        result = make_loop(
            provider,
            loop_config=LoopConfig(max_iterations=2, max_stagnant_iterations=0),
        ).run("task")
        self.assertEqual(result.status, "max_iterations")
        self.assertEqual(result.final_score, 8)
        self.assertIn("byte-identical", result.iterations[-1].critique)

    def test_stagnation_returns_best_not_latest_candidate(self) -> None:
        provider = ScriptedProvider(
            [
                "best",
                "SCORE: 8/10",
                "worse",
                "SCORE: 7/10",
            ]
        )
        result = make_loop(
            provider,
            loop_config=LoopConfig(max_iterations=3, max_stagnant_iterations=1),
        ).run("task")
        self.assertEqual(result.status, "stagnated")
        self.assertEqual(result.final_draft, "best")
        self.assertEqual(result.final_score, 8)

    def test_partial_usage_makes_token_totals_unknown(self) -> None:
        provider = ScriptedProvider(["draft", VALID_TEN])
        original = provider.complete

        def partial(messages, *, temperature, timeout_s=None):
            completion = original(messages, temperature=temperature, timeout_s=timeout_s)
            if len(provider.messages) == 2:
                return Completion(
                    completion.text,
                    completion.provider,
                    completion.latency_ms,
                    input_tokens=None,
                    output_tokens=None,
                    providers_attempted=completion.providers_attempted,
                )
            return completion

        provider.complete = partial
        result = make_loop(provider).run("task")
        self.assertIsNone(result.input_tokens)
        self.assertIsNone(result.output_tokens)
        self.assertEqual(result.usage_coverage, 0.5)
        journal = result.journal_dict()
        serialized = str(journal)
        self.assertNotIn("task", serialized)
        self.assertNotIn("draft", serialized)
        self.assertNotIn("critique", serialized)


if __name__ == "__main__":
    unittest.main()
