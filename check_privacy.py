#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
开源前隐私自检：
1) 检查敏感文件是否被 .gitignore 覆盖
2) 检查敏感文件是否已被 Git 跟踪
3) 扫描已跟踪文件中的疑似密钥/金额信息
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple


SENSITIVE_PATTERNS = [
    "current_position.md",
    ".env",
    "portfolio_snapshot.json",
    "us_snapshot.json",
    "test_snapshot.json",
    "report/*.md",
]

SECRET_REGEXES: List[Tuple[str, re.Pattern[str]]] = [
    ("api_key", re.compile(r"(?i)\b(api[_-]?key|token|secret)\b\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{8,}")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----")),
    ("aws_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
]

MONEY_REGEXES: List[Tuple[str, re.Pattern[str]]] = [
    ("cash_cny_field", re.compile(r"现金（CNY）.*`?\s*\d+(?:\.\d+)?\s*万`?")),
    ("amount_cny_column", re.compile(r"\bAmount_CNY_10k\b")),
    ("amount_usd_column", re.compile(r"\bAmount_USD_k\b")),
]

SCAN_SUFFIXES = {".md", ".py", ".toml", ".yaml", ".yml", ".json", ".txt", ".env"}
SCAN_MAX_BYTES = 2 * 1024 * 1024


def run_git(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        text=True,
        capture_output=True,
        check=False,
    )


def git_root() -> Path:
    cp = run_git(["rev-parse", "--show-toplevel"])
    if cp.returncode != 0:
        raise RuntimeError("当前目录不是 Git 仓库，无法执行隐私自检。")
    return Path(cp.stdout.strip())


def relpath(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def is_ignored(path: Path, root: Path) -> bool:
    cp = run_git(["check-ignore", "-q", relpath(path, root)])
    return cp.returncode == 0


def tracked_files(root: Path) -> List[Path]:
    cp = run_git(["ls-files"])
    if cp.returncode != 0:
        return []
    files = []
    for line in cp.stdout.splitlines():
        p = (root / line.strip()).resolve()
        if p.exists() and p.is_file():
            files.append(p)
    return files


def untracked_not_ignored_files(root: Path) -> List[Path]:
    cp = run_git(["ls-files", "--others", "--exclude-standard"])
    if cp.returncode != 0:
        return []
    files = []
    for line in cp.stdout.splitlines():
        p = (root / line.strip()).resolve()
        if p.exists() and p.is_file():
            files.append(p)
    return files


def expand_sensitive_matches(root: Path) -> List[Path]:
    matched: List[Path] = []
    for pattern in SENSITIVE_PATTERNS:
        for p in root.glob(pattern):
            if p.is_file():
                matched.append(p.resolve())
    uniq = sorted(set(matched))
    return uniq


def read_text_safe(path: Path) -> str:
    try:
        if path.stat().st_size > SCAN_MAX_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def should_scan(path: Path) -> bool:
    if path.suffix.lower() in SCAN_SUFFIXES:
        return True
    if path.name == ".env":
        return True
    return False


def scan_regex(path: Path, regexes: Iterable[Tuple[str, re.Pattern[str]]]) -> List[str]:
    text = read_text_safe(path)
    if not text:
        return []
    hits: List[str] = []
    for label, rx in regexes:
        if rx.search(text):
            hits.append(label)
    return hits


def main() -> int:
    try:
        root = git_root()
    except RuntimeError as e:
        print(f"ERROR: {e}")
        return 2

    tracked = tracked_files(root)
    tracked_set = {p.resolve() for p in tracked}
    untracked_not_ignored = set(untracked_not_ignored_files(root))

    sensitive_files = expand_sensitive_matches(root)
    sensitive_tracked = [p for p in sensitive_files if p in tracked_set]
    sensitive_unignored = [p for p in sensitive_files if not is_ignored(p, root)]

    secret_hits: List[Tuple[Path, List[str]]] = []
    money_hits: List[Tuple[Path, List[str]]] = []
    for p in tracked:
        if not should_scan(p):
            continue
        s_hits = scan_regex(p, SECRET_REGEXES)
        if s_hits:
            secret_hits.append((p, s_hits))
        m_hits = scan_regex(p, MONEY_REGEXES)
        if m_hits:
            money_hits.append((p, m_hits))

    print("=== Privacy Check Report ===")
    print(f"repo: {root}")
    print("")

    risk_fail = False

    print("[1] 敏感文件检查")
    if not sensitive_files:
        print("- 未发现预置敏感文件。")
    else:
        for p in sensitive_files:
            rp = relpath(p, root)
            ignored = is_ignored(p, root)
            state = "ignored" if ignored else "NOT_IGNORED"
            print(f"- {rp}: {state}")

    if sensitive_tracked:
        risk_fail = True
        print("! 高风险：以下敏感文件已被 Git 跟踪（开源前应移出版本控制）")
        for p in sensitive_tracked:
            print(f"  - {relpath(p, root)}")

    if sensitive_unignored:
        risk_fail = True
        print("! 风险：以下敏感文件未被 .gitignore 覆盖")
        for p in sensitive_unignored:
            print(f"  - {relpath(p, root)}")

    print("")
    print("[2] 已跟踪文件内容检查（疑似密钥）")
    if not secret_hits:
        print("- 未发现明显密钥特征。")
    else:
        risk_fail = True
        for p, labels in secret_hits:
            print(f"- {relpath(p, root)}: {', '.join(labels)}")

    print("")
    print("[3] 已跟踪文件内容检查（疑似金额/持仓字段）")
    if not money_hits:
        print("- 未发现明显金额持仓字段。")
    else:
        for p, labels in money_hits:
            print(f"- {relpath(p, root)}: {', '.join(labels)}")

    print("")
    print("[4] 当前未跟踪且未忽略文件（可能被误提交）")
    if not untracked_not_ignored:
        print("- 无。")
    else:
        for p in sorted(untracked_not_ignored):
            print(f"- {relpath(p, root)}")

    print("")
    if risk_fail:
        print("RESULT: FAIL（存在开源前需处理的隐私风险）")
        return 1
    print("RESULT: PASS（未发现高风险项）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
