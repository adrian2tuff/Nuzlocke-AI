import unittest

from engine.damage import damage_rolls
from engine.null_mechanics import crit_chance, paralysis_speed_multiplier, terrain_damage_multiplier, prevents_critical_hit, micle_accuracy_multiplier, should_consume_confusion_berry
from engine.pokemon import Move
from engine.state import BattleState
from environment.loader import DataStore


class TestNullMechanics(unittest.TestCase):
    def test_null_battle_uses_side_specific_pp(self):
        state = BattleState(
            player_team=DataStore().build_team("player_demo_team"),
            enemy_team=DataStore().build_team("rival_1"),
            ruleset="null",
        )
        self.assertTrue(all(mv.pp == 1 for p in state.player_team for mv in p.moves))
        self.assertTrue(all(mv.pp == 8 for p in state.enemy_team for mv in p.moves))

    def test_default_battle_keeps_data_pp(self):
        state = BattleState(
            player_team=DataStore().build_team("player_demo_team"),
            enemy_team=DataStore().build_team("rival_1"),
        )
        self.assertNotEqual(state.player_mon.moves[0].pp, 1)

    def test_null_micle_berry_accuracy_boost(self):
        state = BattleState(
            player_team=DataStore().build_team("player_demo_team"),
            enemy_team=DataStore().build_team("rival_1"),
            ruleset="null",
        )
        mon = state.player_mon
        mon.item = "micle-berry"
        mon.current_hp = mon.max_hp // 4
        self.assertEqual(micle_accuracy_multiplier(mon), 1.5)
        mon.current_hp = max(1, mon.max_hp // 4 + 1)
        self.assertEqual(micle_accuracy_multiplier(mon), 1.0)

    def test_null_confusion_berry_triggers_at_quarter_hp(self):
        state = BattleState(
            player_team=DataStore().build_team("player_demo_team"),
            enemy_team=DataStore().build_team("rival_1"),
            ruleset="null",
        )
        mon = state.player_mon
        mon.item = "figy-berry"
        mon.current_hp = mon.max_hp // 4
        self.assertTrue(should_consume_confusion_berry(mon))
        mon.current_hp = min(mon.max_hp, mon.max_hp // 4 + 1)
        self.assertFalse(should_consume_confusion_berry(mon))

    def test_null_confusion_causes_self_hit_or_failure(self):
        from engine.simulator import resolve_move
        state = BattleState(
            player_team=DataStore().build_team("player_demo_team"),
            enemy_team=DataStore().build_team("rival_1"),
            ruleset="null",
        )
        mon = state.player_mon
        mon.volatile.add("confusion")
        move = mon.moves[0]
        before = mon.current_hp
        log = []
        resolve_move(mon, state.enemy_mon, move, state.field, __import__("random").Random(1), log)
        self.assertLess(mon.current_hp, before)

    def test_null_berserk_gene_confusion_uses_60_power(self):
        from engine.simulator import resolve_move
        state = BattleState(
            player_team=DataStore().build_team("player_demo_team"),
            enemy_team=DataStore().build_team("rival_1"),
            ruleset="null",
        )
        mon = state.player_mon
        mon.ability = "berserk-gene"
        mon.volatile.add("confusion")
        before = mon.current_hp
        log = []
        resolve_move(mon, state.enemy_mon, mon.moves[0], state.field, __import__("random").Random(1), log)
        self.assertLess(mon.current_hp, before)

    def test_null_confusion_berry_heals_and_confuses(self):
        from engine.simulator import _apply_null_confusion_berry
        state = BattleState(
            player_team=DataStore().build_team("player_demo_team"),
            enemy_team=DataStore().build_team("rival_1"),
            ruleset="null",
        )
        mon = state.player_mon
        mon.item = "figy-berry"
        mon.current_hp = mon.max_hp // 4
        log = []
        _apply_null_confusion_berry(mon, log)
        self.assertGreater(mon.current_hp, mon.max_hp // 4)
        self.assertEqual(mon.item, None)
        self.assertIn("confusion", mon.volatile)

    def test_null_leaf_guard_and_magma_armor_prevent_crits(self):
        self.assertTrue(prevents_critical_hit("leaf-guard"))
        self.assertTrue(prevents_critical_hit("magma-armor"))
        self.assertFalse(prevents_critical_hit("intimidate"))

    def test_null_crit_rates(self):
        self.assertAlmostEqual(crit_chance("player", 0), 1 / 16)
        self.assertAlmostEqual(crit_chance("player", 1), 1 / 8)
        self.assertAlmostEqual(crit_chance("enemy", 0), 1 / 8)
        self.assertAlmostEqual(crit_chance("enemy", 1), 1 / 4)

    def test_null_crit_higher_stages_keep_gen9_rates(self):
        self.assertAlmostEqual(crit_chance("player", 2), 1 / 2)
        self.assertAlmostEqual(crit_chance("enemy", 2), 1 / 2)
        self.assertAlmostEqual(crit_chance("player", 3), 1.0)
        self.assertAlmostEqual(crit_chance("enemy", 3), 1.0)

    def test_null_paralysis_speed_multiplier(self):
        self.assertEqual(paralysis_speed_multiplier(), 0.25)

        state = BattleState(
            player_team=DataStore().build_team("player_demo_team"),
            enemy_team=DataStore().build_team("rival_1"),
        )
        mon = state.player_mon
        normal_speed = mon.effective_stat("spe")
        mon.status = "paralysis"
        self.assertAlmostEqual(mon.effective_stat("spe"), normal_speed * 0.25)

    def test_null_sleep_turns_reset_on_reentry(self):
        state = BattleState(
            player_team=DataStore().build_team("player_demo_team"),
            enemy_team=DataStore().build_team("rival_1"),
        )
        mon = state.player_mon
        mon.status = "sleep"
        mon.status_turns = 2

        from engine.simulator import _apply_switch
        log = []
        _apply_switch(state, "player", 1, log)

        incoming = state.player_mon
        incoming.status = "sleep"
        incoming.status_turns = 2
        _apply_switch(state, "player", 0, log)

        self.assertEqual(state.player_mon.status, "sleep")
        self.assertEqual(state.player_mon.status_turns, 0)

    def test_null_terrain_boost_is_50_percent(self):
        self.assertEqual(terrain_damage_multiplier(), 1.5)

        state = BattleState(
            player_team=DataStore().build_team("player_demo_team"),
            enemy_team=DataStore().build_team("rival_1"),
        )
        state.player_active = 1
        state.enemy_active = 1
        state.player_mon.ability = None
        state.player_mon.moves.append(
            Move("thunderbolt", "electric", "special", 90, 100, 15)
        )
        move = state.player_mon.moves[-1]

        neutral = max(damage_rolls(
            state.player_mon, state.enemy_mon, move, state.field
        ))
        state.field.terrain = "electric"
        boosted = max(damage_rolls(
            state.player_mon, state.enemy_mon, move, state.field
        ))

        self.assertGreater(boosted, neutral)
        self.assertAlmostEqual(boosted / neutral, 1.5, delta=0.05)


if __name__ == "__main__":
    unittest.main()
