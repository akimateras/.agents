#!/usr/bin/env python3
"""Deterministic filesystem checks for the Longneck skill suite."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator


TITLE_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
STALE_CREATE_PATTERN = re.compile(r"^\.[a-z0-9]+(?:-[a-z0-9]+)*\.tmp-")
# Temp directories younger than this may belong to an in-flight create;
# neither list nor clean-stale treats them as stale.
STALE_CREATE_MIN_AGE_SECONDS = 3600
TASK_ID_PATTERN = re.compile(r"^### (T-[0-9]{4,})\b")
TASK_HEADING_NAME_PATTERN = re.compile(r"^### (T-[0-9]{4,})(?: — (.+))?$")
DEPENDENCY_LINE_PATTERN = re.compile(r"^- 依存関係:\s*(.*)$")
# Lookarounds instead of \b: Japanese prose around an ID ("T-0002の完了後")
# has no ASCII word boundary, so \b would silently drop the reference.
TASK_REF_PATTERN = re.compile(r"(?<![A-Za-z0-9-])T-[0-9]{4,}(?![0-9])")
# Only なし or a pure separator-delimited ID list is machine-judged runnable;
# prose mixed with IDs may hide extra preconditions the IDs cannot express.
DEPENDENCY_SEPARATOR_PATTERN = re.compile(r"[\s,、。]+")
DEPENDENCY_ID_PATTERN = re.compile(r"T-[0-9]{4,}")
# Any ID mentioned anywhere in its source documents counts as used, including
# retired IDs in 管理作業 log entries and both endpoints of a range notation.
ID_REF_PATTERNS = {
    prefix: re.compile(rf"(?<![A-Za-z0-9-]){prefix}-([0-9]{{4,}})(?![0-9])")
    for prefix in ("T", "D", "I")
}
# Documents scanned per ID prefix; completed tasks and resolved issues vanish
# from state.md / issues.md, so the work log (and its archive) is what keeps
# retired IDs from being reused.
ID_SOURCE_FILES = {
    "T": ("state.md", "progress.md"),
    "D": ("progress.md",),
    "I": ("issues.md", "progress.md"),
}
NO_DEPENDENCY_VALUES = frozenset(("なし", "なし。"))
WORK_LOG_HEADING_PATTERN = re.compile(r"^### (\S+) — (T-[0-9]{4,}|管理作業)$")
ISSUE_ID_PATTERN = re.compile(r"^### (I-[0-9]{4,})\b")
DECISION_ID_PATTERN = re.compile(r"^### (D-[0-9]{4,})\b")
# The 概要 line must be the first non-blank line after the title heading;
# a summary buried elsewhere in the document does not satisfy the format.
SUMMARY_LINE_PATTERN = re.compile(r"概要:\s*(\S.*)")
UPDATED_PATTERN = re.compile(r"^更新日時:\s*(\S+)\s*$", re.MULTILINE)
STATE_PATTERN = re.compile(
    r"^状態:\s*(active|awaiting-user|blocked|completed)\s*$", re.MULTILINE
)
STATE_SECTIONS = ("調査待ち", "判断待ち", "実行待ち", "ブロック中")
EXECUTABLE_SECTIONS = ("調査待ち", "実行待ち")
REQUIRED_FILES = ("description.md", "state.md", "progress.md", "issues.md")
REQUIRED_ENTRIES = frozenset((*REQUIRED_FILES, "docs"))
# Advisory per-title locks live outside the task directories so a sever can
# delete .longneck/<title> while its own lock is still held.
LOCKS_DIR_NAME = ".locks"
LOCK_SUFFIX = ".lock"
# Reserved docs/ file where longneck-flush parks old work-log events; retired
# IDs recorded there must keep counting toward the next-*-id commands.
WORK_LOG_ARCHIVE_NAME = "work-log-archive.md"
# Well-known dependency and cache directories the non-git backlink walk skips;
# git mode already respects .gitignore. Skipped paths are reported as "pruned"
# so callers can see what the partial safety net did not scan.
BACKLINK_WALK_PRUNE_DIRS = frozenset(
    (
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".cache",
        ".yarn",
        ".pnpm-store",
    )
)
# Bloat thresholds for the two growing documents; exceeding one is a warning
# that longneck-flush may be worth proposing, mirroring description.md's caps.
DOCUMENT_SIZE_LIMITS = {
    "state.md": (300, 16 * 1024, "16 KiB"),
    "progress.md": (800, 64 * 1024, "64 KiB"),
}


class LongneckError(RuntimeError):
    """Raised when a Longneck operation cannot be performed safely."""


@dataclass(frozen=True)
class ValidationResult:
    title: str
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    summary: str | None
    lifecycle: str | None
    counts: dict[str, int]
    updated: str | None = None
    sizes: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "ok": self.ok,
            "summary": self.summary,
            "lifecycle": self.lifecycle,
            "updated": self.updated,
            "counts": self.counts,
            "sizes": self.sizes,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


def validate_title(title: str) -> None:
    if not TITLE_PATTERN.fullmatch(title):
        raise LongneckError(
            f"invalid title {title!r}; expected lowercase kebab-case matching "
            "^[a-z0-9]+(?:-[a-z0-9]+)*$"
        )


def _existing_directory(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise LongneckError(f"{label} must not be a symlink: {path}")
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise LongneckError(f"{label} does not exist: {path}") from exc
    if not resolved.is_dir():
        raise LongneckError(f"{label} is not a directory: {path}")
    return resolved


def resolve_root(start: Path) -> Path:
    # The start directory may be reached through symlinks; the symlink bans
    # protect .longneck and task directories, not the caller's project path.
    try:
        start_path = start.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise LongneckError(f"start directory does not exist: {start}") from exc
    if not start_path.is_dir():
        raise LongneckError(f"start directory is not a directory: {start}")
    # Check bareness before --show-toplevel: inside a bare repository
    # --show-toplevel fails, which would silently fall back to start_path.
    bare = subprocess.run(
        ["git", "-C", str(start_path), "rev-parse", "--is-bare-repository"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if bare.returncode == 0 and bare.stdout.strip() == "true":
        raise LongneckError("bare repositories do not have a Longneck working root")
    process = subprocess.run(
        ["git", "-C", str(start_path), "rev-parse", "--show-toplevel"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if process.returncode != 0:
        return start_path

    output = process.stdout.strip()
    if not output:
        raise LongneckError("git returned an empty repository root")
    return _existing_directory(Path(output), "git repository root")


def normalize_root(root: Path) -> Path:
    return _existing_directory(root, "Longneck root")


def _longneck_directory(root: Path, *, create: bool = False) -> Path:
    base = root / ".longneck"
    if os.path.lexists(base):
        if base.is_symlink():
            raise LongneckError(f".longneck must not be a symlink: {base}")
        if not base.is_dir():
            raise LongneckError(f".longneck is not a directory: {base}")
    elif create:
        base.mkdir(mode=0o755)
    return base


def task_directory(root: Path, title: str, *, require: bool = True) -> Path:
    validate_title(title)
    base = _longneck_directory(root)
    task = base / title
    if not os.path.lexists(task):
        if require:
            raise LongneckError(f"Longneck title does not exist: {title}")
        return task
    if task.is_symlink():
        raise LongneckError(f"Longneck task must not be a symlink: {task}")
    if not task.is_dir():
        raise LongneckError(f"Longneck task is not a directory: {task}")
    resolved_base = base.resolve(strict=True)
    resolved_task = task.resolve(strict=True)
    if resolved_task.parent != resolved_base:
        raise LongneckError(f"Longneck task escapes .longneck: {task}")
    return task


def _read_utf8(path: Path, errors: list[str]) -> str | None:
    if path.is_symlink():
        errors.append(f"symlink is not allowed: {path}")
        return None
    if not path.is_file():
        errors.append(f"regular file required: {path}")
        return None
    try:
        data = path.read_bytes()
    except OSError as exc:
        errors.append(f"cannot read {path}: {exc}")
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        errors.append(f"UTF-8 text required: {path}")
        return None
    if not text:
        errors.append(f"document must not be empty: {path}")
    elif not text.endswith("\n"):
        errors.append(f"document must end with a newline: {path}")
    return text


def _parse_rfc3339(value: str, label: str, errors: list[str]) -> datetime | None:
    if "T" not in value:
        errors.append(
            f"timestamp must use 'T' between date and time for {label}: {value}"
        )
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        errors.append(f"invalid RFC 3339 timestamp for {label}: {value}")
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        errors.append(f"timestamp must include an offset for {label}: {value}")
        return None
    return parsed


def now_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _unique_ids(
    text: str, pattern: re.Pattern[str], prefix: str, label: str, errors: list[str]
) -> None:
    ids: list[str] = []
    for line in text.splitlines():
        match = pattern.match(line)
        if match:
            ids.append(match.group(1))
        elif line.startswith(f"### {prefix}-"):
            errors.append(f"malformed {label} ID heading: {line.strip()}")
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        errors.append(f"duplicate {label} IDs: {', '.join(duplicates)}")


def _require_heading(text: str, heading: str, label: str, errors: list[str]) -> None:
    occurrences = text.splitlines().count(heading)
    if occurrences != 1:
        errors.append(f"{label} must contain one {heading!r} heading; found {occurrences}")


def _state_header(text: str) -> str:
    """Return the region before the first '## ' heading."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("## "):
            return "\n".join(lines[:index])
    return text


