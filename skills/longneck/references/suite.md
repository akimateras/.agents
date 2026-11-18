# Longneckスキル群の構成

## 目次

- 配置の前提
- スキル一覧
- `longneck-spawn-*` シリーズ
- 契約文書の正本

## 配置の前提

Longneckは10のスキルで構成され、常に一括で配置する。共有契約（この `references/`
配下）と同梱CLI（`scripts/longneckctl.py`）は `longneck` スキルにだけ同梱され、
他の9スキルは `../longneck/references/` と `../longneck/scripts/` への相対パスで
参照する。部分的な配置では各スキルが起動時に不足を検出して停止し、独自契約で
代用しない。

## スキル一覧

- `longneck`: 親オーケストレーター。実行可能なタスクを1つずつ子へ委譲して進める。
- `longneck-head`: 親専用の子。割り当てられた一作業単位だけを実行する。
- `longneck-spawn`: 新しいタスク一式を原子的に作成する。
- `longneck-spawn-review-cycle`: `longneck-spawn` の特殊化。レビューと修正の
  サイクルを指摘がなくなるまで繰り返すタスクを作成する。
- `longneck-status`: 読み取り専用でタスクの一覧と現在状態を表示する。
- `longneck-amend`: ユーザーの明示指示で `description.md` を改訂し、改訂の帰結
  として必要な `state.md` の整合をユーザー承認のもとで適用する。
- `longneck-repair`: 明示起動とユーザー承認のもとで、壊れた文書の形式だけを修復する。
- `longneck-persist`: 知見と外部正本のギャップを調べ、不足分だけを永続化する。
- `longneck-flush`: 永続化の成功後に `state.md` と `progress.md` をスリム化する。
- `longneck-sever`: full-task 永続化の成功後に、対象1ディレクトリだけを削除する。

## `longneck-spawn-*` シリーズ

`longneck-spawn-*` で命名するスキルは、特定用途のタスクに合わせて文書内容を
テンプレート化した `longneck-spawn` の特殊化とする。次を共通の規則とする。

- 呼出しの形は `<スキル名> <タスク名> <タスク内容>` とする。
- 作成の手順（ルートとtitleの確定、原子的な作成、検証、結果の報告）は
  `longneck-spawn` のSKILL.mdに従う。用途別の規則で置き換えるのは入力の確定と
  文書内容の組み立てだけとし、結果の報告には用途別の項目を加えてよい。
  作成手順を複製しない。
- 作成したタスクは通常のLongneckタスクであり、`longneck` 親と `longneck-head` が
  共有契約のまま進める。用途別の進め方は、`description.md` の長期制約と各タスク
  項目から、特殊化スキルに同梱した規約文書を参照して親と子へ伝える。スキル群は一括で
  配置するため、`longneck` と `longneck-head` からは `../<特殊化スキル名>/references/` の
  相対パスで読める。
- 用途別の規則のために共有契約の変更が必要な場合は、特殊化スキルの中で上書きせず、
  用途に依存しない仕組みとしてこの `references/` へ追加する。

## 契約文書の正本

規範となる契約の正本は `references/` に置き、各スキルのSKILL.mdはトリガー条件と
実行順序を示すエントリポイントとする。同じ規範を複数の場所へ書かず、SKILL.mdからは
契約の該当箇所を参照する。

- [task-format.md](task-format.md): ルート、文書形式、分類、不変条件
- [operations.md](operations.md): スリム化の運用、Git管理の中立性、同時変更の検出と排他
- [targeting.md](targeting.md): ルートとtitleの共通確定手順と呼出元からの引き継ぎ
- [orchestration.md](orchestration.md): `longneck` 親のループ、待機、終了判定
- [worker-contract.md](worker-contract.md): 親子の作業契約、報告、無進捗と終了
- [amend.md](amend.md): `description.md` の改訂契約
- [repair.md](repair.md): 形式修復の診断・承認・適用契約
- [persistence.md](persistence.md): 知見の外部永続化契約
- [flush.md](flush.md): `state.md` と `progress.md` のスリム化契約
