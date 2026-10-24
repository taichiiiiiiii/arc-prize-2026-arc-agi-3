# コンペ内容のまとめ（2026-10-25 JST 時点）

出典: `kaggle competitions pages`（Overview / Rules / Data / Code Requirements）、
LB は `kaggle competitions leaderboard`、公開ノートブックのスコアは各コードページで確認。

## 概要
- **ARC Prize 2026 — ARC-AGI-3**（Featured、総額 $850,000、約 4,780 チーム）
- 手作りの対話型ゲーム（グリッド最大 64×64、色 0–15）を、ルール説明なしで探索・攻略するエージェントを作る。
- 行動: `RESET`、`ACTION1–5`（単純）、`ACTION6`（座標 x,y 付き）、`ACTION7`。意味はゲームごとに違う。
- 状態: `NOT_FINISHED` / `WIN` / `GAME_OVER`。各ゲームは複数レベル。

## 評価
- レベル単位: `min(人間の行動数 / エージェントの行動数, 1)^2`。クリアできなければ 0。
  （arc_agi のスコア計算器は上限 115% で計算しているが、公式説明では 100% 上限）
- ゲーム単位: レベル番号（1 始まり）で重み付けした平均 → 後半レベルほど重い。
- 総合: 全ゲームの平均（0–100%）。
- 採点: **非公開 110 ゲーム**（Public 55 / Private 55）。公開 25 ゲームは練習用で採点に使われない。
- つまり「完走」と「行動数の少なさ」の両方が要る。無駄な探索行動はそのまま減点になる。

## 提出・実行環境
- ノートブック提出のみ。CPU / GPU とも **9 時間以内**、**インターネット無効**。
- 提出ファイルは自動生成（エージェントがゲートウェイ `http://gateway:8001` に対してゲームを遊ぶ）。
  非採点の実行時はダミーの `submission.parquet` を書けばよい（公式サンプル参照）。
- GPU: RTX Pro 6000（`g4-standard-48`）がこのコンペ専用で使える。
- **提出は 1 日 1 回**、最終選択 2 件。チーム上限 8 人。
- 外部データ・事前学習済みモデルは「無料・公開」なら可。ただし入賞時は **CC-BY 4.0 で
  オープンソース化**（システム・モデル・重み）が条件。
- コンペ期間中のコードの私的共有は禁止 → GitHub リポジトリは private を維持。
- テストデータへの人手ラベリング禁止。

## 日程（すべて 23:59 UTC = 翌 08:59 JST）
- 10/26（日本時間 10/27 08:59）: エントリー締切・チーム結成締切（**参加登録済み**を確認）
- **11/2（日本時間 11/3 08:59）: 最終提出締切** → 残り約 8 日 ＝ 提出は最大 8〜9 回
- 12/4: 結果発表

## データ（`data/`）
- `environment_files/`: 公開 25 ゲーム（各ゲームの Python ソース + `metadata.json`。
  `baseline_actions` に人間の各レベル行動数）
- `ARC-AGI-3-Agents/`: 公式エージェント枠組み（`Agent.choose_action` / `is_done`、Swarm）
- `arc_agi_3_wheels/`: オフライン導入用 wheel（arc-agi 0.9.8、arcengine 0.9.3 ほか、cp312 / x86_64）

## LB の状況（2026-10-24 UTC）
- 1 位 68.91（Tufa Labs）、2 位 68.21、3 位 56.02、20 位付近 38
- メダル線（4,776 チーム）: 金 19 位 = 38.2、銀 238 位 = 32.23、**銅 477 位 = 30.91**
- ランダムエージェント: ローカル公開 25 ゲームで 0.011%（300 手、`scripts/local_eval.py`）

## 公開ノートブック（Public スコアはコードページで確認）
- `dfranzen/arc-agi-3-milestone-2-solution`: **33.68**（最高 34.30）。Tufa Labs の Duck harness
  + Qwen3.8-Flash-Next（Intel AutoRound W4A16）+ MTP draft で投機的デコード、sglang で RTX Pro 6000 上に配信。
  Milestone 2 の解法。
- `jingshuifu/arc3-m2-solution`: 33.22
- `heliosli/try-merging-it-you-might-get-lucky-and-win-gold`: 32.60
- `jeroencottaar/tufa-labs-duck-harness-june-30-milestone-winner`（Milestone 1 優勝の原型）: 1.25（現行版）
- 主流は「ローカル LLM（Qwen3.8 系）をエージェントとして回す Duck harness」系統。
  公開最良（約 34）はそのまま出せば銀圏、銅線（30.9）は越える。金（38+）には上積みが要る。
