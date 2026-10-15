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
from .apply import DraftChange, _run_isolated_tests, parse_draft
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
        """import unittest
from solution import clamp

class ClampTests(unittest.TestCase):
    def test_inside_and_edges(self):
        self.assertEqual(clamp(5, 0, 10), 5)
        self.assertEqual(clamp(-1, 0, 10), 0)
        self.assertEqual(clamp(11, 0, 10), 10)
    def test_invalid_bounds(self):
        with self.assertRaises(ValueError):
            clamp(1, 2, 0)
""",
    ),
    BenchmarkTask(
        "normalize-name",
        "在 src/solution.py 实现 normalize_name(name)：把连续空白折叠成单个空格，去除首尾空白，再将每个单词首字母大写、其余字母小写；空字符串或纯空白返回空字符串。",
        """import unittest
from solution import normalize_name

class NormalizeNameTests(unittest.TestCase):
    def test_normalizes_words(self):
        self.assertEqual(normalize_name('  aLICE  van   der  '), 'Alice Van Der')
    def test_empty(self):
        self.assertEqual(normalize_name('  '), '')
""",
    ),
    BenchmarkTask(
        "safe-divide",
        "在 src/solution.py 实现 safe_divide(a, b)：返回 a / b；b 为 0 时抛出 ZeroDivisionError。",
        """import unittest
from solution import safe_divide

class SafeDivideTests(unittest.TestCase):
    def test_divides(self):
        self.assertEqual(safe_divide(9, 2), 4.5)
    def test_zero_divisor(self):
        with self.assertRaises(ZeroDivisionError):
            safe_divide(1, 0)
""",
    ),
    BenchmarkTask(
        "palindrome",
        "在 src/solution.py 实现 is_palindrome(text)：忽略大小写，并删除所有非英文字母和数字字符后，判断文本是否正读反读相同。",
        """import unittest
from solution import is_palindrome

class PalindromeTests(unittest.TestCase):
    def test_palindromes(self):
        self.assertTrue(is_palindrome('Never odd or even'))
        self.assertTrue(is_palindrome('Level'))
    def test_non_palindrome(self):
        self.assertFalse(is_palindrome('hello'))
""",
    ),
    BenchmarkTask(
        "dedupe-order",
        "在 src/solution.py 实现 dedupe_preserve_order(items)：返回去重后的列表，并保留每个值第一次出现的顺序。输入元素可哈希。",
        """import unittest
from solution import dedupe_preserve_order

class DedupeOrderTests(unittest.TestCase):
    def test_keeps_first_occurrences(self):
        self.assertEqual(dedupe_preserve_order([3, 1, 3, 2, 1]), [3, 1, 2])
    def test_empty(self):
        self.assertEqual(dedupe_preserve_order([]), [])
""",
    ),
    BenchmarkTask(
        "word-count",
        "在 src/solution.py 实现 word_count(text)：返回按任意连续空白拆分后的单词数量；空字符串或纯空白返回 0。",
        """import unittest
from solution import word_count

class WordCountTests(unittest.TestCase):
    def test_counts_whitespace_separated_words(self):
        self.assertEqual(word_count('  one\\n two\\tthree '), 3)
    def test_empty(self):
        self.assertEqual(word_count('  '), 0)
""",
    ),
    BenchmarkTask(
        "fibonacci",
        "在 src/solution.py 实现 fibonacci(n)：返回 0 起始、0-based 的第 n 个 Fibonacci 数；负数时抛出 ValueError。",
        """import unittest
from solution import fibonacci

class FibonacciTests(unittest.TestCase):
    def test_sequence(self):
        self.assertEqual([fibonacci(i) for i in range(7)], [0, 1, 1, 2, 3, 5, 8])
    def test_negative(self):
        with self.assertRaises(ValueError):
            fibonacci(-1)
""",
    ),
    BenchmarkTask(
        "is-prime",
        "在 src/solution.py 实现 is_prime(n)：判断整数是否为素数；小于 2 的值返回 False。",
        """import unittest
from solution import is_prime

class IsPrimeTests(unittest.TestCase):
    def test_primes_and_composites(self):
        self.assertTrue(is_prime(2))
        self.assertTrue(is_prime(17))
        self.assertFalse(is_prime(1))
        self.assertFalse(is_prime(21))
""",
    ),
    BenchmarkTask(
        "slugify",
        "在 src/solution.py 实现 slugify(text)：去掉首尾空白、转成小写，并把一个或多个连续空白替换成单个连字符；不改动其他字符。",
        """import unittest
from solution import slugify

class SlugifyTests(unittest.TestCase):
    def test_collapses_whitespace(self):
        self.assertEqual(slugify('  Hello\\tWORLD  '), 'hello-world')
    def test_empty(self):
        self.assertEqual(slugify('  '), '')
""",
    ),
    BenchmarkTask(
        "count-vowels",
        "在 src/solution.py 实现 count_vowels(text)：统计英文元音 a/e/i/o/u 的出现次数，不区分大小写。",
        """import unittest
from solution import count_vowels

class CountVowelsTests(unittest.TestCase):
    def test_counts_vowels(self):
        self.assertEqual(count_vowels('Beautiful Day'), 6)
    def test_no_vowels(self):
        self.assertEqual(count_vowels('rhythm'), 0)
""",
    ),
)
BENCHMARK_VERSION = "1.3"


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
        self.usage_calls = 0
        self.actual_input_tokens: int | None = 0
        self.actual_output_tokens: int | None = 0
        self.actual_total_tokens = 0
        self._lock = Lock()

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        with self._lock:
            self.calls += 1
            self.input_chars += len(system_prompt) + len(user_prompt)
        complete_with_usage = getattr(self.wrapped, "complete_with_usage", None)
        if callable(complete_with_usage):
            result, usage = complete_with_usage(system_prompt, user_prompt)
        else:
            result, usage = self.wrapped.complete(system_prompt, user_prompt), None
        with self._lock:
            self.output_chars += len(result)
            if (
                isinstance(usage, dict)
                and type(usage.get("total_tokens")) is int
                and usage["total_tokens"] >= 0
            ):
                self.usage_calls += 1
                self.actual_total_tokens += usage["total_tokens"]
                self.actual_input_tokens = self._sum_reported_field(
                    self.actual_input_tokens, usage.get("input_tokens")
                )
                self.actual_output_tokens = self._sum_reported_field(
                    self.actual_output_tokens, usage.get("output_tokens")
                )
        return result

    @property
    def estimated_tokens(self) -> int:
        with self._lock:
            return math.ceil((self.input_chars + self.output_chars) / 4)

    @property
    def reported_usage(self) -> dict[str, int] | None:
        with self._lock:
            if not self.calls or self.usage_calls != self.calls:
                return None
            usage = {"total_tokens": self.actual_total_tokens}
            if self.actual_input_tokens is not None:
                usage["input_tokens"] = self.actual_input_tokens
            if self.actual_output_tokens is not None:
                usage["output_tokens"] = self.actual_output_tokens
            return usage

    @staticmethod
    def _sum_reported_field(current: int | None, value: object) -> int | None:
        if current is None or type(value) is not int or value < 0:
            return None
        return current + value


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


