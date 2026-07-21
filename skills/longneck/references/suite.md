# Longneckスキル群の構成

## 目次

- 配置の前提
- スキル一覧
- 契約文書の正本

## 配置の前提

Longneckは9つのスキルで構成され、常に一括で配置する。共有契約（この `references/`
配下）と同梱CLI（`scripts/longneckctl.py`）は `longneck` スキルにだけ同梱され、
他の8スキルは `../longneck/references/` と `../longneck/scripts/` への相対パスで
参照する。部分的な配置では各スキルが起動時に不足を検出して停止し、独自契約で
代用しない。

## スキル一覧

- `longneck`: 親オーケストレーター。実行可能なタスクを1つずつ子へ委譲して進める。
- `longneck-head`: 親専用の子。割り当てられた一作業単位だけを実行する。
- `longneck-spawn`: 新しいタスク一式を原子的に作成する。
- `longneck-status`: 読み取り専用でタスクの一覧と現在状態を表示する。
- `longneck-amend`: ユーザーの明示指示で `description.md` を改訂する。
- `longneck-repair`: 明示起動とユーザー承認のもとで、壊れた文書の形式だけを修復する。
- `longneck-persist`: 知見と外部正本のギャップを調べ、不足分だけを永続化する。
- `longneck-flush`: 永続化の成功後に `state.md` と `progress.md` をスリム化する。
- `longneck-sever`: full-task 永続化の成功後に、対象1ディレクトリだけを削除する。

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
