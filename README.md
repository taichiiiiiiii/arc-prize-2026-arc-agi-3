# ARC Prize 2026 — ARC-AGI-3 (Kaggle)

https://www.kaggle.com/competitions/arc-prize-2026-arc-agi-3

**English summary.** A robustness-first fork of Daniel Franzen's public Milestone-2 solution
(Qwen3.8-Flash-Next W4A16 served by SGLang on one RTX PRO 6000, Duck/TAAF harness), run as an
automated "loop": a cron submission loop that rehearses each kernel and submits one per day, a
throughput-improvement loop that only adopts behaviour-neutral changes measured on a 10-game
bench with pre-registered rules, a local end-to-end smoke test with a mock LLM server, and a
daily review. Notes, decisions and every experiment are in `analysis/` (Japanese).
See `NOTICE.md` for third-party code and licenses.

---

対話型ゲーム環境で、未見のゲームを探索して攻略するエージェントを作るコード・コンペ。
提出はノートブック（インターネット無効・9 時間以内）、採点は Kaggle 側のゲートウェイ上の
非公開 110 ゲーム（Public 55 / Private 55）で行われる。内容のまとめは `docs/competition.md`。

## セットアップ

```bash
uv sync                                   # Python 3.12 / arc-agi 0.9.8 / arcengine 0.9.3（Kaggle 同梱版に固定）
kaggle competitions download arc-prize-2026-arc-agi-3 -p data && (cd data && unzip -q *.zip && rm *.zip)
```

別ツールのシェルから実行すると `PYTHONPATH` に他の Python の site-packages が混ざり、
`pydantic_core` の import に失敗することがある。その場合は `env -u PYTHONPATH uv run ...` を使う。

## ローカル評価（公開 25 ゲーム）

```bash
uv run python scripts/local_eval.py --agent random --max-actions 300
uv run python scripts/local_eval.py --games ls20 ft09 --max-actions 1000 --out work/x.json
```

スコアは `arc_agi` 付属のスコアカード（ゲートウェイと同じ計算器）で出す。ただし公開 25 ゲームは
採点用 110 ゲームとは別物なので、LB の推定値ではなく回帰確認として使う。

## 構成

```
AGENTS.md                      作業ルール（必読）
docs/competition.md            コンペ内容のまとめ（ルール・評価・締切・LB の状況）
analysis/experiment_ledger.md  実験台帳（判定規則を先に書く）
CHECKLIST.md                   進行チェックリスト（テンプレート由来）
scripts/local_eval.py          公開ゲームでのオフライン評価
scripts/submission_status.py   提出一覧・最終選択の検証
data/                          コンペデータ（git 管理外）
work/                          一時出力（git 管理外）
```
