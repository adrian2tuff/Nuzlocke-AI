import random
import unittest
from engine.pokemon import Move, Pokemon, Species
from engine.state import BattleState
from search.enemy_ai import is_support, switch_in_score, choose_switch_in

def make_mon(name, types, moves, ability=""):
    species = Species(name, types, {"hp":100,"atk":100,"def":100,"spa":100,"spd":100,"spe":100})
    return Pokemon(species, 50, "hardy",
        {s:31 for s in ("hp","atk","def","spa","spd","spe")},
        {s:0 for s in ("hp","atk","def","spa","spd","spe")},
        ability, None, moves)

def attack(name, type_, power):
    return Move(name, type_, "special", power, 100, 20)

class TestEnemyAI(unittest.TestCase):
    def test_support_classification(self):
        support = make_mon("Support", ["water"], [attack("surf","water",75), Move("toxic","poison","status",0,90,10)])
        self.assertTrue(is_support(support))
        attacker = make_mon("Attacker", ["water"], [attack("surf","water",75), attack("ice-beam","ice",90)])
        self.assertFalse(is_support(attacker))

    def test_utility_move_does_not_count_but_power_cap_applies(self):
        mon = make_mon("Utility", ["dark"], [attack("knock-off","dark",65), attack("foul-play","dark",95)])
        self.assertFalse(is_support(mon))
        mon.moves[1] = attack("foul-play","dark",75)
        self.assertTrue(is_support(mon))

    def test_imposter_is_never_support(self):
        self.assertFalse(is_support(make_mon("Ditto",["normal"],[],ability="imposter")))

    def test_fast_ohko_gets_five(self):
        player = make_mon("Player",["grass"],[attack("tackle","normal",40)])
        active = make_mon("Active",["water"],[attack("water-gun","water",40)])
        bench = make_mon("Bench",["fire"],[attack("flamethrower","fire",120)])
        player.current_hp = 20
        state = BattleState([player],[active,bench])
        self.assertEqual(switch_in_score(state,1,rng=random.Random(0)),5)

    def test_slow_ohko_gets_four(self):
        player = make_mon("Player",["grass"],[attack("tackle","normal",40)])
        active = make_mon("Active",["water"],[attack("water-gun","water",40)])
        bench = make_mon("Bench",["fire"],[attack("flamethrower","fire",120)])
        bench.stat_stages["spe"] = -6
        player.current_hp = 20
        state = BattleState([player],[active,bench])
        self.assertEqual(switch_in_score(state,1,rng=random.Random(0)),4)

    def test_faster_non_ohko_gets_one(self):
        player = make_mon("Player",["normal"],[attack("tackle","normal",40)])
        active = make_mon("Active",["water"],[attack("water-gun","water",40)])
        bench = make_mon("Bench",["fire"],[])
        state = BattleState([player],[active,bench])
        self.assertEqual(switch_in_score(state,1,rng=random.Random(0)),1)

    def test_slower_ohko_gets_minus_one(self):
        player = make_mon("Player",["normal"],[attack("tackle","normal",500)])
        active = make_mon("Active",["water"],[attack("water-gun","water",40)])
        bench = make_mon("Bench",["fire"],[attack("ember","fire",40)])
        bench.stat_stages["spe"] = -6
        player.current_hp = 20
        state = BattleState([player],[active,bench])
        self.assertEqual(switch_in_score(state,1,rng=random.Random(0)),-1)

    def test_choose_switch_uses_party_order_on_tie(self):
        player = make_mon("Player",["water"],[attack("tackle","normal",40)])
        active = make_mon("Active",["fire"],[attack("ember","fire",40)])
        first = make_mon("First",["normal"],[attack("tackle","normal",40)])
        second = make_mon("Second",["normal"],[attack("tackle","normal",40)])
        state = BattleState([player],[active,first,second])
        self.assertEqual(choose_switch_in(state,rng=random.Random(0)),1)

if __name__ == "__main__":
    unittest.main()