def _benchmark_changes(changes: list[DraftChange]) -> tuple[list[DraftChange], int]:
    """Keep benchmark tasks fixed: only the requested implementation file is applied."""
    implementation = [change for change in changes if change.path == "src/solution.py"]
    return implementation, len(changes) - len(implementation)


def _single_agent(
    project: Path, task: BenchmarkTask, provider: AIProvider
) -> tuple[bool, bool, int, int, int, int, str]:
    task_id = f"bench-single-{task.task_id}"
    context_path = project / "logs" / "context-packs" / f"{task_id}.md"
    ensure_dir(context_path.parent)
    write_text(context_path, f"# Benchmark task\n\n{task.goal}\n")
    context = AgentContext(project, task.goal, task_id, context_path)
    CoderAgent(provider=provider).run(context, [])
    draft_path = project / "dev-vault" / "projects" / f"{task_id}-coder-draft.md"
    parsed = parse_draft(read_text(draft_path))
    if parsed.errors:
        return False, False, 0, 0, 0, 0, "草稿解析失败：" + "；".join(parsed.errors)
    changes, ignored = _benchmark_changes(parsed.changes)
    code, output = _run_isolated_tests(project, changes)
    detail = output[-1200:]
    if ignored:
        detail += f"\n评测器忽略了 {ignored} 个非 src/solution.py 改动，固定测试夹具保持不变。"
    return code == 0, True, len(changes), 0, 0, ignored, detail


def _multi_agent(
    project: Path, task: BenchmarkTask, provider: AIProvider
) -> tuple[bool, bool, int, int, int, int, str]:
    result = run_coding_loop(project, task.goal, apply=False, provider=provider)
    if not result.draft_path or not result.apply_result or not result.apply_result.ok:
        return False, False, 0, 0, 0, 0, result.message[-1200:]
    parsed = parse_draft(read_text(result.draft_path))
    if parsed.errors:
        return False, False, 0, 0, 0, 0, "草稿解析失败：" + "；".join(parsed.errors)
    rejected = sum(
        1 for agent_result in result.workflow.agent_results
        if agent_result.role == "ReviewerAgent"
        and "草稿评审结论：需修改" in agent_result.summary
    )
    retries = sum(
        1 for agent_result in result.workflow.agent_results
        if agent_result.role == "CoderAgent" and "重写代码草稿" in agent_result.summary
    )
    changes, ignored = _benchmark_changes(parsed.changes)
    code, output = _run_isolated_tests(project, changes)
    detail = output[-1200:]
    if ignored:
        detail += f"\n评测器忽略了 {ignored} 个非 src/solution.py 改动，固定测试夹具保持不变。"
    return code == 0, True, len(changes), retries, rejected, ignored, detail


