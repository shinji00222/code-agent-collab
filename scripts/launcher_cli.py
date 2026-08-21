# PyInstaller 入口：CLI（不能直接用包内 cli.py，相对导入会失败）
from code_agent_collab.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
