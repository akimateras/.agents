---
name: longneck
description: "既存のLongneckタスク（.longneck/TITLE/）を進める親オーケストレーター。実行可能なタスクを1つずつ新しい子エージェントへ委譲し、成果を実ファイルで照合しながら、完了するか、全残件が判断待ち・ブロック中になるか、進捗が得られなくなるまで進める。ユーザーが $longneck を指定した場合や、Longneckタスクの継続・再開・残件消化を依頼した場合に使う。Longneck形式でない STATE / PROGRESS には使わず、状態確認、新規作成、定義改訂、形式修復、永続化、スリム化、削除は各専用スキルに委ねる。"
---

# Longneckを進める

選択したLongneckタスクの全体管理、子への委譲、成果の検証、終了判定を行う。
親自身は一作業単位の実装担当にならない。

## 必須契約を読む

作業前に次をすべて読む。

- [task-format.md](references/task-format.md): ルート、文書形式、分類、不変条件
- [operations.md](references/operations.md): スリム化の運用、Git管理の中立性、同時変更の検出と排他
- [targeting.md](references/targeting.md): ルートとtitleの共通確定手順
- [orchestration.md](references/orchestration.md): 親のループ、待機、終了判定
- [worker-contract.md](references/worker-contract.md): 親子の作業契約、報告、検証

スキル群の構成と一括配置の前提は [suite.md](references/suite.md) に定める。
資源の不足を疑う場合に参照すればよい。
同梱CLI `scripts/longneckctl.py` を、ルート特定、一覧、検証、fingerprint、
ロックに使う。参照文書、同梱CLI、または依存する `longneck-head` スキルが
見つからない場合は、独自契約で代用せず停止する。

## 契約を実行する

[orchestration.md](references/orchestration.md) の契約を、対象の選択から
最終報告まで、そのまま実行する。

- 子への委譲、報告の照合、無進捗の扱いは
  [worker-contract.md](references/worker-contract.md) に従う。
- ロックの競合、または自分の管理編集にも委譲した子の成果にも帰属しない
  基準fingerprintとの不一致（第三者による同時変更）を検出した場合は、対象を
  変更せずに停止する。自分の編集後と子の照合後は基準を取り直し、正当な変更を
  同時変更と誤認しない。
