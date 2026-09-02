---
name: longneck-status
description: "Longneckタスクのtitle、概要、全体状態、更新日時、4区分の残件数、形式異常を読み取り専用で一覧または詳細表示する。ユーザーが $longneck-status を指定した場合や、利用可能なLongneckタスク、正確なtitle、現在状態、残件、判断待ち、ブロッカーの確認を求めた場合に使う。タスクの進行、作成、修復、永続化、スリム化、削除には使わない。"
---

# Longneckの状態を確認する

ファイルを変更せず、利用できるタスクと現在状態を報告する。

## 必須契約を読む

[task-format.md](../longneck/references/task-format.md)、
[operations.md](../longneck/references/operations.md)、
[targeting.md](../longneck/references/targeting.md) を読み、同梱CLIを使う。これらまたは
同梱CLIが見つからない場合は、独自に探索した結果をLongneckの正式な状態として
報告せず、スキル資源の不足だけを報告する。

## 一覧を作る

1. `targeting.md` の共通手順でLongneckルートを確定する。
2. `list --root <root>` を実行する。形式エラーがあるとexit codeは1になるが、
   標準出力のJSONは有効なので、コマンド失敗と扱わず内容を報告に使う。
3. 各entryについてtitle、`description.md` の一文概要、`state.md` の全体状態、
   更新日時、4区分の件数、`sizes` が報告する `state.md` と `progress.md` の
   サイズ、validation error/warningを表示する。CLIが2文書のサイズ超過
   （`operations.md` の「定期的なスリム化」のしきい値）をwarningとして報告した
   場合は、ユーザーが `longneck-flush` を明示起動してスリム化できることを添える。
   自動では起動しない。
4. `list` が報告する `entry_errors` と `stale_entries` も一覧へ含める。
   `stale_entries` は作成中断の残留物であり、削除は `longneck` の進行時または
   ユーザーの明示指示により、CLIの `clean-stale` で行えることを示す。
5. `list` が報告する `locks`（助言的ロックの保持状況）も、保持者情報と経過時間と
   ともに表示する。残留が疑われるロックがあっても自分では解除せず、解除には
   ユーザーの明示指示によるCLIの `unlock --force` が必要なことを示す。
6. 0件ならLongneckタスクがないことを返し、作成には `longneck-spawn` を使うと示す。

titleが指定された場合は完全一致だけを認める。存在しなければ候補一覧を示し、
類似名を自動選択しない。対象を `validate` し、`description.md` と `state.md` の
全文と、`issues.md` の未解決一覧を読む。ユーザーが履歴や詳細を求めた場合だけ、
関係する `progress.md` または `docs/` を追加で読む。

## 読み取り専用を守る

形式異常、古い更新日時、状態と件数の不一致を見つけても修正しない。原因、パス、影響と、
`task-format.md` に基づく推奨修復手順を報告する。修復自体は実行せず、ユーザーの
手作業または明示起動された `longneck-repair` に委ねる。サブエージェント、`longneck`、
`longneck-amend`、`longneck-repair`、`longneck-persist`、`longneck-flush`、
`longneck-sever` を起動せず、Gitのindex、working tree、ignore設定を変更しない。
