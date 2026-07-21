# Longneck運用契約

この契約は [task-format.md](task-format.md) の形式を前提に、文書のスリム化の運用、
Git管理の中立性、同時変更の検出と排他を定める。文書の形式だけを必要とする
`longneck-head` はこの契約を読まず、親と各専用スキルが読む。

## 目次

- 定期的なスリム化
- Git管理の中立性
- 同時変更の検出と排他

## 定期的なスリム化

`state.md` または `progress.md` が肥大化した場合は、ユーザーが明示的に求めたときだけ
`longneck-flush` を使う。詳細な分類、永続化、縮約、復旧、検証は
[flush.md](flush.md) に従う。肥大化の把握には、CLIの `list` が各titleについて報告する
両文書のサイズ（`sizes` のbytesとlines）を使う。`state.md` が300行または16 KiB、
`progress.md` が800行または64 KiBのいずれかを超えると、CLIの `list` と `validate` は
warningとして報告する。このwarningは `longneck-flush` の提案材料であり、
自動起動やエラーの根拠にしない。

`longneck-flush` は除去予定の知見を外部正本へ先に永続化し、`state.md` を現在のタスク管理、
`progress.md` を純粋な作業ログへ縮約する。縮約後も `progress.md` がしきい値を超える
場合は、古い作業イベントを `docs/work-log-archive.md` へ退避できる（[flush.md](flush.md)
の「作業ログのアーカイブ」）。`description.md`、`issues.md`、このアーカイブを除く
`docs/` は変更しない。外部へ移した知見を、後続作業で同じLongneck文書へ再び複製しない。

通常の作業で新しい設計判断が生じた場合は `progress.md` へ記録してよい。再度肥大化した
ときに次回の `longneck-flush` で外部へ収束させる。`longneck-flush` を、タスク実行、
完了処理、issue整理、削除の代わりに使わない。

## Git管理の中立性

`.longneck` をGit管理するかどうかはユーザーの選択とし、推奨も非推奨もしない。

- `.gitignore`、`.git/info/exclude`、attributesを自動変更しない。
- 既に追跡されているLongneck文書は既存方針に従う。
- 未追跡の `.longneck` を、明示指示なしに `git add` しない。
- ignored状態を解除しない。
- Longneckの更新検証にはファイルfingerprintを使い、Git差分だけに依存しない。
- 外部へ永続化した変更のコミットは、ユーザー指示とプロジェクト固有ルールに従う。

## 同時変更の検出と排他

同じtitleに対する排他には、CLIの `lock` / `unlock` による助言的ロックと、
`fingerprint` / `manifest` による事後検出を併用する。ロックは
`.longneck/.locks/<title>.lock` に保持者情報とtokenを記録するファイルで、
ファイルシステム上の強制力を持たない。ロックの取得成功を同時変更がないことの
証明として扱わず、fingerprintの照合を省略する根拠にもしない。

- 対象titleの文書を変更するスキル（`longneck` 親、`longneck-amend`、
  `longneck-repair`、`longneck-flush`、`longneck-sever`）と、対象の文書は
  変更しないが調査中の情報源が不変であることに依存する直接起動された
  `longneck-persist` は、対象の確定後、最初の書込みより前に `lock` を取得し、
  終了時に自分のtokenで `unlock` する。取得時は `--note` に実行スキル名と目的を
  短く記録し（例: `--note "longneck-flush: state/progressのスリム化"`）、競合時の
  保持者報告を実用的にする。例外的中断でも可能な限り解放し、
  解放できなければ最終報告で伝える。
- ロックが記録する `pid` はCLI呼出しのプロセスIDであり、即座に終了するため残留
  判定に使えない。残留の疑いは `note` の内容と経過時間で判断する。
- `lock` が既存の保持者を報告した場合は、保持者情報と経過時間を添えて停止する。
  自動でのリトライ、強制解除、保持者への割込みを行わない。
- `unlock --force` は、プロセス異常終了などで残留したロックの解除をユーザーが
  明示的に指示した場合だけ使う。残留の疑いは `list` が報告する `locks` の
  保持者情報と経過時間で判断材料を示し、解除自体はユーザー判断に委ねる。
- 読み取り専用の `longneck-status` と、原子的な `create` で衝突が防がれる
  `longneck-spawn` はロックを取得しない。`longneck-head` は親のロックの下で
  作業するため自分では取得しない。
- 各スキルは、基準として記録した `fingerprint` との不一致を検出した時点で、
  対象を変更せずに停止する。
