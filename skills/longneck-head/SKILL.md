---
name: longneck-head
description: "Longneck親エージェント専用の内部スキル。親のプロンプトで $longneck-head と、完全一致のroot、title、task ID、対象タスク全文を渡された場合だけ使う。一作業単位の実装・調査・検証を行い、Longneck文書へ状態と知見を同期して構造化報告を返す。ユーザーからの直接依頼、対象未指定、次タスク選択、全体ループには使わない。"
---

# Longneck Headとして一作業単位を行う

親から割り当てられた作業だけを完了し、全体をオーケストレーションしない。

## 親契約を確認する

プロンプトに完全一致のLongneck root、title、task ID、完了条件を含む対象タスク全文が
あることを確認する。不足している場合はファイルを変更せず、`worker-contract.md` の終了報告形式の
`status: failed` で、`longneck` 親からの再委譲が必要と返す。
ユーザーから直接起動された場合も作業を選ばず、`longneck` を使うよう案内する。

次を全文読む。

- [task-format.md](../longneck/references/task-format.md)
- [worker-contract.md](../longneck/references/worker-contract.md)

CLIでroot/titleを `validate` し、task IDが現在も `調査待ち` または `実行待ち` にあること、
依存関係を満たすことを確認する。ずれていれば変更せず `no_progress` を返す。

## 作業範囲を読む

ユーザー指示、適用されるすべての `AGENTS.md`、`description.md`、`state.md`、
`issues.md`、関係する `progress.md` と `docs/`、対象の恒久的正本を読む。
起動時のGit状態とLongneck fingerprintを記録し、既存変更を保持する。

## 一作業単位を完了する

`worker-contract.md` の「子の責務」に従い、対象の実装または調査、必要な文書更新、
関係する検証、Longneck文書への分類と同期を一作業単位で行う。知見の分類先と
文書別の書式は `task-format.md` に従う。次タスクを選ばず、ユーザー判断を推測しない。

- サブエージェントは、ファイルを変更しない読取専用の探索（コード検索、広範な調査の
  並列化）に限って起動してよい。実装、文書更新、Longneck記録、検証の実行は委譲せず、
  探索結果は自分で裏取りする。
- 判断が必要なら選択肢とpros/consを `state.md` の `判断待ち` へ、外部条件待ちは
  `ブロック中` へ記録する。
- 完了条件を満たさずに終了する場合は、残作業の分解、ブロッカー、または必要な判断を
  `state.md` へ記録する。この記録がない未完了に対して、親は再委譲せず全体ループを
  停止する。

## 不変条件を検証する

「子の責務」の禁止事項（逆参照の作成、`description.md` の変更、他のLongneckスキル
契約の実行、`.longneck` の追跡状態の独断変更、全体ループ）と、`task-format.md` の
「機密情報と安全性」を守る。対象titleのロックは親が保持しており、自分では
CLIの `lock` を取得しない。コミットは親から渡された方針、ユーザー指示、
プロジェクト固有ルールに従う。

実装検証に加え、CLIの `validate` と `fingerprint` を実行する。検証失敗や完了条件未達を
`completed` としない。

## 構造化報告を返す

`worker-contract.md` の終了報告形式をそのまま使う。通常の成功では永続的知見を
ファイルへ記録し、`unrecorded_findings: none` とする。記録不能なら理由と必要な
ユーザー判断を明記し、親が停止できるようにする。
