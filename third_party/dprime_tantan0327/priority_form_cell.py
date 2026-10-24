# arm dprime: ONE patch on the Franzen M2 copy (priority_form.py); everything else byte-identical.
import os; os.environ['ARC3_PRIORITY_FORM'] = 'dprime'
# PATCH: pluggable slot-priority for Franzen's Milestone-2 harness (CC0 / MIT-0, ours).
#
# What it replaces: ONLY the number the scheduler uses to decide which waiting game gets a
# freed LLM slot (tool_agent.priority_value, called by _PriorityGate._snapshot_priority), the
# per-game pace tracker it reads (tool_agent.ProgressPace), and - optionally - the rule that
# never-started games always jump the queue (they are priced by the same formula instead).
# Harness, model, prompts and everything else are untouched.
#
# Forms (ARC3_PRIORITY_FORM):
#   base   - Franzen's contest formula re-expressed (parity check; the harness default)
#   dprime - the formula published by Osaka Metropolitan "Affectify" (shiiin9) in the public
#            notebook "ARC-AGI-3 Milestone 2 Solution with a new slot priority (D')",
#            implemented here from its stated definition: priority = A*M*C + B*phi
#   ours   - our parametric family (contains both as points), tuned offline on
#            scripts/sched_sim.py; parameters via ARC3_PRIORITY_PARAMS (JSON)
# Other knobs: ARC3_PRIORITY_FADE (tail fade fraction, default 0.4),
#              ARC3_PRIORITY_PRICE_FRESH (1 = price unstarted games, 0 = keep fresh-first).
import json as _json
import math as _math
import os as _os
import threading as _threading
import time as _time

FORM = _os.environ.get("ARC3_PRIORITY_FORM", "ours").strip().lower()
FADE = float(_os.environ.get("ARC3_PRIORITY_FADE", "0.4") or 0.4)
PRICE_FRESH = _os.environ.get("ARC3_PRIORITY_PRICE_FRESH", "1").strip().lower() not in ("0", "false", "off")
SCALE = 1000.0

DPRIME = {"level_pow": 0.5, "eff_const": 300.0, "eff_pow": 2.5, "pace_pow": 0.4, "pace_ref": 30000.0,
          "c_action": 0.1, "action_scale": 115.0, "c_token": 0.9, "token_scale": 225000.0,
          "lin_floor": 0.1, "rel_pow": 0.5, "b1": 10.0, "b2": 14.0, "b3": 16.0}
OURS_DEFAULT = {"level_pow": 0.5, "eff_const": 100.0, "eff_pow": 2.0, "patience_tok": 150000.0,
                "floor": 0.05, "b3": 12.0, "b2": 10.0, "b1": 7.0, "pace_pow": 0.5,
                "fresh_mult": 1.0, "stuck_pen": 0.5, "pace_ref": 20000.0}
try:
    PARAMS = dict(OURS_DEFAULT, **_json.loads(_os.environ.get("ARC3_PRIORITY_PARAMS", "") or "{}"))
except Exception:
    PARAMS = dict(OURS_DEFAULT)


def norm_levels(total_levels):
    try:
        n = int(total_levels)
    except (TypeError, ValueError):
        n = 10
    n = min(10, max(6, n if n > 0 else 10))
    return 55.0 / (n * (n + 1) / 2), n


class PaceTracker:
    """Mean generated tokens per cleared level in this game (0.0 before the first clear).
    Same call shape as the harness's ProgressPace; cost_multiplier() returns the mean itself."""

    def __init__(self):
        self.completed = 0
        self.tokens = 0.0

    def record_completion(self, tokens_used, reference_tokens=0.0):
        self.completed += 1
        self.tokens += max(0.0, float(tokens_used))

    def cost_multiplier(self):
        return self.tokens / self.completed if self.completed else 0.0


def value_base(level, a, t, pace, total_levels, phi):
    norm, n = norm_levels(total_levels)
    eff = (25.0 / (25.0 + a)) ** 2
    A = level * eff * norm
    tail = (0.0, 5.0, 7.0, 8.0)[min(max(0, n - level), 3)] * phi
    chance = 0.25 * 0.5 ** ((a / 115.0) ** 2) + 0.75 * 0.5 ** ((t / 62000.0) ** 2)
    return (A + tail) * chance * 100.0 / SCALE


def value_dprime(level, a, t, pace, total_levels, phi, p=DPRIME):
    norm, n = norm_levels(total_levels)
    A = (1.0 + p["level_pow"] * (level - 1)) * norm * (p["eff_const"] / (p["eff_const"] + a)) ** p["eff_pow"]
    if pace > 0:
        A *= min(4.0, max(0.25, (p["pace_ref"] / max(1.0, pace)) ** p["pace_pow"]))
    rel = pace if pace > 0 else p["pace_ref"]
    scale = p["token_scale"] * (min(2.0, max(0.5, rel / p["pace_ref"])) ** p["rel_pow"])
    C = (p["c_action"] * max(p["lin_floor"], 1.0 - a / p["action_scale"])
         + p["c_token"] * max(p["lin_floor"], 1.0 - t / scale))
    B = (0.0, p["b1"], p["b2"], p["b3"])[min(max(0, n - level), 3)]
    return A * C + B * phi


