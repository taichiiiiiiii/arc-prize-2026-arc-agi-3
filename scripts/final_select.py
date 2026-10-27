"""Apply the fixed final-selection rules (analysis/reports/strategy.md) to the submission list.

Rules (fixed 2026-10-25, before results):
 1. Public only detects broken runs: drop 0.00 and runs >= 12 points below the mean of the other
    runs of the same configuration.
 2. Never pick the max-Public run of a configuration; its representative is the newest healthy run.
 3. Compare configurations by Public mean; a gap under 2 standard errors is "no difference".
 5. Final 2 = representative of B (robust + D') and representative of A (default priority).

Kaggle selects the 2 best-Public submissions automatically when none are chosen, which would break
rule 2 - the two picks printed here must be selected by hand on the Submissions page.

Usage: uv run python scripts/final_select.py            (reads `kaggle competitions submissions`)
       uv run python scripts/final_select.py --csv f.csv
"""

from __future__ import annotations

import argparse
import csv
import io
import math
import statistics as st
import subprocess
from dataclasses import dataclass

COMP = "arc-prize-2026-arc-agi-3"
SD_RUN = 3.93  # spread of unmodified M2 copies (Discussion #745062)
BROKEN_GAP = 12.0


@dataclass
class Sub:
    ref: str
    date: str
    desc: str
    status: str
    public: float | None

    @property
    def config(self) -> str:
        return "B" if ("dprime" in self.desc or "D'" in self.desc) else "A"


def parse(text: str) -> list[Sub]:
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        if not r.get("ref"):
            continue
        try:
            pub = float(r.get("publicScore") or "nan")
        except ValueError:
            pub = float("nan")
        rows.append(Sub(r["ref"], r["date"], r.get("description", ""), r.get("status", ""),
                        None if math.isnan(pub) else pub))
    return rows


def select(subs: list[Sub]) -> dict:
    done = [s for s in subs if "COMPLETE" in s.status and s.public is not None]
    out: dict = {"configs": {}, "excluded": [], "picks": []}
    for cfg in ("A", "B"):
        runs = sorted((s for s in done if s.config == cfg), key=lambda s: s.date)
        healthy = []
        for s in runs:
            others = [o.public for o in runs if o is not s and o.public]
            broken = s.public == 0.0 or (others and s.public <= st.mean(others) - BROKEN_GAP)
            (out["excluded"] if broken else healthy).append(s)
        scores = [s.public for s in healthy]
        out["configs"][cfg] = {
            "n": len(healthy), "mean": round(st.mean(scores), 2) if scores else None,
            "runs": [(s.ref, s.public) for s in healthy],
            "representative": healthy[-1].ref if healthy else None,  # rule 2: newest healthy
        }
    a, b = out["configs"]["A"], out["configs"]["B"]
    if a["n"] and b["n"]:
        se = SD_RUN * math.sqrt(1 / a["n"] + 1 / b["n"])
        gap = b["mean"] - a["mean"]
        out["compare"] = {"B_minus_A": round(gap, 2), "two_se": round(2 * se, 2),
                          "verdict": "差あり" if abs(gap) >= 2 * se else "差なし"}
    out["picks"] = [x for x in (b["representative"], a["representative"]) if x]  # rule 5
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    a = ap.parse_args()
    if a.csv:
        text = open(a.csv).read()
    else:
        text = subprocess.run(["kaggle", "competitions", "submissions", COMP, "--page-size", "100", "--csv"],
                              capture_output=True, text=True, timeout=300).stdout
        text = "\n".join(l for l in text.splitlines() if not l.startswith("Warning"))
    r = select(parse(text))
    for cfg, c in r["configs"].items():
        print(f"{cfg}: n={c['n']} mean={c['mean']} runs={c['runs']} representative={c['representative']}")
    for s in r["excluded"]:
        print(f"excluded (rule 1): {s.ref} {s.public} {s.desc[:60]}")
    if "compare" in r:
        print(f"B-A = {r['compare']['B_minus_A']} (2SE {r['compare']['two_se']}) -> {r['compare']['verdict']}")
    print("final picks (select by hand on Kaggle):", ", ".join(r["picks"]))


if __name__ == "__main__":
    main()
