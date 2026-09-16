from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from code_agent_collab.mcp_bridge import (
    TOOL_CALL_FENCE,
    ToolCallParseError,
    ToolCallRequest,
    McpServerSpec,
    McpToolRegistry,
    default_python_command,
    parse_tool_call,
    run_tool_loop,
)
from code_agent_collab.providers import AIProvider

FIXTURE = Path(__file__).parent / "fixtures" / "fake_mcp_server.py"


def call_block(tool: str, arguments: dict) -> str:
    payload = json.dumps({"tool": tool, "arguments": arguments}, ensure_ascii=False)
    return f"```{TOOL_CALL_FENCE}\n{payload}\n```"


class ScriptedProvider(AIProvider):
    """按脚本依次返回预设回复，用来离线驱动工具循环。"""

    name = "scripted"

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[str, str]] = []

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        if not self.replies:
            raise AssertionError("ScriptedProvider 的预设回复已用尽")
        return self.replies.pop(0)


def registry() -> McpToolRegistry:
    return McpToolRegistry(
        [
            McpServerSpec(
                name="fake",
                command=tuple(default_python_command(FIXTURE)),
                env={"FAKE_MCP_MODE": "normal"},
                timeout_seconds=15.0,
            )
        ]
    )


class ParseToolCallTests(unittest.TestCase):
    def test_plain_text_is_not_a_tool_call(self) -> None:
        self.assertIsNone(parse_tool_call("这是最终答复，没有工具调用。"))
        self.assertIsNone(parse_tool_call(""))

    def test_valid_block_is_parsed(self) -> None:
        request = parse_tool_call(call_block("fake.echo", {"text": "hi"}))
        self.assertEqual(request, ToolCallRequest(tool="fake.echo", arguments={"text": "hi"}))

    def test_missing_arguments_defaults_to_empty_object(self) -> None:
        text = f'```{TOOL_CALL_FENCE}\n{{"tool": "fake.echo"}}\n```'
        self.assertEqual(parse_tool_call(text).arguments, {})

    def test_invalid_json_raises_parse_error(self) -> None:
        with self.assertRaises(ToolCallParseError):
            parse_tool_call(f"```{TOOL_CALL_FENCE}\nnot json\n```")

    def test_missing_tool_field_raises_parse_error(self) -> None:
        with self.assertRaises(ToolCallParseError):
            parse_tool_call(f'```{TOOL_CALL_FENCE}\n{{"arguments": {{}}}}\n```')

    def test_non_object_arguments_raises_parse_error(self) -> None:
        with self.assertRaises(ToolCallParseError):
            parse_tool_call(f'```{TOOL_CALL_FENCE}\n{{"tool": "a", "arguments": [1,2]}}\n```')


