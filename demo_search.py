"""
Run with: python demo_search.py

Shows the Phase 2 milestone: instead of you picking two actions and asking
"how risky is this", the search tries EVERY legal action for you, assumes
worst-case enemy play, and ranks them.
"""

import time

from environment.loader import DataStore
from engine.state import BattleState
from search.expectiminimax import search_best_action, describe_action


def make_battle() -> BattleState:
    store = DataStore()
    player_team = store.build_team("player_demo_team")
    enemy_team = store.build_team("rival_1")
    state = BattleState(player_team=player_team, enemy_team=enemy_team)
    state.player_active = 1  # Rotom-Wash out first, same risky matchup as before
    return state


def run(depth: int, damage_buckets: int):
    state = make_battle()
    print(state.describe_active())
    print(f"\nSearching depth={depth}, damage_buckets={damage_buckets} ...")

    t0 = time.time()
    result = search_best_action(state, depth=depth, damage_buckets=damage_buckets)
    elapsed = time.time() - t0

    print(f"Done in {elapsed:.2f}s -- {result.nodes_evaluated} nodes evaluated\n")
    print(f"{'ACTION':40s} {'SCORE':>8s} {'WORST ENEMY REPLY':25s} {'FAINT%':>8s} {'WIPE%':>8s}  TIER")
    print("-" * 100)
    for r in result.ranked:
        action_desc = describe_action(state, "player", r.action)
        enemy_desc = describe_action(state, "enemy", r.worst_case_enemy_action)
        risk = r.immediate_risk
        print(
            f"{action_desc:40s} {r.value:8.3f} {enemy_desc:25s} "
            f"{risk['active_faint_probability']*100:7.2f}% "
            f"{risk['team_wipe_probability']*100:7.2f}%  {risk['risk_tier']}"
        )

    best_desc = describe_action(state, "player", result.best_action)
    print(f"\n==> Recommended: {best_desc}")


if __name__ == "__main__":
    run(depth=1, damage_buckets=3)
    print("\n" + "=" * 100 + "\n")
    run(depth=2, damage_buckets=3)
    print(
        "\n(compare this depth=2 timing to what you saw before the alpha-beta pruning "
        "update -- same recommendation, same scores, should be noticeably faster)"
    )
