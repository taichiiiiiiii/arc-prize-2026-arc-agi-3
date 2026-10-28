"""Build the "M2 robust" Kaggle notebook from Daniel Franzen's Milestone-2 notebook.

Only reliability changes; the agent, model, prompts and scheduler are untouched.

  1. Keepalive: the warmup game keeps sending a RESET every ARC3_KEEPALIVE_SECONDS while the
     model server is still loading, so the gateway's 15-minute idle rule cannot end the run at
     0.00 when model loading is slow (Discussion #751598 / #751631 / #750173).
  2. First-request grace 900 s -> 7200 s (= keepalive cap; v1 used 5400), so the other games do not give up on a slow server.
  3. Gateway wait 600 s -> 1800 s.
  4. TRUE_SUBMISSION also turns on when the host name "gateway" resolves (guards against the
     rerun flag not being seen, #affectify D1).
  5. Rehearsal (interactive Save & Run only): 2 public games, 1 pass, 80 min each (covers ~55 min model load), server released
     after 90 s so the keepalive path is exercised. The scored-rerun branch is not affected.

Every edit asserts that its anchor occurs exactly once.

Usage: uv run python kernels/m2_robust/build.py [robust] [dprime]  -> kernels/m2_robust/out/<variant>/

Variant "dprime" additionally inserts tantan0327's D' slot-priority cell (third_party/dprime_tantan0327).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT / "third_party" / "dfranzen_m2"
SRC_NB = SRC_DIR / "arc-agi-3-milestone-2-solution.ipynb"
OUT = Path(__file__).resolve().parent / "out"
BENCH10 = ["ar25", "bp35", "cd82", "ft09", "lp85", "ls20", "r11l", "sp80", "tr87", "vc33"]
VARIANTS = {
    # name: kernel slug, extra cell, rehearsal games, rehearsal minutes per game
    "robust": dict(slug="arc3-m2-robust", extra=None, games=["ls20", "ft09"], minutes=80),
    "dprime": dict(slug="arc3-m2-robust-dprime",
                   extra=ROOT / "third_party" / "dprime_tantan0327" / "priority_form_cell.py",
                   games=["ls20", "ft09"], minutes=80),
    # throughput bench: 10 streams busy like the scored run (tok/s, prefix cache, load time)
    "bench10": dict(slug="arc3-m2-bench10", extra=None, games=BENCH10, minutes=75, watchdog=True),
}
ALL_PUBLIC = ["ar25", "bp35", "cd82", "cn04", "dc22", "ft09", "g50t", "ka59", "lf52", "lp85",
              "ls20", "m0r0", "r11l", "re86", "s5i5", "sb26", "sc25", "sk48", "sp80", "su15",
              "tn36", "tr87", "tu93", "vc33", "wa30"]

# Inserted into solver.py (harness, after Franzen's patch is applied).
KEEPALIVE_CALL_ANCHOR = """            self._execute_auto_reset()
        try:
            retry_analysis_step: int | None = None
            consecutive_failures = 0
"""
KEEPALIVE_CALL_NEW = """            self._execute_auto_reset()
            _arc3_keepalive_until_ready(self, run)
        try:
            retry_analysis_step: int | None = None
            consecutive_failures = 0
