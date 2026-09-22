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


    def test_defense_curl_rollout_bonus_is_one(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["normal"], [
            move("defense-curl", "normal", "status", 0),
            move("rollout", "rock", "physical", 30),
        ])
        enemy.moves[0].effect = "stat_change"
        enemy.moves[0].effect_data = {"stat": "def", "stages": 1}
        state = BattleState([player], [enemy])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}, rng=random.Random(1)), 1.0)

    def test_stockpile_spit_up_bonus_is_one(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["normal"], [
            move("stockpile", "normal", "status", 0),
            move("spit-up", "normal", "special", 100),
        ])
        enemy.moves[0].effect = "stat_change"
        enemy.moves[0].effect_data = {"stat": "def", "stages": 1}
        state = BattleState([player], [enemy])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}, rng=random.Random(1)), 1.0)

    def test_charge_rewards_any_electric_attack(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["electric"], [
            move("charge", "electric", "status", 0),
            move("wild-charge", "electric", "physical", 90),
        ])
        enemy.moves[0].effect = "stat_change"
        enemy.moves[0].effect_data = {"stat": "spa", "stages": 1}
        state = BattleState([player], [enemy])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}), 1.0)


    def test_sleep_scores_one_when_target_can_sleep(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["normal"], [move("spore", "grass", "status", 0)])
        enemy.moves[0].effect = "sleep"
        state = BattleState([player], [enemy])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}), 1.0)

    def test_sleep_gets_synergy_bonus(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["normal"], [
            move("spore", "grass", "status", 0),
            move("dream-eater", "psychic", "special", 100),
        ])
        enemy.moves[0].effect = "sleep"
        state = BattleState([player], [enemy])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}), 2.0)

    def test_poison_scores_one_against_passive_target(self):
        player = make_mon("Player", ["normal"], [move("toxic", "poison", "status", 0)])
        enemy = make_mon("Enemy", ["normal"], [move("poison", "poison", "status", 0)])
        enemy.moves[0].effect = "poison"
        state = BattleState([player], [enemy])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}), 1.0)

    def test_paralysis_rewards_slow_ai(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("normal-enemy", ["normal"], [move("thunder-wave", "electric", "status", 0)])
        enemy.moves[0].effect = "paralysis"
        enemy.stat_stages["spe"] = -6
        state = BattleState([player], [enemy])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}), 2.0)

    def test_burn_rewards_physical_player(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["fire"], [move("will-o-wisp", "fire", "status", 0)])
        enemy.moves[0].effect = "burn"
        state = BattleState([player], [enemy])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}), 2.0)

    def test_confusion_scores_one(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["psychic"], [move("confuse-ray", "ghost", "status", 0)])
        enemy.moves[0].effect = "confusion"
        state = BattleState([player], [enemy])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}), 1.0)

    def test_status_is_ignored_when_max_roll_guarantees_ko(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["fire"], [
            move("will-o-wisp", "fire", "status", 0),
            move("blast", "fire", "special", 500),
        ])
        enemy.moves[0].effect = "burn"
        state = BattleState([player], [enemy])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}), 0.0)


    def test_stealth_rock_gets_first_turn_bonus(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["rock"], [move("stealth-rock", "rock", "status", 0)])
        enemy.moves[0].effect = "stealth_rock"
        state = BattleState([player, make_mon("Bench", ["normal"], [])], [enemy])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}, rng=random.Random(1)), 2.0)

    def test_hazard_is_penalized_when_player_is_last_mon(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["rock"], [move("stealth-rock", "rock", "status", 0)])
        enemy.moves[0].effect = "stealth_rock"
        state = BattleState([player], [enemy])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}), -10.0)

    def test_duplicate_stealth_rock_is_useless(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["rock"], [move("stealth-rock", "rock", "status", 0)])
        enemy.moves[0].effect = "stealth_rock"
        state = BattleState([player, make_mon("Bench", ["normal"], [])], [enemy])
        state.field.hazards["player"]["stealth_rock"] = True
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}), -20.0)

    def test_spikes_stop_at_three_layers(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["ground"], [move("spikes", "ground", "status", 0)])
        enemy.moves[0].effect = "spikes"
        state = BattleState([player, make_mon("Bench", ["normal"], [])], [enemy])
        state.field.hazards["player"]["spikes"] = 3
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}), -20.0)

    def test_toxic_spikes_second_layer_gets_penalty(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["poison"], [move("toxic-spikes", "poison", "status", 0)])
        enemy.moves[0].effect = "toxic_spikes"
        state = BattleState([player, make_mon("Bench", ["normal"], [])], [enemy])
        state.field.hazards["player"]["toxic_spikes"] = 1
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}, rng=random.Random(1)), 1.0)

    def test_sticky_web_gets_stronger_first_turn_bonus(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["bug"], [move("sticky-web", "bug", "status", 0)])
        enemy.moves[0].effect = "sticky_web"
        state = BattleState([player, make_mon("Bench", ["normal"], [])], [enemy])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}, rng=random.Random(1)), 3.0)

    def test_hazard_alive_ratio_bonus_can_apply(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["rock"], [move("stealth-rock", "rock", "status", 0)])
        enemy.moves[0].effect = "stealth_rock"
        enemy2 = make_mon("Bench", ["normal"], [])
        enemy2.current_hp = 0
        state = BattleState([player, make_mon("Bench", ["normal"], [])], [enemy, enemy2])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}, rng=random.Random(1)), 2.0)

    def test_stone_axe_counts_as_stealth_rock(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["rock"], [move("stone-axe", "rock", "physical", 65)])
        enemy.moves[0].effect = "stealth_rock"
        state = BattleState([player, make_mon("Bench", ["normal"], [])], [enemy])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}, rng=random.Random(1)), 2.0)

    def test_ceaseless_edge_counts_as_spikes(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["dark"], [move("ceaseless-edge", "dark", "physical", 65)])
        enemy.moves[0].effect = "spikes"
        state = BattleState([player, make_mon("Bench", ["normal"], [])], [enemy])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}, rng=random.Random(1)), 2.0)


    def test_protect_is_penalized_for_incapacitated_ai(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["normal"], [move("protect", "normal", "status", 0)])
        enemy.status = "sleep"
        state = BattleState([player], [enemy, make_mon("Bench", ["normal"], [])])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}), -20.0)

    def test_protect_is_penalized_when_about_to_faint_to_burn(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["normal"], [move("protect", "normal", "status", 0)])
        enemy.status = "burn"
        enemy.current_hp = 1
        state = BattleState([player], [enemy, make_mon("Bench", ["normal"], [])])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}), -10.0)

    def test_protect_second_consecutive_use_is_penalized(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["normal"], [move("protect", "normal", "status", 0)])
        enemy.protect_streak = 2
        state = BattleState([player], [enemy, make_mon("Bench", ["normal"], [])])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}), -10.0)

    def test_protect_previous_use_can_be_penalized(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["normal"], [move("protect", "normal", "status", 0)])
        enemy.protect_streak = 1
        state = BattleState([player], [enemy, make_mon("Bench", ["normal"], [])])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}, rng=random.Random(1)), -10.0)

    def test_protect_has_neutral_baseline(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["normal"], [move("protect", "normal", "status", 0)])
        state = BattleState([player], [enemy, make_mon("Bench", ["normal"], [])])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}), 0.0)

    def test_endure_rewards_pinch_or_endure_combo(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 500)])
        enemy = make_mon("Enemy", ["normal"], [move("endure", "normal", "status", 0), move("flail", "normal", "physical", 1)])
        enemy.item = "salac-berry"
        state = BattleState([player], [enemy, make_mon("Bench", ["normal"], [])])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}), 2.0)

    def test_endure_speed_boost_baton_pass_gets_two(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 500)])
        enemy = make_mon("Enemy", ["normal"], [move("endure", "normal", "status", 0), move("baton-pass", "normal", "status", 0)])
        enemy.ability = "speed-boost"
        state = BattleState([player], [enemy, make_mon("Bench", ["normal"], [])])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}), 2.0)

    def test_endure_can_be_neutral_when_no_reason_to_use(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["normal"], [move("endure", "normal", "status", 0)])
        state = BattleState([player], [enemy, make_mon("Bench", ["normal"], [])])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}, rng=random.Random(1)), 0.0)

    def test_explosion_prefers_low_hp(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["normal"], [move("explosion", "normal", "physical", 250)])
        enemy.current_hp = 5
        state = BattleState([player], [enemy, make_mon("Bench", ["normal"], [])])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}), 10.0)

    def test_explosion_is_bad_if_last_mon(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["normal"], [move("explosion", "normal", "physical", 250)])
        state = BattleState([player, make_mon("Bench", ["normal"], [])], [enemy])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}), -10.0)

    def test_explosion_last_mon_can_be_used_if_player_is_also_last(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["normal"], [move("explosion", "normal", "physical", 250)])
        state = BattleState([player], [enemy])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}), -1.0)

    def test_memento_is_useless_when_both_stats_cannot_drop(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["dark"], [move("memento", "dark", "status", 0)])
        enemy.moves[0].effect = "stat_change"
        enemy.moves[0].effect_data = {"stat": "atk", "stages": -2}
        player.stat_stages["atk"] = -6
        player.stat_stages["spa"] = -6
        state = BattleState([player, make_mon("Bench", ["normal"], [])], [enemy])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}), -20.0)

    def test_final_gambit_rewards_fast_equal_hp(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["normal"], [move("final-gambit", "fighting", "special", 0)])
        state = BattleState([player], [enemy])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}), -1.0)

    def test_final_gambit_gets_seven_when_fast_and_will_die(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 500)])
        enemy = make_mon("Enemy", ["normal"], [move("final-gambit", "fighting", "special", 0)])
        enemy.current_hp = 50
        state = BattleState([player], [enemy, make_mon("Bench", ["normal"], [])])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}), 7.0)

