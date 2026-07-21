---
name: longneck-persist
description: "完全一致で指定された .longneck/TITLE/ の知見と外部正本との意味上のギャップを調査し、不足分だけを自己完結した形で外部へ永続化する。ユーザーが $longneck-persist を指定した場合や、Longneckタスクの知見保存・削除前の退避・外部正本への収束を直接求めた場合に使う。longneck-sever と longneck-flush は persistence.md の契約を自身のコンテキスト内で実行するため、その前処理としてこのスキルを別エージェントで起動しない。タスクの実行、スリム化、削除には使わない。"
---

# Longneckの知見を永続化する

外部正本との差分を先に調べ、未記録の意味だけを適切な場所へ統合する。

## 必須契約を読む

作業前に次を全文読む。

- [task-format.md](../longneck/references/task-format.md)
- [operations.md](../longneck/references/operations.md)
- [targeting.md](../longneck/references/targeting.md)
- [persistence.md](../longneck/references/persistence.md)

`flush-state-progress` を使う場合は
[flush.md](../longneck/references/flush.md) も全文読む。

同梱CLIを使えない場合は、収束性とfingerprintを独自判断で代用せず失敗を返す。

## 契約を実行する

[persistence.md](../longneck/references/persistence.md) の契約を、永続化範囲の
確定から終了報告まで、そのまま実行する。対象の確定と呼出元からの引き継ぎは
[targeting.md](../longneck/references/targeting.md) に従い、完全一致titleを必須と
して自動選択しない。コミットの要否はユーザー指示とプロジェクト固有ルールに従う。
