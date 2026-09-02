---
name: longneck-flush
description: "完全一致で指定された .longneck/TITLE/ について、除去予定の知見を longneck-persist の flush-state-progress 範囲で外部正本へ収束させた後、state.md と progress.md をスリム化する。縮約後も肥大な古い作業ログは docs/work-log-archive.md へ退避する。ユーザーが $longneck-flush を指定した場合や、この2文書の肥大化解消・圧縮・整理を明示的に求めた場合に使う。タスクの実行、他文書の整理、削除前の全知見永続化、タスク削除には使わない。"
---

# Longneckの状態と履歴をスリム化する

除去する知見を外部正本へ先に永続化し、現在のタスク管理と純粋な作業履歴だけを残す。

## 必須契約を読む

作業前に次を全文読む。

- [task-format.md](../longneck/references/task-format.md)
- [operations.md](../longneck/references/operations.md)
- [targeting.md](../longneck/references/targeting.md)
- [persistence.md](../longneck/references/persistence.md)
- [flush.md](../longneck/references/flush.md)

同梱CLIまたは `persistence.md` の契約資源を使えない場合は、独自手順で知見を除去せず
失敗を返す。

## 契約を実行する

[flush.md](../longneck/references/flush.md) の契約を、情報の分類から終了報告まで、
そのまま実行する。

- 対象の確定は [targeting.md](../longneck/references/targeting.md) に従い、
  完全一致titleの明示指定を必須として自動選択しない。
- 縮約後も `progress.md` がしきい値を超える場合の古い作業イベントの退避は、
  flush.md の「作業ログのアーカイブ」に従い `docs/work-log-archive.md` だけへ行う。
- `persistence.md` の契約は、完全一致のtitleと `source_scope: flush-state-progress`
  を明示して実行し、スリム化へ進む受入条件は flush.md の
  「`longneck-persist` との境界」に従う。
- 新しい保存先の許可を `longneck-flush` 側で推測しない。
- コミットの要否はユーザー指示とプロジェクト固有ルールに従う。`longneck-flush` の
  成功をタスク完了または削除可能の根拠にしない。
