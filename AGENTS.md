# AGENTS.md — ARC-AGI-3

## 言語
応答・ドキュメント・コミットメッセージは日本語。

## 承認が必要な操作（その都度ユーザーの明示承認）
- `kaggle kernels push`、`kaggle competitions submit`、Dataset / Model の作成・更新
- `git push`（commit はローカルで可。push 前に確認）
- 提出は **1 日 1 回**（UTC 00:00 リセット）。枠は貴重なので、検証済みのものだけを出す。

## 守ること
- コンペ期間中のコードの私的共有は禁止（公開するなら Kaggle 上で全員に）。リポジトリの公開は締切後。
- 提出カーネルは `is_private: true` を push 前に確認する。
- 外部モデル・データは「無料で誰でも入手可能」なものだけ。入賞時は CC-BY 4.0 でオープンソース化が条件
  なので、ライセンスが OSI 互換でない部品は使う前にユーザーに確認する。
- 公開 25 ゲームのローカルスコアは LB の推定値ではない（採点は未見の 110 ゲーム）。公開ゲームに
  特化した手書き解法で上がった数字を「改善」と呼ばない。
- `data/`・`work/`・重みはコミットしない。
- 判定規則は結果が出る前に `analysis/experiment_ledger.md` に書く。

## 公開を前提に書く（Issue #4）
- 認証情報・トークン・個人の絶対パス（`/Users/...`）・メールアドレスをコミットしない。パスはリポジトリからの相対で書く。
- コンペデータ、公開ゲームの盤面・手順、要求ログの本文は `data/` か `work/`（git 外）に置く。`analysis/` には集計値だけを置く。
- 第三者のコードは `third_party/` に無改変で置き、出典とライセンスを `NOTICE.md` に書く。

## 環境
- Python 3.12（Kaggle の wheel が cp312）。`arc-agi==0.9.8` / `arcengine==0.9.3` は Kaggle 同梱版に固定。
- 別ツールのシェルから実行するときは `env -u PYTHONPATH uv run ...`（別 Python の site-packages が混入するため）。
- 手元の機械は他のジョブと共有している前提で、重い処理の前に空きメモリ・ディスクを確認し、他プロセスに触らない。
- Kaggle のカーネル所有者は環境変数 `KAGGLE_USERNAME` で変えられる（既定は作者のアカウント）。

## Git 運用（2026-10-29〜、1 つの作業 = 1 Issue = 1 ブランチ = 1 PR）
1. **Issue を立てる**（日本語）。ラベルは `lineage-loop` と種類（`bug` / `enhancement`）。オーナーの判断が要るものは `needs-decision`。追跡用の親は #1。
2. **ブランチを切る**: 最新の `origin/develop` から `<種類>/<Issue番号>-<内容>`（例: `fix/5-pv-tuple-keys`、`feat/2-ci-git-workflow`）。
3. **コミット**: 1 論理単位ごと、`feat(...)` / `fix(...)` / `chore(...)` の形、本文に `Refs #番号`。
4. **PR**: ブランチを push して `gh pr create --base develop`。本文に変更内容・数値・`Fixes #番号`。
5. **CI**: GitHub Actions の `tests` が通るまでマージしない。
   - 暫定（2026-10-29 オーナー承認、締切まで）: GitHub Actions が課金エラーで開始されないため、PR の head で手元の `env -u PYTHONPATH uv run pytest -q tests/` を実行し、結果（passed/skipped 数と head のコミット）を PR にコメントしたものを CI 通過とみなす。public 化後は Actions に戻す。
6. **マージ**: 受け入れ条件を満たしたら `gh pr merge --merge --delete-branch`（マージコミットを残す）。
7. **確認と記録**: マージ後の `develop` で測り直し、結果を Issue にコメントし、#1 のチェックを更新する。

補足:
- 作業ディレクトリは 1 つ（worktree は作らない）。cron の提出ループ・改善ループはこの作業ツリーのスクリプトを実行するので、作業ブランチにいる時間は短くし、終わったら必ず `develop` に戻る。
- 自動ループが書き換える記録ファイル（`analysis/loop_state.json`、`analysis/bench_state.json`、`analysis/submission_log.md`、`analysis/smoke/*.json`、`analysis/reviews/*.md`）は、日次レビューでまとめて `chore/<親番号>-records-YYYYMMDD` ブランチの PR にする（`Refs #1`）。
- `main` は締切時点の最終版を残すためだけに使い、`develop` からマージする。
