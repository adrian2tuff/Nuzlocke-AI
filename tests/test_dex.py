import unittest

from engine.dex import Dex, DexError


class TestDex(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dex = Dex()

    def test_loads_builtin_data(self):
        self.assertIn("garchomp", self.dex.species_names())
        self.assertIn("earthquake", self.dex.move_names())
        self.assertIn("rival_1", self.dex.trainer_names())

    def test_species_becomes_engine_species(self):
        species = self.dex.species("Garchomp")
        self.assertEqual(species.name, "garchomp")
        self.assertEqual(species.types, ["dragon", "ground"])
        self.assertEqual(species.base_stats["atk"], 130)

    def test_move_becomes_engine_move(self):
        move = self.dex.move("Earthquake")
        self.assertEqual(move.name, "earthquake")
        self.assertEqual(move.power, 100)
        self.assertEqual(move.category, "physical")

    def test_pokemon_factory_builds_real_engine_pokemon(self):
        stats = ("hp", "atk", "def", "spa", "spd", "spe")
        mon = self.dex.pokemon(
            "Garchomp", 50, "jolly",
            {s: 31 for s in stats},
            {s: 0 for s in stats},
            "rough-skin", "life-orb",
            ["Earthquake", "Dragon Claw"],
        )
        self.assertEqual(mon.species.name, "garchomp")
        self.assertEqual([m.name for m in mon.moves], ["earthquake", "dragon-claw"])
        self.assertGreater(mon.max_hp, 0)

    def test_trainer_factory(self):
        team = self.dex.trainer("rival_1")
        self.assertEqual(len(team), 2)
        self.assertEqual(team[0].species.name, "nidoking")
        self.assertEqual(team[1].moves[0].name, "fire-blast")

    def test_unknown_entry_is_clear_error(self):
        with self.assertRaises(DexError):
            self.dex.species("missingno")


if __name__ == "__main__":
    unittest.main()
