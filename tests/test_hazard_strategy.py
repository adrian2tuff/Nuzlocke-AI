import unittest

from engine.pokemon import Move, Pokemon, Species
from engine.simulator import resolve_move
from engine.state import BattleState
from search.evaluator import evaluate_breakdown


def make_mon(name, types, moves):
    species = Species(
        name=name,
        types=types,
        base_stats={"hp": 100, "atk": 100, "def": 100, "spa": 100, "spd": 100, "spe": 100},
    )
    return Pokemon(
        species=species,
        level=50,
        nature="hardy",
        ivs={"hp": 31, "atk": 31, "def": 31, "spa": 31, "spd": 31, "spe": 31},
        evs={"hp": 0, "atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0},
        ability="",
        item=None,
        moves=moves,
    )


class TestHazardStrategy(unittest.TestCase):
    def test_hazard_removal_clears_all_own_hazards(self):
        rapid_spin = Move(
            name="rapid-spin",
            type="normal",
            category="physical",
            power=50,
            accuracy=100,
            pp=40,
            effect="hazard_removal",
            effect_chance=100,
            effect_data={"target": "field"},
        )
        attacker = make_mon("Spinner", ["normal"], [rapid_spin])
        defender = make_mon(
            "Target",
            ["normal"],
            [Move("tackle", "normal", "physical", 40, 100, 35)],
        )

        from engine.state import Field
        field = Field()
        field.hazards["player"] = {
            "stealth_rock": True,
            "spikes": 3,
            "toxic_spikes": 2,
        }

        log = []
        resolve_move(
            attacker,
            defender,
            rapid_spin,
            field,
            __import__("random").Random(0),
            log,
            attacker_side="player",
        )

        self.assertFalse(field.hazards["player"]["stealth_rock"])
        self.assertEqual(field.hazards["player"]["spikes"], 0)
        self.assertEqual(field.hazards["player"]["toxic_spikes"], 0)

    def test_evaluator_values_clearing_future_switching_burden(self):
        rapid_spin = Move(
            name="rapid-spin",
            type="normal",
            category="physical",
            power=50,
            accuracy=100,
            pp=40,
            effect="hazard_removal",
            effect_chance=100,
            effect_data={"target": "field"},
        )
        player_active = make_mon("Spinner", ["normal"], [rapid_spin])
        player_bench = make_mon("Bench", ["fire"], [rapid_spin])
        enemy_active = make_mon("Enemy", ["normal"], [rapid_spin])
        enemy_bench = make_mon("EnemyBench", ["normal"], [rapid_spin])

        state = BattleState(
            player_team=[player_active, player_bench],
            enemy_team=[enemy_active, enemy_bench],
        )
        state.field.hazards["player"]["stealth_rock"] = True
        state.field.hazards["player"]["spikes"] = 2

        burdened = evaluate_breakdown(state).total
        state.field.hazards["player"] = {
            "stealth_rock": False,
            "spikes": 0,
            "toxic_spikes": 0,
        }
        cleared = evaluate_breakdown(state).total

        self.assertGreater(cleared, burdened)


if __name__ == "__main__":
    unittest.main()
