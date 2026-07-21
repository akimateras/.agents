---
name: longneck-sever
description: "Longneckタスクを削除する破壊的な専用スキル。ユーザーが $longneck-sever と完全一致のtitleを明示した削除依頼にだけ使う。persistence.md の契約を full-task 範囲で成功させた後だけ、同梱CLIで .longneck/TITLE の1ディレクトリを削除する。タスク完了、整理、類似名、暗黙の意図からは起動しない。"
---

# Longneckタスクを切り離す

知見の永続化に成功した対象だけを、完全一致のpathから削除する。
このスキルを暗黙に起動しない。

## 必須契約を読む

作業前に次を全文読む。

- [task-format.md](../longneck/references/task-format.md)
- [operations.md](../longneck/references/operations.md)
- [targeting.md](../longneck/references/targeting.md)
- [persistence.md](../longneck/references/persistence.md)

どれかが存在しなければ削除しない。

## 対象だけを先に検証する

原則: 有効な対象を特定できている限り、ユーザーへの質問より先にpersistを実行する。
titleが未指定、不正、不存在の場合だけは対象が分からずpersistを実行できないため、
例外として `targeting.md` に従いこの段階で聞き返す。類似名、唯一の既存title、
会話内容から補完しない。

`targeting.md` の共通手順でLongneckルートを確定し、persistより前に行える唯一の
確認として、次を読み取り専用で検証する。

1. ユーザーが `$longneck-sever` と完全一致のtitleを明示している。
2. titleが `^[a-z0-9]+(?:-[a-z0-9]+)*$` に一致する。
3. Longneckルート、`.longneck`、対象が通常ディレクトリで、symlinkではない。
4. `.longneck/<title>` が実在し、ルート外へ解決されない。

## 必ず永続化する

1. CLIの `lock` で対象titleのロックを取得する。取得できなければ、保持者情報を
   報告して中止する。ロックは削除の完了または中止の後に、自分のtokenで解放する。
2. CLIの `fingerprint` で開始fingerprintを取得する。
3. 同じtitleと `source_scope: full-task` を明示し、`persistence.md` の契約の手順と
   終了報告を、保持したロックの下で実行する。確定済みのrootとtitleは
   `targeting.md` の引き継ぎ規則に従い再解決しない。
4. 結果が `persisted` または `already_persisted`、`source_scope` が `full-task`、
   `deletion_ready: true`、未解決ギャップ0件、検証成功であることを確認する。
5. 失敗、判断待ち、矛盾、保存先許可待ちなら、このスキルも中止して削除しない。
6. CLIの `backlinks` で、対象title自身を除くLongneckルート配下（他titleを含む）に
   対象パスへの参照がないことを確認する。残っていれば永続化未完了として削除しない。
   `backlinks` はパス形式 `.longneck/<title>` と対象内へ解決されるsymlinkだけを
   検出する部分的な安全網であり、title単独や内部IDによる参照は検出しない。
   Gitリポジトリでは追跡ファイルと未追跡の非ignoreファイル、および `.longneck`
   配下全体を走査し、ignoreされた外部ファイルとsubmodule内部は走査しない。
   Git外では既知の依存・キャッシュディレクトリ（`node_modules` など、結果の
   `pruned` に報告される）を走査しない。走査エラーがあると有効なJSONとともに
   exit code `2` を返すため、参照なしの根拠にせず永続化未完了として削除しない。
   逆参照禁止の契約遵守の確認をこの検査だけで代替しない。

## 復元可能性を確認する

削除の直前に、対象の原本がGit履歴から復元できるかを確認する。

1. Gitリポジトリなら、対象 `.longneck/<title>` の追跡状態と未コミット変更を
   読み取り専用で調べる（例: `git status --porcelain` と `git ls-files` を対象パスに
   限定して実行する）。
2. 対象の全ファイルが追跡済みで未コミット変更がなければ、履歴から復元可能なので
   そのまま削除へ進む。
3. 未追跡ファイルまたは未コミット変更がある場合、もしくはルートがGitリポジトリで
   ない場合は、削除により原本自体が復元不能になることを提示し、一度だけ削除の
   最終確認をユーザーへ求める。承認を得られなければ削除しない。承認後に同じ確認を
   繰り返さない。

## 完全一致の対象だけを削除する

persist報告の `source_fingerprint` を明示して、CLIで削除する。

```text
python3 <longneck-skill>/scripts/longneckctl.py sever --root <root> --title <exact-title> --expect-fingerprint <sha256>
```

CLIは削除の直前にfingerprintを再計算し、一致した場合だけ `.longneck/<title>` の
1ディレクトリを削除する。この照合とロックは助言的な安全網であり、完全な排他は
保証しない。不一致で失敗した場合は対象が変更されているため、削除せず
persistを最初からやり直すか、安全に再実行できなければ中止する。`rm` による手動削除、
親 `.longneck` や複数titleの指定、失敗時の強制再試行を行わない。

削除後、対象pathが存在せず、他titleが変化していないことを確認し、保持していた
ロックを自分のtokenで解放する。外部へ永続化した
変更、実行した検証、削除したtitle、復元可能性の確認結果を報告する。
削除のコミットはユーザー指示とプロジェクト固有ルールに従い、コミットメッセージに
Longneckのパス、title、内部IDへの逆参照を作らない。
