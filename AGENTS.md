# AGENTS.md — ARC-AGI-3

## 言語
応答・ドキュメント・コミットメッセージは日本語。

## 承認が必要な操作（その都度ユーザーの明示承認）
- `kaggle kernels push`、`kaggle competitions submit`、Dataset / Model の作成・更新
- `git push`（commit はローカルで可。push 前に確認）
- 提出は **1 日 1 回**（UTC 00:00 リセット）。枠は貴重なので、検証済みのものだけを出す。

## 守ること
- **リポジトリは private のまま。** コンペ期間中のコードの私的共有は禁止（公開するなら Kaggle 上で全員に）。
- 提出カーネルは `is_private: true` を push 前に確認する。
- 外部モデル・データは「無料で誰でも入手可能」なものだけ。入賞時は CC-BY 4.0 でオープンソース化が条件
  なので、ライセンスが OSI 互換でない部品は使う前にユーザーに確認する。
- 公開 25 ゲームのローカルスコアは LB の推定値ではない（採点は未見の 110 ゲーム）。公開ゲームに
  特化した手書き解法で上がった数字を「改善」と呼ばない。
- `data/`・`work/`・重みはコミットしない。
- 判定規則は結果が出る前に `analysis/experiment_ledger.md` に書く。

## 環境
- Python 3.12（Kaggle の wheel が cp312）。`arc-agi==0.9.8` / `arcengine==0.9.3` は Kaggle 同梱版に固定。
- Hermes のシェルでは `env -u PYTHONPATH uv run ...`（別 Python の site-packages が混入するため）。
- この Mac は他の重いジョブ・Docker と共有。重い処理の前に空きメモリを確認し、他プロセスに触らない。
  ディスク空きは約 20 GB しかないので、大きなモデルの重みをローカルに置くときは事前に確認する。

## Git 運用（2026-10-29〜、1 つの作業 = 1 Issue = 1 ブランチ = 1 PR）
1. **Issue を立てる**（日本語）。ラベルは `lineage-loop` と種類（`bug` / `enhancement`）。オーナーの判断が要るものは `needs-decision`。追跡用の親は #1。
2. **ブランチを切る**: 最新の `origin/develop` から `<種類>/<Issue番号>-<内容>`（例: `fix/5-pv-tuple-keys`、`feat/2-ci-git-workflow`）。
3. **コミット**: 1 論理単位ごと、`feat(...)` / `fix(...)` / `chore(...)` の形、本文に `Refs #番号`。
4. **PR**: ブランチを push して `gh pr create --base develop`。本文に変更内容・数値・`Fixes #番号`。
5. **CI**: GitHub Actions の `tests` が通るまでマージしない。
6. **マージ**: 受け入れ条件を満たしたら `gh pr merge --merge --delete-branch`（マージコミットを残す）。
7. **確認と記録**: マージ後の `develop` で測り直し、結果を Issue にコメントし、#1 のチェックを更新する。

補足:
- 作業ディレクトリは 1 つ（worktree は作らない）。cron の提出ループ・改善ループはこの作業ツリーのスクリプトを実行するので、作業ブランチにいる時間は短くし、終わったら必ず `develop` に戻る。
- 自動ループが書き換える記録ファイル（`analysis/loop_state.json`、`analysis/bench_state.json`、`analysis/submission_log.md`、`analysis/smoke/*.json`、`analysis/reviews/*.md`）は、日次レビューでまとめて `chore/<親番号>-records-YYYYMMDD` ブランチの PR にする（`Refs #1`）。
- `main` は締切時点の最終版を残すためだけに使い、`develop` からマージする。
