"""
Run with:  python demo.py

Demonstrates the Phase-1 milestone in three parts:

1. Loading trainers from JSON (so "update Brock's team" = edit a file).
2. `step()` being exact & reproducible for a given RNG seed.
3. `enumerate_turn_outcomes()` giving the FULL probability distribution over
   a turn, which is what lets you tell a "guaranteed" line from a "risky" one.
"""

import random

from environment.loader import DataStore
from engine.state import BattleState
from engine.simulator import step, enumerate_turn_outcomes, summarize_risk


def make_battle() -> BattleState:
    store = DataStore()
    player_team = store.build_team("player_demo_team")
    enemy_team = store.build_team("rival_1")
    return BattleState(player_team=player_team, enemy_team=enemy_team)


def part1_reproducibility():
    print("=" * 70)
    print("PART 1 -- step() is exact and reproducible for a seeded RNG")
    print("=" * 70)

    state = make_battle()
    print(state.describe_active())
    print(f"Your legal actions: {state.legal_actions('player')}")

    player_action = {"type": "move", "move_index": 0}   # Garchomp Earthquake
    enemy_action = {"type": "move", "move_index": 0}     # Nidoking Earthquake

    result_a = step(state, player_action, enemy_action, random.Random(42))
    result_b = step(state, player_action, enemy_action, random.Random(42))
    result_c = step(state, player_action, enemy_action, random.Random(999))

    print("\nSeed 42, run A:", result_a.describe_active())
    print("Seed 42, run B:", result_b.describe_active())
    print("Seed 999, run C:", result_c.describe_active())
    print(
        "\nSame seed => identical result:",
        result_a.player_mon.current_hp == result_b.player_mon.current_hp
        and result_a.enemy_mon.current_hp == result_b.enemy_mon.current_hp,
    )
    print("\nFull log from run A:")
    for line in result_a.log:
        print(" ", line)


def part2_risk_analysis():
    print("\n" + "=" * 70)
    print("PART 2 -- enumerate_turn_outcomes(): exact risk, not a guess")
    print("=" * 70)

    state = make_battle()
    # Put a faster, frailer mon in to make the risk question non-trivial:
    # Rotom-Wash (in slot 2) vs enemy Nidoking's Earthquake.
    state.player_active = 1  # Rotom-Wash
    print(state.describe_active())

    # Question: if we Volt Switch out while Nidoking Earthquakes us, how
    # risky is that turn, exactly?
    player_action = {"type": "move", "move_index": 0}   # Rotom-Wash Volt Switch
    enemy_action = {"type": "move", "move_index": 0}     # Nidoking Earthquake

    outcomes = enumerate_turn_outcomes(state, player_action, enemy_action)
    risk = summarize_risk(outcomes, watch="player")

    print(f"\nEnumerated {risk['branch_count']} exact branches for this turn.")
    print(f"Your active Pokemon faints in {risk['active_faint_probability']*100:.2f}% of branches")
    print(f"Your team is wiped in {risk['team_wipe_probability']*100:.2f}% of branches")
    print(f"Risk tier: {risk['risk_tier'].upper()}")

    # Compare against staying in and attacking with Thunderbolt instead:
    player_action_2 = {"type": "move", "move_index": 2}  # Thunderbolt
    outcomes_2 = enumerate_turn_outcomes(state, player_action_2, enemy_action)
    risk_2 = summarize_risk(outcomes_2, watch="player")
    print(f"\nAlternative line (Thunderbolt instead of Volt Switch):")
    print(f"  faint prob: {risk_2['active_faint_probability']*100:.2f}%  "
          f"tier: {risk_2['risk_tier'].upper()}")

    print("\nA few individual branches (probability, description):")
    for o in sorted(outcomes, key=lambda o: -o.probability)[:5]:
        print(f"  p={o.probability:.4f}  {o.description}")


if __name__ == "__main__":
    part1_reproducibility()
    part2_risk_analysis()
