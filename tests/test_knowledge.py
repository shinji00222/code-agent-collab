from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from code_agent_collab.agents import AgentContext, KnowledgeAgent
from code_agent_collab.knowledge import extract_keywords, search_knowledge


class KeywordTests(unittest.TestCase):
    def test_extract_keywords_filters_stopwords(self) -> None:
        keywords = extract_keywords("请帮我测试DeepSeek真实调用")
        self.assertIn("DeepSeek", keywords)
        self.assertIn("真实调用", keywords)
        self.assertNotIn("请", keywords)
        self.assertNotIn("测试", keywords)

    def test_extract_keywords_returns_empty_for_stopwords_only(self) -> None:
        self.assertEqual(extract_keywords("请帮我做一下测试"), [])


class SearchKnowledgeTests(unittest.TestCase):
    def test_search_finds_matching_markdown_and_skips_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            (vault / "00-系统").mkdir(parents=True)
            (vault / "99-附件").mkdir()
            (vault / "01-项目").mkdir()
            (vault / ".obsidian").mkdir()
            (vault / "00-系统" / "踩坑.md").write_text(
                "# 踩坑\n\nDeepSeek 模型名要写 deepseek-chat", encoding="utf-8"
            )
            (vault / "99-附件" / "图片说明.md").write_text(
                "DeepSeek 相关内容", encoding="utf-8"
            )
            (vault / "01-项目" / "源码笔记.md").write_text(
                "DeepSeek 相关内容", encoding="utf-8"
            )
            (vault / ".obsidian" / "配置.md").write_text(
                "DeepSeek 相关内容", encoding="utf-8"
            )

            hits = search_knowledge(vault, ["DeepSeek"])

            self.assertEqual(len(hits), 1)
            self.assertIn("踩坑.md", hits[0].path)
            self.assertIn("deepseek-chat", hits[0].excerpt)

    def test_search_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            (vault / "00-系统").mkdir(parents=True)
            note = vault / "00-系统" / "经验.md"
            note.write_text("# 经验\n\n关于 Agent 协作", encoding="utf-8")
            before = note.read_text(encoding="utf-8")

            search_knowledge(vault, ["Agent"])

            self.assertEqual(note.read_text(encoding="utf-8"), before)
            self.assertEqual(sorted(item.name for item in vault.rglob("*")), ["00-系统", "经验.md"])

    def test_search_missing_base_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hits = search_knowledge(Path(tmp) / "不存在", ["DeepSeek"])
        self.assertEqual(hits, [])

    def test_search_empty_keywords_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hits = search_knowledge(Path(tmp), [])
        self.assertEqual(hits, [])


class KnowledgeAgentTests(unittest.TestCase):
    def test_agent_writes_knowledge_note_and_stays_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            project_root.mkdir()
            docs_dir = project_root / "product-docs"
            docs_dir.mkdir()
            (docs_dir / "项目定义.md").write_text("多 Agent 测试", encoding="utf-8")

            vault = Path(tmp) / "vault"
            (vault / "00-系统").mkdir(parents=True)
            (vault / "00-系统" / "经验.md").write_text(
                "# 经验\n\nDeepSeek 调用经验", encoding="utf-8"
            )
            context = AgentContext(
                project_root=project_root,
                task_goal="DeepSeek 调用经验",
                task_id="20260820-000000-test",
                context_pack_path=project_root / "logs" / "context-packs" / "20260820-000000-test.md",
            )

            result = KnowledgeAgent(base_path=vault).run(context, [])

            self.assertIn("1 个", result.summary)
            knowledge_path = (
                project_root / "logs" / "context-packs" / "20260820-000000-test-knowledge.md"
            )
            self.assertTrue(knowledge_path.exists())
            content = knowledge_path.read_text(encoding="utf-8")
            self.assertIn("经验.md", content)
            self.assertIn("只读检索", content)
            self.assertEqual(len(list(vault.rglob("*.md"))), 1)

    def test_agent_no_hits_does_not_write_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            project_root.mkdir()
            vault = Path(tmp) / "vault"
            (vault / "00-系统").mkdir(parents=True)
            (vault / "00-系统" / "无关.md").write_text("无关内容", encoding="utf-8")
            context = AgentContext(
                project_root=project_root,
                task_goal="完全不存在的主题词",
                task_id="20260820-000001-test",
                context_pack_path=project_root / "logs" / "context-packs" / "20260820-000001-test.md",
            )

            result = KnowledgeAgent(base_path=vault).run(context, [])

            self.assertIn("未检索到", result.summary)
            self.assertFalse(
                (project_root / "logs" / "context-packs" / "20260820-000001-test-knowledge.md").exists()
            )


if __name__ == "__main__":
    unittest.main()
