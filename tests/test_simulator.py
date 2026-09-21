"""
Run with: python -m unittest tests.test_simulator -v
(from the nuzlocke_ai/ directory)

These tests exist specifically to catch the class of bug that just got
fixed: the simulator LOOKING correct in a demo while being wrong underneath.
Each test below maps to a concrete thing that was either broken or fragile:

  - test_determinism / test_different_seeds_can_differ
        step() is exact & reproducible -- the Phase 1 headline claim.
  - test_probabilities_sum_to_one
        enumerate_turn_outcomes() must be a real probability distribution.
  - test_switch_immunity_calculated_against_new_defender
        THE bug: second mover's move must be evaluated against the
        post-first-move state, not the pre-move state. Directly tests the
        "switch into a type immunity" scenario that exposed this.
  - test_switching_resets_outgoing_not_incoming_stats
        THE other bug: stat stages/volatile clear on the Pokemon LEAVING
        the field, not the one arriving.
  - test_secondary_effect_probability_is_not_forced_to_100_percent
        THE third bug: a 10%-chance secondary effect must land ~10% of the
        time under enumeration, not 100%.
  - test_hp_bounds / test_fainted_cannot_act / test_no_double_action_after_ko
        basic sanity invariants that should never be violated.
"""

import random
import unittest

from engine.mechanics import type_effectiveness
from environment.loader import DataStore
from engine.state import BattleState
from engine.simulator import step, enumerate_turn_outcomes, summarize_risk


def fresh_state() -> BattleState:
    store = DataStore()
    player_team = store.build_team("player_demo_team")
    enemy_team = store.build_team("rival_1")
    return BattleState(player_team=player_team, enemy_team=enemy_team)


class TestDeterminism(unittest.TestCase):
    def test_determinism(self):
        state = fresh_state()
        pa = {"type": "move", "move_index": 0}
        ea = {"type": "move", "move_index": 0}
        r1 = step(state, pa, ea, random.Random(2024))
        r2 = step(state, pa, ea, random.Random(2024))
        self.assertEqual(r1.player_mon.current_hp, r2.player_mon.current_hp)
        self.assertEqual(r1.enemy_mon.current_hp, r2.enemy_mon.current_hp)
        self.assertEqual(r1.log, r2.log)

    def test_different_seeds_can_differ(self):
        # Use the Rotom-Wash vs Nidoking matchup (149 HP into a real damage
        # spread), NOT Garchomp's Earthquake -- that one-shots this Nidoking
        # on every possible roll, so its outcome has zero variance to observe
        # regardless of seed, which would make this test meaningless.
        state = fresh_state()
        state.player_active = 1  # Rotom-Wash
        pa = {"type": "move", "move_index": 1}   # hydro-pump
        ea = {"type": "move", "move_index": 0}   # earthquake
        results = {
            step(state, pa, ea, random.Random(seed)).enemy_mon.current_hp
            for seed in range(30)
        }
        self.assertGreater(len(results), 1, "30 different seeds produced identical results -- RNG isn't being used")


