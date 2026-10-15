from __future__ import annotations

import json
import math
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Callable

from .agents import AgentContext
from .agents.coder import CoderAgent
from .apply import _run_isolated_tests, parse_draft
from .coding_loop import run_coding_loop
from .file_utils import ensure_dir, read_text, write_text
from .permissions import ensure_inside_project
from .providers import AIProvider, create_provider


@dataclass(frozen=True)
class BenchmarkTask:
    task_id: str
    goal: str
    test_source: str


TASKS = (
    BenchmarkTask(
        "clamp",
        "在 src/solution.py 实现 clamp(value, lower, upper)：把 value 限制在闭区间内；lower 大于 upper 时抛出 ValueError。",
        "import unittest\nfrom solution import clamp\n\nclass ClampTests(unittest.TestCase):\n    def test_inside_and_edges(self):\n        self.assertEqual(clamp(5, 0, 10), 5)\n        self.assertEqual(clamp(-1, 0, 10), 0)\n        self.assertEqual(clamp(11, 0, 10), 10)\n    def test_invalid_bounds(self):\n        with self.assertRaises(ValueError):\n            clamp(1, 2, 0)\n",
    ),
    BenchmarkTask(
        "normalize-name",
        "在 src/solution.py 实现 normalize_name(name)：去除首尾空白，将每个单词首字母大写、其余字母小写；空字符串或纯空白返回空字符串。",
        "import unittest\nfrom solution import normalize_name\n\nclass NormalizeNameTests(unittest.TestCase):\n    def test_normalizes_words(self):\n        self.assertEqual(normalize_name('  aLICE  van   der  '), 'Alice Van Der')\n    def test_empty(self):\n        self.assertEqual(normalize_name('  '), '')\n",
    ),
)


class CountingProvider(AIProvider):
    """记录字符级 token 估算；不冒充 Provider 的真实 usage 账单数据。"""

    def __init__(self, wrapped: AIProvider) -> None:
        self.wrapped = wrapped
        self.name = wrapped.name
        config = getattr(wrapped, "config", None)
        self.model = getattr(
            config, "model", "mock-model" if self.name == "mock" else "unknown"
        )
        self.calls = 0
        self.input_chars = 0
        self.output_chars = 0
        self._lock = Lock()

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        with self._lock:
            self.calls += 1
            self.input_chars += len(system_prompt) + len(user_prompt)
        result = self.wrapped.complete(system_prompt, user_prompt)
        with self._lock:
            self.output_chars += len(result)
        return result

    @property
    def estimated_tokens(self) -> int:
        with self._lock:
            return math.ceil((self.input_chars + self.output_chars) / 4)


def _sandbox(task: BenchmarkTask, root: Path) -> Path:
    project = root / task.task_id
    (project / "src").mkdir(parents=True)
    (project / "tests").mkdir()
    (project / "product-docs").mkdir()
    (project / "src" / "__init__.py").write_text("", encoding="utf-8")
    (project / "tests" / "test_solution.py").write_text(task.test_source, encoding="utf-8")
    (project / "tests" / "__init__.py").write_text("", encoding="utf-8")
    return project


def _short_detail(detail: str) -> str:
    for line in reversed(detail.splitlines()):
        text = line.strip()
        if text.startswith(
            ("AssertionError:", "ModuleNotFoundError:", "ImportError:", "SyntaxError:", "NameError:")
        ):
            return text
    return " ".join(detail.split())[-240:]


def _single_agent(
    project: Path, task: BenchmarkTask, provider: AIProvider
) -> tuple[bool, bool, int, int, int, str]:
    task_id = f"bench-single-{task.task_id}"
    context_path = project / "logs" / "context-packs" / f"{task_id}.md"
    ensure_dir(context_path.parent)
    write_text(context_path, f"# Benchmark task\n\n{task.goal}\n")
    context = AgentContext(project, task.goal, task_id, context_path)
    CoderAgent(provider=provider).run(context, [])
    draft_path = project / "dev-vault" / "projects" / f"{task_id}-coder-draft.md"
    parsed = parse_draft(read_text(draft_path))
    if parsed.errors:
        return False, False, 0, 0, 0, "草稿解析失败：" + "；".join(parsed.errors)
    code, output = _run_isolated_tests(project, parsed.changes)
    return code == 0, True, len(parsed.changes), 0, 0, output[-1200:]


def _multi_agent(
    project: Path, task: BenchmarkTask, provider: AIProvider
) -> tuple[bool, bool, int, int, int, str]:
    result = run_coding_loop(project, task.goal, apply=False, provider=provider)
    if not result.draft_path or not result.apply_result or not result.apply_result.ok:
        return False, False, 0, 0, 0, result.message[-1200:]
    parsed = parse_draft(read_text(result.draft_path))
    if parsed.errors:
        return False, False, 0, 0, 0, "草稿解析失败：" + "；".join(parsed.errors)
    rejected = sum(
        1 for agent_result in result.workflow.agent_results
        if agent_result.role == "ReviewerAgent"
        and "草稿评审结论：需修改" in agent_result.summary
    )
    retries = sum(
        1 for agent_result in result.workflow.agent_results
        if agent_result.role == "CoderAgent" and "重写代码草稿" in agent_result.summary
    )
    code, output = _run_isolated_tests(project, parsed.changes)
    return code == 0, True, len(parsed.changes), retries, rejected, output[-1200:]