class ToolLoopTests(unittest.TestCase):
    def test_loop_returns_final_answer_without_tools(self) -> None:
        provider = ScriptedProvider(["直接回答，无需工具。"])
        with registry() as tools:
            result = run_tool_loop(provider, "系统提示", "任务目标", tools)
        self.assertEqual(result.text, "直接回答，无需工具。")
        self.assertEqual(result.stop_reason, "final")
        self.assertFalse(result.used_tools)
        self.assertEqual(result.rounds, 1)

    def test_loop_executes_tool_then_returns_final_answer(self) -> None:
        provider = ScriptedProvider(
            [call_block("fake.echo", {"text": "hello"}), "根据工具结果，答案是 hello。"]
        )
        with registry() as tools:
            result = run_tool_loop(provider, "系统提示", "任务目标", tools)

        self.assertEqual(result.stop_reason, "final")
        self.assertTrue(result.used_tools)
        self.assertEqual(result.rounds, 2)
        self.assertEqual(result.calls[0].tool, "fake.echo")
        self.assertTrue(result.calls[0].ok)
        self.assertEqual(result.calls[0].output, "echo: hello")
        # 工具结果必须回灌给下一轮
        self.assertIn("echo: hello", provider.calls[1][1])
        # 系统提示必须包含工具协议说明与工具清单
        self.assertIn(TOOL_CALL_FENCE, provider.calls[0][0])
        self.assertIn("fake.echo", provider.calls[0][0])

    def test_loop_stops_at_max_rounds(self) -> None:
        provider = ScriptedProvider([call_block("fake.echo", {"text": str(i)}) for i in range(5)])
        with registry() as tools:
            result = run_tool_loop(provider, "系统", "目标", tools, max_rounds=2)
        self.assertEqual(result.stop_reason, "max_rounds")
        self.assertEqual(result.rounds, 2)
        self.assertEqual(len(result.calls), 2)

    def test_loop_feeds_back_tool_execution_error(self) -> None:
        provider = ScriptedProvider([call_block("fake.fail", {}), "工具失败了，我说明原因。"])
        with registry() as tools:
            result = run_tool_loop(provider, "系统", "目标", tools)
        self.assertFalse(result.calls[0].ok)
        self.assertIn("isError", result.calls[0].detail)
        self.assertIn("上游 API 限流", provider.calls[1][1])

    def test_loop_feeds_back_unknown_tool_error(self) -> None:
        """工具名不存在时由注册表本地拦截（不必往返服务端），失败也要回灌给模型。"""
        provider = ScriptedProvider([call_block("fake.nope", {}), "换一种方式回答。"])
        with registry() as tools:
            result = run_tool_loop(provider, "系统", "目标", tools)
        self.assertFalse(result.calls[0].ok)
        self.assertIn("找不到工具", result.calls[0].detail)
        self.assertIn("调用失败", provider.calls[1][1])

    def test_loop_retries_after_malformed_tool_block(self) -> None:
        provider = ScriptedProvider(
            [f"```{TOOL_CALL_FENCE}\n{{oops\n```", "格式修正后的最终答复。"]
        )
        with registry() as tools:
            result = run_tool_loop(provider, "系统", "目标", tools)
        self.assertEqual(result.text, "格式修正后的最终答复。")
        self.assertEqual(result.rounds, 2)
        self.assertEqual(result.calls, [])
        self.assertIn("格式非法", provider.calls[1][1])

    def test_denied_call_is_recorded_and_not_executed(self) -> None:
        provider = ScriptedProvider([call_block("fake.echo", {"text": "x"}), "被拒绝了，我换方案。"])
        with registry() as tools:
            result = run_tool_loop(
                provider,
                "系统",
                "目标",
                tools,
                allow_call=lambda request: False,
            )
        self.assertEqual(len(result.calls), 1)
        self.assertFalse(result.calls[0].ok)
        self.assertIn("未获授权", result.calls[0].detail)
        self.assertEqual(result.calls[0].output, "")
        self.assertIn("需要人工确认", provider.calls[1][1])

    def test_allow_call_receives_request_details(self) -> None:
        seen: list[ToolCallRequest] = []

        def allow(request: ToolCallRequest) -> bool:
            seen.append(request)
            return True

        provider = ScriptedProvider([call_block("fake.echo", {"text": "y"}), "完成。"])
        with registry() as tools:
            run_tool_loop(provider, "系统", "目标", tools, allow_call=allow)
        self.assertEqual(seen[0].tool, "fake.echo")
        self.assertEqual(seen[0].arguments, {"text": "y"})

    def test_long_observation_is_truncated(self) -> None:
        long_text = "A" * 500
        provider = ScriptedProvider([call_block("fake.echo", {"text": long_text}), "好了。"])
        with registry() as tools:
            run_tool_loop(provider, "系统", "目标", tools, max_observation_chars=50)
        self.assertIn("已截断", provider.calls[1][1])

    def test_evidence_lines_summarize_calls(self) -> None:
        provider = ScriptedProvider([call_block("fake.echo", {"text": "z"}), "完成。"])
        with registry() as tools:
            result = run_tool_loop(provider, "系统", "目标", tools)
        lines = result.evidence_lines()
        self.assertEqual(len(lines), 1)
        self.assertIn("fake.echo", lines[0])
        self.assertIn("成功", lines[0])

    def test_max_rounds_must_be_positive(self) -> None:
        provider = ScriptedProvider(["x"])
        with registry() as tools:
            with self.assertRaises(ValueError):
                run_tool_loop(provider, "系统", "目标", tools, max_rounds=0)


if __name__ == "__main__":
    unittest.main()
