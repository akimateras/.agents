# Longneck対象確定契約

## 目次

- 共通手順
- スキル別の差分
- 呼出元からの引き継ぎ

## 共通手順

ルートとtitleを対象にするすべてのLongneckスキルは、次の共通手順で対象を確定する。
`longneck-head` は対象を親プロンプトから受け取るため、この契約を使わない。

1. スキル起動時の作業ディレクトリを保持し、以後ディレクトリを移動しても基準を
   変えない。
2. 同梱CLIの `root --start <initial-cwd>` でLongneckルートを確定する。
   Gitリポジトリならリポジトリルート、それ以外なら起動時の作業ディレクトリになる。
3. 指定されたtitleは `^[a-z0-9]+(?:-[a-z0-9]+)*$` への完全一致だけを認める。
   無断の正規化、lowercase化、suffix追加、曖昧一致を行わない。
4. titleが未指定、不正、不存在なら、類似名、会話内容、更新日時、`AGENTS.md` から
   推測せず、CLIの `list --root <root>` による候補を示して聞き返す。唯一の
   既存titleからの自動選択は、次節で明示的に許可されたスキルだけが行える。

## スキル別の差分

破壊的または不可逆な操作ほど自動選択を認めない。ここに挙げないスキルは
自動選択不可を既定とする。

- `longneck`: titleが1件でユーザー未指定なら、その1件を自動選択してよい。
  複数あれば概要付き一覧を示して聞き返す。
- `longneck-status`: 既定で全titleを一覧する。title指定時だけ完全一致で
  詳細表示する。
- `longneck-spawn`: 新規作成であり既存titleを選択しない。ユーザー指定titleの
  検証・衝突確認と、未指定時の命名は `task-format.md` に従う。
- `longneck-amend`: 合意済みのタスク定義を変更するため、完全一致titleの明示指定を
  必須とし、自動選択しない。
- `longneck-repair`: 合意済み文書の形式を変更するため、完全一致titleの明示指定を
  必須とし、自動選択しない。title未指定の診断は読み取り専用の報告に限る。
- `longneck-persist` / `longneck-flush`: 完全一致titleの明示指定を必須とし、
  自動選択しない。
- `longneck-sever`: 破壊的操作。`$longneck-sever` と完全一致titleの明示を必須とし、
  自動選択しない。

## 呼出元からの引き継ぎ

別のLongneckスキルの内部で契約として実行される場合は、呼出元が確定済みの root、
title、および指定があれば `source_scope` をそのまま引き継ぎ、rootの再解決、
titleの再選択、範囲の再判定を行わない。対象は次のとおりとする。

- `longneck-flush` と `longneck-sever` が実行する `persistence.md` の契約
- `longneck` 親が実行する `amend.md` の契約

引き継いだ値の検証(validate、fingerprint)は各契約の定めに従って行う。