def _parse_state(
    text: str, errors: list[str]
) -> tuple[str | None, dict[str, int], str | None]:
    counts = {section: 0 for section in STATE_SECTIONS}
    current_section: str | None = None
    seen_sections: list[str] = []
    task_ids: list[str] = []

    for line in text.splitlines():
        if line.startswith("## "):
            heading = line[3:]
            current_section = heading.strip()
            if current_section in STATE_SECTIONS:
                if heading != current_section:
                    errors.append(
                        f"state section heading has surrounding whitespace: {line.rstrip()!r}"
                    )
                seen_sections.append(current_section)
            continue
        match = TASK_ID_PATTERN.match(line)
        if not match:
            if line.startswith("### T-"):
                errors.append(f"malformed task ID heading: {line.strip()}")
            continue
        task_id = match.group(1)
        task_ids.append(task_id)
        if current_section not in STATE_SECTIONS:
            errors.append(f"task {task_id} is outside a state task section")
        else:
            counts[current_section] += 1

    for section in STATE_SECTIONS:
        occurrences = seen_sections.count(section)
        if occurrences != 1:
            errors.append(f"state.md must contain one '## {section}' section; found {occurrences}")
    if seen_sections != list(STATE_SECTIONS) and all(
        seen_sections.count(section) == 1 for section in STATE_SECTIONS
    ):
        errors.append(
            "state.md task sections are out of order; expected " + ", ".join(STATE_SECTIONS)
        )

    duplicates = sorted({item for item in task_ids if task_ids.count(item) > 1})
    if duplicates:
        errors.append(f"duplicate task IDs: {', '.join(duplicates)}")

    # Both metadata lines belong to the header; matches inside task items or
    # the snapshot must not satisfy (or shadow) the required lines.
    header = _state_header(text)
    updated_value: str | None = None
    updated = UPDATED_PATTERN.search(header)
    if updated:
        updated_value = updated.group(1)
        _parse_rfc3339(updated_value, "state.md 更新日時", errors)
    elif any(line.startswith("更新日時:") for line in header.splitlines()):
        errors.append("state.md has an invalid 更新日時 line")
    else:
        errors.append("state.md is missing 更新日時")

    state_match = STATE_PATTERN.search(header)
    lifecycle = state_match.group(1) if state_match else None
    if lifecycle is None:
        errors.append("state.md is missing a valid 状態")
        return lifecycle, counts, updated_value

    executable = counts["調査待ち"] + counts["実行待ち"]
    decisions = counts["判断待ち"]
    blocked = counts["ブロック中"]
    total = executable + decisions + blocked
    expected: str
    if total == 0:
        expected = "completed"
    elif executable > 0:
        expected = "active"
    elif decisions > 0:
        expected = "awaiting-user"
    else:
        expected = "blocked"
    if lifecycle != expected:
        errors.append(
            f"state lifecycle {lifecycle!r} is inconsistent with task counts; expected {expected!r}"
        )
    return lifecycle, counts, updated_value


def _extract_tasks(text: str) -> list[dict[str, Any]]:
    """Extract task entries, raw 依存関係 values, and full bodies from state.md.

    The verbatim heading-to-end text of each item is kept as `body` so callers
    (the parent delegating to a child) can pass the exact task text without
    retranscribing it from state.md.
    """
    tasks: list[dict[str, Any]] = []
    section: str | None = None
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            current = None
            continue
        if line.startswith("### "):
            current = None
            match = TASK_HEADING_NAME_PATTERN.match(line)
            if match and section in STATE_SECTIONS:
                current = {
                    "id": match.group(1),
                    "section": section,
                    "name": match.group(2),
                    "dependencies": None,
                    "extra_dependency_lines": 0,
                    "body_lines": [line],
                }
                tasks.append(current)
            continue
        if current is not None:
            current["body_lines"].append(line)
            match = DEPENDENCY_LINE_PATTERN.match(line)
            if match:
                if current["dependencies"] is None:
                    current["dependencies"] = match.group(1).strip()
                else:
                    # A second 依存関係 line would be silently ignored by the
                    # dependency analysis, hiding preconditions; reject it.
                    current["extra_dependency_lines"] += 1
    for task in tasks:
        lines = task.pop("body_lines")
        while lines and not lines[-1].strip():
            lines.pop()
        task["body"] = "\n".join(lines)
    return tasks


