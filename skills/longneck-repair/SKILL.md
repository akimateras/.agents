---
name: longneck-repair
description: "CLIの validate がエラーを報告する .longneck/TITLE/ の形式だけを診断し、修復案ごとにユーザー承認を得てから意味内容を変えない最小修復を適用する。ユーザーが $longneck-repair を指定した場合や、Longneck文書の形式エラー修復を明示的に求めた場合に使う。タスクの実行、意味の変更、知見の追加・除去、永続化、スリム化、削除、欠けた内容の推測による補完には使わない。"
---

# Longneckの形式を修復する

形式エラーだけを、ユーザー承認のうえで最小限に修復する。このスキルを暗黙に起動しない。

## 必須契約を読む

作業前に次を全文読む。

- [task-format.md](../longneck/references/task-format.md)
- [operations.md](../longneck/references/operations.md)
- [targeting.md](../longneck/references/targeting.md)
- [repair.md](../longneck/references/repair.md)

同梱CLIを使えない場合は、独自の診断や修復で代用せず失敗を返す。

## 契約を実行する

[repair.md](../longneck/references/repair.md) の契約を、診断から終了報告まで、
そのまま実行する。承認前にLongneck文書を変更せず、修復後に `longneck` を
自動起動しない。
