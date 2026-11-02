# ARC Prize 2026 — ARC-AGI-3 (Kaggle): a robustness-first M2 fork run as an automated loop

Competition: https://www.kaggle.com/competitions/arc-prize-2026-arc-agi-3 (deadline 2026-11-02 23:59 UTC)

This repository is a fork of Daniel Franzen's public *Milestone 2* solution (Qwen3.8-Flash-Next
W4A16 served by SGLang on one RTX PRO 6000, Duck/TAAF tool-calling harness). All changes are
applied as patches by `kernels/m2_robust/build.py` on top of the unchanged notebook in
`third_party/`, so every modification is visible as a diff. Notes and the experiment ledger are in
Japanese.

## Results

| # | Kernel | Change | Public |
|---|---|---|---|
| E1 | m2-robust v1 | M2 + start-up keep-alive | 25.67 |
| E2 | m2-robust-dprime v1 | + D' slot priority | 25.66 |
| E3 / E5 / E7 / E9 | m2-robust v2 | robust v2 (default priority) | 27.31 / 21.32 / **32.26** / 26.79 |
| E4 / E6 / E8 | m2-robust-dprime v1 | robust v2 + D' | 28.96 / **29.88** / 26.53 |
| E10 | m2-robust-pv v4 | + weight precache, persistent tool variables, input-path fix | 26.99 |

- Mean of 10 runs: 27.1. An unmodified copy of M2 averages about 25.8 with SD about 3.9 per run,
  so **none of the changes is distinguishable from run-to-run noise**. E7 crossing the bronze line
  (about 30.9) is best read as a lucky run.
- Final selection: E7 and E6 (rule fixed in advance: the two best public scores among healthy runs,
  because public and private are scored in the same run and share its luck).
  Private score: to be added after the deadline.

## What worked, what did not

Worked (engineering):
- Zero-score protection: keep-alive RESETs while the server loads, a grace period, a rehearsal
  run that must pass log checks before a version is allowed to replace the scheduled submission.
- Weight precache with 8 parallel readers: server ready time 975 s → 523 s (measured I/O:
  1 reader 217 MB/s, 8+ readers ~750 MB/s).
- A local end-to-end smoke test (`scripts/local_smoke.py` + `scripts/mock_llm_server.py`) that runs
  the real notebook against a mock LLM and catches patch and path errors before any GPU time.
- Robustness to Kaggle's new flat input layout (`/kaggle/input/<slug>`), see `inputfix` in `build.py`.

Did not work (score):
- Points are lost mostly to **running out of time on unsolved levels** (about −24 of the gap), not to
  wasted actions (about −2); the GPU and KV cache are near saturation (`analysis/reports/`).
- The improvement loop only accepted behaviour-neutral speed-ups because a single run moves ±5
  points. That ruled out every change that could move the score. The post-mortem and a redesigned
  loop (paired per-game comparisons, repeated runs budgeted from the GPU quota, failure alerts) are
  in [`docs/improvement-loop.md`](docs/improvement-loop.md) and `scripts/paired_eval.py`.

## Layout

```
kernels/m2_robust/build.py     builds every kernel variant (robust / dprime, opts: precache8, spec4,
                               fp8ple, persistvars, inputfix) from the unchanged M2 notebook
kernels/io_bench/              CPU kernel that measured Kaggle input read throughput
third_party/                   unchanged upstream notebooks/cells (see NOTICE.md)
scripts/loop_tick.py           submission loop: rehearse → verify logs → submit one per day
scripts/bench_loop.py          improvement loop on a 10-game bench with pre-registered rules
scripts/local_smoke.py         local end-to-end test of a built notebook with a mock LLM server
scripts/local_eval.py          offline scoring on the 25 public games (regression check only)
scripts/paired_eval.py         paired per-game comparison between bench runs
scripts/transcript_report.py   token / tool-error breakdown from request logs
scripts/final_select.py        final-selection rule
analysis/                      experiment ledger, reports, daily reviews, loop state (aggregates only)
docs/                          competition summary, improvement-loop post-mortem
tests/                         pytest (patches, loops, persistvars)
```

## Reproduce

```bash
uv sync                                    # Python 3.12, arc-agi 0.9.8 / arcengine 0.9.3 (Kaggle versions)
kaggle competitions download arc-prize-2026-arc-agi-3 -p data && (cd data && unzip -q *.zip && rm *.zip)
uv run pytest -q tests/
uv run python scripts/local_eval.py --agent random --max-actions 300

# build a kernel variant (pushing needs your own Kaggle account)
export KAGGLE_USERNAME=<your-kaggle-name>
uv run python kernels/m2_robust/build.py robust --opts precache8,inputfix --slug arc3-m2-robust-x

# local end-to-end smoke test: needs the TAAF source bundle (Kaggle dataset) in data/bundle
kaggle datasets download dfranzen/taaf-kaggle-source-bundle-copy -p data/bundle --unzip
uv run python scripts/local_smoke.py robust --opts precache8,inputfix
```

Four tests skip without `data/bundle` (they apply the patches to the real harness).

`scripts/loop_tick.py` (submits) and `scripts/bench_loop.py` (pushes kernels, starts GPU runs) are
the author's scheduled automation. They read the author's queue in `analysis/*.json` and have side
effects on your Kaggle account; read them before running, and set `KAGGLE_USERNAME` (and
`KAGGLE_CLI` if `kaggle` is not on `PATH`).

Model weights, the TAAF source bundle and the SGLang wheelhouse are Kaggle inputs and are not in
this repository. When run from another tool's shell, `env -u PYTHONPATH uv run ...` avoids a stray
`PYTHONPATH` breaking `pydantic_core`.

## License

MIT for the code written here (`LICENSE`). Third-party code under `third_party/` keeps its
original license (Apache 2.0); see `NOTICE.md`.

---

## 日本語の概要

Kaggle「ARC Prize 2026 — ARC-AGI-3」で、Daniel Franzen の公開解法（M2）を土台に、0 点事故を防ぐ
堅牢化・起動の高速化・自動提出ループ・改善ループ・手元の通しテストを作った記録です。

- 10 回の提出の Public 平均は 27.1 で、M2 無改変（約 25.8、1 回の SD 約 3.9）と誤差の範囲でした。
  最終選択は E7（32.26）と E6（29.88）です。
- 失点の主因は、解けないレベルでの時間切れでした。改善ループが「判断を変えない速度改善」しか
  扱わなかったため、点数は上がりませんでした。振り返りと作り直したループの設計は
  `docs/improvement-loop.md` にあります。
- 実験の経緯は `analysis/experiment_ledger.md`、コンペの内容は `docs/competition.md` です。
