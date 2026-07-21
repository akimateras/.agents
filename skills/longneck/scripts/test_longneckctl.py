#!/usr/bin/env python3

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import longneckctl


NOW = "2026-07-22T12:00:00+09:00"


def age_beyond_stale_threshold(path: Path) -> None:
    old = time.time() - longneckctl.STALE_CREATE_MIN_AGE_SECONDS - 60
    os.utime(path, (old, old))


def valid_spec(title: str = "sample-task") -> dict[str, str]:
    return {
        "description": f"""# {title} — タスク定義

概要: 検証用のLongneckタスクを完了する。

## 目的

検証する。

## スコープ

- 検証

## 非スコープ

- なし

## 完了条件

- 検証が成功する。

## 長期制約

- 既存内容を保持する。

## 主な作業対象

- `src/`
""",
        "state": f"""# {title} — 現在の状態

更新日時: {NOW}
状態: active

## 現在のスナップショット

初期状態。

## 調査待ち

### T-0001 — 調査する

- 目的: 調査する。
- 完了条件: 結果を得る。
- 依存関係: なし

## 判断待ち

なし。

## 実行待ち

なし。

## ブロック中

なし。
""",
        "progress": f"""# {title} — 進捗

## 設計判断

なし。

## 作業ログ

### {NOW} — T-0001

- 実施: タスクを作成した。
- 検証: 初期形式を確認した。
""",
        "issues": f"""# {title} — 将来の検討事項

現在の目的の達成には不要だが、将来の判断に必要な未解決知見を記録する。
現在の完了条件に必要な作業や判断は `state.md` に置く。

## 未解決

なし。
""",
    }


class LongneckCtlTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_spec(self, title: str = "sample-task") -> Path:
        path = self.root / "spec.json"
        path.write_text(json.dumps(valid_spec(title), ensure_ascii=False), encoding="utf-8")
        return path

    def write_spec_dir(self, title: str = "sample-task") -> Path:
        path = self.root / "spec-dir"
        path.mkdir(exist_ok=True)
        for key, content in valid_spec(title).items():
            (path / f"{key}.md").write_text(content, encoding="utf-8")
        return path

    def create(self, title: str = "sample-task") -> dict[str, object]:
        return longneckctl.create_task(self.root, title, valid_spec(title))

    def task_path(self, *parts: str) -> Path:
        return self.root.joinpath(".longneck", "sample-task", *parts)

    def test_resolve_root_outside_git_uses_start_directory(self) -> None:
        nested = self.root / "nested"
        nested.mkdir()
        self.assertEqual(longneckctl.resolve_root(nested), nested.resolve())

    def test_create_validate_list_and_fingerprint(self) -> None:
        created = self.create()
        self.assertEqual(created["title"], "sample-task")
        self.assertTrue(self.task_path("docs").is_dir())
        self.assertEqual(self.task_path().stat().st_mode & 0o777, 0o755)

        validation = longneckctl.validate_task(self.root, "sample-task")
        self.assertTrue(validation.ok, validation.errors)
        self.assertEqual(validation.lifecycle, "active")
        self.assertEqual(validation.counts["調査待ち"], 1)

        listing = longneckctl.list_tasks(self.root)
        self.assertEqual([task["title"] for task in listing["tasks"]], ["sample-task"])
        self.assertEqual(listing["entry_errors"], [])
        self.assertEqual(
            created["fingerprint"], longneckctl.fingerprint_task(self.root, "sample-task")
        )

    def test_manifest_reports_per_entry_hashes_and_tree_fingerprint(self) -> None:
        self.create()
        manifest = longneckctl.manifest_task(self.root, "sample-task")
        entries = {entry["path"]: entry for entry in manifest["entries"]}

        self.assertEqual(manifest["root"], str(self.root))
        self.assertEqual(manifest["title"], "sample-task")
        self.assertEqual(
            manifest["fingerprint"], longneckctl.fingerprint_task(self.root, "sample-task")
        )
        self.assertEqual(entries["docs"], {"path": "docs", "type": "directory"})
        self.assertEqual(entries["state.md"]["type"], "file")
        self.assertEqual(
            entries["state.md"]["bytes"], self.task_path("state.md").stat().st_size
        )
        self.assertEqual(
            entries["state.md"]["lines"],
            self.task_path("state.md").read_text(encoding="utf-8").count("\n"),
        )
        self.assertRegex(entries["state.md"]["sha256"], r"^[0-9a-f]{64}$")

        before = manifest
        state = self.task_path("state.md")
        state.write_text(
            state.read_text(encoding="utf-8").replace("初期状態。", "更新した状態。"),
            encoding="utf-8",
        )
        after = longneckctl.manifest_task(self.root, "sample-task")
        before_entries = {entry["path"]: entry for entry in before["entries"]}
        after_entries = {entry["path"]: entry for entry in after["entries"]}

        self.assertNotEqual(before["fingerprint"], after["fingerprint"])
        self.assertNotEqual(before_entries["state.md"], after_entries["state.md"])
        self.assertEqual(before_entries["issues.md"], after_entries["issues.md"])

    def test_list_does_not_parse_large_task_history(self) -> None:
        self.create()
        progress = self.task_path("progress.md")
        progress.write_bytes(b"\xff\xfe not UTF-8")
        listing = longneckctl.list_tasks(self.root)
        self.assertTrue(listing["tasks"][0]["ok"])
        self.assertFalse(longneckctl.validate_task(self.root, "sample-task").ok)

    def test_invalid_title_and_collision_are_rejected(self) -> None:
        with self.assertRaises(longneckctl.LongneckError):
            longneckctl.create_task(self.root, "Invalid_Title", valid_spec())
        self.create()
        with self.assertRaises(longneckctl.LongneckError):
            self.create()

    def test_invalid_creation_is_rolled_back(self) -> None:
        spec = valid_spec()
        spec["state"] = spec["state"].replace("状態: active", "状態: completed")
        with self.assertRaises(longneckctl.LongneckError):
            longneckctl.create_task(self.root, "sample-task", spec)
        self.assertFalse(self.task_path().exists())
        # A .longneck created only for this failed attempt is removed again.
        self.assertFalse((self.root / ".longneck").exists())

        self.create("other-task")
        with self.assertRaises(longneckctl.LongneckError):
            longneckctl.create_task(self.root, "sample-task", spec)
        # A pre-existing .longneck with other titles is kept.
        self.assertFalse(self.task_path().exists())
        self.assertTrue((self.root / ".longneck" / "other-task").is_dir())

    def test_create_via_json_spec_path(self) -> None:
        spec_path = self.write_spec()
        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = longneckctl.main(
                [
                    "create",
                    "--root",
                    str(self.root),
                    "--title",
                    "sample-task",
                    "--spec",
                    str(spec_path),
                ]
            )
        self.assertEqual(exit_code, 0)
        self.assertTrue(longneckctl.validate_task(self.root, "sample-task").ok)

    def test_create_via_spec_dir(self) -> None:
        spec_dir = self.write_spec_dir()
        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = longneckctl.main(
                [
                    "create",
                    "--root",
                    str(self.root),
                    "--title",
                    "sample-task",
                    "--spec-dir",
                    str(spec_dir),
                ]
            )
        self.assertEqual(exit_code, 0)
        self.assertTrue(longneckctl.validate_task(self.root, "sample-task").ok)

    def test_spec_dir_rejects_extra_and_missing_entries(self) -> None:
        spec_dir = self.write_spec_dir()
        extra = spec_dir / "extra.md"
        extra.write_text("余分な文書。\n", encoding="utf-8")
        with self.assertRaises(longneckctl.LongneckError):
            longneckctl._load_creation_spec_dir(spec_dir)
        extra.unlink()
        (spec_dir / "issues.md").unlink()
        with self.assertRaises(longneckctl.LongneckError):
            longneckctl._load_creation_spec_dir(spec_dir)

    def test_clean_stale_removes_only_stale_creation_directories(self) -> None:
        self.create()
        stale = self.root / ".longneck" / ".sample-task.tmp-abcd1234"
        (stale / "docs").mkdir(parents=True)
        age_beyond_stale_threshold(stale)
        invalid = self.root / ".longneck" / "Invalid Entry"
        invalid.mkdir()
        result = longneckctl.clean_stale(self.root)
        self.assertEqual(result["removed"], [".sample-task.tmp-abcd1234"])
        self.assertFalse(stale.exists())
        self.assertTrue(invalid.is_dir())
        self.assertTrue(self.task_path().is_dir())
        self.assertEqual(longneckctl.clean_stale(self.root)["removed"], [])

    def test_fresh_creation_directory_is_not_treated_as_stale(self) -> None:
        self.create()
        fresh = self.root / ".longneck" / ".sample-task.tmp-fresh123"
        fresh.mkdir()
        listing = longneckctl.list_tasks(self.root)
        self.assertEqual(listing["stale_entries"], [])
        self.assertEqual(listing["entry_errors"], [])
        self.assertEqual(longneckctl.clean_stale(self.root)["removed"], [])
        self.assertTrue(fresh.is_dir())

    def test_invalid_docs_metadata_is_reported(self) -> None:
        self.create()
        note = self.task_path("docs", "note.md")
        note.write_text("# missing metadata\n", encoding="utf-8")
        result = longneckctl.validate_task(self.root, "sample-task")
        self.assertFalse(result.ok)
        self.assertTrue(any("metadata" in error for error in result.errors))
        self.assertRegex(longneckctl.fingerprint_task(self.root, "sample-task"), r"^[0-9a-f]{64}$")

    def test_state_lifecycle_must_match_task_counts(self) -> None:
        self.create()
        state = self.task_path("state.md")
        state.write_text(
            state.read_text(encoding="utf-8").replace("状態: active", "状態: completed"),
            encoding="utf-8",
        )
        result = longneckctl.validate_task(self.root, "sample-task")
        self.assertFalse(result.ok)
        self.assertTrue(any("inconsistent" in error for error in result.errors))

    def test_completed_state_without_tasks_is_valid(self) -> None:
        self.create()
        state = self.task_path("state.md")
        text = state.read_text(encoding="utf-8")
        research_start = text.index("## 調査待ち")
        decision_start = text.index("## 判断待ち")
        completed = (
            text[:research_start]
            + "## 調査待ち\n\nなし。\n\n"
            + text[decision_start:]
        ).replace("状態: active", "状態: completed")
        state.write_text(completed, encoding="utf-8")
        result = longneckctl.validate_task(self.root, "sample-task")
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.lifecycle, "completed")

    def test_state_sections_must_be_in_standard_order(self) -> None:
        self.create()
        state = self.task_path("state.md")
        text = state.read_text(encoding="utf-8")
        swapped = text.replace(
            "## 判断待ち\n\nなし。\n\n## 実行待ち\n\nなし。\n",
            "## 実行待ち\n\nなし。\n\n## 判断待ち\n\nなし。\n",
        )
        self.assertNotEqual(text, swapped)
        state.write_text(swapped, encoding="utf-8")
        result = longneckctl.validate_task(self.root, "sample-task")
        self.assertFalse(result.ok)
        self.assertTrue(any("out of order" in error for error in result.errors))

    def test_five_digit_task_id_is_counted(self) -> None:
        self.create()
        state = self.task_path("state.md")
        text = state.read_text(encoding="utf-8")
        expanded = text.replace(
            "## 実行待ち\n\nなし。\n",
            "## 実行待ち\n\n### T-10000 — 実装する\n\n"
            "- 目的: 実装する。\n- 完了条件: 完了する。\n- 依存関係: なし\n",
        )
        self.assertNotEqual(text, expanded)
        state.write_text(expanded, encoding="utf-8")
        result = longneckctl.validate_task(self.root, "sample-task")
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.counts["実行待ち"], 1)

    def test_malformed_task_id_heading_is_reported(self) -> None:
        self.create()
        state = self.task_path("state.md")
        text = state.read_text(encoding="utf-8")
        state.write_text(
            text.replace("### T-0001 — 調査する", "### T-001 — 調査する"),
            encoding="utf-8",
        )
        result = longneckctl.validate_task(self.root, "sample-task")
        self.assertFalse(result.ok)
        self.assertTrue(any("malformed" in error for error in result.errors))

    def test_now_outputs_offset_rfc3339(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            exit_code = longneckctl.main(["now"])
        self.assertEqual(exit_code, 0)
        errors: list[str] = []
        parsed = longneckctl._parse_rfc3339(buffer.getvalue().strip(), "now", errors)
        self.assertEqual(errors, [])
        self.assertIsNotNone(parsed)

    def test_repair_docs_recreates_missing_docs_only(self) -> None:
        self.create()
        docs = self.task_path("docs")
        docs.rmdir()
        result = longneckctl.repair_docs(self.root, "sample-task")
        self.assertTrue(result["created"])
        self.assertTrue(docs.is_dir())
        self.assertTrue(longneckctl.validate_task(self.root, "sample-task").ok)
        self.assertFalse(longneckctl.repair_docs(self.root, "sample-task")["created"])
        docs.rmdir()
        docs.touch()
        with self.assertRaises(longneckctl.LongneckError):
            longneckctl.repair_docs(self.root, "sample-task")

    def test_validate_all_reports_every_title(self) -> None:
        self.create()
        self.create("other-task")
        note = self.root / ".longneck" / "other-task" / "docs" / "note.md"
        note.write_text("# missing metadata\n", encoding="utf-8")
        result = longneckctl.validate_all_tasks(self.root)
        by_title = {task["title"]: task for task in result["tasks"]}
        self.assertTrue(by_title["sample-task"]["ok"])
        self.assertFalse(by_title["other-task"]["ok"])
        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = longneckctl.main(["validate", "--root", str(self.root), "--all"])
        self.assertEqual(exit_code, 1)

    def test_invalid_updated_line_is_distinguished_from_missing(self) -> None:
        self.create()
        state = self.task_path("state.md")
        text = state.read_text(encoding="utf-8")
        state.write_text(
            text.replace(f"更新日時: {NOW}", "更新日時: 2026-07-22 12:00:00+09:00"),
            encoding="utf-8",
        )
        result = longneckctl.validate_task(self.root, "sample-task")
        self.assertFalse(result.ok)
        self.assertTrue(any("invalid 更新日時" in error for error in result.errors))
        state.write_text(
            text.replace(f"更新日時: {NOW}\n", ""),
            encoding="utf-8",
        )
        result = longneckctl.validate_task(self.root, "sample-task")
        self.assertFalse(result.ok)
        self.assertTrue(any("missing 更新日時" in error for error in result.errors))

    def test_docs_timestamp_requires_t_separator(self) -> None:
        self.create()
        note = self.task_path("docs", "note.md")
        note.write_text(
            f"作成日時: 2026-07-22 12:00:00+09:00\n更新日時: {NOW}\n概要: 検証。\n",
            encoding="utf-8",
        )
        result = longneckctl.validate_task(self.root, "sample-task")
        self.assertFalse(result.ok)
        self.assertTrue(any("'T'" in error for error in result.errors))

    def test_docs_updated_must_not_precede_created(self) -> None:
        self.create()
        note = self.task_path("docs", "note.md")
        note.write_text(
            f"作成日時: {NOW}\n更新日時: 2026-07-22T11:00:00+09:00\n概要: 検証。\n",
            encoding="utf-8",
        )
        result = longneckctl.validate_task(self.root, "sample-task")
        self.assertFalse(result.ok)
        self.assertTrue(
            any("must not precede 作成日時" in error for error in result.errors)
        )

    def test_work_log_heading_format_is_validated(self) -> None:
        self.create()
        progress = self.task_path("progress.md")
        text = progress.read_text(encoding="utf-8")
        progress.write_text(
            text.replace(f"### {NOW} — T-0001", f"### {NOW} / T-0001"),
            encoding="utf-8",
        )
        result = longneckctl.validate_task(self.root, "sample-task")
        self.assertFalse(result.ok)
        self.assertTrue(any("work log heading" in error for error in result.errors))

    def test_work_log_must_be_newest_first(self) -> None:
        self.create()
        progress = self.task_path("progress.md")
        text = progress.read_text(encoding="utf-8")
        older = (
            "\n### 2026-07-21T12:00:00+09:00 — 管理作業\n\n"
            "- 実施: 過去の管理作業。\n- 検証: なし。\n"
        )
        progress.write_text(text + older, encoding="utf-8")
        self.assertTrue(
            longneckctl.validate_task(self.root, "sample-task").ok,
            longneckctl.validate_task(self.root, "sample-task").errors,
        )
        newer = (
            "\n### 2026-07-23T12:00:00+09:00 — T-0001\n\n"
            "- 実施: 後から追記した。\n- 検証: なし。\n"
        )
        progress.write_text(text + newer, encoding="utf-8")
        result = longneckctl.validate_task(self.root, "sample-task")
        self.assertFalse(result.ok)
        self.assertTrue(any("newest first" in error for error in result.errors))

    @unittest.skipUnless(shutil.which("git"), "git is required")
    def test_resolve_root_rejects_bare_repository(self) -> None:
        bare = self.root / "bare-repo"
        subprocess.run(
            ["git", "init", "--bare", str(bare)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with self.assertRaises(longneckctl.LongneckError):
            longneckctl.resolve_root(bare)

    def test_backlinks_find_reference_from_other_title(self) -> None:
        self.create()
        self.create("other-task")
        reference = ".longneck" + "/sample-task/state.md"
        other_doc = self.root / ".longneck" / "other-task" / "docs" / "ref.md"
        other_doc.write_text(
            f"作成日時: {NOW}\n更新日時: {NOW}\n概要: 別titleからの参照。\n\n{reference}\n",
            encoding="utf-8",
        )
        result = longneckctl.find_backlinks(self.root, "sample-task")
        self.assertEqual(result["hits"], [".longneck/other-task/docs/ref.md"])
        self.assertEqual(result["errors"], [])

    def test_backlinks_ignore_longneck_and_find_external_reference(self) -> None:
        self.create()
        internal = self.task_path("docs", "note.md")
        reference = ".longneck" + "/sample-task/state.md"
        internal.write_text(
            f"作成日時: {NOW}\n更新日時: {NOW}\n概要: 内部参照。\n\n{reference}\n",
            encoding="utf-8",
        )
        external = self.root / "README.md"
        external.write_text(f"See {reference}\n", encoding="utf-8")
        result = longneckctl.find_backlinks(self.root, "sample-task")
        self.assertEqual(result["hits"], ["README.md"])
        self.assertEqual(result["errors"], [])

    def test_backlinks_ignore_prefix_title_reference(self) -> None:
        self.create()
        self.create("sample-task-extra")
        external = self.root / "README.md"
        external.write_text("See .longneck" + "/sample-task-extra/docs\n", encoding="utf-8")
        result = longneckctl.find_backlinks(self.root, "sample-task")
        self.assertEqual(result["hits"], [])
        self.assertEqual(result["errors"], [])
        self.assertEqual(
            longneckctl.find_backlinks(self.root, "sample-task-extra")["hits"],
            ["README.md"],
        )

    def test_backlinks_match_across_chunk_boundaries(self) -> None:
        self.create()
        chunk = 1024 * 1024
        needle = ".longneck" + "/sample-task"
        straddling = self.root / "straddling.bin"
        straddling.write_bytes(b"a" * (chunk - 5) + needle.encode("utf-8") + b"\n")
        boundary_prefix = self.root / "boundary-prefix.bin"
        boundary_prefix.write_bytes(
            b"a" * (chunk - len(needle)) + needle.encode("utf-8") + b"-extra/docs\n"
        )
        result = longneckctl.find_backlinks(self.root, "sample-task")
        self.assertEqual(result["hits"], ["straddling.bin"])
        self.assertEqual(result["errors"], [])

    @unittest.skipUnless(shutil.which("git"), "git is required")
    def test_backlinks_in_git_repo_skip_ignored_files_but_scan_longneck(self) -> None:
        subprocess.run(
            ["git", "init", str(self.root)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.create()
        self.create("other-task")
        reference = ".longneck" + "/sample-task/state.md"
        (self.root / ".gitignore").write_text("vendor/\n.longneck/\n", encoding="utf-8")
        vendor = self.root / "vendor"
        vendor.mkdir()
        (vendor / "blob.txt").write_text(f"See {reference}\n", encoding="utf-8")
        (self.root / "notes.md").write_text(f"See {reference}\n", encoding="utf-8")
        other_doc = self.root / ".longneck" / "other-task" / "docs" / "ref.md"
        other_doc.write_text(
            f"作成日時: {NOW}\n更新日時: {NOW}\n概要: 別titleからの参照。\n\n{reference}\n",
            encoding="utf-8",
        )
        result = longneckctl.find_backlinks(self.root, "sample-task")
        self.assertEqual(result["mode"], "git")
        self.assertEqual(
            result["hits"], [".longneck/other-task/docs/ref.md", "notes.md"]
        )
        self.assertEqual(result["errors"], [])

    def test_backlinks_outside_git_scan_everything(self) -> None:
        self.create()
        result = longneckctl.find_backlinks(self.root, "sample-task")
        self.assertEqual(result["mode"], "walk")
        self.assertEqual(result["hits"], [])
        self.assertEqual(result["pruned"], [])

    def test_backlinks_walk_mode_prunes_dependency_directories(self) -> None:
        self.create()
        vendored = self.root / "node_modules" / "pkg"
        vendored.mkdir(parents=True)
        (vendored / "README.md").write_text(
            "See .longneck" + "/sample-task/state.md\n", encoding="utf-8"
        )
        external = self.root / "note.md"
        external.write_text("See .longneck" + "/sample-task/state.md\n", encoding="utf-8")
        result = longneckctl.find_backlinks(self.root, "sample-task")
        self.assertEqual(result["mode"], "walk")
        self.assertEqual(result["hits"], ["note.md"])
        self.assertEqual(result["pruned"], ["node_modules"])
        self.assertEqual(result["errors"], [])

    @unittest.skipIf(os.geteuid() == 0, "root ignores file permissions")
    def test_backlinks_scan_errors_exit_2_with_stderr_message(self) -> None:
        self.create()
        unreadable = self.root / "secret.md"
        unreadable.write_text("no reference\n", encoding="utf-8")
        unreadable.chmod(0o000)
        try:
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = longneckctl.main(
                    ["backlinks", "--root", str(self.root), "--title", "sample-task"]
                )
            self.assertEqual(code, 2)
            result = json.loads(stdout.getvalue())
            self.assertTrue(result["errors"])
            self.assertIn("longneckctl:", stderr.getvalue())
        finally:
            unreadable.chmod(0o644)

    def test_list_reports_stale_creation_directory(self) -> None:
        self.create()
        stale = self.root / ".longneck" / ".sample-task.tmp-abcd1234"
        stale.mkdir()
        age_beyond_stale_threshold(stale)
        listing = longneckctl.list_tasks(self.root)
        self.assertEqual(listing["stale_entries"], [".sample-task.tmp-abcd1234"])
        self.assertEqual(listing["entry_errors"], [])
        self.assertTrue(listing["tasks"][0]["ok"])

    def test_list_reports_state_updated_timestamp(self) -> None:
        self.create()
        listing = longneckctl.list_tasks(self.root)
        self.assertEqual(listing["tasks"][0]["updated"], NOW)
        validation = longneckctl.validate_task(self.root, "sample-task")
        self.assertEqual(validation.updated, NOW)

    def test_sever_deletes_only_on_fingerprint_match(self) -> None:
        self.create()
        self.create("other-task")
        fingerprint = longneckctl.fingerprint_task(self.root, "sample-task")
        state = self.task_path("state.md")
        state.write_text(
            state.read_text(encoding="utf-8").replace("初期状態。", "変更後の状態。"),
            encoding="utf-8",
        )
        with self.assertRaises(longneckctl.LongneckError):
            longneckctl.sever_task(self.root, "sample-task", fingerprint)
        self.assertTrue(self.task_path().is_dir())

        current = longneckctl.fingerprint_task(self.root, "sample-task")
        result = longneckctl.sever_task(self.root, "sample-task", current)
        self.assertTrue(result["removed"])
        self.assertFalse(self.task_path().exists())
        self.assertTrue((self.root / ".longneck" / "other-task").is_dir())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support is required")
    def test_resolve_root_accepts_symlinked_start_directory(self) -> None:
        nested = self.root / "nested"
        nested.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(nested, target_is_directory=True)
        self.assertEqual(longneckctl.resolve_root(alias), nested.resolve())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support is required")
    def test_backlinks_find_external_symlink_into_task(self) -> None:
        self.create()
        external = self.root / "task-state.md"
        external.symlink_to(self.task_path("state.md"))
        result = longneckctl.find_backlinks(self.root, "sample-task")
        self.assertEqual(result["hits"], ["task-state.md"])
        self.assertEqual(result["errors"], [])

    def append_pending_task(self, task_id: str, dependencies: str) -> None:
        state = self.task_path("state.md")
        text = state.read_text(encoding="utf-8")
        expanded = text.replace(
            "## 実行待ち\n\nなし。\n",
            f"## 実行待ち\n\n### {task_id} — 実装する\n\n"
            f"- 目的: 実装する。\n- 完了条件: 完了する。\n- 依存関係: {dependencies}\n",
        )
        self.assertNotEqual(text, expanded)
        state.write_text(expanded, encoding="utf-8")

    def test_tasks_reports_dependency_graph_and_runnable_ids(self) -> None:
        self.create()
        self.append_pending_task("T-0002", "T-0001")
        report = longneckctl.tasks_report(self.root, "sample-task")
        by_id = {task["id"]: task for task in report["tasks"]}
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["lifecycle"], "active")
        self.assertEqual(report["updated"], NOW)
        self.assertEqual(by_id["T-0001"]["section"], "調査待ち")
        self.assertEqual(by_id["T-0001"]["name"], "調査する")
        self.assertTrue(by_id["T-0001"]["runnable"])
        self.assertEqual(by_id["T-0002"]["depends_on"], ["T-0001"])
        self.assertEqual(by_id["T-0002"]["blocked_by"], ["T-0001"])
        self.assertFalse(by_id["T-0002"]["runnable"])
        self.assertEqual(by_id["T-0001"]["unlocks"], ["T-0002"])
        self.assertEqual(by_id["T-0002"]["unlocks"], [])
        self.assertEqual(report["runnable"], ["T-0001"])

    def test_tasks_report_includes_verbatim_task_body(self) -> None:
        self.create()
        report = longneckctl.tasks_report(self.root, "sample-task")
        self.assertEqual(
            report["tasks"][0]["body"],
            "### T-0001 — 調査する\n\n"
            "- 目的: 調査する。\n- 完了条件: 結果を得る。\n- 依存関係: なし",
        )

    def test_missing_purpose_and_completion_lines_warn_for_executable_tasks(self) -> None:
        self.create()
        state = self.task_path("state.md")
        text = state.read_text(encoding="utf-8")
        stripped = text.replace("- 目的: 調査する。\n", "").replace(
            "- 完了条件: 結果を得る。\n", ""
        )
        # 判断待ち / ブロック中 items use freer prose; they must not warn.
        blocked = stripped.replace(
            "## ブロック中\n\nなし。\n",
            "## ブロック中\n\n### T-0002 — 外部待ち\n\n- 依存関係: 外部APIの復旧\n",
        )
        self.assertNotEqual(text, blocked)
        state.write_text(blocked, encoding="utf-8")
        result = longneckctl.validate_task(self.root, "sample-task")
        self.assertTrue(result.ok, result.errors)
        self.assertIn("task T-0001 has no '- 目的:' line", result.warnings)
        self.assertIn("task T-0001 has no '- 完了条件:' line", result.warnings)
        self.assertFalse(
            any("T-0002 has no '-" in warning for warning in result.warnings)
        )

    def test_tasks_command_exit_codes(self) -> None:
        self.create()
        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = longneckctl.main(
                ["tasks", "--root", str(self.root), "--title", "sample-task"]
            )
        self.assertEqual(exit_code, 0)
        state = self.task_path("state.md")
        state.write_text(
            state.read_text(encoding="utf-8").replace(
                "- 依存関係: なし", "- 依存関係: T-0001"
            ),
            encoding="utf-8",
        )
        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = longneckctl.main(
                ["tasks", "--root", str(self.root), "--title", "sample-task"]
            )
        self.assertEqual(exit_code, 1)

    def test_unknown_dependency_is_treated_as_satisfied_with_warning(self) -> None:
        self.create()
        self.append_pending_task("T-0002", "T-0009")
        result = longneckctl.validate_task(self.root, "sample-task")
        self.assertTrue(result.ok, result.errors)
        self.assertTrue(any("unknown task T-0009" in warning for warning in result.warnings))
        report = longneckctl.tasks_report(self.root, "sample-task")
        by_id = {task["id"]: task for task in report["tasks"]}
        self.assertEqual(by_id["T-0002"]["unknown_dependencies"], ["T-0009"])
        self.assertTrue(by_id["T-0002"]["runnable"])

    def test_self_dependency_is_an_error(self) -> None:
        self.create()
        self.append_pending_task("T-0002", "T-0002")
        result = longneckctl.validate_task(self.root, "sample-task")
        self.assertFalse(result.ok)
        self.assertTrue(any("depends on itself" in error for error in result.errors))

    def test_dependency_cycle_is_an_error(self) -> None:
        self.create()
        state = self.task_path("state.md")
        text = state.read_text(encoding="utf-8")
        state.write_text(
            text.replace("- 依存関係: なし", "- 依存関係: T-0002"),
            encoding="utf-8",
        )
        self.append_pending_task("T-0002", "T-0001")
        result = longneckctl.validate_task(self.root, "sample-task")
        self.assertFalse(result.ok)
        self.assertTrue(any("dependency cycle" in error for error in result.errors))

    def test_missing_dependency_line_warns_for_executable_tasks(self) -> None:
        self.create()
        state = self.task_path("state.md")
        text = state.read_text(encoding="utf-8")
        state.write_text(text.replace("- 依存関係: なし\n", ""), encoding="utf-8")
        result = longneckctl.validate_task(self.root, "sample-task")
        self.assertTrue(result.ok, result.errors)
        self.assertTrue(any("no 依存関係 line" in warning for warning in result.warnings))
        report = longneckctl.tasks_report(self.root, "sample-task")
        self.assertIsNone(report["tasks"][0]["runnable"])
        self.assertEqual(report["runnable"], [])

    def test_free_text_dependency_without_ids_is_not_judged(self) -> None:
        self.create()
        state = self.task_path("state.md")
        text = state.read_text(encoding="utf-8")
        state.write_text(
            text.replace("- 依存関係: なし", "- 依存関係: ユーザーの回答後に着手する"),
            encoding="utf-8",
        )
        result = longneckctl.validate_task(self.root, "sample-task")
        self.assertTrue(result.ok, result.errors)
        report = longneckctl.tasks_report(self.root, "sample-task")
        self.assertIsNone(report["tasks"][0]["runnable"])

    def test_id_list_dependency_with_separators_is_judged(self) -> None:
        self.create()
        self.append_pending_task("T-0002", "T-0001、T-0009")
        report = longneckctl.tasks_report(self.root, "sample-task")
        by_id = {task["id"]: task for task in report["tasks"]}
        self.assertEqual(by_id["T-0002"]["blocked_by"], ["T-0001"])
        self.assertEqual(by_id["T-0002"]["unknown_dependencies"], ["T-0009"])
        self.assertFalse(by_id["T-0002"]["runnable"])
        self.assertFalse(
            any("mixes task IDs and free text" in warning for warning in report["warnings"])
        )

    def test_mixed_id_and_free_text_dependency_is_not_judged(self) -> None:
        self.create()
        self.append_pending_task("T-0002", "T-0001 の完了後、外部APIの復旧も必要")
        result = longneckctl.validate_task(self.root, "sample-task")
        self.assertTrue(result.ok, result.errors)
        self.assertTrue(
            any("mixes task IDs and free text" in warning for warning in result.warnings)
        )
        report = longneckctl.tasks_report(self.root, "sample-task")
        by_id = {task["id"]: task for task in report["tasks"]}
        # Graph data is still extracted, but runnable is left to the caller.
        self.assertEqual(by_id["T-0002"]["blocked_by"], ["T-0001"])
        self.assertIsNone(by_id["T-0002"]["runnable"])
        self.assertEqual(report["runnable"], ["T-0001"])

    def test_duplicate_dependency_lines_are_an_error(self) -> None:
        self.create()
        state = self.task_path("state.md")
        state.write_text(
            state.read_text(encoding="utf-8").replace(
                "- 依存関係: なし\n",
                "- 依存関係: なし\n- 依存関係: T-0009\n",
            ),
            encoding="utf-8",
        )
        result = longneckctl.validate_task(self.root, "sample-task")
        self.assertFalse(result.ok)
        self.assertTrue(
            any("multiple 依存関係 lines" in error for error in result.errors)
        )
        report = longneckctl.tasks_report(self.root, "sample-task")
        self.assertTrue(
            any("multiple 依存関係 lines" in error for error in report["errors"])
        )

    def test_list_and_validate_report_document_sizes(self) -> None:
        self.create()
        listing = longneckctl.list_tasks(self.root)
        sizes = listing["tasks"][0]["sizes"]
        self.assertEqual(
            sizes["state.md"]["bytes"], self.task_path("state.md").stat().st_size
        )
        self.assertEqual(
            sizes["progress.md"]["lines"],
            self.task_path("progress.md").read_text(encoding="utf-8").count("\n"),
        )
        validation = longneckctl.validate_task(self.root, "sample-task")
        self.assertEqual(validation.sizes, sizes)

    def test_bloated_state_and_progress_report_size_warnings(self) -> None:
        self.create()
        state = self.task_path("state.md")
        filler = "".join(f"追記 {index}\n" for index in range(301))
        state.write_text(
            state.read_text(encoding="utf-8").replace("初期状態。\n", "初期状態。\n" + filler),
            encoding="utf-8",
        )
        progress = self.task_path("progress.md")
        progress.write_text(
            progress.read_text(encoding="utf-8") + "- 補足: " + "x" * (64 * 1024) + "\n",
            encoding="utf-8",
        )
        result = longneckctl.validate_task(self.root, "sample-task")
        self.assertTrue(result.ok, result.errors)
        self.assertIn("state.md exceeds 300 lines", result.warnings)
        self.assertIn("progress.md exceeds 64 KiB", result.warnings)
        listing = longneckctl.list_tasks(self.root)
        warnings = listing["tasks"][0]["warnings"]
        self.assertIn("state.md exceeds 300 lines", warnings)
        self.assertIn("progress.md exceeds 64 KiB", warnings)

    def test_updated_line_outside_header_does_not_count(self) -> None:
        self.create()
        state = self.task_path("state.md")
        text = state.read_text(encoding="utf-8")
        moved = text.replace(f"更新日時: {NOW}\n", "").replace(
            "初期状態。", f"初期状態。\n\n更新日時: {NOW}"
        )
        state.write_text(moved, encoding="utf-8")
        result = longneckctl.validate_task(self.root, "sample-task")
        self.assertFalse(result.ok)
        self.assertTrue(any("missing 更新日時" in error for error in result.errors))
        self.assertIsNone(result.updated)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support is required")
    def test_symlink_task_is_rejected(self) -> None:
        base = self.root / ".longneck"
        base.mkdir()
        target = self.root / "outside"
        target.mkdir()
        (base / "sample-task").symlink_to(target, target_is_directory=True)
        with self.assertRaises(longneckctl.LongneckError):
            longneckctl.task_directory(self.root, "sample-task")

    def test_lock_acquire_conflict_and_release(self) -> None:
        self.create()
        first = longneckctl.acquire_lock(self.root, "sample-task", "parent run")
        self.assertTrue(first["acquired"])
        self.assertEqual(first["note"], "parent run")

        second = longneckctl.acquire_lock(self.root, "sample-task", None)
        self.assertFalse(second["acquired"])
        self.assertEqual(second["holder"]["note"], "parent run")
        self.assertIsNotNone(second["age_seconds"])

        with self.assertRaises(longneckctl.LongneckError):
            longneckctl.release_lock(self.root, "sample-task", "wrong-token")
        released = longneckctl.release_lock(self.root, "sample-task", first["token"])
        self.assertTrue(released["removed"])
        with self.assertRaises(longneckctl.LongneckError):
            longneckctl.release_lock(self.root, "sample-task", first["token"])

    def test_unlock_force_removes_any_lock(self) -> None:
        self.create()
        longneckctl.acquire_lock(self.root, "sample-task", None)
        forced = longneckctl.release_lock(self.root, "sample-task", None, force=True)
        self.assertTrue(forced["removed"])
        absent = longneckctl.release_lock(self.root, "sample-task", None, force=True)
        self.assertFalse(absent["removed"])

    def test_list_reports_locks_and_ignores_locks_directory(self) -> None:
        self.create()
        longneckctl.acquire_lock(self.root, "sample-task", "held by test")
        listing = longneckctl.list_tasks(self.root)
        self.assertEqual(listing["entry_errors"], [])
        self.assertEqual(len(listing["locks"]), 1)
        self.assertEqual(listing["locks"][0]["title"], "sample-task")
        self.assertEqual(listing["locks"][0]["holder"]["note"], "held by test")
        self.assertTrue(listing["tasks"][0]["ok"])

    def test_lock_command_exit_codes(self) -> None:
        self.create()
        with contextlib.redirect_stdout(io.StringIO()):
            first = longneckctl.main(
                ["lock", "--root", str(self.root), "--title", "sample-task"]
            )
            second = longneckctl.main(
                ["lock", "--root", str(self.root), "--title", "sample-task"]
            )
        self.assertEqual(first, 0)
        self.assertEqual(second, 1)

    def test_severed_title_keeps_its_lock_until_released(self) -> None:
        self.create()
        held = longneckctl.acquire_lock(self.root, "sample-task", None)
        fingerprint = longneckctl.fingerprint_task(self.root, "sample-task")
        longneckctl.sever_task(self.root, "sample-task", fingerprint)
        self.assertFalse(self.task_path().exists())
        released = longneckctl.release_lock(self.root, "sample-task", held["token"])
        self.assertTrue(released["removed"])

    def write_manifest_baseline(self, title: str = "sample-task") -> Path:
        baseline = self.root / "baseline.json"
        baseline.write_text(
            json.dumps(longneckctl.manifest_task(self.root, title), ensure_ascii=False),
            encoding="utf-8",
        )
        return baseline

    def test_manifest_diff_reports_allowed_and_disallowed_changes(self) -> None:
        self.create()
        baseline = self.write_manifest_baseline()
        unchanged = longneckctl.manifest_diff(
            self.root, "sample-task", baseline, ["state.md"]
        )
        self.assertEqual(unchanged["changed"], [])
        self.assertEqual(unchanged["disallowed_changes"], [])

        state = self.task_path("state.md")
        state.write_text(
            state.read_text(encoding="utf-8").replace("初期状態。", "変更後。"),
            encoding="utf-8",
        )
        (self.task_path("docs") / "note.md").write_text(
            f"作成日時: {NOW}\n更新日時: {NOW}\n概要: 追加文書。\n", encoding="utf-8"
        )
        result = longneckctl.manifest_diff(self.root, "sample-task", baseline, ["state.md"])
        self.assertEqual(result["changed"], ["state.md"])
        self.assertEqual(result["added"], ["docs/note.md"])
        self.assertEqual(result["disallowed_changes"], ["docs/note.md"])
        self.assertNotEqual(
            result["baseline_fingerprint"], result["current_fingerprint"]
        )

    def test_manifest_diff_rejects_baseline_for_other_title(self) -> None:
        self.create()
        self.create("other-task")
        baseline = self.write_manifest_baseline("other-task")
        with self.assertRaises(longneckctl.LongneckError):
            longneckctl.manifest_diff(self.root, "sample-task", baseline, [])

    def test_manifest_diff_command_exit_codes(self) -> None:
        self.create()
        baseline = self.write_manifest_baseline()
        state = self.task_path("state.md")
        state.write_text(
            state.read_text(encoding="utf-8").replace("初期状態。", "変更後。"),
            encoding="utf-8",
        )
        arguments = [
            "manifest-diff",
            "--root",
            str(self.root),
            "--title",
            "sample-task",
            "--baseline",
            str(baseline),
        ]
        with contextlib.redirect_stdout(io.StringIO()):
            refused = longneckctl.main(arguments)
            allowed = longneckctl.main([*arguments, "--allow", "state.md"])
        self.assertEqual(refused, 1)
        self.assertEqual(allowed, 0)

    def test_next_decision_id_counts_headings_and_retired_ranges(self) -> None:
        self.create()
        fresh = longneckctl.next_decision_id(self.root, "sample-task")
        self.assertIsNone(fresh["max_used"])
        self.assertEqual(fresh["next_id"], "D-0001")

        progress = self.task_path("progress.md")
        progress.write_text(
            progress.read_text(encoding="utf-8")
            .replace("## 設計判断\n\nなし。\n", "## 設計判断\n\n### D-0002 — 方針\n\n- 決定: 維持する。\n")
            .replace(
                "- 検証: 初期形式を確認した。\n",
                "- 検証: 初期形式を確認した。退役設計判断ID: D-0003..D-0006\n",
            ),
            encoding="utf-8",
        )
        result = longneckctl.next_decision_id(self.root, "sample-task")
        self.assertEqual(result["max_used"], "D-0006")
        self.assertEqual(result["next_id"], "D-0007")

    def test_next_task_id_scans_state_progress_and_archive(self) -> None:
        self.create()
        result = longneckctl.next_id(self.root, "sample-task", "T")
        self.assertEqual(result["sources"], ["state.md", "progress.md"])
        self.assertEqual(result["max_used"], "T-0001")
        self.assertEqual(result["next_id"], "T-0002")

        # A completed task survives only in the work log; it must still block
        # its ID from reuse even after state.md no longer mentions it.
        progress = self.task_path("progress.md")
        progress.write_text(
            progress.read_text(encoding="utf-8").replace(
                f"### {NOW} — T-0001\n", f"### {NOW} — T-0005\n"
            ),
            encoding="utf-8",
        )
        archive = self.task_path("docs", "work-log-archive.md")
        archive.write_text(
            f"作成日時: {NOW}\n更新日時: {NOW}\n概要: 作業ログのアーカイブ。\n\n"
            f"### {NOW} — T-0009\n\n- 実施: 完了した。\n- 検証: 成功した。\n",
            encoding="utf-8",
        )
        result = longneckctl.next_id(self.root, "sample-task", "T")
        self.assertEqual(
            result["sources"], ["state.md", "progress.md", "docs/work-log-archive.md"]
        )
        self.assertEqual(result["max_used"], "T-0009")
        self.assertEqual(result["next_id"], "T-0010")

    def test_next_issue_id_scans_issues_and_progress(self) -> None:
        self.create()
        fresh = longneckctl.next_id(self.root, "sample-task", "I")
        self.assertEqual(fresh["sources"], ["issues.md", "progress.md"])
        self.assertIsNone(fresh["max_used"])
        self.assertEqual(fresh["next_id"], "I-0001")

        # A resolved issue is deleted from issues.md; the I-ID recorded in the
        # work log is what keeps it from being reused.
        progress = self.task_path("progress.md")
        progress.write_text(
            progress.read_text(encoding="utf-8").replace(
                "- 検証: 初期形式を確認した。\n",
                "- 検証: 初期形式を確認した。解消したissue: I-0004\n",
            ),
            encoding="utf-8",
        )
        result = longneckctl.next_id(self.root, "sample-task", "I")
        self.assertEqual(result["max_used"], "I-0004")
        self.assertEqual(result["next_id"], "I-0005")

    def test_next_decision_id_includes_work_log_archive(self) -> None:
        self.create()
        docs = self.task_path("docs")
        archive = docs / "work-log-archive.md"
        archive.write_text(
            f"作成日時: {NOW}\n更新日時: {NOW}\n概要: 作業ログのアーカイブ。\n\n"
            "## 作業ログ\n\n"
            f"### {NOW} — 管理作業\n\n"
            "- 実施: スリム化した。退役設計判断ID: D-0004..D-0012\n"
            "- 検証: validateが成功した。\n",
            encoding="utf-8",
        )
        result = longneckctl.next_decision_id(self.root, "sample-task")
        self.assertEqual(result["sources"], ["progress.md", "docs/work-log-archive.md"])
        self.assertEqual(result["max_used"], "D-0012")
        self.assertEqual(result["next_id"], "D-0013")

    def test_work_log_archive_heading_format_is_validated(self) -> None:
        self.create()
        archive = self.task_path("docs", "work-log-archive.md")
        metadata = f"作成日時: {NOW}\n更新日時: {NOW}\n概要: 作業ログのアーカイブ。\n\n"
        archive.write_text(
            metadata + f"### {NOW} — T-0001\n\n- 実施: 完了した。\n- 検証: 成功した。\n",
            encoding="utf-8",
        )
        result = longneckctl.validate_task(self.root, "sample-task")
        self.assertTrue(result.ok, result.errors)

        archive.write_text(
            metadata + f"### {NOW} / T-0001\n\n- 実施: 完了した。\n",
            encoding="utf-8",
        )
        result = longneckctl.validate_task(self.root, "sample-task")
        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "work log heading in docs/work-log-archive.md" in error
                for error in result.errors
            )
        )

        archive.write_text(
            metadata
            + "### 2026-07-21T12:00:00+09:00 — T-0001\n\n- 実施: 古い記録。\n\n"
            + "### 2026-07-22T12:00:00+09:00 — T-0001\n\n- 実施: 新しい記録。\n",
            encoding="utf-8",
        )
        result = longneckctl.validate_task(self.root, "sample-task")
        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "newest first in docs/work-log-archive.md" in error
                for error in result.errors
            )
        )

    def test_summary_line_must_directly_follow_title_heading(self) -> None:
        self.create()
        description = self.task_path("description.md")
        text = description.read_text(encoding="utf-8")
        description.write_text(
            text.replace(
                "\n概要: 検証用のLongneckタスクを完了する。\n\n## 目的\n",
                "\n## 目的\n",
            )
            + "\n概要: 検証用のLongneckタスクを完了する。\n",
            encoding="utf-8",
        )
        result = longneckctl.validate_task(self.root, "sample-task")
        self.assertFalse(result.ok)
        self.assertTrue(
            any("directly after the title heading" in error for error in result.errors)
        )

    def test_state_section_heading_whitespace_is_an_error(self) -> None:
        self.create()
        state = self.task_path("state.md")
        state.write_text(
            state.read_text(encoding="utf-8").replace("## 実行待ち\n", "## 実行待ち \n"),
            encoding="utf-8",
        )
        result = longneckctl.validate_task(self.root, "sample-task")
        self.assertFalse(result.ok)
        self.assertTrue(
            any("surrounding whitespace" in error for error in result.errors)
        )

    def test_nameless_task_heading_is_a_warning(self) -> None:
        self.create()
        state = self.task_path("state.md")
        state.write_text(
            state.read_text(encoding="utf-8").replace(
                "### T-0001 — 調査する", "### T-0001"
            ),
            encoding="utf-8",
        )
        result = longneckctl.validate_task(self.root, "sample-task")
        self.assertTrue(result.ok, result.errors)
        self.assertIn("task T-0001 has no name in its heading", result.warnings)


if __name__ == "__main__":
    unittest.main()
