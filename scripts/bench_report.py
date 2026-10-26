"""Summarize a throughput bench (build.py bench10) from its Kaggle outputs.

Usage: uv run python scripts/bench_report.py work/bench/bench10_v1 [more dirs...]

Reads <dir>/*.log (notebook log, JSON stream) and <dir>/serve.log (SGLang).
Prints: weight-load seconds, server-ready time, decode throughput while >=8 requests run,
mean speculative accept length, prefix-cache share, harness tokens and levels per game.
"""

from __future__ import annotations

import json
import re
import statistics as st
import sys
from datetime import datetime
from pathlib import Path

DEC = re.compile(r"^\[(.+?)\] Decode batch, #running-req: (\d+).*?accept len: ([\d.]+).*?"
                 r"gen throughput \(token/s\): ([\d.]+)")
PRE = re.compile(r"^\[(.+?)\] Prefill batch, #new-seq: \d+, #new-token: (\d+), #cached-token: (\d+)")
LOAD = re.compile(r"^\[(.+?)\] Load weight end\. elapsed=([\d.]+) s, type=Qwen4ExpForConditionalGeneration")
READY = re.compile(r"^\[(.+?)\] The server is fired up")
START = re.compile(r"^\[(.+?)\] server_args=")
GAME = re.compile(r"^\s+([a-z0-9]{4}-[0-9a-f]+): score=([\d.]+), levels=([\d.]+)/(\d+), actions=(\d+), tokens=(\d+)\s*$", re.M)


def ts(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


def report(d: Path) -> dict:
    serve = (d / "serve.log").read_text(errors="replace").splitlines()
    nb = next(p for p in d.glob("*.log") if p.name != "serve.log")
    text = "".join(x.get("data", "") for x in json.loads(nb.read_text()))
    out: dict = {"dir": d.name}
    start = ready = None
    dec_full, acc, cached, new = [], [], 0, 0
    for line in serve:
        if m := START.match(line):
            start = start or ts(m.group(1))
        elif m := LOAD.match(line):
            out["weight_load_s"] = float(m.group(2))
        elif m := READY.match(line):
            ready = ts(m.group(1))
        elif m := DEC.match(line):
            if int(m.group(2)) >= 8:
                dec_full.append(float(m.group(4)))
                acc.append(float(m.group(3)))
        elif m := PRE.match(line):
            new += int(m.group(2))
            cached += int(m.group(3))
    if start and ready:
        out["ready_after_s"] = (ready - start).total_seconds()
    out["decode_tok_s_ge8"] = round(st.median(dec_full), 1) if dec_full else None
    out["decode_samples"] = len(dec_full)
    out["accept_len"] = round(st.mean(acc), 2) if acc else None
    out["prefix_cached_share"] = round(cached / (cached + new), 3) if cached + new else None
    games = {g[0]: g for g in GAME.findall(text)}  # last summary per game
    out["games"] = len(games)
    out["harness_tokens"] = sum(int(g[5]) for g in games.values())
    out["levels"] = sum(float(g[2]) for g in games.values())
    out["actions"] = sum(int(g[4]) for g in games.values())
    out["mean_score_public_subset"] = round(st.mean(float(g[1]) for g in games.values()), 2) if games else None
    return out


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        print(json.dumps(report(Path(arg)), ensure_ascii=False))
