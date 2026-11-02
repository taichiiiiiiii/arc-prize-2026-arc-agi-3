"""One tick of the submission loop (run by cron every 15 min; prints only when something happens).

Each tick:
  1. Kaggle auth check (prints AUTH FAIL and stops if the CLI lost its login).
  2. Reads the submissions list; every newly finished submission is appended to
     analysis/submission_log.md and reported.
  3. If no submission is pending and none was made today (UTC), takes the next queue item whose
     rehearsal kernel passed its log checks and submits it.

The queue and all state live in analysis/loop_state.json. The plan is fixed in advance
(analysis/reports/strategy.md, "最終選択と提出の規則"); this script makes no score-based choices.
Final selection (2 slots) is NOT done here.

Usage:  env -u PYTHONPATH uv run python scripts/loop_tick.py [--dry-run] [--verbose]
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import subprocess
import sys
from datetime import datetime, UTC
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "analysis" / "loop_state.json"
LOG_MD = ROOT / "analysis" / "submission_log.md"
COMP = "arc-prize-2026-arc-agi-3"
KAGGLE = "/Library/Frameworks/Python.framework/Versions/3.14/bin/kaggle"
WORK = ROOT / "work" / "loop"
SUMMARY_RE = re.compile(r"^\s+([a-z0-9]{4}-[0-9a-f]+): score=([\d.]+), levels=([\d.]+)/(\d+), "
                        r"actions=(\d+), tokens=(\d+)\s*$", re.M)


def kaggle(*args: str, timeout: int = 300) -> str:
    r = subprocess.run([KAGGLE, *args], capture_output=True, text=True, timeout=timeout)
    out = r.stdout + r.stderr
    return "\n".join(line for line in out.splitlines() if "outdated" not in line)


def submissions() -> list[dict]:
    out = kaggle("competitions", "submissions", COMP, "--page-size", "50", "--csv")
    if "Authentication" in out:
        raise PermissionError(out)
    lines = [ln for ln in out.splitlines() if "," in ln]
    return list(csv.DictReader(io.StringIO("\n".join(lines))))


def verify_kernel(item: dict) -> tuple[str, str]:
    """-> (status, detail): status in {'ok', 'fail', 'wait'}."""
    slug, ver = item["kernel"], item["version"]
    st = kaggle("kernels", "status", slug)
    if "RUNNING" in st or "QUEUED" in st:
        return "wait", st.strip()
    if "COMPLETE" not in st:
        return "fail", st.strip()
    d = WORK / f"{slug.replace('/', '_')}_v{ver}"
    d.mkdir(parents=True, exist_ok=True)
    name = slug.split("/")[1]
    kaggle("kernels", "output", slug, "-p", str(d), "--file-pattern",
           rf"({re.escape(name)}\.log|submission\.parquet)$", timeout=900)
    logf = d / f"{name}.log"
    if not logf.exists():
        return "fail", "no log"
    text = "".join(x.get("data", "") for x in json.loads(logf.read_text()))
    (d / "log.txt").write_text(text)
    missing = [m for m in item.get("markers", []) if m not in text]
    games = SUMMARY_RE.findall(text)
    used = [g for g in games if int(g[5]) > 0]
    if not (d / "submission.parquet").exists():
        missing.append("submission.parquet")
    if not used:
        missing.append("a game with tokens>0")
    if missing:
        return "fail", "missing: " + "; ".join(missing)
    final = {g[0]: g for g in games}  # summaries repeat during the run; keep the last per game
    return "ok", ", ".join(f"{g[0][:4]} {float(g[2]):.0f}/{g[3]} lv tok={g[5]}" for g in final.values())


def append_log(row: dict) -> None:
    if not LOG_MD.exists():
        LOG_MD.write_text("# 提出記録（loop_tick.py が自動追記）\n\n"
                          "| ref | 提出 (UTC) | 説明 | 状態 | Public |\n|---|---|---|---|---|\n")
    with LOG_MD.open("a") as f:
        f.write(f"| {row['ref']} | {row['date'][:16]} | {row['description']} | "
                f"{row['status'].split('.')[-1]} | {row.get('publicScore', '')} |\n")


def _lock():
    import fcntl
    f = open(ROOT / "analysis" / ".loop.lock", "w")
    fcntl.flock(f, fcntl.LOCK_EX)  # loop_tick and bench_loop both write analysis/loop_state.json
    return f


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    state = json.loads(STATE.read_text())
    msgs: list[str] = []

    try:
        subs = submissions()
    except PermissionError:
        print("⚠️ ARC-AGI-3 ループ: Kaggle の認証が切れています。`kaggle auth login` を実行してください。")
        return 0

    # 2. newly finished submissions
    seen = set(state.get("reported", []))
    for s in subs:
        if "PENDING" in s["status"] or s["ref"] in seen:
            continue
        seen.add(s["ref"])
        if not a.dry_run:
            append_log(s)
        msgs.append(f"採点完了: {s['description'][:60]} → {s['status'].split('.')[-1]} "
                    f"Public {s.get('publicScore') or '-'}")
    state["reported"] = sorted(seen)

    # 3. submit the next item
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    pending = [s for s in subs if "PENDING" in s["status"]]
    today_n = sum(1 for s in subs if s["date"].startswith(today))
    queue = state["queue"]
    nxt = next((q for q in queue if q.get("state") not in ("submitted", "failed")), None)
    if nxt is not None and nxt.get("verify") != "ok":
        status, detail = verify_kernel(nxt)
        if status != "wait":
            nxt["verify"], nxt["verify_detail"] = status, detail
            msgs.append(f"試走確認 {nxt['tag']} ({nxt['kernel']} v{nxt['version']}): {status} — {detail}")
            if status == "fail":
                nxt["state"] = "failed"
    if nxt is not None and nxt.get("verify") == "ok" and not pending and today_n == 0:
        msg = f"{nxt['tag']} {nxt['config']}: {nxt['kernel'].split('/')[1]} v{nxt['version']}"
        if any(s["description"] == msg for s in subs):
            nxt["state"] = "submitted"
        elif a.dry_run:
            msgs.append(f"[dry-run] would submit: {msg}")
        else:
            out = kaggle("competitions", "submit", COMP, "-k", nxt["kernel"], "-v", str(nxt["version"]),
                         "-f", "submission.parquet", "-m", msg)
            ok = any(s2["description"] == msg for s2 in submissions())  # confirm by reading back
            if ok:
                nxt["state"], nxt["submitted_at"] = "submitted", datetime.now(UTC).isoformat()
                msgs.append(f"提出しました: {msg}")
            else:
                msgs.append(f"提出失敗: {msg}: {out.strip()[:300]}")
    if a.verbose:
        msgs.append(f"[status] pending={len(pending)} today={today_n} next={nxt and nxt['tag']}")

    if not a.dry_run:
        STATE.write_text(json.dumps(state, indent=1, ensure_ascii=False))
    if msgs:
        print("ARC-AGI-3 ループ:\n- " + "\n- ".join(msgs))
    return 0


if __name__ == "__main__":
    _lk = _lock()
    sys.exit(main())
