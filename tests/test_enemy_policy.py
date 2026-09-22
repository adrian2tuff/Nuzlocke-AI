import random
import unittest

from engine.pokemon import Move, Pokemon, Species
from engine.state import BattleState
from search.enemy_ai import enemy_action_distribution, score_enemy_move


def make_mon(name, types, moves):
    species = Species(name, types, {
        "hp": 100, "atk": 100, "def": 100,
        "spa": 100, "spd": 100, "spe": 100,
    })
    return Pokemon(
        species, 50, "hardy",
        {s: 31 for s in ("hp", "atk", "def", "spa", "spd", "spe")},
        {s: 0 for s in ("hp", "atk", "def", "spa", "spd", "spe")},
        "", None, moves,
    )


def move(name, type_, category, power):
    return Move(name, type_, category, power, 100, 20)


class TestEnemyPolicy(unittest.TestCase):
    def test_null_prefers_ohko(self):
        player = make_mon("Player", ["grass"], [
            move("tackle", "normal", "physical", 40),
        ])
        enemy = make_mon("Enemy", ["fire"], [
            move("ember", "fire", "special", 40),
            move("blast", "fire", "special", 500),
        ])
        state = BattleState([player], [enemy])
        actions = enemy_action_distribution(state)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0][0], {"type": "move", "move_index": 1})

    def test_null_ties_are_uniform(self):
        player = make_mon("Player", ["grass"], [
            move("tackle", "normal", "physical", 40),
        ])
        enemy = make_mon("Enemy", ["fire"], [
            move("blast-a", "fire", "special", 500),
            move("blast-b", "fire", "special", 500),
        ])
        state = BattleState([player], [enemy])
        actions = enemy_action_distribution(state)
        self.assertEqual(len(actions), 2)
        self.assertEqual({a["move_index"] for a, _ in actions}, {0, 1})
        self.assertEqual([p for _, p in actions], [0.5, 0.5])

    def test_status_move_gets_generic_six(self):
        player = make_mon("Player", ["grass"], [
            move("tackle", "normal", "physical", 40),
        ])
        enemy = make_mon("Enemy", ["fire"], [
            move("toxic", "poison", "status", 0),
        ])
        state = BattleState([player], [enemy])
        action = {"type": "move", "move_index": 0}
        self.assertEqual(score_enemy_move(state, action), 6.0)

    def test_faster_ohko_gets_fourteen(self):
        player = make_mon("Player", ["grass"], [
            move("tackle", "normal", "physical", 40),
        ])
        enemy = make_mon("Enemy", ["fire"], [
            move("blast", "fire", "special", 500),
        ])
        state = BattleState([player], [enemy])
        action = {"type": "move", "move_index": 0}
        self.assertEqual(score_enemy_move(state, action), 14.0)

    def test_slower_ohko_gets_twelve(self):
        player = make_mon("Player", ["grass"], [
            move("tackle", "normal", "physical", 500),
        ])
        enemy = make_mon("Enemy", ["fire"], [
            move("blast", "fire", "special", 500),
        ])
        enemy.stat_stages["spe"] = -6
        state = BattleState([player], [enemy])
        action = {"type": "move", "move_index": 0}
        self.assertEqual(score_enemy_move(state, action), 12.0)

    def test_faster_two_hko_gets_eleven(self):
        player = make_mon("Player", ["grass"], [
            move("tackle", "normal", "physical", 40),
        ])
        enemy = make_mon("Enemy", ["fire"], [
            move("ember", "fire", "special", 40),
        ])
        player.current_hp = max(1, player.max_hp // 2 + 1)
        state = BattleState([player], [enemy])
        action = {"type": "move", "move_index": 0}
        self.assertEqual(score_enemy_move(state, action), 11.0)

    def test_high_damage_move_can_get_eight(self):
        player = make_mon("Player", ["grass"], [
            move("tackle", "normal", "physical", 40),
        ])
        enemy = make_mon("Enemy", ["normal"], [
            move("blast", "normal", "special", 80),
        ])
        state = BattleState([player], [enemy])
        action = {"type": "move", "move_index": 0}
        self.assertEqual(score_enemy_move(state, action, rng=random.Random(1)), 8.0)


    def test_offensive_setup_penalized_by_hard_counter(self):
        player = make_mon("Player", ["grass"], [move("haze", "ice", "status", 0)])
        enemy = make_mon("Enemy", ["fire"], [move("swords-dance", "normal", "status", 0)])
        enemy.moves[0].effect = "stat_change"
        enemy.moves[0].effect_data = {"stat": "atk", "stages": 2}
        state = BattleState([player], [enemy])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}), -20.0)

    def test_speed_setup_rejected_when_already_faster(self):
        player = make_mon("Player", ["grass"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["fire"], [move("agility", "psychic", "status", 0)])
        enemy.moves[0].effect = "stat_change"
        enemy.moves[0].effect_data = {"stat": "spe", "stages": 2}
        state = BattleState([player], [enemy])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}), -20.0)

    def test_defensive_setup_rewards_physical_only_player(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["fire"], [move("iron-defense", "steel", "status", 0)])
        enemy.moves[0].effect = "stat_change"
        enemy.moves[0].effect_data = {"stat": "def", "stages": 1}
        state = BattleState([player], [enemy])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}, rng=random.Random(1)), 1.0)

if __name__ == "__main__":
    unittest.main()
