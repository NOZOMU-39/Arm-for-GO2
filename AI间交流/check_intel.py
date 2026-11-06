#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""情报站自检：目录页 ↔ 分册、每册唯一「最后更新」、Markdown 内链可解析。

用法：
    python AI间交流/check_intel.py
    python AI间交流/check_intel.py --root AI间交流

退出码：0 = 通过；1 = 有问题。
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import unquote

DATE_LINE = re.compile(r"^最后更新：(\d{4}-\d{2}-\d{2})\s*$")
MD_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
BOOK_NAME = re.compile(r"^\d{2}_.+\.md$")
SKIP_PREFIX = ("http://", "https://", "mailto:", "#")


def read_utf8(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def check_date_line(path: Path, text: str, errors: list[str]) -> None:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("最后更新：")]
    if len(lines) != 1:
        errors.append(f"{path}: 「最后更新」应恰好 1 行，实际 {len(lines)} 行")
        return
    m = DATE_LINE.match(lines[0])
    if not m:
        errors.append(f"{path}: 日期格式不是「最后更新：YYYY-MM-DD」: {lines[0]!r}")
        return
    try:
        date.fromisoformat(m.group(1))
    except ValueError:
        errors.append(f"{path}: 日期非法: {m.group(1)}")


def check_links(path: Path, text: str, errors: list[str]) -> None:
    for m in MD_LINK.finditer(text):
        raw = m.group(1).strip()
        if raw.startswith("<") and raw.endswith(">"):
            raw = raw[1:-1].strip()
        target = raw.split("#", 1)[0].strip()
        if not target or target.startswith(SKIP_PREFIX):
            continue
        target = unquote(target).replace("\\", "/")
        resolved = (path.parent / target).resolve()
        if not resolved.exists():
            errors.append(f"{path}: 内链不存在: {raw}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=None, help="AI间交流 目录；默认脚本所在目录")
    args = parser.parse_args()
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent
    index = root / "情报.md"
    books_dir = root / "情报"
    errors: list[str] = []

    if not index.is_file():
        print(f"FAIL: 目录页不存在: {index}")
        return 1
    if not books_dir.is_dir():
        print(f"FAIL: 分册目录不存在: {books_dir}")
        return 1

    index_text = read_utf8(index)
    check_date_line(index, index_text, errors)
    check_links(index, index_text, errors)

    # 目录表：| [册](情报/xx.md) | ... |
    listed: list[Path] = []
    table_rows = 0
    for line in index_text.splitlines():
        if not line.startswith("| ["):
            continue
        table_rows += 1
        m = MD_LINK.search(line)
        if not m:
            errors.append(f"{index}: 目录表行没有链接: {line.strip()}")
            continue
        raw = m.group(1).strip()
        if raw.startswith("<") and raw.endswith(">"):
            raw = raw[1:-1].strip()
        target = (index.parent / unquote(raw).replace("\\", "/")).resolve()
        if not target.is_file():
            errors.append(f"{index}: 目录表链接不存在: {raw}")
            continue
        if target.parent != books_dir.resolve():
            errors.append(f"{index}: 目录表链接不在 情报/ 下: {raw}")
            continue
        listed.append(target)

    # 表头不应再有「最后更新」列（各册日期只在册内）
    header_line = next((ln for ln in index_text.splitlines() if ln.startswith("| 册 |")), "")
    if "最后更新" in header_line:
        errors.append(f"{index}: 目录表仍有「最后更新」列，应删除（各册日期只在册内）")

    # 反向：情报/ 下每个 01..99 分册都应在目录表里
    books = sorted(p for p in books_dir.glob("*.md") if BOOK_NAME.match(p.name))
    listed_set = {p.name for p in listed}
    book_set = {p.name for p in books}
    for name in sorted(book_set - listed_set):
        errors.append(f"{index}: 分册 {name} 未列入目录表")
    for name in sorted(listed_set - book_set):
        errors.append(f"{index}: 目录表列了不存在的分册 {name}")
    if len(listed) != len(set(listed)):
        errors.append(f"{index}: 目录表有重复分册")

    # 每册：唯一日期 + 内链
    for book in books:
        text = read_utf8(book)
        check_date_line(book, text, errors)
        check_links(book, text, errors)

    # 99 的原文口径：git 取回，不搬原文
    n99 = books_dir / "99_变更记录.md"
    if n99.is_file():
        t99 = read_utf8(n99)
        if "git show" not in t99:
            errors.append(f"{n99}: 缺少「git show」原文取回说明")
        if "被覆写/删除原文的存档" in t99:
            errors.append(f"{n99}: 仍写「原文存档」，应改为「摘要 + commit」")

    if errors:
        print(f"FAIL: {len(errors)} 项")
        for e in errors:
            print(" - " + e)
        return 1

    print(f"OK: 目录页 1 个、分册 {len(books)} 个、目录表 {table_rows} 行；日期与内链均通过。")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
