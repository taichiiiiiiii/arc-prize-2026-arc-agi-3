"""Local end-to-end smoke test of a built submission notebook, with a mock LLM server.

Runs the real notebook cells (harness patch, keepalive patch, D' cell, TAAF benchmark, real game
engine on the public games) on this Mac. Only the GPU parts are replaced:
  - wheel install + model precache cells -> skipped (the repo venv already has arc-agi)
  - SGLang launcher cell -> scripts/mock_llm_server.py (503 until --ready-after, then tool calls)
All /kaggle/ paths are redirected into work/smoke/kaggle.

Checks (exit 1 if any fails): notebook ran without error, keepalive patch line, variant markers,
per-game summary lines with actions > 0, keepalive RESET while the mock was "loading",
mock received chat requests.

Usage: env -u PYTHONPATH uv run python scripts/local_smoke.py robust --games ls20 --minutes 4
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kernels" / "m2_robust"))
import build as nbbuild  # noqa: E402

DATA = ROOT / "data"
SMOKE = ROOT / "work" / "smoke"
GAME = re.compile(r"^\s+([a-z0-9]{4}-[0-9a-f]+): score=([\d.]+), levels=([\d.]+)/(\d+), actions=(\d+), tokens=(\d+)\s*$", re.M)

LAUNCHER = '''# [local smoke] mock LLM server instead of SGLang
import subprocess, sys, time, urllib.request
mock_proc = subprocess.Popen([sys.executable, {mock!r}, "--port", str(SERVED_MODEL_PORT),
                              "--ready-after", "{ready}", "--log", {log!r}])
t0 = time.time()
while time.time() - NOTEBOOK_START_TIME < SERVER_STARTUP_TIMEOUT:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{{SERVED_MODEL_PORT}}/health", timeout=5) as r:
            if r.status == 200:
                print(f"READY after {{int(time.time()-t0)}}s (mock)"); break
    except Exception:
        pass
    time.sleep(2)
else:
    print(f"DEADLINE at {{int(time.time()-NOTEBOOK_START_TIME)}}s from notebook start; mock still loading")
'''


def sandbox() -> Path:
    k = SMOKE / "kaggle"
    if k.exists():
        shutil.rmtree(k)
    comp = k / "input" / "competitions" / "arc-prize-2026-arc-agi-3"
    comp.mkdir(parents=True)
    for name in ("environment_files", "arc_agi_3_wheels"):
        (comp / name).symlink_to(DATA / name)
    # a real copy: the notebook `cp -a`s it and `git apply`s into the copy
    shutil.copytree(DATA / "bundle", k / "input" / "datasets" / "dfranzen" / "taaf-kaggle-source-bundle-copy")
    (k / "working").mkdir()
    return k


def prepare(variant: str, games: list[str], minutes: float, ready_after: float, k: Path, log: Path) -> dict:
    out = nbbuild.build(variant)
    nb = json.loads(out.read_text())
    seen = set()
    for c in nb["cells"]:
        if c["cell_type"] != "code":
            continue
        s = "".join(c["source"])
        c["outputs"], c["execution_count"] = [], None
        if s.startswith("%%writefile "):
            # local IPython strips whitespace-only lines in %%writefile bodies, which breaks the
            # patch's blank context lines; write the file byte-exact instead
            first, body = s.split("\n", 1)
            body += "" if body.endswith("\n") else "\n"  # %%writefile ends the file with a newline
            path = first.split(None, 1)[1].strip().replace("/kaggle/", f"{k}/")
            s, tag = f"from pathlib import Path\nPath({path!r}).write_text({body!r})\nprint('wrote', {path!r})\n", "writefile"
        elif "arc_agi_3_wheels" in s and "pip" in s and "install" in s:
            s, tag = "print('[local smoke] wheel install skipped')\n", "pip"
        elif "def precache(" in s:
            s, tag = "print('[local smoke] precache skipped')\n", "precache"
        elif "Paste this entire file into the launcher cell" in s:
            s, tag = LAUNCHER.format(mock=str(ROOT / "scripts" / "mock_llm_server.py"), ready=ready_after,
                                     log=str(log)), "launcher"
        elif "bm.solver.max_runtime_s_per_game" in s and "demo_excluded_games" in s:
            all_games = sorted({p.name.split("-")[0] for p in (DATA / "environment_files").iterdir()})
            s += (f"\n# [local smoke] overrides\nbm.solver.concurrency = {len(games)}\n"
                  f"bm.solver.max_runtime_s_per_game = {minutes} * 60\nbm.n_passes = 1\n"
                  f"demo_excluded_games = {[g for g in all_games if g not in games]!r}\n")
            tag = "config"
        else:
            tag = None
        if tag:
            seen.add(tag)
        if tag != "writefile":  # its path is already redirected; the body is data
            s = s.replace("/kaggle/", f"{k}/")
        c["source"] = s
    missing = {"writefile", "pip", "precache", "launcher", "config"} - seen
    assert not missing, f"cells not found: {missing}"
    return nb


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("variant", nargs="?", default="robust")
    ap.add_argument("--games", default="ls20")
    ap.add_argument("--minutes", type=float, default=4)
    ap.add_argument("--ready-after", type=float, default=150, help="mock 'model load' seconds")
    a = ap.parse_args()
    games = a.games.split(",")

    import nbclient
    import nbformat

    k = sandbox()
    log = SMOKE / f"mock_{a.variant}.jsonl"
    log.unlink(missing_ok=True)
    nb = nbformat.from_dict(prepare(a.variant, games, a.minutes, a.ready_after, k, log))
    pth = Path(sysconfig.get_paths()["purelib"]) / "taaf_kaggle_sources.pth"
    env_keep = dict(os.environ)
    os.environ.pop("KAGGLE_IS_COMPETITION_RERUN", None)
    # the sandbox sits inside this git repo; without a ceiling `git apply` resolves paths against the
    # repo root and silently skips every hunk of the harness patch
    os.environ["GIT_CEILING_DIRECTORIES"] = str(SMOKE)
    t0 = time.time()
    err = None
    client = nbclient.NotebookClient(nb, timeout=None, kernel_name="python3",
                                     resources={"metadata": {"path": str(k / "working")}})
    try:
        client.execute()
    except Exception as e:  # noqa: BLE001
        err = e
    finally:
        os.environ.clear()
        os.environ.update(env_keep)
        pth.unlink(missing_ok=True)  # cell 10 writes it into the venv; do not leave it behind
        subprocess.run(["pkill", "-f", str(ROOT / "scripts" / "mock_llm_server.py")], check=False)
    nbformat.write(nb, SMOKE / f"executed_{a.variant}.ipynb")
    text = ""
    for c in nb.cells:
        for o in c.get("outputs", []):
            text += o.get("text", "") if o.get("output_type") == "stream" else ""
            if o.get("output_type") == "error":
                text += "\n".join(o.get("traceback", []))
    (SMOKE / f"output_{a.variant}.txt").write_text(text)

    reqs = [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []
    found = {g[0]: g for g in GAME.findall(text)}
    checks = {
        "notebook ran without error": err is None,
        "keepalive patch applied": "m2-robust: keepalive patch applied" in text,
        "TRUE_SUBMISSION=False": "taaf.kaggle: TRUE_SUBMISSION=False" in text,
        "keepalive RESET while loading": bool(re.search(r"keepalive RESET #\d+, server still loading", text)),
        "mock got chat requests": len(reqs) > 0,
        "mock replies had tool calls": bool(reqs) and all(r["reply"][0] for r in reqs),
        f"game summaries for {games}": all(any(n.startswith(g) for n in found) for g in games),
        "actions > 0 in every game": bool(found) and all(int(g[4]) > 0 for g in found.values()),
    }
    if a.variant == "dprime":
        checks["D' installed"] = "PRIORITY_FORM installed: form=dprime" in text
    print(f"local smoke {a.variant}: {time.time()-t0:.0f}s, {len(reqs)} mock requests, error={err!r:.300}")
    for g in found.values():
        print(f"  {g[0]}: levels={g[2]}/{g[3]} actions={g[4]} tokens={g[5]}")
    for name, ok in checks.items():
        print(f"  [{'ok' if ok else 'NG'}] {name}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
