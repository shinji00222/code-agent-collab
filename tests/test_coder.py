from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from code_agent_collab.agents.base import AgentContext
from code_agent_collab.agents.coder import CoderAgent
from code_agent_collab.providers import AIProvider


class CapturingProvider(AIProvider):
    name = "capture"

    def __init__(self) -> None:
        self.user_prompts: list[str] = []

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        del system_prompt
        self.user_prompts.append(user_prompt)
        return """## 修改文件清单
- src/example.py（修改）
## 修改原因
根据上下文补充示例实现。
## 建议代码
### src/example.py
def answer():
    return 42
## 测试方法
运行 python -m unittest discover -s tests。
## 风险
示例改动风险低。
"""


class CoderAgentTests(unittest.TestCase):
    def test_coder_prompt_embeds_context_pack_excerpt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context_pack = root / "logs" / "context-packs" / "task.md"
            context_pack.parent.mkdir(parents=True)
            context_pack.write_text(
                "# 任务上下文包\n\n"
                "## 相关代码文件\n"
                "- src/example.py：选择原因：任务命中 example。\n\n"
                "## 代码文件摘录\n"
                "### src/example.py\n"
                "```python\n"
                "def answer():\n"
                "    return 41\n"
                "```\n",
                encoding="utf-8",
            )
            context = AgentContext(
                project_root=root,
                task_goal="修正 example answer",
                task_id="task",
                context_pack_path=context_pack,
            )
            provider = CapturingProvider()

            CoderAgent(provider=provider).run(context, [])

            self.assertEqual(len(provider.user_prompts), 1)
            prompt = provider.user_prompts[0]
            self.assertIn("参考上下文包路径：", prompt)
            self.assertIn("参考上下文包内容摘录：", prompt)
            self.assertIn("## 相关代码文件", prompt)
            self.assertIn("def answer():", prompt)


if __name__ == "__main__":
    unittest.main()