def run_benchmark(
    output_root: Path,
    *,
    project_root: Path | None = None,
    tasks: tuple[BenchmarkTask, ...] = TASKS,
    modes: tuple[str, ...] = ("single", "multi"),
    provider_factory: Callable[[], AIProvider] = create_provider,
) -> Path:
    """Run the built-in coding benchmark without applying changes to the real project."""
    if project_root is not None:
        output_root = ensure_inside_project(
            output_root, project_root, action="保存 benchmark 报告"
        )
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
    run_dir = output_root / stamp
    ensure_dir(run_dir)
    raw_path = run_dir / "runs.jsonl"
    records: list[dict] = []
    for task in tasks:
        for mode in modes:
            with tempfile.TemporaryDirectory(prefix="agent-benchmark-") as temp:
                project = _sandbox(task, Path(temp))
                provider = CountingProvider(provider_factory())
                started = time.perf_counter()
                try:
                    if mode == "single":
                        (
                            success,
                            tests_executed,
                            changed_files,
                            retries,
                            rejected,
                            detail,
                        ) = _single_agent(project, task, provider)
                    elif mode == "multi":
                        (
                            success,
                            tests_executed,
                            changed_files,
                            retries,
                            rejected,
                            detail,
                        ) = _multi_agent(project, task, provider)
                    else:
                        raise ValueError(f"不支持的 benchmark 模式：{mode}")
                except Exception as exc:  # one task failure must not erase the remaining measurements
                    success, tests_executed, changed_files, retries, rejected = False, False, 0, 0, 0
                    detail = f"{type(exc).__name__}: {exc}"
                elapsed = time.perf_counter() - started
                records.append({
                    "task_id": task.task_id,
                    "task_goal": task.goal,
                    "mode": mode,
                    "provider": provider.name,
                    "model": provider.model,
                    "success": success,
                    "tests_executed": tests_executed,
                    "tests_passed": success if tests_executed else None,
                    "changed_files": changed_files,
                    "retry_count": retries,
                    "reviewer_rejections": rejected,
                    "provider_calls": provider.calls,
                    "estimated_tokens": provider.estimated_tokens,
                    "token_estimate_method": "ceil((input_chars + output_chars) / 4)",
                    "input_chars": provider.input_chars,
                    "output_chars": provider.output_chars,
                    "latency_seconds": round(elapsed, 3),
                    "detail": detail,
                })
    raw_path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records),
        encoding="utf-8",
    )
    report_path = run_dir / "summary.md"
    lines = [
        "# Benchmark Summary",
        "",
        f"- Run: `{stamp}`",
        "- Provider/model: `"
        + ", ".join(
            sorted({item["provider"] + "/" + item["model"] for item in records})
        )
        + "`",
        "- Token 数为按字符数除以 4 的估算值，不是 Provider 账单 usage。",
        "- 每条任务在独立临时项目中运行；生成的改动只进入隔离测试副本。",
        "",
        "| 模式 | 成功率 | 测试通过率 | 平均估算 token | 平均耗时(s) | 平均改动文件 | 平均重试 | Reviewer 驳回 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for mode in modes:
        group = [item for item in records if item["mode"] == mode]
        if not group:
            continue
        count = len(group)
        lines.append(
            f"| {mode} | {sum(x['success'] for x in group)}/{count} | "
            f"{sum(bool(x['tests_passed']) for x in group)}/{sum(x['tests_executed'] for x in group)} | "
            f"{sum(x['estimated_tokens'] for x in group) / count:.1f} | "
            f"{sum(x['latency_seconds'] for x in group) / count:.3f} | "
            f"{sum(x['changed_files'] for x in group) / count:.2f} | "
            f"{sum(x['retry_count'] for x in group) / count:.2f} | "
            f"{sum(x['reviewer_rejections'] for x in group)} |"
        )
    lines.extend(["", f"原始记录：`{raw_path.name}`", "", "## 逐任务结果", ""])
    for item in records:
        lines.append(
            f"- `{item['mode']}` / `{item['task_id']}`: "
            f"{'通过' if item['success'] else '失败'}，{item['latency_seconds']}s，"
            f"约 {item['estimated_tokens']} tokens，Provider 调用 {item['provider_calls']} 次。"
        )
        if item["detail"]:
            lines.append(f"  - {_short_detail(item['detail'])}")
    write_text(report_path, "\n".join(lines) + "\n")
    return report_path