def _find_dependency_cycle(edges: dict[str, list[str]]) -> list[str] | None:
    status: dict[str, int] = dict.fromkeys(edges, 0)  # 0 new, 1 on path, 2 done
    for start in edges:
        if status[start]:
            continue
        path: list[str] = [start]
        stack: list[Iterator[str]] = [iter(edges[start])]
        status[start] = 1
        while stack:
            for neighbor in stack[-1]:
                if status[neighbor] == 1:
                    return path[path.index(neighbor) :] + [neighbor]
                if status[neighbor] == 0:
                    status[neighbor] = 1
                    path.append(neighbor)
                    stack.append(iter(edges[neighbor]))
                    break
            else:
                status[path.pop()] = 2
                stack.pop()
    return None


def _is_id_only_dependency(raw: str) -> bool:
    """True when 依存関係 is a pure separator-delimited task ID list."""
    tokens = [token for token in DEPENDENCY_SEPARATOR_PATTERN.split(raw) if token]
    return bool(tokens) and all(DEPENDENCY_ID_PATTERN.fullmatch(token) for token in tokens)


def _analyze_tasks(
    tasks: list[dict[str, Any]], errors: list[str], warnings: list[str]
) -> None:
    """Annotate dependency data in place and report graph problems.

    A referenced ID that no longer exists in state.md is treated as a
    completed, satisfied dependency and only reported as a warning.
    """
    present = {task["id"] for task in tasks}
    edges: dict[str, list[str]] = {}
    for task in tasks:
        if task["name"] is None:
            warnings.append(f"task {task['id']} has no name in its heading")
        if task["section"] in EXECUTABLE_SECTIONS:
            # 判断待ち / ブロック中 items describe questions and blockers in
            # freer prose; only executable tasks must carry these two lines so
            # a delegated child never receives a task without 完了条件.
            body_lines = task["body"].splitlines()
            for key in ("目的", "完了条件"):
                if not any(line.startswith(f"- {key}:") for line in body_lines):
                    warnings.append(f"task {task['id']} has no '- {key}:' line")
        if task["extra_dependency_lines"]:
            errors.append(
                f"task {task['id']} has multiple 依存関係 lines; only the first "
                "is analyzed, so merge them into one line"
            )
        raw = task["dependencies"]
        refs = TASK_REF_PATTERN.findall(raw) if raw else []
        blocked = sorted({ref for ref in refs if ref in present and ref != task["id"]})
        unknown = sorted({ref for ref in refs if ref not in present})
        task["depends_on"] = sorted(set(refs))
        task["blocked_by"] = blocked
        task["unknown_dependencies"] = unknown
        if task["id"] in refs:
            errors.append(f"task {task['id']} depends on itself")
        for ref in unknown:
            warnings.append(
                f"task {task['id']} depends on unknown task {ref}; "
                "a removed task is treated as a satisfied dependency"
            )
        executable = task["section"] in EXECUTABLE_SECTIONS
        if raw is None:
            if executable:
                warnings.append(f"task {task['id']} has no 依存関係 line")
            task["runnable"] = None if executable else False
        elif raw in NO_DEPENDENCY_VALUES or _is_id_only_dependency(raw):
            task["runnable"] = executable and not blocked
        else:
            # Free-text dependencies cannot be judged here, even when IDs
            # appear inside the prose: the surrounding text may add
            # preconditions the IDs do not express. The caller must decide
            # from the prose in state.md.
            if refs:
                warnings.append(
                    f"task {task['id']} mixes task IDs and free text in 依存関係; "
                    "write a pure ID list or judge runnable from the prose"
                )
            task["runnable"] = None if executable else False
        edges[task["id"]] = blocked
    unlocked: dict[str, list[str]] = {task["id"]: [] for task in tasks}
    for task in tasks:
        for ref in task["blocked_by"]:
            unlocked[ref].append(task["id"])
    for task in tasks:
        task["unlocks"] = sorted(unlocked[task["id"]])
    cycle = _find_dependency_cycle(edges)
    if cycle:
        errors.append("dependency cycle: " + " -> ".join(cycle))


def _validate_log_headings(
    lines: Iterable[str], errors: list[str], *, label: str = ""
) -> None:
    """Check work-log event headings for format and newest-first ordering."""
    suffix = f" in {label}" if label else ""
    timestamps: list[datetime] = []
    for line in lines:
        if not line.startswith("### "):
            continue
        match = WORK_LOG_HEADING_PATTERN.match(line)
        if not match:
            errors.append(f"malformed work log heading{suffix}: {line.strip()}")
            continue
        parsed = _parse_rfc3339(match.group(1), f"作業ログ見出し{suffix}", errors)
        if parsed is not None:
            timestamps.append(parsed)
    for previous, current in zip(timestamps, timestamps[1:]):
        if current > previous:
            errors.append(f"work log entries must be ordered newest first{suffix}")
            break


def _validate_work_log(progress: str, errors: list[str]) -> None:
    in_log = False
    log_lines: list[str] = []
    for line in progress.splitlines():
        if line.startswith("## "):
            in_log = line[3:].strip() == "作業ログ"
            continue
        if in_log:
            log_lines.append(line)
    _validate_log_headings(log_lines, errors)


def _validate_docs(docs: Path, errors: list[str]) -> None:
    if docs.is_symlink():
        errors.append(f"docs must not be a symlink: {docs}")
        return
    if not docs.is_dir():
        errors.append(f"docs directory is required: {docs}")
        return

    for directory, directory_names, file_names in os.walk(docs, followlinks=False):
        directory_path = Path(directory)
        for name in list(directory_names):
            child = directory_path / name
            if child.is_symlink():
                errors.append(f"symlink directory is not allowed in docs: {child}")
                directory_names.remove(name)
        for name in file_names:
            path = directory_path / name
            text = _read_utf8(path, errors)
            if text is None:
                continue
            lines = text.splitlines()
            if len(lines) < 3:
                errors.append(f"docs metadata requires three opening lines: {path}")
                continue
            expected_prefixes = ("作成日時: ", "更新日時: ", "概要: ")
            for index, prefix in enumerate(expected_prefixes):
                if not lines[index].startswith(prefix) or not lines[index][len(prefix) :].strip():
                    errors.append(f"docs line {index + 1} must start with {prefix!r}: {path}")
            created = updated = None
            if lines[0].startswith(expected_prefixes[0]):
                created = _parse_rfc3339(
                    lines[0][len(expected_prefixes[0]) :].strip(),
                    f"{path} 作成日時",
                    errors,
                )
            if lines[1].startswith(expected_prefixes[1]):
                updated = _parse_rfc3339(
                    lines[1][len(expected_prefixes[1]) :].strip(),
                    f"{path} 更新日時",
                    errors,
                )
            if created is not None and updated is not None and updated < created:
                errors.append(f"docs 更新日時 must not precede 作成日時: {path}")
            if directory_path == docs and name == WORK_LOG_ARCHIVE_NAME:
                # next-*-id and flush rely on this reserved archive keeping the
                # work-log event format, so its headings are validated too.
                _validate_log_headings(
                    lines[3:], errors, label=f"docs/{WORK_LOG_ARCHIVE_NAME}"
                )


