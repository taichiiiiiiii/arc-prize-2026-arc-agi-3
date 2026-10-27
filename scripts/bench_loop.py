"""One tick of the throughput-improvement loop (cron every 15 min; prints only on events).

Plan (analysis/reports/strategy.md, 改善ループ): measure behaviour-neutral throughput options on the
bench10 kernel (10 public games, 10 streams), decide by pre-registered rules, then promote adopted
options into the A/B submission kernels and swap them into the submission queue
(analysis/loop_state.json) only after their rehearsal passed.

State: analysis/bench_state.json. Usage: env -u PYTHONPATH uv run python scripts/bench_loop.py
"""

from __future__ import annotations

import json
import shutil
import statistics as st
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import bench_report  # noqa: E402
import loop_tick  # noqa: E402

STATE = ROOT / "analysis" / "bench_state.json"
QUEUE = ROOT / "analysis" / "loop_state.json"
BUILD = ROOT / "kernels" / "m2_robust" / "build.py"
PUSH_DIR = ROOT / "work" / "push"
OUT_DIR = ROOT / "work" / "bench"
PY = sys.executable


def sh(*args: str, timeout: int = 600) -> str:
    r = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout, cwd=ROOT)
    return r.stdout + r.stderr


def gpu_hours_left() -> float:
    """Weekly GPU quota left (`kaggle quota`); scored reruns of submissions do not use it."""
    out = loop_tick.kaggle("quota")
    for line in out.splitlines():
        if line.startswith("GPU"):
            try:
                return float(line.split()[2].rstrip("h"))
            except (IndexError, ValueError):
                break
    return 0.0


MIN_GPU_HOURS = 2.0  # one bench10 / rehearsal run is ~1.5 h


def push(variant: str, opts: list[str], slug: str) -> str:
    left = gpu_hours_left()
    if left < MIN_GPU_HOURS:
        return f"GPU_QUOTA_HOLD: {left:.2f}h left < {MIN_GPU_HOURS}h"
    sh(PY, str(BUILD), variant, "--opts", ",".join(opts), "--slug", slug)
    src = ROOT / "kernels" / "m2_robust" / "out" / slug
    if not src.exists():  # default slug builds into out/<variant>
        src = ROOT / "kernels" / "m2_robust" / "out" / variant
    meta = json.loads((src / "kernel-metadata.json").read_text())
    assert meta["is_private"] is True and meta["id"].endswith("/" + slug), meta["id"]
    dst = PUSH_DIR / slug
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return loop_tick.kaggle("kernels", "push", "-p", str(dst))


def status(slug: str) -> str:
    s = loop_tick.kaggle("kernels", "status", f"taichiiiii/{slug}")
    for k in ("RUNNING", "QUEUED", "COMPLETE", "ERROR", "CANCEL"):
        if k in s:
            return k
    return s.strip()[:80]


def decide(state: dict) -> list[str]:
    done = {b["name"]: b for b in state["benches"] if b.get("metrics")}
    b1, b2 = done["base1"]["metrics"], done["base2"]["metrics"]
    msgs, adopted = [], []
    dec_b = st.mean([b1["decode_tok_s_ge8"], b2["decode_tok_s_ge8"]])
    dec_thr = max(2 * abs(b1["decode_tok_s_ge8"] - b2["decode_tok_s_ge8"]), 0.04 * dec_b)
    rdy_b = st.mean([b1["ready_after_s"], b2["ready_after_s"]])
    rdy_thr = max(2 * abs(b1["ready_after_s"] - b2["ready_after_s"]), 120.0)
    lv_min = min(b1["levels"], b2["levels"])
    for b in state["benches"]:
        if not b["name"].startswith("c_") or not b.get("metrics"):
            continue
        m = b["metrics"]
        ok_run = m["games"] == 10 and m.get("decode_tok_s_ge8") is not None and m.get("harness_tokens", 0) > 0
        if not ok_run:
            msgs.append(f"{b['name']}: 実行不良（サーバ未起動・トークン 0 など）-> 不採用")
            continue
        if b["metric"] == "decode":
            gain = m["decode_tok_s_ge8"] - dec_b
            ok = ok_run and gain > dec_thr and m["levels"] >= lv_min
            msgs.append(f"{b['name']}: decode {m['decode_tok_s_ge8']} vs base {dec_b:.1f} "
                        f"(gain {gain:+.1f}, need >{dec_thr:.1f}), levels {m['levels']} (base min {lv_min}) -> "
                        + ("採用" if ok else "不採用"))
        else:
            gain = rdy_b - m["ready_after_s"]
            ok = ok_run and gain > rdy_thr
            msgs.append(f"{b['name']}: ready {m['ready_after_s']:.0f}s vs base {rdy_b:.0f}s "
                        f"(短縮 {gain:+.0f}s, need >{rdy_thr:.0f}s) -> " + ("採用" if ok else "不採用"))
        if ok:
            adopted += b["opts"]
    state["adopted"] = adopted
    state["decided"] = True
    return msgs


def swap_queue(config_prefix: str, slug: str, version: int, markers_extra: list[str]) -> int:
    q = json.loads(QUEUE.read_text())
    n = 0
    for item in q["queue"]:
        if item.get("state") in ("submitted", "failed") or not item["config"].startswith(config_prefix):
            continue
        item["kernel"], item["version"] = f"taichiiiii/{slug}", version
        item["config"] += " +opt"
        item.pop("verify", None)
        item.pop("verify_detail", None)
        n += 1
    QUEUE.write_text(json.dumps(q, indent=1, ensure_ascii=False))
    return n


def _lock():
    import fcntl
    f = open(ROOT / "analysis" / ".loop.lock", "w")
    fcntl.flock(f, fcntl.LOCK_EX)  # loop_tick and bench_loop both write analysis/loop_state.json
    return f