def value_ours(level, a, t, pace, total_levels, phi, p=None):
    p = p or PARAMS
    norm, n = norm_levels(total_levels)
    A = (1.0 + p["level_pow"] * (level - 1)) * norm
    A *= (p["eff_const"] / (p["eff_const"] + a)) ** p["eff_pow"]
    if pace > 0:
        A *= min(4.0, max(0.25, (p["pace_ref"] / max(1.0, pace)) ** p["pace_pow"]))
    scale = p["patience_tok"] * (min(2.0, max(0.5, (pace if pace > 0 else p["pace_ref"]) / p["pace_ref"])) ** 0.5)
    C = max(p["floor"], 1.0 - t / scale)
    if t > scale:
        C *= p["stuck_pen"]
    B = (0.0, p["b1"], p["b2"], p["b3"])[min(max(0, n - level), 3)]
    return A * C + B * phi


VALUE = {"base": value_base, "dprime": value_dprime, "ours": value_ours}[FORM]


def priority_value(state, *, tail_fraction=None, **_ignored):
    """Drop-in for tool_agent.priority_value: integer priority from a PrioritySnapshot
    (level, actions, tokens, cost_multiplier = our pace, total_levels)."""
    phi = 1.0 if tail_fraction is None else min(1.0, max(0.0, float(tail_fraction)))
    v = VALUE(max(1, int(state.level)), max(0, int(state.actions)), max(0.0, float(state.tokens)),
              float(getattr(state, "cost_multiplier", 0.0) or 0.0), getattr(state, "total_levels", None), phi)
    return max(1, int(v * SCALE))


_TL = _threading.local()
STATS = {"fresh_priced": 0}


def install(tool_agent, solver):
    for name in ("priority_value", "ProgressPace", "_PriorityGate", "PrioritySnapshot",
                 "_PRIORITY_UNTRIMMED_BASE", "_PRIORITY_BAND"):
        if not hasattr(tool_agent, name):
            raise RuntimeError("tool_agent lacks %s: the harness version changed" % name)
    gate_cls = tool_agent._PriorityGate
    for name in ("acquire", "_enqueue_and_wait", "_snapshot_priority"):
        if not callable(getattr(gate_cls, name, None)):
            raise RuntimeError("_PriorityGate lacks %s: the harness version changed" % name)
    session_cls = getattr(solver, "_HarnessGameSession", None)
    if session_cls is None or not callable(getattr(session_cls, "play", None)):
        raise RuntimeError("solver lacks _HarnessGameSession.play: the harness version changed")

    tool_agent.priority_value = priority_value
    tool_agent.ProgressPace = PaceTracker
    _os.environ["ARC3_PRIORITY_PACE"] = "1"
    _os.environ["ARC3_PRIORITY_REFRESH_QUEUE"] = "1"
    _os.environ["ARC3_PRIORITY_TAIL_FADE"] = "1"
    _os.environ["ARC3_PRIORITY_TAIL_FADE_FRACTION"] = str(FADE)

    if PRICE_FRESH and not getattr(session_cls.play, "_priority_form", False):
        orig_play = session_cls.play

        def play(self, *args, **kwargs):
            run = getattr(getattr(self, "game", None), "game_run", None)
            _TL.total_levels = getattr(run, "number_of_levels", None)
            try:
                return orig_play(self, *args, **kwargs)
            finally:
                _TL.total_levels = None

        play._priority_form = True
        session_cls.play = play

        orig_acquire = gate_cls.acquire
        fresh_floor = tool_agent._PRIORITY_UNTRIMMED_BASE - tool_agent._PRIORITY_BAND
        snapshot_cls = tool_agent.PrioritySnapshot

        def acquire(self, priority):
            if priority < fresh_floor:
                return orig_acquire(self, priority)
            snap = snapshot_cls(1, 0, 0.0, 0.0, getattr(_TL, "total_levels", None))
            value = self._snapshot_priority(snap, _time.monotonic())
            with self._cond:
                self._enqueue_and_wait(value, snap)
            STATS["fresh_priced"] += 1

        acquire._priority_form = True
        gate_cls.acquire = acquire

    line = ("PRIORITY_FORM installed: form=%s fade=%.2f price_fresh=%s params=%s"
            % (FORM, FADE, PRICE_FRESH, _json.dumps(PARAMS if FORM == "ours" else (DPRIME if FORM == "dprime" else {}))))
    print(line, flush=True)
    return line


try:
    import inference.agent.tool_agent as _ta
    import inference.framework.solver as _sv
    install(_ta, _sv)
except ImportError as _exc:  # outside the harness (unit test imports the module by exec)
    print("PRIORITY_FORM not installed (no harness on the path): %s" % _exc, flush=True)
