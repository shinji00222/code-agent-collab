from __future__ import annotations

import argparse
from pathlib import Path

from .config import save_default_config
from .context_pack import create_context_pack


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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    project_root = Path(args.project_root).resolve()

    if args.command == "init":
        path = save_default_config(project_root)
        print(f"已生成配置文件：{path}")
        return 0

    if args.command == "start":
        result = create_context_pack(project_root, args.goal)
        print(f"已生成任务上下文包：{result.output_path}")
        print(f"任务ID：{result.task_id}")
        return 0

    parser.error("未知命令")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