def main() -> int:
    state = json.loads(STATE.read_text())
    msgs: list[str] = []
    if "Authentication" in loop_tick.kaggle("competitions", "submissions", loop_tick.COMP, "--page-size", "1"):
        print("⚠️ 改善ループ: Kaggle の認証が切れています。`kaggle auth login` を実行してください。")
        return 0

    # 1. benches
    running = [b for b in state["benches"] if b.get("status") == "running"]
    for b in running:
        s = status(b["slug"])
        if s in ("RUNNING", "QUEUED"):
            continue
        d = OUT_DIR / b["name"]
        d.mkdir(parents=True, exist_ok=True)
        loop_tick.kaggle("kernels", "output", f"taichiiiii/{b['slug']}", "-p", str(d), "--file-pattern",
                         rf"({b['slug']}\.log|serve\.log)$", timeout=900)
        try:
            b["metrics"] = bench_report.report(d)
            b["status"] = "done"
            msgs.append(f"ベンチ完了 {b['name']}: " + json.dumps(
                {k: b["metrics"].get(k) for k in ("ready_after_s", "decode_tok_s_ge8", "accept_len",
                                                  "prefix_cached_share", "levels", "games")}, ensure_ascii=False))
        except Exception as e:  # noqa: BLE001
            b["status"] = "failed"
            msgs.append(f"ベンチ失敗 {b['name']} ({s}): {e}")
    if not any(b.get("status") == "running" for b in state["benches"]):
        nxt = next((b for b in state["benches"] if b.get("status") == "pending"), None)
        if nxt is not None:
            out = push("bench10", nxt["opts"], nxt["slug"])
            if out.startswith("GPU_QUOTA_HOLD"):
                if not state.get("hold_notified"):
                    msgs.append(f"GPU クォータ不足でベンチを保留: {out}")
                    state["hold_notified"] = True
                nxt = None
        if nxt is not None:
            nxt["status"] = "running" if "successfully pushed" in out else "failed"
            msgs.append(f"ベンチ開始 {nxt['name']} ({nxt['slug']}, opts={nxt['opts']}): {out.strip()[:120]}")

    # 2. decision
    names = {b["name"]: b for b in state["benches"]}
    if (not state.get("decided") and all(b.get("status") in ("done", "failed") for b in state["benches"])
            and names["base1"].get("metrics") and names["base2"].get("metrics")):
        msgs += ["判定（事前登録の規則）:"] + decide(state)
        if state["adopted"]:
            state["promote"] = [
                {"variant": "robust", "slug": "arc3-m2-robust-opt", "config": "A=", "status": "pending",
                 "markers": []},
                {"variant": "dprime", "slug": "arc3-m2-robust-dprime-opt", "config": "B=", "status": "pending",
                 "markers": ["PRIORITY_FORM installed: form=dprime"]},
            ]
        else:
            msgs.append("採用なし: 提出計画は変更しない")

    # 3. promotion (one rehearsal at a time; swap the queue only after the rehearsal log check)
    for p in state.get("promote", []):
        if p["status"] == "running":
            s = status(p["slug"])
            if s in ("RUNNING", "QUEUED"):
                break
            item = {"kernel": f"taichiiiii/{p['slug']}", "version": p["version"],
                    "markers": ["m2-robust: keepalive patch applied", "taaf.kaggle: TRUE_SUBMISSION=False"]
                    + p["markers"]}
            v, detail = loop_tick.verify_kernel(item)
            if v == "ok":
                n = swap_queue(p["config"], p["slug"], p["version"], p["markers"])
                p["status"] = "swapped"
                msgs.append(f"昇格 {p['slug']} v{p['version']}: 試走 ok（{detail}）→ 提出計画の {p['config']} 枠 {n} 件を差し替え")
            else:
                p["status"] = "failed"
                msgs.append(f"昇格失敗 {p['slug']}: {detail} → 提出計画は元のまま")
        if p["status"] == "pending":
            smoke = ROOT / "analysis" / "smoke" / f"{p['variant']}-{'-'.join(sorted(state['adopted']))}.json"
            res = json.loads(smoke.read_text()) if smoke.exists() else {}
            if not (res.get("ok") and sorted(res.get("opts", [])) == sorted(state["adopted"])):
                if not state.get("smoke_notified"):
                    msgs.append(f"昇格保留: 手元の通しテスト未合格 ({smoke.name})。"
                                f"`scripts/local_smoke.py {p['variant']} --opts {','.join(state['adopted'])} --result {smoke}`")
                    state["smoke_notified"] = True
                break
            out = push(p["variant"], state["adopted"], p["slug"])
            if out.startswith("GPU_QUOTA_HOLD"):
                if not state.get("hold_notified"):
                    msgs.append(f"GPU クォータ不足で昇格の試走を保留（10/31 00:00 UTC にリセット）: {out}")
                    state["hold_notified"] = True
                break
            state["hold_notified"] = False
            ver = None
            if "successfully pushed" in out:
                try:
                    ver = int(out.split("Kernel version ")[1].split()[0])
                except Exception:  # noqa: BLE001
                    ver = None
            p["status"], p["version"] = ("running", ver) if ver else ("failed", None)
            msgs.append(f"昇格の試走開始 {p['slug']} opts={state['adopted']}: {out.strip()[:100]}")
            break
        if p["status"] == "running":
            break

    STATE.write_text(json.dumps(state, indent=1, ensure_ascii=False))
    if msgs:
        print("ARC-AGI-3 改善ループ:\n- " + "\n- ".join(msgs))
    return 0


if __name__ == "__main__":
    _lk = _lock()
    sys.exit(main())
