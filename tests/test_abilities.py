import unittest

from engine.damage import damage_rolls
from engine.simulator import step, enumerate_turn_outcomes
from environment.loader import DataStore
from engine.state import BattleState


def fresh_state():
    store = DataStore()
    return BattleState(
        player_team=store.build_team("player_demo_team"),
        enemy_team=store.build_team("rival_1"),
    )


class TestAbilities(unittest.TestCase):
    def test_sheer_force_boosts_secondary_move_and_suppresses_effect(self):
        state = fresh_state()
        state.player_active = 0
        state.enemy_active = 0
        attacker = state.player_mon
        defender = state.enemy_mon
        move = DataStore().build_move("iron-head")

        attacker.ability = None
        normal = max(damage_rolls(attacker, defender, move, state.field))

        attacker.ability = "sheer-force"
        boosted = max(damage_rolls(attacker, defender, move, state.field))
        self.assertGreater(boosted, normal)

        attacker.moves = [move]
        outcomes = enumerate_turn_outcomes(
            state,
            {"type": "move", "move_index": 0},
            {"type": "switch", "target_index": 1},
        )
        self.assertTrue(all("flinched and couldn't move" not in o.description for o in outcomes))

    def test_solar_power_boosts_special_damage_in_sun(self):
        state = fresh_state()
        state.player_active = 1
        state.enemy_active = 1
        attacker = state.player_mon
        defender = state.enemy_mon
        move = DataStore().build_move("hydro-pump")

        attacker.ability = None
        neutral = max(damage_rolls(attacker, defender, move, state.field))

        attacker.ability = "solar-power"
        sunny = state.clone()
        sunny.field.weather = "sun"
        boosted = max(damage_rolls(sunny.player_mon, sunny.enemy_mon, move, sunny.field))
        self.assertGreater(boosted, neutral)

    def test_solar_power_causes_end_of_turn_damage_in_sun(self):
        state = fresh_state()
        state.player_active = 1
        state.player_mon.ability = "solar-power"
        state.field.weather = "sun"
        before = state.player_mon.current_hp

        result = step(
            state,
            {"type": "move", "move_index": 3},
            {"type": "switch", "target_index": 1},
            __import__("random").Random(1),
        )
        self.assertEqual(
            result.player_mon.current_hp,
            before - max(1, result.player_mon.max_hp // 8),
        )

    def test_pressure_consumes_two_pp(self):
        state = fresh_state()
        state.player_active = 1
        state.enemy_active = 0
        state.enemy_mon.ability = "pressure"
        before = state.player_mon.moves[1].pp

        result = step(
            state,
            {"type": "move", "move_index": 1},
            {"type": "switch", "target_index": 1},
            __import__("random").Random(1),
        )
        self.assertEqual(result.player_mon.moves[1].pp, before - 2)

    def test_life_orb_recoil_happens_once_for_multi_hit_move(self):
        state = fresh_state()
        state.player_active = 0
        state.enemy_active = 0
        attacker = state.player_mon
        attacker.item = "life-orb"
        attacker.ability = None
        attacker.moves = [DataStore().build_move("rock-blast")]
        before = attacker.current_hp

        outcomes = enumerate_turn_outcomes(
            state,
            {"type": "move", "move_index": 0},
            {"type": "switch", "target_index": 1},
            damage_buckets=1,
        )
        self.assertTrue(outcomes)
        expected_recoil = max(1, attacker.max_hp // 10)
        for outcome in outcomes:
            self.assertEqual(
                outcome.state.player_mon.current_hp,
                before - expected_recoil,
            )


if __name__ == "__main__":
    unittest.main()