class TestEnumeration(unittest.TestCase):
    def test_probabilities_sum_to_one(self):
        state = fresh_state()
        pa = {"type": "move", "move_index": 0}
        ea = {"type": "move", "move_index": 0}
        outcomes = enumerate_turn_outcomes(state, pa, ea)
        total = sum(o.probability for o in outcomes)
        self.assertAlmostEqual(total, 1.0, places=6)

    def test_probabilities_sum_to_one_with_bucketing(self):
        state = fresh_state()
        pa = {"type": "move", "move_index": 0}
        ea = {"type": "move", "move_index": 0}
        outcomes = enumerate_turn_outcomes(state, pa, ea, damage_buckets=3)
        total = sum(o.probability for o in outcomes)
        self.assertAlmostEqual(total, 1.0, places=6)

    def test_switch_immunity_calculated_against_new_defender(self):
        """
        The bug this catches: if you switch into a Ground-immune Pokemon,
        the opponent's Earthquake branches must be computed against THAT
        Pokemon, not whoever was active before the switch.
        """
        state = fresh_state()
        # Rotom-Wash (index 1) is active and NOT ground-immune.
        state.player_active = 1
        self.assertNotIn("flying", state.player_mon.species.types)

        switch_to_corviknight = {"type": "switch", "target_index": 2}  # Corviknight: flying/steel
        enemy_earthquake = {"type": "move", "move_index": 0}  # rival_1's nidoking, move 0 = earthquake

        outcomes = enumerate_turn_outcomes(state, switch_to_corviknight, enemy_earthquake)

        # After switching in, every outcome's active Pokemon should be
        # Corviknight, and Earthquake (Ground) is 0-effective against it
        # (Flying/Steel), so its HP must be untouched in every branch.
        for o in outcomes:
            mon = o.state.player_mon
            self.assertEqual(mon.species.name, "corviknight")
            self.assertEqual(mon.current_hp, mon.max_hp, "Earthquake should deal 0 damage to a Flying-type -- "
                                                            "if this fails, the bug (checking the pre-switch "
                                                            "defender) has come back.")

    def test_switching_resets_outgoing_not_incoming_stats(self):
        state = fresh_state()
        garchomp = state.player_team[0]
        rotom = state.player_team[1]
        garchomp.stat_stages["atk"] = 2  # simulate a prior Swords Dance
        rotom.stat_stages["atk"] = 0

        # Garchomp (active, index 0) switches out to Rotom (index 1).
        switch_action = {"type": "switch", "target_index": 1}
        enemy_action = {"type": "move", "move_index": 0}
        outcomes = enumerate_turn_outcomes(state, switch_action, enemy_action)

        for o in outcomes:
            resulting_garchomp = o.state.player_team[0]
            resulting_rotom = o.state.player_team[1]
            self.assertEqual(resulting_garchomp.stat_stages["atk"], 0,
                              "the outgoing Pokemon's boosted stat should clear when it leaves the field")
            self.assertEqual(resulting_rotom.stat_stages["atk"], 0,
                              "the incoming Pokemon shouldn't have gained a stat change from switching in")

    def test_secondary_effect_probability_is_not_forced_to_100_percent(self):
        """
        Thunderbolt has a 10% chance to paralyze. Enumerated branches should
        show enemy-paralyzed in ~10% of total probability mass, not 100%.
        """
        state = fresh_state()
        state.player_active = 1  # Rotom-Wash, has thunderbolt at move_index 2
        thunderbolt = {"type": "move", "move_index": 2}
        enemy_action = {"type": "move", "move_index": 0}

        outcomes = enumerate_turn_outcomes(state, thunderbolt, enemy_action)
        p_paralyzed = sum(o.probability for o in outcomes if o.state.enemy_mon.status == "paralysis")

        self.assertLess(p_paralyzed, 0.15, "paralysis probability mass is way above the move's 10% effect chance")
        self.assertGreater(p_paralyzed, 0.0, "paralysis should still be reachable in some branches")

    def test_full_paralysis_branches_with_correct_probability(self):
        """A paralyzed attacker should fail to act in ~25% of the total
        probability mass, and act normally in the other ~75%."""
        state = fresh_state()
        state.player_mon.status = "paralysis"
        pa = {"type": "move", "move_index": 0}  # garchomp earthquake
        ea = {"type": "move", "move_index": 0}

        outcomes = enumerate_turn_outcomes(state, pa, ea)
        # "Failed to act" shows up as: enemy took no damage from this move
        # this turn (garchomp's earthquake never landed).
        p_failed_to_act = sum(
            o.probability for o in outcomes
            if o.state.enemy_mon.current_hp == o.state.enemy_mon.max_hp
        )
        self.assertAlmostEqual(p_failed_to_act, 0.25, delta=0.05)

    def test_speed_tie_branches_fifty_fifty(self):
        """
        Build a scenario with genuinely equal speed and equal priority, and
        confirm enumerate_turn_outcomes actually branches over who goes
        first, 50/50, instead of always resolving one side first.
        """
        state = fresh_state()
        # Force an exact speed tie between the two actives.
        state.enemy_mon.stat_stages["spe"] = 0
        state.player_mon.stat_stages["spe"] = 0
        # Nudge enemy's effective speed to exactly match player's by
        # directly overwriting the cached base stat (test-only hack -- fine
        # since we're just constructing a controlled scenario).
        state.enemy_team[state.enemy_active]._stats["spe"] = state.player_mon.base_stat("spe")

        pa = {"type": "move", "move_index": 0}
        ea = {"type": "move", "move_index": 0}
        from engine.simulator import order_branches
        branches = order_branches(state, pa, ea)
        self.assertEqual(len(branches), 2, "a genuine speed tie should produce two order branches")
        weights = sorted(w for w, _ in branches)
        self.assertAlmostEqual(weights[0], 0.5)
        self.assertAlmostEqual(weights[1], 0.5)

    def test_step_can_resolve_either_side_first_on_a_tie(self):
        """step() should actually use the seeded rng to break speed ties,
        not silently always go player-first regardless of seed."""
        state = fresh_state()
        state.enemy_team[state.enemy_active]._stats["spe"] = state.player_mon.base_stat("spe")
        pa = {"type": "move", "move_index": 0}
        ea = {"type": "move", "move_index": 0}

        first_movers = set()
        for seed in range(40):
            result = step(state, pa, ea, random.Random(seed))
            # If player moved first and KO'd, enemy dealt 0 damage back;
            # if enemy moved first, player's HP changed. Use player's
            # resulting HP as a signal of who acted first.
            first_movers.add(result.player_mon.current_hp)
        self.assertGreater(len(first_movers), 1, "speed tie never resolved differently across 40 seeds")