def _catalog_description(
    description: str, title: str, errors: list[str], warnings: list[str]
) -> str | None:
    """Shared description.md checks: title heading, 概要 line, size caps."""
    summary: str | None = None
    if not description.startswith(f"# {title} — タスク定義\n"):
        errors.append("description.md has an invalid title heading")
    lines = description.splitlines()
    first_body_line = next((line for line in lines[1:] if line.strip()), None)
    summary_match = (
        SUMMARY_LINE_PATTERN.fullmatch(first_body_line)
        if first_body_line is not None
        else None
    )
    if summary_match:
        summary = summary_match.group(1).strip()
    else:
        errors.append(
            "description.md must place a non-empty 概要 line directly after the title heading"
        )
    if len(description.encode("utf-8")) > 8192:
        warnings.append("description.md exceeds 8 KiB")
    if len(description.splitlines()) > 100:
        warnings.append("description.md exceeds 100 lines")
    return summary


def _catalog_state(
    state: str, title: str, errors: list[str]
) -> tuple[str | None, dict[str, int], str | None]:
    """Shared state.md checks: title heading plus header and count parsing."""
    if not state.startswith(f"# {title} — 現在の状態\n"):
        errors.append("state.md has an invalid title heading")
    return _parse_state(state, errors)


def validate_task_path(path: Path, title: str) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    summary: str | None = None
    lifecycle: str | None = None
    counts = {section: 0 for section in STATE_SECTIONS}

    if path.is_symlink():
        errors.append(f"task must not be a symlink: {path}")
        return ValidationResult(title, tuple(errors), tuple(warnings), summary, lifecycle, counts)
    if not path.is_dir():
        errors.append(f"task directory is required: {path}")
        return ValidationResult(title, tuple(errors), tuple(warnings), summary, lifecycle, counts)

    actual_entries = {entry.name for entry in path.iterdir()}
    for missing in sorted(REQUIRED_ENTRIES - actual_entries):
        errors.append(f"missing required entry: {missing}")
    for unexpected in sorted(actual_entries - REQUIRED_ENTRIES):
        errors.append(f"unexpected task-root entry: {unexpected}")

    documents: dict[str, str] = {}
    for filename in REQUIRED_FILES:
        document = _read_utf8(path / filename, errors)
        if document is not None:
            documents[filename] = document

    description = documents.get("description.md")
    if description is not None:
        summary = _catalog_description(description, title, errors, warnings)
        for heading in (
            "## 目的",
            "## スコープ",
            "## 非スコープ",
            "## 完了条件",
            "## 長期制約",
            "## 主な作業対象",
        ):
            _require_heading(description, heading, "description.md", errors)

    updated: str | None = None
    state = documents.get("state.md")
    if state is not None:
        _require_heading(state, "## 現在のスナップショット", "state.md", errors)
        lifecycle, counts, updated = _catalog_state(state, title, errors)
        _analyze_tasks(_extract_tasks(state), errors, warnings)

    progress = documents.get("progress.md")
    if progress is not None:
        if not progress.startswith(f"# {title} — 進捗\n"):
            errors.append("progress.md has an invalid title heading")
        level_two = [line[3:].strip() for line in progress.splitlines() if line.startswith("## ")]
        _require_heading(progress, "## 設計判断", "progress.md", errors)
        _require_heading(progress, "## 作業ログ", "progress.md", errors)
        if not level_two or level_two[-1] != "作業ログ":
            errors.append("progress.md must end with the '## 作業ログ' section")
        _unique_ids(progress, DECISION_ID_PATTERN, "D", "decision", errors)
        _validate_work_log(progress, errors)

    issues = documents.get("issues.md")
    if issues is not None:
        if not issues.startswith(f"# {title} — 将来の検討事項\n"):
            errors.append("issues.md has an invalid title heading")
        _require_heading(issues, "## 未解決", "issues.md", errors)
        _unique_ids(issues, ISSUE_ID_PATTERN, "I", "issue", errors)

    _validate_docs(path / "docs", errors)
    sizes = _document_sizes(documents.get("state.md"), documents.get("progress.md"))
    _size_warnings(sizes, warnings)
    return ValidationResult(
        title=title,
        errors=tuple(errors),
        warnings=tuple(warnings),
        summary=summary,
        lifecycle=lifecycle,
        counts=counts,
        updated=updated,
        sizes=sizes,
    )


def _document_sizes(
    state: str | dict[str, int] | None, progress: str | dict[str, int] | None
) -> dict[str, Any] | None:
    """Report state.md and progress.md sizes so callers can spot bloat."""
    sizes: dict[str, Any] = {}
    for filename, content in (("state.md", state), ("progress.md", progress)):
        if content is None:
            continue
        if isinstance(content, dict):
            sizes[filename] = content
            continue
        raw = content.encode("utf-8")
        sizes[filename] = {"bytes": len(raw), "lines": raw.count(b"\n")}
    return sizes or None


def _stream_sizes(path: Path) -> dict[str, int] | None:
    """Count bytes and lines without holding the whole file in memory."""
    if path.is_symlink() or not path.is_file():
        return None
    size = 0
    lines = 0
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                lines += chunk.count(b"\n")
    except OSError:
        return None
    return {"bytes": size, "lines": lines}


def _size_warnings(sizes: dict[str, Any] | None, warnings: list[str]) -> None:
    if not sizes:
        return
    for filename, (max_lines, max_bytes, bytes_label) in DOCUMENT_SIZE_LIMITS.items():
        info = sizes.get(filename)
        if info is None:
            continue
        if info["bytes"] > max_bytes:
            warnings.append(f"{filename} exceeds {bytes_label}")
        if info["lines"] > max_lines:
            warnings.append(f"{filename} exceeds {max_lines} lines")


def summarize_task_path(path: Path, title: str) -> ValidationResult:
    """Read only catalog data; do not traverse progress, issues, or docs."""
    errors: list[str] = []
    warnings: list[str] = []
    summary: str | None = None
    lifecycle: str | None = None
    counts = {section: 0 for section in STATE_SECTIONS}

    if path.is_symlink():
        errors.append(f"task must not be a symlink: {path}")
        return ValidationResult(title, tuple(errors), tuple(warnings), summary, lifecycle, counts)
    if not path.is_dir():
        errors.append(f"task directory is required: {path}")
        return ValidationResult(title, tuple(errors), tuple(warnings), summary, lifecycle, counts)

    actual_entries = {entry.name for entry in path.iterdir()}
    for missing in sorted(REQUIRED_ENTRIES - actual_entries):
        errors.append(f"missing required entry: {missing}")
    for unexpected in sorted(actual_entries - REQUIRED_ENTRIES):
        errors.append(f"unexpected task-root entry: {unexpected}")

    description = _read_utf8(path / "description.md", errors)
    if description is not None:
        summary = _catalog_description(description, title, errors, warnings)

    updated: str | None = None
    state = _read_utf8(path / "state.md", errors)
    if state is not None:
        lifecycle, counts, updated = _catalog_state(state, title, errors)

    for filename in ("progress.md", "issues.md"):
        document = path / filename
        if document.is_symlink():
            errors.append(f"symlink is not allowed: {document}")
        elif not document.is_file():
            errors.append(f"regular file required: {document}")
    docs = path / "docs"
    if docs.is_symlink():
        errors.append(f"docs must not be a symlink: {docs}")
    elif not docs.is_dir():
        errors.append(f"docs directory is required: {docs}")

    # Size reporting only; the potentially large history is streamed for its
    # byte and line counts and never parsed or held in memory here.
    sizes = _document_sizes(state, _stream_sizes(path / "progress.md"))
    _size_warnings(sizes, warnings)
    return ValidationResult(
        title=title,
        errors=tuple(errors),
        warnings=tuple(warnings),
        summary=summary,
        lifecycle=lifecycle,
        counts=counts,
        updated=updated,
        sizes=sizes,
    )