if __name__ == "__main__":
    unittest.main()


    def test_sticky_web_is_set_on_field(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["bug"], [move("sticky-web", "bug", "status", 0)])
        enemy.moves[0].effect = "sticky_web"
        state = BattleState([player], [enemy])
        from engine.simulator import step
        next_state = step(state, {"type": "move", "move_index": 0}, {"type": "move", "move_index": 0}, rng=random.Random(1))
        self.assertTrue(next_state.field.hazards["player"]["sticky_web"])

    def test_sticky_web_lowers_grounded_switch_in_speed(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["bug"], [move("sticky-web", "bug", "status", 0)])
        enemy.moves[0].effect = "sticky_web"
        state = BattleState([player, make_mon("Bench", ["normal"], [])], [enemy])
        state.field.hazards["player"]["sticky_web"] = True
        from engine.simulator import step
        next_state = step(state, {"type": "switch", "target_index": 1}, {"type": "move", "move_index": 0}, rng=random.Random(1))
        self.assertEqual(next_state.player_mon.stat_stages["spe"], -1)

    def test_sticky_web_does_not_affect_flying_switch_in(self):
        player = make_mon("Player", ["flying"], [move("tackle", "normal", "physical", 40)])
        bench = make_mon("Bench", ["flying"], [])
        enemy = make_mon("Enemy", ["bug"], [move("sticky-web", "bug", "status", 0)])
        enemy.moves[0].effect = "sticky_web"
        state = BattleState([player, bench], [enemy])
        state.field.hazards["player"]["sticky_web"] = True
        from engine.simulator import step
        next_state = step(state, {"type": "switch", "target_index": 1}, {"type": "move", "move_index": 0}, rng=random.Random(1))
        self.assertEqual(next_state.player_mon.stat_stages["spe"], 0)

    def test_hazard_removal_clears_sticky_web(self):
        player = make_mon("Player", ["normal"], [move("rapid-spin", "normal", "physical", 50)])
        enemy = make_mon("Enemy", ["normal"], [move("tackle", "normal", "physical", 40)])
        player.moves[0].effect = "hazard_removal"
        state = BattleState([player], [enemy])
        state.field.hazards["player"]["sticky_web"] = True
        from engine.simulator import step
        next_state = step(state, {"type": "move", "move_index": 0}, {"type": "move", "move_index": 0}, rng=random.Random(1))
        self.assertFalse(next_state.field.hazards["player"]["sticky_web"])


    def test_tailwind_gets_bonus_when_enemy_is_slower(self):
        player = make_mon("Fast", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Slow", ["flying"], [move("tailwind", "flying", "status", 0)])
        enemy.moves[0].effect = "tailwind"
        enemy.moves[0].effect_data = {"turns": 4}
        enemy.stat_stages["spe"] = -6
        state = BattleState([player], [enemy])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}), 3.0)

    def test_trick_room_gets_bonus_when_enemy_is_faster(self):
        player = make_mon("Fast", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Slow", ["psychic"], [move("trick-room", "psychic", "status", 0)])
        enemy.moves[0].effect = "trick_room"
        enemy.moves[0].effect_data = {"turns": 5}
        state = BattleState([player], [enemy])
        self.assertEqual(score_enemy_move(state, {"type": "move", "move_index": 0}), 4.0)

    def test_trick_room_reverses_turn_order(self):
        player = make_mon("Fast", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Slow", ["psychic"], [move("trick-room", "psychic", "status", 0)])
        enemy.moves[0].effect = "trick_room"
        state = BattleState([player], [enemy])
        state.field.trick_room_turns = 3
        from engine.simulator import turn_order
        self.assertEqual(turn_order(state, {"type": "move", "move_index": 0}, {"type": "move", "move_index": 0}), ["enemy", "player"])

    def test_tailwind_doubles_side_speed(self):
        player = make_mon("Player", ["normal"], [move("tackle", "normal", "physical", 40)])
        enemy = make_mon("Enemy", ["flying"], [move("tailwind", "flying", "status", 0)])
        enemy.moves[0].effect = "tailwind"
        state = BattleState([player], [enemy])
        state.field.tailwind_turns["enemy"] = 4
        from engine.simulator import turn_order
        self.assertEqual(turn_order(state, {"type": "move", "move_index": 0}, {"type": "move", "move_index": 0}), ["enemy", "player"])
