---
name: longneck-spawn
description: "新しいLongneckタスク一式（description・state・progress・issues・docs）を .longneck/TITLE/ へ原子的に作成する。ユーザーが $longneck-spawn を指定した場合、作業内容とともに新しいLongneckタスクの作成・登録・開始準備を依頼した場合、または既存の非Longneck形式の管理文書（旧形式のSTATE / PROGRESSなど）のLongneckタスクへの移行を依頼した場合に使う。既存titleの更新、タスクの実行、永続化、スリム化、削除には使わない。"
---

# Longneckタスクを作る

新しいタスク一式を、既存内容を上書きせずに作成する。

## 必須契約を読む

最初に [task-format.md](../longneck/references/task-format.md)、
[operations.md](../longneck/references/operations.md)、
[targeting.md](../longneck/references/targeting.md) を全文読み、同梱CLIの利用方法を
確認する。依存資源がなければ推測で作成せず、Longneckスキル群の不足を報告する。

## 入力を確定する

1. ユーザーの最新指示と適用される `AGENTS.md` を確認する。
2. 目的、スコープ、全体の完了条件を特定する。タスク内容がない、目的が複数に
   解釈できる、完了を判定できない場合は、不足する一点を具体的に聞き返す。
3. 実装方法が未調査なだけなら聞き返さず、最初の `調査待ち` タスクとして表現する。
4. 既存の非Longneck管理文書（旧形式のSTATE / PROGRESSなど）からの移行では、
   その内容を素材として読み、目的・スコープ・完了条件・残タスク・将来知見を
   4文書へ再分類する。元文書は変更・削除せず、その後の扱い（削除、保管、参照）は
   ユーザー指示に従う。
5. `targeting.md` の共通手順でLongneckルートを確定する。
6. CLIの `list --root <root>` で既存titleと壊れたentryを確認する。

## titleを決める

ユーザーがtitleを指定した場合、`^[a-z0-9]+(?:-[a-z0-9]+)*$` への完全一致と
既存titleとの非衝突を確認する。不正または衝突なら作成せず、有効な候補を1つ提案して
聞き返す。ユーザー指定を無断でlowercase化、suffix追加、置換しない。

指定がなければ目的を表す短いlowercase kebab-caseを作る。既存名と衝突する場合は、
意味を保つ語または数値suffixで一意にする。

## 文書内容を組み立てる

`task-format.md` のtemplateに従い、次を用意する。

- `description.md`: 一文概要、目的、スコープ、非スコープ、完了条件、長期制約、作業対象
- `state.md`: 現在snapshot、`T-0001` から始まる残タスク、4つの状態区分
- `progress.md`: 必要な初期設計判断と、作成を記録する最初の作業ログ
- `issues.md`: 収録基準と空の未解決一覧。既知の将来知見があれば初期項目
- `docs/`: 空ディレクトリ

日時は同梱CLIの `now` が出力する現在時刻を使う。初期タスクが実装可能な粒度なら
`実行待ち`、調査・分解が必要なら `調査待ち` に置く。目的達成に必要な判断を最初から
`issues.md` へ退避しない。

## 原子的に作成する

1. `.longneck` がsymlinkでないこと、対象titleが存在しないことを再確認する。
2. 4文書の完成内容を、`description.md`、`state.md`、`progress.md`、`issues.md` の
   4ファイルだけを持つ、リポジトリ外の専用一時ディレクトリへUTF-8で用意する。
3. CLIの `create --root <root> --title <title> --spec-dir <dir-path>` を実行する。
   CLIは一時ディレクトリで全内容を作り、完成後に対象titleへrenameする。
4. 成否にかかわらず、自分が作成したspec一時ディレクトリだけを除去する。
5. CLIの `validate` と `fingerprint` を実行する。
6. 失敗時は既存entryへ再試行せず、原因と残存状態を確認して報告する。

`.gitignore`、exclude、stagingを変更しない。未追跡の `.longneck` を自動で
`git add` しない。作成後に `longneck` を自動起動しない。

## 結果を返す

root、title、作成した4文書と `docs/`、最初のタスクIDと状態、validation結果を返す。
ユーザーが同じ依頼で実行開始も明示した場合だけ、作成完了後に `longneck` の契約へ
切り替える。
