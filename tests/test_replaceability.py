"""
Run with: python -m unittest tests.test_replaceability -v
(from the nuzlocke_ai/ directory)
"""

import unittest

from environment.loader import DataStore
from engine.state import BattleState
from search.replaceability import compute_replaceability, attacking_style
from search.evaluator import evaluate


def fresh_state() -> BattleState:
    store = DataStore()
    player_team = store.build_team("player_demo_team")
    enemy_team = store.build_team("rival_1")
    return BattleState(player_team=player_team, enemy_team=enemy_team)


class TestReplaceability(unittest.TestCase):
    def test_sole_special_attacker_is_least_replaceable(self):
        """In the demo team, Rotom-Wash is the only special attacker and
        the only status-inflicter -- it should score as the LEAST
        replaceable of the three, not tied with the others."""
        state = fresh_state()
        scores = compute_replaceability(state.player_team)
        rotom_idx = next(i for i, p in enumerate(state.player_team) if p.species.name == "rotom-wash")
        others = [s for i, s in scores.items() if i != rotom_idx]
        self.assertTrue(all(scores[rotom_idx] < o for o in others),
                         f"expected rotom to be strictly least replaceable, got {scores}")

    def test_fainted_pokemon_score_zero(self):
        state = fresh_state()
        state.player_team[0].current_hp = 0
        scores = compute_replaceability(state.player_team)
        self.assertEqual(scores[0], 0.0)

    def test_sole_survivor_is_fully_irreplaceable(self):
        state = fresh_state()
        state.player_team[0].current_hp = 0
        state.player_team[2].current_hp = 0
        scores = compute_replaceability(state.player_team)
        self.assertEqual(scores[1], 0.0)

    def test_scores_are_bounded(self):
        state = fresh_state()
        scores = compute_replaceability(state.player_team)
        for s in scores.values():
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 1.0)

    def test_adding_a_redundant_clone_increases_original_replaceability(self):
        """If a teammate with the same attacking style and move types shows
        up, the original Pokemon should become MORE replaceable, not less."""
        state = fresh_state()
        before = compute_replaceability(state.player_team)
        garchomp_idx = next(i for i, p in enumerate(state.player_team) if p.species.name == "garchomp")

        clone = state.player_team[garchomp_idx].clone()
        state.player_team.append(clone)

        after = compute_replaceability(state.player_team)
        self.assertGreaterEqual(after[garchomp_idx], before[garchomp_idx])

    def test_evaluator_penalizes_losing_irreplaceable_mon_more(self):
        """The actual point of Phase 3: losing the team's least-replaceable
        Pokemon should hurt evaluate() more than losing an equally-healthy
        but more-replaceable one, even though both are just 'one faint'."""
        state = fresh_state()
        baseline = evaluate(state, watch="player")

        rotom_idx = next(i for i, p in enumerate(state.player_team) if p.species.name == "rotom-wash")
        garchomp_idx = next(i for i, p in enumerate(state.player_team) if p.species.name == "garchomp")

        lose_rotom = state.clone()
        lose_rotom.player_team[rotom_idx].current_hp = 0
        drop_rotom = baseline - evaluate(lose_rotom, watch="player")

        lose_garchomp = state.clone()
        lose_garchomp.player_team[garchomp_idx].current_hp = 0
        drop_garchomp = baseline - evaluate(lose_garchomp, watch="player")

        self.assertGreater(drop_rotom, drop_garchomp,
                            "losing the least-replaceable Pokemon should hurt the score more")


if __name__ == "__main__":
    unittest.main()
