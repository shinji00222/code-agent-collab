from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from code_agent_collab.agents import (
    ComplexityLevel,
    OrchestratorAgent,
    build_plan,
    estimate_complexity,
    estimate_complexity_with_provider,
)
from code_agent_collab.agents.base import AgentContext
from code_agent_collab.providers import MockProvider


class ComplexityTests(unittest.TestCase):
    def test_short_simple_task_is_simple(self) -> None:
        self.assertEqual(estimate_complexity("写个计算器"), ComplexityLevel.SIMPLE)

    def test_long_single_topic_task_is_medium(self) -> None:
        goal = "我需要一个非常详细的完整开发计划来指导整个项目的编码工作"
        self.assertEqual(estimate_complexity(goal), ComplexityLevel.MEDIUM)

    def test_split_signal_task_is_medium(self) -> None:
        self.assertEqual(estimate_complexity("写多个功能模块"), ComplexityLevel.MEDIUM)

    def test_multi_topic_task_is_complex(self) -> None:
        goal = "用 python 和前端写一个带多个模块和接口的完整网站，拆成前后端"
        self.assertEqual(estimate_complexity(goal), ComplexityLevel.COMPLEX)

    def test_mock_provider_falls_back_to_rules(self) -> None:
        self.assertEqual(
            estimate_complexity_with_provider("写个计算器", MockProvider()),
            ComplexityLevel.SIMPLE,
        )

    def test_plan_worker_counts(self) -> None:
        self.assertEqual(build_plan(ComplexityLevel.SIMPLE).worker_count, 1)
        self.assertEqual(build_plan(ComplexityLevel.MEDIUM).worker_count, 2)
        self.assertEqual(build_plan(ComplexityLevel.COMPLEX).worker_count, 4)


class OrchestratorAgentTests(unittest.TestCase):
    def test_agent_emits_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = AgentContext(
                project_root=root,
                task_goal="写个计算器",
                task_id="t1",
                context_pack_path=root / "context.md",
            )
            agent = OrchestratorAgent(provider=MockProvider())
            result = agent.run(context, [])
            self.assertIsNotNone(agent.last_plan)
            assert agent.last_plan is not None
            self.assertEqual(agent.last_plan.complexity, ComplexityLevel.SIMPLE)
            self.assertIn("共 1 个 worker", result.summary)


if __name__ == "__main__":
    unittest.main()
