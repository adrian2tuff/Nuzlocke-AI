"""
Run with: python demo_replaceability.py

Two things to look at:
1. The replaceability breakdown for the demo team -- does it match your
   intuition about which Pokemon matters more?
2. A concrete "which faint hurts more" comparison using the evaluator --
   this is the actual "sack Bidoof, not Garchomp" logic in action.
"""

from environment.loader import DataStore
from engine.state import BattleState
from search.replaceability import explain
from search.evaluator import evaluate


def main():
    store = DataStore()
    player_team = store.build_team("player_demo_team")
    enemy_team = store.build_team("rival_1")
    state = BattleState(player_team=player_team, enemy_team=enemy_team)

    print("=" * 70)
    print("Replaceability breakdown -- player_demo_team")
    print("=" * 70)
    for line in explain(state.player_team):
        print(" ", line)

    print("\nRead this as: higher replaceability = losing it barely hurts.")
    print("Lower replaceability = the team has no other answer for what it does.\n")

    baseline = evaluate(state, watch="player")
    print(f"Baseline evaluate() score with full team healthy: {baseline:.3f}\n")

    # Compare: what does the score look like if EACH Pokemon, one at a
    # time, faints -- holding everything else constant?
    print(f"{'IF THIS FAINTS':20s} {'SCORE':>8s} {'DROP FROM BASELINE':>20s}")
    print("-" * 55)
    for i, mon in enumerate(state.player_team):
        hypothetical = state.clone()
        hypothetical.player_team[i].current_hp = 0
        score = evaluate(hypothetical, watch="player")
        print(f"{mon.display_name():20s} {score:8.3f} {baseline - score:20.3f}")

    print(
        "\nIf this worked as intended: fainting the most 'irreplaceable' "
        "Pokemon above should produce the biggest score drop, even though "
        "every Pokemon here is a single faint (same 'alive count' loss)."
    )


if __name__ == "__main__":
    main()
