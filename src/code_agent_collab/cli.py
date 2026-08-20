from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .config import save_default_config
from .context_pack import create_context_pack
from .demo import run_demo
from .reflection import create_reflection, list_pending_notes
from .providers import SUPPORTED_PROVIDERS, ProviderConfig, create_provider
from .workflow import run_workflow


def _ensure_utf8_stdio() -> None:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError):
                pass


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-workbench",
        description="Local-first multi-agent coding workbench prototype.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create local project config.")
    init_parser.add_argument(
        "--project-root",
        default=".",
        help="Project root. Defaults to current directory.",
    )

    start_parser = subparsers.add_parser("start", help="Create a task context pack.")
    start_parser.add_argument("goal", help="Task goal.")
    start_parser.add_argument(
        "--project-root",
        default=".",
        help="Project root. Defaults to current directory.",
    )

    reflect_parser = subparsers.add_parser("reflect", help="Create a pending compounding note.")
    reflect_parser.add_argument(
        "--task",
        default=None,
        help="Task id or keyword. Defaults to the latest context pack.",
    )
    reflect_parser.add_argument(
        "--project-root",
        default=".",
        help="Project root. Defaults to current directory.",
    )

    pending_parser = subparsers.add_parser("pending", help="List pending compounding notes.")
    pending_parser.add_argument(
        "--project-root",
        default=".",
        help="Project root. Defaults to current directory.",
    )

    demo_parser = subparsers.add_parser("demo", help="Run start, reflect, and pending in one command.")
    demo_parser.add_argument("goal", help="Task goal.")
    demo_parser.add_argument(
        "--project-root",
        default=".",
        help="Project root. Defaults to current directory.",
    )

    run_parser = subparsers.add_parser("run", help="Run the rule-based multi-agent workflow.")
    run_parser.add_argument("goal", help="Task goal.")
    run_parser.add_argument(
        "--project-root",
        default=".",
        help="Project root. Defaults to current directory.",
    )

    subparsers.add_parser("provider", help="Show the active AI provider configuration.")
    return parser


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdio()
    parser = _build_parser()
    args = parser.parse_args(argv)
    project_root = Path(getattr(args, "project_root", ".")).resolve()

    if args.command == "init":
        path = save_default_config(project_root)
        print(f"已生成配置文件：{path}")
        return 0

    if args.command == "start":
        result = create_context_pack(project_root, args.goal)
        print(f"已生成任务上下文包：{result.output_path}")
        print(f"任务ID：{result.task_id}")
        return 0

    if args.command == "reflect":
        result = create_reflection(project_root, args.task)
        print(f"已生成候选复利记录：{result.output_path}")
        print(f"来源任务ID：{result.task_id}")
        return 0

    if args.command == "pending":
        notes = list_pending_notes(project_root)
        if not notes:
            print("暂无待确认候选复利记录。")
            return 0
        print(f"待确认候选复利记录：{len(notes)} 条")
        for index, note in enumerate(notes, start=1):
            print(f"{index}. {note.title}")
            print(f"   状态：{note.status}")
            print(f"   更新时间：{note.updated_at:%Y-%m-%d %H:%M:%S}")
            print(f"   路径：{note.path}")
        return 0

    if args.command == "demo":
        result = run_demo(project_root, args.goal)
        print("已完成 demo 闭环。")
        print(f"上下文包：{result.context_pack.output_path}")
        print(f"候选复利记录：{result.reflection.output_path}")
        print(f"当前待确认候选记录：{len(result.pending_notes)} 条")
        return 0

    if args.command == "run":
        try:
            result = run_workflow(project_root, args.goal)
        except ValueError as exc:
            print(f"无法运行工作流：{exc}")
            return 2
        print("已完成多 Agent 工作流。")
        print(f"任务ID：{result.task_id}")
        print(f"上下文包：{result.context_pack.output_path}")
        print(f"工作流日志：{result.workflow_log_path}")
        print(f"候选复利记录：{result.reflection.output_path}")
        print("Agent 顺序：" + " -> ".join(item.role for item in result.agent_results))
        return 0

    if args.command == "provider":
        config = ProviderConfig.from_env()
        provider = create_provider(config)
        print(f"当前 Provider：{config.name}")
        print(f"模型：{config.model or '未设置'}")
        print(f"接口地址：{config.base_url or '本地模拟，不联网'}")
        print(f"密钥环境变量：{config.api_key_env or '未配置'}")
        key_configured = bool(config.api_key_env and os.getenv(config.api_key_env))
        print(f"密钥状态：{'已配置' if key_configured else '未配置'}")
        print("可用 Provider：" + ", ".join(SUPPORTED_PROVIDERS))
        print("切换示例：$env:AGENT_WORKBENCH_PROVIDER='deepseek'")
        return 0

    parser.error("未知命令")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
