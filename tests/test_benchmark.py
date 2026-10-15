from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from code_agent_collab.benchmark import (
    TASKS,
    BenchmarkTask,
    CountingProvider,
    _benchmark_changes,
    run_benchmark,
)
from code_agent_collab.apply import DraftChange
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


class UsageProvider(DraftProvider):
    def complete_with_usage(self, system_prompt: str, user_prompt: str):
        return self.complete(system_prompt, user_prompt), {
            "input_tokens": 11,
            "output_tokens": 7,
            "total_tokens": 18,
        }


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

    def test_repeats_must_be_positive(self):
        with tempfile.TemporaryDirectory(prefix="benchmark-repeat-") as temp:
            with self.assertRaisesRegex(ValueError, "至少为 1"):
                run_benchmark(Path(temp), tasks=(), modes=(), repeats=0)

    def test_benchmark_keeps_fixed_tests_out_of_model_changes(self):
        changes, ignored = _benchmark_changes([
            DraftChange("src/solution.py", "def answer(): return 42"),
            DraftChange("tests/test_solution.py", "# model supplied tests"),
        ])
        self.assertEqual([change.path for change in changes], ["src/solution.py"])
        self.assertEqual(ignored, 1)

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

    def test_counting_provider_prefers_reported_usage_when_available(self):
        provider = CountingProvider(UsageProvider())
        provider.complete("system", "user")
        self.assertEqual(
            provider.reported_usage,
            {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
        )

    def test_benchmark_records_provider_usage_in_jsonl(self):
        with tempfile.TemporaryDirectory(prefix="benchmark-usage-") as temp:
            report = run_benchmark(
                Path(temp),
                tasks=(TASKS[0],),
                modes=("single",),
                provider_factory=UsageProvider,
            )
            record = json.loads(
                (report.parent / "runs.jsonl").read_text(encoding="utf-8")
            )
        self.assertEqual(record["token_source"], "provider_usage")
        self.assertEqual(record["token_count"], 18)
        self.assertEqual(record["reported_usage"]["input_tokens"], 11)

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
                repeats=2,
                provider_factory=DraftProvider,
            )
            run_dir = report.parent
            records = [
                json.loads(line)
                for line in (run_dir / "runs.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(records), 2)
            self.assertTrue(all(record["success"] for record in records))
            self.assertTrue(all(record["tests_executed"] for record in records))
            self.assertTrue(all(record["tests_passed"] for record in records))
            self.assertTrue(all(record["benchmark_version"] == "1.3" for record in records))
            self.assertTrue(all(record["token_source"] == "character_estimate" for record in records))
            self.assertTrue(all(record["changed_files"] == 1 for record in records))
            self.assertTrue(all(record["retry_count"] == 0 for record in records))
            self.assertTrue(all(record["task_goal"] == task.goal for record in records))
            self.assertIn("独立临时项目", report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