class TestBattleMechanics(unittest.TestCase):
    def test_stealth_rock_sets_hazard_and_damages_switch_in(self):
        state = fresh_state()
        # Stealth Rock is not part of the demo team's normal moveset, so
        # add the real data-defined move to the active Garchomp for this
        # controlled mechanics test.
        store = DataStore()
        state.player_mon.moves.append(store.build_move("stealth-rock"))
        set_rocks = {"type": "move", "move_index": len(state.player_mon.moves) - 1}
        enemy_action = {"type": "move", "move_index": 0}
        outcomes = enumerate_turn_outcomes(state, set_rocks, enemy_action)
        self.assertTrue(all(o.state.field.hazards["player"]["stealth_rock"] for o in outcomes))

        switched = outcomes[0].state
        switch = {"type": "switch", "target_index": 1}
        # Use a switch for the opponent so this test isolates entry-hazard
        # damage rather than depending on ability mechanics (Rotom's
        # Levitate is not part of the current Phase 1 scope).
        enemy = {"type": "switch", "target_index": 1}
        switch_outcomes = enumerate_turn_outcomes(switched, switch, enemy)
        for o in switch_outcomes:
            incoming = o.state.player_mon
            expected = incoming.max_hp - max(1, int(incoming.max_hp * type_effectiveness("rock", incoming.species.types) / 8))
            self.assertEqual(incoming.current_hp, expected)

    def test_explosion_faints_user(self):
        state = fresh_state()
        state.player_active = 1
        from engine.pokemon import Move
        state.player_mon.moves.append(Move(name="explosion", type="normal", category="physical", power=250, accuracy=100, pp=5, effect="self_faint", effect_chance=100, effect_data={"target": "self"}))
        result = step(state, {"type": "move", "move_index": len(state.player_mon.moves)-1}, {"type": "move", "move_index": 0}, random.Random(1))
        self.assertTrue(result.player_mon.is_fainted)


class TestInvariants(unittest.TestCase):
    def test_hp_never_negative_or_over_max(self):
        state = fresh_state()
        pa = {"type": "move", "move_index": 0}
        ea = {"type": "move", "move_index": 0}
        for seed in range(50):
            result = step(state, pa, ea, random.Random(seed))
            for mon in result.player_team + result.enemy_team:
                self.assertGreaterEqual(mon.current_hp, 0)
                self.assertLessEqual(mon.current_hp, mon.max_hp)

    def test_fainted_pokemon_cannot_act_and_deals_no_damage(self):
        state = fresh_state()
        state.player_mon.current_hp = 0  # force a faint
        pa = {"type": "switch", "target_index": 1}  # forced switch, only legal action
        ea = {"type": "move", "move_index": 0}
        result = step(state, pa, ea, random.Random(1))
        # enemy's hp should be untouched by the fainted mon (it never got to act)
        self.assertEqual(result.enemy_mon.current_hp, result.enemy_mon.max_hp)

    def test_legal_actions_forces_switch_when_active_fainted(self):
        state = fresh_state()
        state.player_mon.current_hp = 0
        actions = state.legal_actions("player")
        self.assertTrue(all(a["type"] == "switch" for a in actions),
                         "a fainted active Pokemon should only be able to switch")


class TestRiskSummary(unittest.TestCase):
    def test_guaranteed_tier_means_zero_wipe_probability(self):
        state = fresh_state()
        pa = {"type": "move", "move_index": 0}
        ea = {"type": "move", "move_index": 0}
        outcomes = enumerate_turn_outcomes(state, pa, ea)
        risk = summarize_risk(outcomes)
        if risk["risk_tier"] == "guaranteed":
            self.assertEqual(risk["team_wipe_probability"], 0.0)

    def test_exact_flag_present(self):
        state = fresh_state()
        pa = {"type": "move", "move_index": 0}
        ea = {"type": "move", "move_index": 0}
        outcomes = enumerate_turn_outcomes(state, pa, ea, damage_buckets=None)
        risk = summarize_risk(outcomes, exact=True)
        self.assertTrue(risk["exact"])
        self.assertIn("unmodeled_randomness", risk)


if __name__ == "__main__":
    unittest.main()
