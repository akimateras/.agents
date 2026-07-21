---
name: longneck-amend
description: "完全一致で指定された .longneck/TITLE/ の description.md を、ユーザーが明示した変更内容だけで改訂し、残タスクへの影響を報告する。ユーザーが $longneck-amend を指定した場合や、Longneckタスクの目的・スコープ・完了条件の変更・再定義を明示的に求めた場合に使う。タスクの実行、新規作成、state.md・issues.md の編集、永続化、スリム化、削除には使わない。"
---

# Longneckタスク定義を改訂する

ユーザーが明示した変更だけを `description.md` へ反映し、残タスクへの影響を報告する。
このスキルを暗黙に起動しない。

## 必須契約を読む

作業前に次を全文読む。

- [task-format.md](../longneck/references/task-format.md)
- [operations.md](../longneck/references/operations.md)
- [targeting.md](../longneck/references/targeting.md)
- [amend.md](../longneck/references/amend.md)

同梱CLIを使えない場合は、独自の検証で代用せず失敗を返す。

## 契約を実行する

[amend.md](../longneck/references/amend.md) の契約を、対象と変更内容の確定から検証と
報告まで、そのまま実行する。`description.md` と `progress.md` の管理作業ログ以外を
変更せず、改訂後に `longneck` を自動起動しない。