def validate_task(root: Path, title: str) -> ValidationResult:
    path = task_directory(root, title)
    return validate_task_path(path, title)


def tasks_report(root: Path, title: str) -> dict[str, Any]:
    """Extract the remaining tasks and their dependency graph from state.md."""
    path = task_directory(root, title)
    errors: list[str] = []
    warnings: list[str] = []
    state = _read_utf8(path / "state.md", errors)
    if state is None:
        raise LongneckError("; ".join(errors) or f"cannot read state.md for {title}")
    lifecycle, counts, updated = _parse_state(state, errors)
    tasks = _extract_tasks(state)
    _analyze_tasks(tasks, errors, warnings)
    return {
        "root": str(root),
        "title": title,
        "lifecycle": lifecycle,
        "updated": updated,
        "counts": counts,
        "tasks": tasks,
        "runnable": [task["id"] for task in tasks if task["runnable"]],
        "errors": errors,
        "warnings": warnings,
    }


def manifest_task(root: Path, title: str) -> dict[str, Any]:
    path = task_directory(root, title)
    digest = hashlib.sha256()
    digest.update(b"longneck-task-v1\0")
    digest.update(title.encode("utf-8"))
    digest.update(b"\0")
    entries: list[dict[str, Any]] = []
    children: list[Path] = []
    for directory, directory_names, file_names in os.walk(path, followlinks=False):
        directory_path = Path(directory)
        for name in (*directory_names, *file_names):
            children.append(directory_path / name)
    for child in sorted(children, key=lambda item: item.relative_to(path).as_posix()):
        relative = child.relative_to(path).as_posix()
        if child.is_symlink():
            raise LongneckError(f"cannot inspect a symlink: {child}")
        if child.is_dir():
            digest.update(b"D\0")
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            entries.append({"path": relative, "type": "directory"})
            continue
        if not child.is_file():
            raise LongneckError(f"unsupported filesystem entry: {child}")
        digest.update(b"F\0")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        file_digest = hashlib.sha256()
        size = 0
        lines = 0
        try:
            with child.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                    file_digest.update(chunk)
                    size += len(chunk)
                    lines += chunk.count(b"\n")
        except OSError as exc:
            raise LongneckError(f"cannot read filesystem entry {child}: {exc}") from exc
        digest.update(b"\0")
        entries.append(
            {
                "path": relative,
                "type": "file",
                "bytes": size,
                "lines": lines,
                "sha256": file_digest.hexdigest(),
            }
        )
    return {
        "root": str(root),
        "title": title,
        "fingerprint": digest.hexdigest(),
        "entries": entries,
    }


def fingerprint_task(root: Path, title: str) -> str:
    return str(manifest_task(root, title)["fingerprint"])


def manifest_diff(
    root: Path, title: str, baseline_path: Path, allowed: Iterable[str]
) -> dict[str, Any]:
    """Compare the current manifest against a saved baseline manifest JSON."""
    if baseline_path.is_symlink() or not baseline_path.is_file():
        raise LongneckError(f"baseline must be a regular file: {baseline_path}")
    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LongneckError(
            f"cannot read baseline manifest {baseline_path}: {exc}"
        ) from exc
    if not isinstance(baseline, dict) or not isinstance(baseline.get("entries"), list):
        raise LongneckError("baseline manifest must be the JSON output of `manifest`")
    if baseline.get("title") != title:
        raise LongneckError(
            f"baseline manifest is for {baseline.get('title')!r}, not {title!r}"
        )
    current = manifest_task(root, title)

    def indexed(entries: Iterable[Any]) -> dict[str, tuple[Any, Any]]:
        index: dict[str, tuple[Any, Any]] = {}
        for entry in entries:
            if not isinstance(entry, dict) or "path" not in entry or "type" not in entry:
                raise LongneckError("manifest entries must have path and type")
            index[entry["path"]] = (entry["type"], entry.get("sha256"))
        return index

    before = indexed(baseline["entries"])
    after = indexed(current["entries"])
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(
        path for path in set(before) & set(after) if before[path] != after[path]
    )
    allowed_set = set(allowed)
    disallowed = sorted(
        path for path in (*added, *removed, *changed) if path not in allowed_set
    )
    return {
        "root": str(root),
        "title": title,
        "baseline_fingerprint": baseline.get("fingerprint"),
        "current_fingerprint": current["fingerprint"],
        "added": added,
        "removed": removed,
        "changed": changed,
        "allowed": sorted(allowed_set),
        "disallowed_changes": disallowed,
    }


def next_id(root: Path, title: str, prefix: str) -> dict[str, Any]:
    """Report the next unused ID for the prefix from every ID mentioned in its
    source documents and, when present, the docs/ work-log archive written by
    longneck-flush.

    Only the maximum matters, so range notations for retired IDs are covered
    by their endpoints without expanding them.
    """
    if prefix not in ID_REF_PATTERNS:
        raise LongneckError(f"unsupported ID prefix: {prefix}")
    path = task_directory(root, title)
    sources: list[str] = []
    texts: list[str] = []
    for filename in ID_SOURCE_FILES[prefix]:
        errors: list[str] = []
        text = _read_utf8(path / filename, errors)
        if text is None:
            raise LongneckError(
                "; ".join(errors) or f"cannot read {filename} for {title}"
            )
        sources.append(filename)
        texts.append(text)
    archive = path / "docs" / WORK_LOG_ARCHIVE_NAME
    if os.path.lexists(archive):
        archive_errors: list[str] = []
        archive_text = _read_utf8(archive, archive_errors)
        if archive_text is None:
            raise LongneckError(
                "; ".join(archive_errors) or f"cannot read work-log archive for {title}"
            )
        sources.append(f"docs/{WORK_LOG_ARCHIVE_NAME}")
        texts.append(archive_text)
    numbers = [
        int(match.group(1))
        for text in texts
        for match in ID_REF_PATTERNS[prefix].finditer(text)
    ]
    highest = max(numbers, default=0)
    return {
        "root": str(root),
        "title": title,
        "prefix": prefix,
        "sources": sources,
        "max_used": f"{prefix}-{highest:0{max(4, len(str(highest)))}d}" if numbers else None,
        "next_id": f"{prefix}-{highest + 1:0{max(4, len(str(highest + 1)))}d}",
    }