"""
KEEPALIVE_FUNC = '''

def _arc3_keepalive_until_ready(session, run) -> None:
    """[m2-robust] Keep the scorecard alive while the model server is still loading.

    The Kaggle gateway ends a run that makes no game action for 15 minutes. With slow model
    loading the single warmup RESET is not enough, so this game repeats a RESET every
    ARC3_KEEPALIVE_SECONDS until the server's /health answers 200 (or the cap is hit).
    """
    import urllib.request as _req

    period = float(os.environ.get("ARC3_KEEPALIVE_SECONDS", "0") or 0)
    if period <= 0:
        return
    cap = float(os.environ.get("ARC3_KEEPALIVE_MAX_SECONDS", "7200") or 7200)
    poll = float(os.environ.get("ARC3_KEEPALIVE_POLL_SECONDS", "10") or 10)
    base = os.environ.get("OPENAI_BASE_URL", "").rstrip("/")
    url = (base[:-3] if base.endswith("/v1") else base) + "/health"
    t0 = time.monotonic()
    last = t0
    sent = 0
    while not session.should_stop() and time.monotonic() - t0 < cap:
        try:
            with _req.urlopen(url, timeout=5) as resp:
                if resp.status == 200:
                    break
        except Exception:
            pass
        if time.monotonic() - last >= period:
            session._execute_auto_reset()
            sent += 1
            last = time.monotonic()
            log.warning("%s: [m2-robust] keepalive RESET #%d, server still loading (%.0fs)",
                        run.game_id, sent, last - t0)
        time.sleep(poll)
    log.warning("%s: [m2-robust] keepalive finished after %.0fs with %d RESETs",
                run.game_id, time.monotonic() - t0, sent)
'''

APPLY_SNIPPET = '''
# [m2-robust] keepalive while the model server loads (see kernels/m2_robust/build.py)
_solver_py = BUNDLE_DIR / "src" / "ARC3-Inference" / "inference" / "framework" / "solver.py"
_s = _solver_py.read_text()
_anchor = {anchor!r}
assert _s.count(_anchor) == 1, "m2-robust: keepalive anchor not found exactly once"
_s = _s.replace(_anchor, {new!r}) + {func!r}
_solver_py.write_text(_s)
compile(_s, str(_solver_py), "exec")
print("m2-robust: keepalive patch applied", flush=True)
'''


# Bench-only: stop the notebook when the model server dies, so a broken option does not burn GPU
# quota for the rest of the run (c_spec4 kept running 75 min with a dead server on 2026-10-26).
WATCHDOG = """

# [bench watchdog] interrupt the run if the SGLang process exits
import _thread, threading
def _server_watchdog():
    while proc.poll() is None:
        time.sleep(15)
    print(f"[bench watchdog] model server exited with {proc.returncode}; aborting the run", flush=True)
    _thread.interrupt_main()
