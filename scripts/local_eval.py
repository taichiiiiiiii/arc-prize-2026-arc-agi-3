"""Run an agent on the 25 public games offline and print the official-toolkit score.

Usage:
    uv run python scripts/local_eval.py --agent random --max-actions 500
    uv run python scripts/local_eval.py --games ls20 ft09 --seed 1

The score comes from arc_agi's own scorecard (the same calculator the Kaggle
gateway uses), so a local number is comparable in definition to the LB number.
The public 25 games are NOT the hidden 110 games: treat local scores as a
smoke test / regression check, not as an LB estimate.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import time
from pathlib import Path
from typing import Any
from collections.abc import Callable

import arc_agi
from arcengine import GameAction, GameState

ROOT = Path(__file__).resolve().parents[1]
ENV_DIR = ROOT / "data" / "environment_files"

Policy = Callable[[Any, random.Random], tuple[GameAction, dict[str, Any]]]


def random_policy(frame: Any, rng: random.Random) -> tuple[GameAction, dict[str, Any]]:
    """Uniform over the actions the game says are available (never RESET)."""
    avail = [GameAction.from_id(a) for a in (frame.available_actions or [])]
    avail = [a for a in avail if a is not GameAction.RESET] or [GameAction.ACTION1]
    action = rng.choice(avail)
    data = {"x": rng.randint(0, 63), "y": rng.randint(0, 63)} if action.is_complex() else {}
    return action, data


POLICIES: dict[str, Policy] = {"random": random_policy}


def play(arcade: arc_agi.Arcade, game_id: str, card: str, policy: Policy,
         max_actions: int, rng: random.Random) -> dict[str, Any]:
    env = arcade.make(game_id, scorecard_id=card)
    frame = env.reset()
    n = 0
    t0 = time.time()
    while n < max_actions and frame is not None:
        if frame.state is GameState.WIN:
            break
        if frame.state is GameState.GAME_OVER:
            frame = env.step(GameAction.RESET)
        else:
            action, data = policy(frame, rng)
            frame = env.step(action, data=data)
        n += 1
    return {
        "game": game_id,
        "actions": n,
        "levels_completed": getattr(frame, "levels_completed", None),
        "win_levels": getattr(frame, "win_levels", None),
        "state": getattr(getattr(frame, "state", None), "name", None),
        "sec": round(time.time() - t0, 2),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="random", choices=sorted(POLICIES))
    ap.add_argument("--games", nargs="*", help="game prefixes, e.g. ls20 ft09 (default: all)")
    ap.add_argument("--max-actions", type=int, default=500)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, help="write per-game JSON here")
    args = ap.parse_args()

    quiet = logging.getLogger("arc_quiet")
    quiet.addHandler(logging.NullHandler())
    quiet.propagate = False
    arcade = arc_agi.Arcade(operation_mode=arc_agi.OperationMode.OFFLINE,
                            environments_dir=str(ENV_DIR), logger=quiet)
    games = [e.game_id for e in arcade.available_environments]
    if args.games:
        games = [g for g in games if any(g.startswith(p) for p in args.games)]
    card = arcade.create_scorecard()
    rng = random.Random(args.seed)

    rows = []
    for g in sorted(games):
        r = play(arcade, g, card, POLICIES[args.agent], args.max_actions, rng)
        rows.append(r)
        print(f"{g:16s} levels {r['levels_completed']}/{r['win_levels']}  "
              f"actions {r['actions']:5d}  {r['state']}  {r['sec']}s")

    sc = arcade.close_scorecard(card)
    per_game = {}
    for envlist in sc.environments:
        for run in envlist.runs:
            per_game[envlist.id] = run.score
    print(f"\n{len(rows)} games  scorecard score = {sc.score:.3f}")
    nonzero = {k: round(v, 2) for k, v in per_game.items() if v}
    print("non-zero games:", nonzero or "none")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"score": sc.score, "per_game": per_game, "rows": rows},
                                       indent=1))


if __name__ == "__main__":
    main()