def next_decision_id(root: Path, title: str) -> dict[str, Any]:
    return next_id(root, title, "D")


def _is_stale_create_dir(entry: Path) -> bool:
    if (
        not STALE_CREATE_PATTERN.match(entry.name)
        or entry.is_symlink()
        or not entry.is_dir()
    ):
        return False
    try:
        age = time.time() - entry.stat().st_mtime
    except OSError:
        return False
    return age >= STALE_CREATE_MIN_AGE_SECONDS


def _scan_tasks(root: Path, inspect: Any) -> dict[str, Any]:
    base = _longneck_directory(root)
    if not base.exists():
        return {
            "root": str(root),
            "tasks": [],
            "entry_errors": [],
            "stale_entries": [],
            "locks": [],
        }

    tasks: list[dict[str, Any]] = []
    entry_errors: list[str] = []
    stale_entries: list[str] = []
    for entry in sorted(base.iterdir(), key=lambda item: item.name):
        if entry.name == LOCKS_DIR_NAME:
            continue
        if not TITLE_PATTERN.fullmatch(entry.name):
            if (
                STALE_CREATE_PATTERN.match(entry.name)
                and not entry.is_symlink()
                and entry.is_dir()
            ):
                if _is_stale_create_dir(entry):
                    stale_entries.append(entry.name)
                # Fresh temp directories may belong to an in-flight create.
            else:
                entry_errors.append(f"invalid entry name under .longneck: {entry.name}")
            continue
        try:
            task = task_directory(root, entry.name)
            result = inspect(task, entry.name)
        except LongneckError as exc:
            entry_errors.append(str(exc))
            continue
        tasks.append(result.as_dict())
    locks, lock_errors = _list_locks(base)
    entry_errors.extend(lock_errors)
    return {
        "root": str(root),
        "tasks": tasks,
        "entry_errors": entry_errors,
        "stale_entries": stale_entries,
        "locks": locks,
    }


def list_tasks(root: Path) -> dict[str, Any]:
    return _scan_tasks(root, summarize_task_path)


def validate_all_tasks(root: Path) -> dict[str, Any]:
    return _scan_tasks(root, validate_task_path)


def repair_docs(root: Path, title: str) -> dict[str, Any]:
    """Recreate an empty docs/ lost by checkout; refuse anything else."""
    task = task_directory(root, title)
    docs = task / "docs"
    if docs.is_symlink():
        raise LongneckError(f"docs must not be a symlink: {docs}")
    if os.path.lexists(docs):
        if not docs.is_dir():
            raise LongneckError(f"docs is not a directory: {docs}")
        created = False
    else:
        docs.mkdir(mode=0o755)
        created = True
    return {"root": str(root), "title": title, "path": str(docs), "created": created}


def _validate_creation_spec(raw: dict[str, Any]) -> dict[str, str]:
    expected_keys = {name.removesuffix(".md") for name in REQUIRED_FILES}
    if set(raw) != expected_keys:
        raise LongneckError(
            "creation spec must contain exactly: " + ", ".join(sorted(expected_keys))
        )
    spec: dict[str, str] = {}
    for key in sorted(expected_keys):
        value = raw[key]
        if not isinstance(value, str) or not value:
            raise LongneckError(f"creation spec value must be a non-empty string: {key}")
        if not value.endswith("\n"):
            raise LongneckError(f"creation spec value must end with a newline: {key}")
        spec[key] = value
    return spec