def run_benchmark(
    output_root: Path,
    *,
    project_root: Path | None = None,
    tasks: tuple[BenchmarkTask, ...] = TASKS,
    modes: tuple[str, ...] = ("single", "multi"),
    repeats: int = 1,
    provider_factory: Callable[[], AIProvider] = create_provider,
) -> Path:
    """Run the built-in coding benchmark without applying changes to the real project."""
    if repeats < 1:
        raise ValueError("repeats 必须至少为 1")
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
        for repeat in range(1, repeats + 1):
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
                                ignored_files,
                                detail,
                            ) = _single_agent(project, task, provider)
                        elif mode == "multi":
                            (
                                success,
                                tests_executed,
                                changed_files,
                                retries,
                                rejected,
                                ignored_files,
                                detail,
                            ) = _multi_agent(project, task, provider)
                        else:
                            raise ValueError(f"不支持的 benchmark 模式：{mode}")
                    except Exception as exc:  # one task failure must not erase the remaining measurements
                        success, tests_executed, changed_files, retries, rejected, ignored_files = False, False, 0, 0, 0, 0
                        detail = f"{type(exc).__name__}: {exc}"
                    elapsed = time.perf_counter() - started
                    usage = provider.reported_usage
                    token_source = "provider_usage" if usage is not None else "character_estimate"
                    token_count = (
                        usage["total_tokens"] if usage is not None else provider.estimated_tokens
                    )
                    records.append({
                        "benchmark_version": BENCHMARK_VERSION,
                        "task_id": task.task_id,
                        "task_goal": task.goal,
                        "repeat": repeat,
                        "mode": mode,
                        "provider": provider.name,
                        "model": provider.model,
                        "success": success,
                        "tests_executed": tests_executed,
                        "tests_passed": success if tests_executed else None,
                        "changed_files": changed_files,
                        "ignored_files": ignored_files,
                        "retry_count": retries,
                        "reviewer_rejections": rejected,
                        "provider_calls": provider.calls,
                        "usage_calls": provider.usage_calls,
                        "reported_usage": usage,
                        "token_count": token_count,
                        "token_source": token_source,
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
        f"- Benchmark version: `{BENCHMARK_VERSION}`; task count: `{len(tasks)}`; repeats: `{repeats}`",
        "- Provider/model: `"
        + ", ".join(
            sorted({item["provider"] + "/" + item["model"] for item in records})
        )
        + "`",
        "- 优先记录 Provider 响应返回的 token usage；缺失时按字符数除以 4 估算。usage 是响应报告值，不保证覆盖被重试请求等所有计费情况。",
        "- 每条任务在独立临时项目中运行；生成的改动只进入隔离测试副本。",
        "",
        "| 模式 | 成功率 | 测试通过率 | 平均 token | 用量来源 | 平均耗时(s) | 平均改动文件 | 忽略文件 | 平均重试 | Reviewer 驳回 |",
        "|---|---:|---:|---:|---|---:|---:|---:|---:|---:|",
    ]
    for mode in modes:
        group = [item for item in records if item["mode"] == mode]
        if not group:
            continue
        count = len(group)
        sources = {item["token_source"] for item in group}
        source_label = (
            "Provider usage" if sources == {"provider_usage"}
            else "字符估算" if sources == {"character_estimate"}
            else "混合"
        )
        lines.append(
            f"| {mode} | {sum(x['success'] for x in group)}/{count} | "
            f"{sum(bool(x['tests_passed']) for x in group)}/{sum(x['tests_executed'] for x in group)} | "
            f"{sum(x['token_count'] for x in group) / count:.1f} | {source_label} | "
            f"{sum(x['latency_seconds'] for x in group) / count:.3f} | "
            f"{sum(x['changed_files'] for x in group) / count:.2f} | "
            f"{sum(x['ignored_files'] for x in group)} | "
            f"{sum(x['retry_count'] for x in group) / count:.2f} | "
            f"{sum(x['reviewer_rejections'] for x in group)} |"
        )
    lines.extend(["", f"原始记录：`{raw_path.name}`", "", "## 逐任务结果", ""])
    for item in records:
        lines.append(
            f"- `{item['mode']}` / `{item['task_id']}`: "
            f"{'通过' if item['success'] else '失败'}，{item['latency_seconds']}s，"
            f"{item['token_count']} tokens ({item['token_source']})，"
            f"Provider 调用 {item['provider_calls']} 次。"
        )
        if item["detail"]:
            lines.append(f"  - {_short_detail(item['detail'])}")
    write_text(report_path, "\n".join(lines) + "\n")
    return report_path
