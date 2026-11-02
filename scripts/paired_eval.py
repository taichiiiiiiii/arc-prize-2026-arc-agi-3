"""Paired score comparison between bench runs (behaviour-changing candidates).

The leaderboard number moves +-5 per run, but most of that is game-to-game luck. Comparing two
variants on the SAME games (paired per-game differences) removes the game difficulty term, and
repeating runs removes run luck. This is what makes behaviour changes measurable.

Input: bench output dirs that contain benchmark.json (game_runs[*].game_id, final_score).
Usage:
  python scripts/paired_eval.py --base work/bench/base1 work/bench/base2 --cand work/bench/c_x work/bench/c_x2
Output: per-game mean difference, paired SE, 2-SE decision, and how many more runs would be needed
for a given effect size.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics as st
from pathlib import Path


def scores(d: Path) -> dict[str, float]:
    p = d / "benchmark.json"
    if not p.exists():
        p = next(d.rglob("benchmark.json"))
    b = json.loads(p.read_text())
    return {g["game_id"].split("-")[0]: float(g["final_score"]) for g in b["game_runs"]}


def compare(base: list[dict[str, float]], cand: list[dict[str, float]]) -> dict:
    games = sorted(set.intersection(*(set(x) for x in base + cand)))
    if not games:
        raise ValueError("no common games")
    mb = {g: st.mean(r[g] for r in base) for g in games}
    mc = {g: st.mean(r[g] for r in cand) for g in games}
    diffs = [mc[g] - mb[g] for g in games]
    n = len(diffs)
    mean = st.mean(diffs)
    se = st.stdev(diffs) / math.sqrt(n) if n > 1 else float("inf")
    # within-variant run-to-run spread per game (only if repeated runs exist)
    def spread(rs):
        if len(rs) < 2:
            return None
        return st.mean(st.stdev([r[g] for r in rs]) for g in games)
    return {"games": n, "base_runs": len(base), "cand_runs": len(cand),
            "base_mean": round(st.mean(mb.values()), 2), "cand_mean": round(st.mean(mc.values()), 2),
            "diff": round(mean, 2), "paired_se": round(se, 2),
            "verdict": "改善" if mean > 2 * se else ("悪化" if mean < -2 * se else "差なし"),
            "per_game_run_sd_base": spread(base), "per_game_run_sd_cand": spread(cand),
            "worst_games": sorted(((round(mc[g] - mb[g], 1), g) for g in games))[:3],
            "best_games": sorted(((round(mc[g] - mb[g], 1), g) for g in games))[-3:]}


def runs_needed(sd_pergame_diff: float, games: int, effect: float) -> int:
    """Runs per variant so that 2*SE < effect (paired, per-game diff SD shrinks with sqrt(runs))."""
    if effect <= 0:
        return 10 ** 6
    k = 1
    while 2 * sd_pergame_diff / math.sqrt(games * k) >= effect and k < 1000:
        k += 1
    return k


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", nargs="+", required=True)
    ap.add_argument("--cand", nargs="+", required=True)
    ap.add_argument("--effect", type=float, default=3.0, help="effect size (points) to plan runs for")
    a = ap.parse_args()
    r = compare([scores(Path(x)) for x in a.base], [scores(Path(x)) for x in a.cand])
    print(json.dumps(r, ensure_ascii=False, indent=1))
    sd = r["paired_se"] * math.sqrt(r["games"])
    print(f"runs per variant for a {a.effect}-point effect at 2 SE: ~{runs_needed(sd, r['games'], a.effect)}")


if __name__ == "__main__":
    main()