def _load_creation_spec(path: Path) -> dict[str, str]:
    if path.is_symlink() or not path.is_file():
        raise LongneckError(f"spec must be a regular file: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LongneckError(f"cannot read creation spec {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise LongneckError("creation spec must be a JSON object")
    return _validate_creation_spec(raw)


def _load_creation_spec_dir(path: Path) -> dict[str, str]:
    if path.is_symlink() or not path.is_dir():
        raise LongneckError(f"spec directory must be a regular directory: {path}")
    expected = set(REQUIRED_FILES)
    actual = {entry.name for entry in path.iterdir()}
    if actual != expected:
        raise LongneckError(
            "spec directory must contain exactly: " + ", ".join(sorted(expected))
        )
    raw: dict[str, str] = {}
    for filename in sorted(expected):
        errors: list[str] = []
        text = _read_utf8(path / filename, errors)
        if text is None or errors:
            raise LongneckError(
                f"invalid spec file {path / filename}: " + "; ".join(errors)
            )
        raw[filename.removesuffix(".md")] = text
    return _validate_creation_spec(raw)


def create_task(root: Path, title: str, spec: dict[str, str]) -> dict[str, Any]:
    validate_title(title)
    base_existed = os.path.lexists(root / ".longneck")
    base = _longneck_directory(root, create=True)
    moved = False
    temporary: Path | None = None
    try:
        target = base / title
        if os.path.lexists(target):
            raise LongneckError(f"Longneck title already exists: {title}")
        spec = _validate_creation_spec(spec)
        temporary = Path(tempfile.mkdtemp(prefix=f".{title}.tmp-", dir=base))
        for key, content in spec.items():
            destination = temporary / f"{key}.md"
            with destination.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
        (temporary / "docs").mkdir(mode=0o755)
        validation = validate_task_path(temporary, title)
        if not validation.ok:
            raise LongneckError("creation spec is invalid: " + "; ".join(validation.errors))
        if os.path.lexists(target):
            raise LongneckError(f"Longneck title appeared during creation: {title}")
        # mkdtemp creates 0700 directories; align with docs/ before publishing.
        temporary.chmod(0o755)
        os.rename(temporary, target)
        moved = True
    finally:
        if not moved:
            if temporary is not None and os.path.lexists(temporary):
                shutil.rmtree(temporary)
            if not base_existed:
                # Leave no empty .longneck behind for a failed first create;
                # rmdir refuses if another process populated it meanwhile.
                try:
                    base.rmdir()
                except OSError:
                    pass

    return {
        "root": str(root),
        "title": title,
        "path": str(target),
        "fingerprint": fingerprint_task(root, title),
    }


def clean_stale(root: Path) -> dict[str, Any]:
    """Remove interrupted-create leftovers that `list` reports as stale_entries."""
    base = _longneck_directory(root)
    removed: list[str] = []
    if base.exists():
        for entry in sorted(base.iterdir(), key=lambda item: item.name):
            if _is_stale_create_dir(entry):
                shutil.rmtree(entry)
                removed.append(entry.name)
    return {"root": str(root), "removed": removed}


def _locks_directory(root: Path, *, create: bool = False) -> Path:
    base = _longneck_directory(root)
    if not base.exists():
        raise LongneckError(f".longneck does not exist under {root}")
    locks = base / LOCKS_DIR_NAME
    if os.path.lexists(locks):
        if locks.is_symlink():
            raise LongneckError(f"locks directory must not be a symlink: {locks}")
        if not locks.is_dir():
            raise LongneckError(f"locks directory is not a directory: {locks}")
    elif create:
        locks.mkdir(mode=0o755)
    return locks


def _lock_path(root: Path, title: str, *, create_dir: bool = False) -> Path:
    validate_title(title)
    return _locks_directory(root, create=create_dir) / f"{title}{LOCK_SUFFIX}"


def _read_lock(path: Path) -> dict[str, Any] | None:
    if not os.path.lexists(path):
        return None
    if path.is_symlink() or not path.is_file():
        raise LongneckError(f"lock must be a regular file: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LongneckError(f"cannot read lock {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise LongneckError(f"lock content must be a JSON object: {path}")
    return raw


def _lock_age_seconds(path: Path) -> int | None:
    try:
        return max(0, int(time.time() - path.stat().st_mtime))
    except OSError:
        return None


def acquire_lock(root: Path, title: str, note: str | None) -> dict[str, Any]:
    """Take the advisory per-title lock; it never replaces fingerprint checks."""
    path = _lock_path(root, title, create_dir=True)
    holder = {
        "title": title,
        "token": secrets.token_hex(16),
        "pid": os.getpid(),
        "created": now_timestamp(),
        "note": note,
    }
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(holder, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
    except FileExistsError:
        try:
            existing = _read_lock(path)
        except LongneckError as exc:
            existing = {"error": str(exc)}
        return {
            "acquired": False,
            "path": str(path),
            "holder": existing,
            "age_seconds": _lock_age_seconds(path),
        }
    return {"acquired": True, "path": str(path), **holder}


def release_lock(
    root: Path, title: str, token: str | None, *, force: bool = False
) -> dict[str, Any]:
    path = _lock_path(root, title)
    if not os.path.lexists(path):
        if force:
            return {"removed": False, "path": str(path), "reason": "no lock present"}
        raise LongneckError(f"no lock is held for {title}")
    try:
        existing = _read_lock(path)
    except LongneckError:
        if not force:
            raise
        existing = None
    if not force and (not existing or existing.get("token") != token):
        raise LongneckError(
            f"lock token mismatch for {title}; use the token returned by lock, "
            "or --force only on explicit user instruction"
        )
    path.unlink()
    return {"removed": True, "path": str(path), "holder": existing}


def _list_locks(base: Path) -> tuple[list[dict[str, Any]], list[str]]:
    locks_dir = base / LOCKS_DIR_NAME
    locks: list[dict[str, Any]] = []
    errors: list[str] = []
    if locks_dir.is_symlink():
        errors.append(f"locks directory must not be a symlink: {locks_dir}")
        return locks, errors
    if not locks_dir.is_dir():
        return locks, errors
    for entry in sorted(locks_dir.iterdir(), key=lambda item: item.name):
        title = entry.name.removesuffix(LOCK_SUFFIX)
        if not entry.name.endswith(LOCK_SUFFIX) or not TITLE_PATTERN.fullmatch(title):
            errors.append(f"invalid entry under .longneck/{LOCKS_DIR_NAME}: {entry.name}")
            continue
        try:
            holder = _read_lock(entry)
        except LongneckError as exc:
            errors.append(str(exc))
            continue
        locks.append(
            {
                "title": title,
                "holder": holder,
                "age_seconds": _lock_age_seconds(entry),
            }
        )
    return locks, errors


def sever_task(root: Path, title: str, expected_fingerprint: str) -> dict[str, Any]:
    """Delete one task directory only while its fingerprint still matches."""
    path = task_directory(root, title)
    actual = fingerprint_task(root, title)
    if actual != expected_fingerprint:
        raise LongneckError(
            f"fingerprint mismatch for {title}: expected {expected_fingerprint}, "
            f"found {actual}; the task changed after persistence"
        )
    shutil.rmtree(path)
    return {
        "root": str(root),
        "title": title,
        "path": str(path),
        "fingerprint": actual,
        "removed": True,
    }


def _file_contains_pattern(path: Path, pattern: re.Pattern[bytes], keep: int) -> bool:
    overlap = b""
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            data = overlap + chunk
            at_eof = not chunk
            for match in pattern.finditer(data):
                # A match ending at the buffer boundary lacks the byte the
                # trailing lookahead must inspect; defer it to the next chunk.
                if at_eof or match.end() < len(data):
                    return True
            if at_eof:
                return False
            overlap = data[-keep:]


def _git_candidate_files(root: Path) -> list[Path] | None:
    """List tracked and untracked non-ignored paths, or None outside a work tree."""
    process = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if process.returncode != 0:
        return None
    return [root / os.fsdecode(raw) for raw in process.stdout.split(b"\0") if raw]


def find_backlinks(root: Path, title: str) -> dict[str, Any]:
    task = task_directory(root, title).resolve(strict=True)
    needle_text = f".longneck/{title}"
    needle = needle_text.encode("utf-8")
    # Reject prefix matches so ".longneck/foo" does not hit ".longneck/foo-bar".
    needle_pattern = re.compile(re.escape(needle) + rb"(?![a-z0-9-])")
    needle_text_pattern = re.compile(re.escape(needle_text) + r"(?![a-z0-9-])")
    hits: list[str] = []
    errors: list[str] = []
    pruned: list[str] = []
    scanned: set[Path] = set()

    def inspect_symlink(path: Path) -> None:
        try:
            raw_target = os.readlink(path)
            resolved_target = path.resolve(strict=False)
        except OSError as exc:
            errors.append(f"cannot inspect symlink {path}: {exc}")
            return
        if needle_text_pattern.search(raw_target.replace(os.sep, "/")) or (
            resolved_target == task or task in resolved_target.parents
        ):
            hits.append(path.relative_to(root).as_posix())

    def scan_entry(path: Path) -> None:
        if path in scanned:
            return
        scanned.add(path)
        if path.is_symlink():
            inspect_symlink(path)
            return
        if not path.is_file():
            # Submodule roots and index entries missing from disk cannot be
            # scanned as regular files; they stay outside this safety net.
            return
        try:
            if _file_contains_pattern(path, needle_pattern, len(needle)):
                hits.append(path.relative_to(root).as_posix())
        except OSError as exc:
            errors.append(f"cannot scan {path}: {exc}")

    def walk_tree(top: Path) -> None:
        for directory, directory_names, file_names in os.walk(top, followlinks=False):
            directory_path = Path(directory)
            relative_directory = directory_path.relative_to(root)
            directory_names[:] = [name for name in directory_names if name != ".git"]
            if relative_directory == Path(".longneck"):
                directory_names[:] = [name for name in directory_names if name != title]
            for name in list(directory_names):
                child = directory_path / name
                if child.is_symlink():
                    scan_entry(child)
                    directory_names.remove(name)
                elif name in BACKLINK_WALK_PRUNE_DIRS:
                    pruned.append(child.relative_to(root).as_posix())
                    directory_names.remove(name)
            for name in file_names:
                scan_entry(directory_path / name)

    candidates = _git_candidate_files(root)
    if candidates is None:
        mode = "walk"
        walk_tree(root)
    else:
        mode = "git"
        for path in candidates:
            parts = path.relative_to(root).parts
            if parts and parts[0] == ".git":
                continue
            if len(parts) >= 2 and parts[0] == ".longneck" and parts[1] == title:
                continue
            scan_entry(path)
        # .longneck may be gitignored; other titles must always be scanned.
        base = root / ".longneck"
        if not base.is_symlink() and base.is_dir():
            walk_tree(base)
    return {
        "title": title,
        "needle": needle_text,
        "mode": mode,
        "hits": sorted(set(hits)),
        "pruned": sorted(set(pruned)),
        "errors": errors,
    }


def _json_dump(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    root_parser = subparsers.add_parser("root", help="resolve the Longneck root")
    root_parser.add_argument("--start", type=Path, required=True)

    subparsers.add_parser("now", help="print the current offset RFC 3339 timestamp")

    for name in (
        "list",
        "tasks",
        "fingerprint",
        "manifest",
        "backlinks",
        "repair-docs",
        "next-task-id",
        "next-decision-id",
        "next-issue-id",
    ):
        command = subparsers.add_parser(name)
        command.add_argument("--root", type=Path, required=True)
        if name != "list":
            command.add_argument("--title", required=True)

    lock = subparsers.add_parser("lock", help="acquire the advisory per-title lock")
    lock.add_argument("--root", type=Path, required=True)
    lock.add_argument("--title", required=True)
    lock.add_argument("--note", help="short holder description recorded in the lock")

    unlock = subparsers.add_parser("unlock", help="release the advisory per-title lock")
    unlock.add_argument("--root", type=Path, required=True)
    unlock.add_argument("--title", required=True)
    release_mode = unlock.add_mutually_exclusive_group(required=True)
    release_mode.add_argument("--token", help="token returned by lock")
    release_mode.add_argument(
        "--force",
        action="store_true",
        help="remove any holder; only on explicit user instruction",
    )

    diff = subparsers.add_parser(
        "manifest-diff", help="compare the current manifest against a saved baseline"
    )
    diff.add_argument("--root", type=Path, required=True)
    diff.add_argument("--title", required=True)
    diff.add_argument(
        "--baseline",
        type=Path,
        required=True,
        help="JSON file saved from a previous `manifest` run",
    )
    diff.add_argument(
        "--allow",
        action="append",
        default=[],
        help="relative path allowed to change; repeatable",
    )

    validate = subparsers.add_parser("validate")
    validate.add_argument("--root", type=Path, required=True)
    validate_target = validate.add_mutually_exclusive_group(required=True)
    validate_target.add_argument("--title")
    validate_target.add_argument(
        "--all", action="store_true", help="fully validate every title under the root"
    )

    create = subparsers.add_parser("create")
    create.add_argument("--root", type=Path, required=True)
    create.add_argument("--title", required=True)
    spec_source = create.add_mutually_exclusive_group(required=True)
    spec_source.add_argument("--spec", type=Path, help="JSON file with the four documents")
    spec_source.add_argument(
        "--spec-dir", type=Path, help="directory holding exactly the four .md documents"
    )

    clean = subparsers.add_parser("clean-stale")
    clean.add_argument("--root", type=Path, required=True)

    sever = subparsers.add_parser(
        "sever", help="delete one task directory after a fingerprint match"
    )
    sever.add_argument("--root", type=Path, required=True)
    sever.add_argument("--title", required=True)
    sever.add_argument(
        "--expect-fingerprint",
        required=True,
        help="sha256 fingerprint verified by the completed full-task persistence",
    )
    return parser


def run(arguments: argparse.Namespace) -> int:
    if arguments.command == "root":
        print(resolve_root(arguments.start))
        return 0
    if arguments.command == "now":
        print(now_timestamp())
        return 0

    root = normalize_root(arguments.root)
    if arguments.command == "list":
        result = list_tasks(root)
        _json_dump(result)
        return 1 if result["entry_errors"] or any(not task["ok"] for task in result["tasks"]) else 0
    if arguments.command == "validate":
        if arguments.all:
            result = validate_all_tasks(root)
            _json_dump(result)
            return (
                1
                if result["entry_errors"] or any(not task["ok"] for task in result["tasks"])
                else 0
            )
        result = validate_task(root, arguments.title)
        _json_dump(result.as_dict())
        return 0 if result.ok else 1
    if arguments.command == "tasks":
        result = tasks_report(root, arguments.title)
        _json_dump(result)
        return 1 if result["errors"] else 0
    if arguments.command == "fingerprint":
        print(fingerprint_task(root, arguments.title))
        return 0
    if arguments.command == "manifest":
        _json_dump(manifest_task(root, arguments.title))
        return 0
    if arguments.command == "create":
        if arguments.spec_dir is not None:
            spec = _load_creation_spec_dir(arguments.spec_dir)
        else:
            spec = _load_creation_spec(arguments.spec)
        _json_dump(create_task(root, arguments.title, spec))
        return 0
    if arguments.command == "clean-stale":
        _json_dump(clean_stale(root))
        return 0
    if arguments.command == "sever":
        _json_dump(sever_task(root, arguments.title, arguments.expect_fingerprint))
        return 0
    if arguments.command == "repair-docs":
        _json_dump(repair_docs(root, arguments.title))
        return 0
    if arguments.command in ("next-task-id", "next-decision-id", "next-issue-id"):
        prefixes = {"next-task-id": "T", "next-decision-id": "D", "next-issue-id": "I"}
        _json_dump(next_id(root, arguments.title, prefixes[arguments.command]))
        return 0
    if arguments.command == "lock":
        result = acquire_lock(root, arguments.title, arguments.note)
        _json_dump(result)
        return 0 if result["acquired"] else 1
    if arguments.command == "unlock":
        _json_dump(
            release_lock(root, arguments.title, arguments.token, force=arguments.force)
        )
        return 0
    if arguments.command == "manifest-diff":
        result = manifest_diff(root, arguments.title, arguments.baseline, arguments.allow)
        _json_dump(result)
        return 1 if result["disallowed_changes"] else 0
    if arguments.command == "backlinks":
        result = find_backlinks(root, arguments.title)
        _json_dump(result)
        if result["errors"]:
            print(
                "longneckctl: backlink scan is incomplete; "
                "see the errors list in the JSON output",
                file=sys.stderr,
            )
            return 2
        return 1 if result["hits"] else 0
    raise LongneckError(f"unsupported command: {arguments.command}")


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return run(arguments)
    except LongneckError as exc:
        print(f"longneckctl: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