threading.Thread(target=_server_watchdog, daemon=True).start()
"""

PERSISTVARS = '\n# [persistvars] keep JSON-safe snippet variables between python tool calls (Prime Agent-style\n# persistent namespace, limited). Cleared at session start and at every level transition.\ndef _pv_patch(path, pairs):\n    t = path.read_text()\n    for old, new in pairs:\n        assert t.count(old) == 1, f"persistvars anchor x{t.count(old)} in {path.name}: {old[:60]!r}"\n        t = t.replace(old, new)\n    path.write_text(t)\n    compile(t, str(path), "exec")\n_pv_dir = BUNDLE_DIR / "src" / "ARC3-Inference" / "inference" / "agent"\n_pv_patch(_pv_dir / "python_tool_sandbox.py", [\n    ("        def _collect_retention_payload():\\n",\n     "        _pv_enabled = bool(initial.get(\\"vars_enabled\\"))\\n"\n     "        _pv_reserved = set(runtime_globals) | {\\"result\\"}\\n"\n     "        if _pv_enabled:\\n"\n     "            _pv_in = initial.get(\\"kept_variables\\") or {}\\n"\n     "            for _k, _v in (_pv_in.items() if isinstance(_pv_in, dict) else []):\\n"\n     "                if isinstance(_k, str) and _k.isidentifier() and not _k.startswith(\\"_\\") and _k not in _pv_reserved:\\n"\n     "                    runtime_globals[_k] = _v\\n"\n     "\\n"\n     "        def _collect_variables():\\n"\n     "            if not _pv_enabled:\\n"\n     "                return {}\\n"\n     "            out, total = {}, 0\\n"\n     "            try:\\n"\n     "                for _k, _v in list(runtime_globals.items()):\\n"\n     "                    if (not isinstance(_k, str) or _k.startswith(\\"_\\") or _k in _pv_reserved\\n"\n     "                            or callable(_v) or type(_v).__name__ == \\"module\\"):\\n"\n     "                        continue\\n"\n     "                    try:\\n"\n     "                        enc = json.dumps(_v)\\n"\n     "                    except Exception:\\n"\n     "                        continue\\n"\n     "                    if len(enc) > 4000 or total + len(enc) > 30000 or enc.count(\\"\\\\\\\\n\\") >= 8:\\n"\n     "                        continue  # small values only: plans, counters, coordinates; no board dumps\\n"\n     "                    back = json.loads(enc)\\n"\n     "                    if back != _v or type(back) is not type(_v):\\n"\n     "                        continue  # tuples / int dict keys would come back changed\\n"\n     "                    out[_k] = back\\n"\n     "                    total += len(enc)\\n"\n     "            except Exception:\\n"\n     "                return {}\\n"\n     "            return out\\n"\n     "\\n"\n     "        def _collect_retention_payload():\\n"),\n])\n_t = (_pv_dir / "python_tool_sandbox.py").read_text()\nassert _t.count("                    **_collect_retention_payload(),\\n") == 2\n_t = _t.replace("                    **_collect_retention_payload(),\\n",\n                "                    **_collect_retention_payload(),\\n                    \\"kept_variables\\": _collect_variables(),\\n")\nfor _a in (\'                    "keepable_functions": list(message.get("keepable_functions") or []),\\n\',\n           \'                "kept_functions": list(kept_functions or []),\\n\',\n           \'    kept_functions: list[str] | None = None,\\n\'):\n    assert _t.count(_a) == 1, _a\n_t = _t.replace(\'                    "keepable_functions": list(message.get("keepable_functions") or []),\\n\',\n                \'                    "keepable_functions": list(message.get("keepable_functions") or []),\\n\'\n                \'                    "kept_variables": message.get("kept_variables") or {},\\n\', 1)\n_t = _t.replace(\'                "kept_functions": list(kept_functions or []),\\n\',\n                \'                "kept_functions": list(kept_functions or []),\\n\'\n                \'                "kept_variables": kept_variables or {},\\n\'\n                \'                "vars_enabled": kept_variables is not None,\\n\', 1)\n_t = _t.replace(\'    kept_functions: list[str] | None = None,\\n\',\n                \'    kept_functions: list[str] | None = None,\\n    kept_variables: dict | None = None,\\n\', 1)\n(_pv_dir / "python_tool_sandbox.py").write_text(_t)\ncompile(_t, "python_tool_sandbox.py", "exec")\n_pv_patch(_pv_dir / "tool_agent.py", [\n    ("            kept_functions=self._retained_sources(),\\n",\n     "            kept_functions=self._retained_sources(),\\n"\n     "            kept_variables=(getattr(self, \\"_kept_variables\\", None) or {}) if os.environ.get(\\"ARC3_PERSIST_VARS\\") == \\"1\\" else None,\\n"),\n    ("        self._record_retained_functions(sandbox_result, payload)\\n",\n     "        self._record_retained_functions(sandbox_result, payload)\\n"\n     "        if os.environ.get(\\"ARC3_PERSIST_VARS\\") == \\"1\\":\\n"\n     "            self._kept_variables = dict(sandbox_result.get(\\"kept_variables\\") or {})\\n"),\n    ("            self._session_runtime_dir = runtime_dir\\n",\n     "            self._session_runtime_dir = runtime_dir\\n            self._kept_variables = {}\\n"),\n    ("        if summary.get(\\"level_transition\\") and _persistent_functions_scope() == \\"levelup\\":\\n",\n     "        if summary.get(\\"level_transition\\"):\\n            self._kept_variables = {}  # old-layout data must not leak into a new level\\n"\n     "        if summary.get(\\"level_transition\\") and _persistent_functions_scope() == \\"levelup\\":\\n"),\n])\nos.environ["ARC3_PERSIST_VARS"] = "1"\nprint("persistvars patch applied", flush=True)\n'

# Behaviour-neutral throughput options (same decisions, faster): name -> (cell, old, new)
OPTS = {
    "precache8": (6, "kwargs={'delay': 60, 'threads': 3})", "kwargs={'delay': 60, 'threads': 8})"),
    "spec4": (12, "    SPEC_STEPS=3,\n", "    SPEC_STEPS=4,\n"),
    # same AutoRound target weights, PLE table in FP8 (125 GB instead of 181 GB; Franzen mirror 10/12).
    # The M2 launcher supports it ("BF16 PLE or albucino FP8 PLE"); model source swapped in build().
    "fp8ple": (4, "MODEL_DIR         = '/kaggle/input/models/dfranzen/intel-qwen3.8-flash-next-w4a16-autoround/transformers/default/1'",
               "MODEL_DIR         = '/kaggle/input/models/dfranzen/albucino-qwen3.8-flash-next-w4a16-fp8ple/transformers/default/1'"),
}
MODEL_SWAP = {"fp8ple": ("dfranzen/intel-qwen3.8-flash-next-w4a16-autoround/Transformers/default/1",
                         "dfranzen/albucino-qwen3.8-flash-next-w4a16-fp8ple/Transformers/default/1")}


def replace_once(text: str, old: str, new: str, where: str) -> str:
    n = text.count(old)
    assert n == 1, f"{where}: anchor found {n} times: {old[:80]!r}"
    return text.replace(old, new)


def build(variant: str = "robust", opts: tuple[str, ...] = (), slug: str | None = None) -> Path:
    cfg = VARIANTS[variant]
    slug, extra_cell, rgames, rmin = slug or cfg["slug"], cfg["extra"], cfg["games"], cfg["minutes"]
    kernel_id = f"taichiiiii/{slug}"
    nb = json.loads(SRC_NB.read_text())
    cells = nb["cells"]
    src = lambda i: "".join(cells[i]["source"])  # noqa: E731

    def put(i: int, text: str) -> None:
        cells[i]["source"] = text.splitlines(keepends=True)

    # --- cell 4: env, keepalive patch, TRUE_SUBMISSION fallback, rehearsal release ---
    c = src(4)
    c = replace_once(c, "os.environ['ARC3_HTTP_RETRY_INITIAL_SECONDS'] = '900'\n",
                     "os.environ['ARC3_HTTP_RETRY_INITIAL_SECONDS'] = '7200'  # m2-robust: 900 -> 7200\n"
                     "os.environ['ARC3_KEEPALIVE_SECONDS'] = '240'      # m2-robust\n"
                     "os.environ['ARC3_KEEPALIVE_MAX_SECONDS'] = '7200' # m2-robust\n", "cell4 env")
    c = replace_once(c, "print('harness patch applied successfully')\n",
                     "print('harness patch applied successfully')\n"
                     + APPLY_SNIPPET.format(anchor=KEEPALIVE_CALL_ANCHOR, new=KEEPALIVE_CALL_NEW,
                                            func=KEEPALIVE_FUNC), "cell4 apply")
    old_ts = ('TRUE_SUBMISSION = os.environ.get("KAGGLE_IS_COMPETITION_RERUN", "").strip().lower() '
              'in {"1", "true"}\n')
    new_ts = old_ts + '''# m2-robust: also treat a resolvable "gateway" host as a scored rerun (never true in Save & Run)
if not TRUE_SUBMISSION:
    import socket as _socket
    for _i in range(12):
        try:
            _socket.getaddrinfo("gateway", 8001)
            TRUE_SUBMISSION = True
            print("m2-robust: gateway host resolves -> TRUE_SUBMISSION=True", flush=True)
            break
        except OSError:
            time.sleep(5)
# m2-robust rehearsal: release the benchmark early so the keepalive path runs in Save & Run
if not TRUE_SUBMISSION:
    SERVER_STARTUP_TIMEOUT = 90
'''
    c = replace_once(c, old_ts, new_ts, "cell4 TRUE_SUBMISSION")
    put(4, c)

    # --- cell 16: rehearsal size (the TRUE_SUBMISSION branch is left as is) ---
    c = src(16)
    excluded = [g for g in ALL_PUBLIC if g not in rgames]
    c = replace_once(c, "demo_excluded_games = [] if TRUE_SUBMISSION else []\n",
                     f"demo_excluded_games = [] if TRUE_SUBMISSION else {excluded!r}  # m2-robust rehearsal\n",
                     "cell16 excluded")
    c = c.replace("# show config\n",
                  "if not TRUE_SUBMISSION:  # m2-robust rehearsal: short, proves start-up + actions\n"
                  "    bm.n_passes = 1\n"
                  f"    bm.solver.concurrency = {len(rgames)}\n"
                  f"    bm.solver.max_runtime_s_per_game = {rmin} * 60  # includes waiting for the model load\n\n# show config\n", 1)
    assert "m2-robust rehearsal: short" in c
    put(16, c)

    # --- cell 20: longer gateway wait ---
    c = src(20)
    c = replace_once(c, "_wait_for_gateway(os.environ[\"ARC_BASE_URL\"])\n",
                     "_wait_for_gateway(os.environ[\"ARC_BASE_URL\"], timeout_s=1800.0)  # m2-robust\n",
                     "cell20 gateway")
    put(20, c)

    if "persistvars" in opts:  # behaviour-CHANGING bet (not a throughput option): appended to cell 4
        put(4, src(4) + PERSISTVARS)
    if cfg.get("watchdog"):
        assert "proc = subprocess.Popen(args" in src(12), "launcher cell moved"
        put(12, src(12) + WATCHDOG)
    for o in opts:  # behaviour-neutral throughput options, applied before the extra cell shifts indices
        if o == "persistvars":
            continue
        ci, old, new = OPTS[o]
        put(ci, replace_once(src(ci), old, new, f"opt {o}"))

    # optional extra cell, inserted right after the customization hook (cell 16)
    if extra_cell is not None:
        cells.insert(17, {"cell_type": "code", "metadata": {}, "outputs": [], "execution_count": None,
                          "source": Path(extra_cell).read_text().splitlines(keepends=True)})

    # strip outputs
    for cell in cells:
        if cell["cell_type"] == "code":
            cell["outputs"] = []
            cell["execution_count"] = None

    out = OUT / (variant if slug == cfg["slug"] else slug)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    nb_name = f"{slug}.ipynb"
    (out / nb_name).write_text(json.dumps(nb, indent=1, ensure_ascii=False))
    meta = json.loads((SRC_DIR / "kernel-metadata.json").read_text())
    for o in opts:
        if o in MODEL_SWAP:
            old, new = MODEL_SWAP[o]
            assert old in meta["model_sources"], meta["model_sources"]
            meta["model_sources"] = [new if m == old else m for m in meta["model_sources"]]
    for k in ("id_no",):
        meta.pop(k, None)
    meta.update({"id": kernel_id, "title": slug, "code_file": nb_name, "is_private": True,
                 "keywords": []})
    assert meta["is_private"] is True and meta["enable_internet"] is False
    (out / "kernel-metadata.json").write_text(json.dumps(meta, indent=2))
    print("built", out / nb_name)
    return out / nb_name


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("variants", nargs="*", default=["robust"])
    ap.add_argument("--opts", default="", help="comma list of OPTS names")
    ap.add_argument("--slug", default=None)
    a = ap.parse_args()
    for v in a.variants:
        build(v, tuple(x for x in a.opts.split(",") if x), a.slug)
