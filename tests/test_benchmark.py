from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from code_agent_collab.benchmark import BenchmarkTask, CountingProvider, run_benchmark
from code_agent_collab.permissions import PermissionDenied
from code_agent_collab.providers import AIProvider


class DraftProvider(AIProvider):
    name = "benchmark-test-double"

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        del system_prompt, user_prompt
        return """## 修改文件清单
- src/solution.py（新增）
## 修改原因
实现 benchmark 的纯函数，并覆盖有效输入与边界。
## 建议代码
### src/solution.py
def clamp(value, lower, upper):
    if lower > upper:
        raise ValueError('lower must not exceed upper')
    return min(max(value, lower), upper)
## 测试方法
运行 python -m unittest discover -s tests。
## 风险
只新增一个无外部副作用的纯函数。
"""


class BenchmarkTests(unittest.TestCase):
    def test_cli_output_cannot_escape_project_root(self):
        with tempfile.TemporaryDirectory(prefix="benchmark-boundary-") as temp:
            root = Path(temp) / "project"
            root.mkdir()
            with self.assertRaises(PermissionDenied):
                run_benchmark(
                    root.parent / "outside",
                    project_root=root,
                    tasks=(),
                    modes=(),
                )

    def test_counting_provider_labels_character_estimate(self):
        provider = CountingProvider(DraftProvider())
        response = provider.complete("sys", "user")
        self.assertIn("def clamp", response)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(provider.model, "unknown")
        self.assertEqual(provider.input_chars, len("sysuser"))
        self.assertGreater(provider.estimated_tokens, 1)

    def test_counting_provider_keeps_parallel_call_totals(self):
        provider = CountingProvider(DraftProvider())
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda index: provider.complete("s", str(index)), range(40)))
        self.assertEqual(provider.calls, 40)
        self.assertEqual(provider.input_chars, sum(len("s") + len(str(i)) for i in range(40)))

    def test_single_agent_benchmark_runs_isolated_tests_and_writes_records(self):
        task = BenchmarkTask(
            "clamp",
            "实现 clamp(value, lower, upper)，越界时夹紧；lower > upper 抛 ValueError。",
            "import unittest\nfrom solution import clamp\n\n"
            "class ClampTests(unittest.TestCase):\n"
            "    def test_clamps(self):\n"
            "        self.assertEqual(clamp(-1, 0, 3), 0)\n"
            "        self.assertEqual(clamp(4, 0, 3), 3)\n"
            "    def test_invalid_bounds(self):\n"
            "        with self.assertRaises(ValueError):\n"
            "            clamp(1, 2, 0)\n",
        )
        with tempfile.TemporaryDirectory(prefix="benchmark-test-") as temp:
            report = run_benchmark(
                Path(temp),
                tasks=(task,),
                modes=("single",),
                provider_factory=DraftProvider,
            )
            run_dir = report.parent
            record = json.loads((run_dir / "runs.jsonl").read_text(encoding="utf-8"))
            self.assertTrue(record["success"])
            self.assertTrue(record["tests_executed"])
            self.assertTrue(record["tests_passed"])
            self.assertEqual(record["changed_files"], 1)
            self.assertEqual(record["retry_count"], 0)
            self.assertEqual(record["task_goal"], task.goal)
            self.assertIn("独立临时项目", report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
