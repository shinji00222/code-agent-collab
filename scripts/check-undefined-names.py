"""静态检查：找出「引用了但没定义、也没导入」的模块级全局名字。

为什么需要它：v0.17.4 / v0.17.5 把 `webui.py` 拆成 `web_jobs.py`、`web_project.py`
等模块后，出现过 `run_cli()` 里用了未导入的 `Path` 与 `CLI_EXE_NAME` 这类残留。
这种错误 `py_compile` 和 unittest 都抓不到——只有真的走到那一行才会抛 `NameError`，
而它偏偏只在打包（frozen）分支上，普通测试永远走不到。

用 `symtable` 按作用域扫描：某个函数里引用了「既不是本函数局部变量、也不是外层
闭包变量」的名字，却又不属于模块级绑定或内置名字，就报出来。

用法：
    python scripts/check-undefined-names.py            # 默认扫 src
    python scripts/check-undefined-names.py src tests  # 指定多个目录

退出码：0 = 干净，1 = 发现问题。

已知误报：`__file__` 这类模块级 dunder 会被当作「未绑定」，已在输出里过滤。
"""
from __future__ import annotations

import builtins
import symtable
import sys
from pathlib import Path

IGNORED_NAMES = {"__file__", "__name__", "__doc__", "__package__", "__spec__", "__loader__"}


def module_bindings(table: symtable.SymbolTable) -> set[str]:
    """模块作用域里真正被绑定的名字：赋值、导入、def/class、参数。"""
    names = set()
    for symbol in table.get_symbols():
        if (
            symbol.is_assigned()
            or symbol.is_imported()
            or symbol.is_namespace()
            or symbol.is_parameter()
        ):
            names.add(symbol.get_name())
    return names


def walk(
    table: symtable.SymbolTable,
    module_names: set[str],
    findings: list[tuple[str, str, str]],
    relative: str,
) -> None:
    for symbol in table.get_symbols():
        name = symbol.get_name()
        if not symbol.is_global():
            continue
        if name in IGNORED_NAMES or name in module_names or hasattr(builtins, name):
            continue
        findings.append((relative, table.get_name(), name))
    for child in table.get_children():
        walk(child, module_names, findings, relative)


def check(target: Path) -> tuple[int, list[tuple[str, str, str]]]:
    findings: list[tuple[str, str, str]] = []
    checked = 0
    root = target if target.is_dir() else target.parent
    for path in sorted(target.rglob("*.py") if target.is_dir() else [target]):
        if "__pycache__" in path.parts:
            continue
        checked += 1
        source = path.read_text(encoding="utf-8")
        table = symtable.symtable(source, str(path), "exec")
        walk(table, module_bindings(table), findings, str(path.relative_to(root)))
    return checked, findings


def main(argv: list[str]) -> int:
    targets = [Path(item) for item in argv] or [Path("src")]
    total_checked = 0
    all_findings: list[tuple[str, str, str]] = []

    for target in targets:
        if not target.exists():
            print(f"跳过不存在的路径：{target}")
            continue
        checked, findings = check(target)
        total_checked += checked
        all_findings.extend(findings)

    print(f"checked {total_checked} files")
    if not all_findings:
        print("OK: 没有「引用了但未定义」的全局名字")
        return 0

    print(f"FOUND {len(all_findings)}:")
    for relative, scope, name in all_findings:
        print(f"  {relative}: scope {scope} -> 未定义名字 {name}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
