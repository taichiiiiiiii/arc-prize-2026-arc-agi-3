# Third-party code and attributions

This repository builds on public work from the ARC Prize 2026 — ARC-AGI-3 community. The code
under `third_party/` is kept unchanged so that every change made here is visible as a diff in
`kernels/m2_robust/build.py`.

| Path | Origin | License |
|---|---|---|
| `third_party/dfranzen_m2/` | Daniel Franzen, "ARC-AGI-3 Milestone 2 Solution" (Kaggle notebook `dfranzen/arc-agi-3-milestone-2-solution`, pulled 2026-10-24). It builds on Tufa Labs' Duck harness / TAAF. | Apache 2.0 (as released on Kaggle) |
| `third_party/dprime_tantan0327/priority_form_cell.py` | Cell 17 of `tantan0327/arc3-franzen-dprime` (pulled 2026-10-25). The D' slot-priority formula is from shiiin9's public notebook. | Apache 2.0 (Kaggle); the cell header states CC0 / MIT-0 |

Not included in this repository (downloaded at run time or attached as Kaggle inputs):
- Model weights: Qwen3.8-Flash-Next (Qwen Community License 1.0), Intel AutoRound W4A16
  quantization, the albucino MTP drafter and FP8-PLE build (Kaggle mirrors by dfranzen).
- The TAAF Kaggle source bundle (`dfranzen/taaf-kaggle-source-bundle-copy`) and the Pennyroyal
  SGLang wheelhouse (`dfranzen/pennyroyal-v253`).
- Competition data and game environments (`data/`, Kaggle competition terms).

The Apache License 2.0 text is in `third_party/LICENSE-APACHE-2.0.txt`; the files under
`third_party/` remain under their original license and copyright.

Everything else in this repository is under the MIT License (`LICENSE`).
