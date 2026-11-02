"""Where do the tokens and turns go? Per-game failure-mode report from harness request logs.

Reads <dir>/*_requests.jsonl (save_request_logs=True in rehearsals/benches; each line is a
`request` or `response` event with the full message list) and prints per game:
  turns, completion/reasoning tokens, finish_reason counts (length = output cut off),
  python tool results: non-zero returncode, top error types, action() calls that executed nothing,
  guard/refusal messages, and the share of completion tokens spent in turns whose tool call failed.

Usage: python scripts/transcript_report.py work/analysis/base2 [--json out.json]
"""

from __future__ import annotations

import collections
import json
import re
from pathlib import Path

ERR = re.compile(r"([A-Za-z_]+(?:Error|Exception|Exit|Interrupt))\b")


def tool_result(msg: dict) -> dict | None:
    if msg.get("role") != "tool":
        return None
    c = msg.get("content")
    if isinstance(c, list):
        c = " ".join(str(x.get("text", "")) for x in c if isinstance(x, dict))
    try:
        return json.loads(c)
    except Exception:  # noqa: BLE001
        return {"raw": str(c)}


def game_report(path: Path) -> dict:
    fin = collections.Counter()
    comp = reas = prompt = cached = 0
    seen_tools: set[str] = set()
    rc_bad = 0
    errs = collections.Counter()
    noexec = guard = tools_n = 0
    turns = 0
    bad_turn_tokens = 0
    last_comp = 0
    samples: dict[str, str] = {}
    for line in path.open():
        d = json.loads(line)
        if d["event"] == "response":
            turns += 1
            fin[d.get("finish_reason") or ""] += 1
            u = d.get("usage") or {}
            last_comp = int(u.get("completion_tokens") or 0)
            comp += last_comp
            reas += int(u.get("reasoning_tokens") or 0)
            prompt += int(u.get("prompt_tokens") or 0)
            cached += int((u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
            continue
        # request: new tool results are the trailing tool messages not seen before
        for m in d.get("messages") or []:
            if m.get("role") != "tool":
                continue
            tid = m.get("tool_call_id") or str(hash(str(m.get("content"))[:200]))
            if tid in seen_tools:
                continue
            seen_tools.add(tid)
            r = tool_result(m) or {}
            tools_n += 1
            text = json.dumps(r)[:20000]
            bad = False
            if r.get("returncode") not in (0, None) or r.get("error"):
                rc_bad += 1
                bad = True
                e = ERR.findall(str(r.get("error") or r.get("stderr") or text))
                errs[e[-1] if e else "other"] += 1
                samples.setdefault(e[-1] if e else "other", str(r.get("error") or "")[-300:])
            if "'executed': False" in text or '"executed": false' in text:
                noexec += 1
            if re.search(r"blocked|refus|not allowed|rejected", text, re.I):
                guard += 1
            if bad:
                bad_turn_tokens += last_comp
    return {"turns": turns, "completion_tok": comp, "reasoning_tok": reas, "prompt_tok": prompt,
            "cached_share": round(cached / prompt, 3) if prompt else None,
            "finish": dict(fin), "tool_results": tools_n, "tool_rc_nonzero": rc_bad,
            "top_errors": errs.most_common(5), "error_samples": samples, "action_noexec": noexec, "guard_msgs": guard,
            "share_tokens_in_failed_tool_turns": round(bad_turn_tokens / comp, 3) if comp else None}


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Token / tool-error breakdown from *_requests.jsonl request logs.")
    ap.add_argument("dirs", nargs="+", help="directories that contain <game>_requests.jsonl")
    ap.add_argument("--json", dest="out", help="also write the per-game report to this JSON file")
    a = ap.parse_args()
    args, out = a.dirs, a.out
    allr = {}
    for d in args:
        for p in sorted(Path(d).glob("*_requests.jsonl")):
            key = f"{Path(d).name}/{p.name.split('_')[0]}"
            allr[key] = r = game_report(p)
            print(key, json.dumps(r, ensure_ascii=False))
    if out:
        Path(out).write_text(json.dumps(allr, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
