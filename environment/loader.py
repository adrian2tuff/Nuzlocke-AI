"""
Loads data/pokemon.json, data/moves.json, data/trainers.json into engine
objects. This is the file that makes "editing a trainer" a JSON edit, not a
code edit: nothing in engine/ or search/ ever needs to change when you add
or update a trainer, species, or move.
"""

from __future__ import annotations

import json
from pathlib import Path

from engine.pokemon import Species, Move, Pokemon

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

DEFAULT_IVS = {"hp": 31, "atk": 31, "def": 31, "spa": 31, "spd": 31, "spe": 31}
DEFAULT_EVS = {"hp": 0, "atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0}


def _load_json(name: str) -> dict:
    with open(DATA_DIR / name) as f:
        return json.load(f)


class DataStore:
    """Holds the parsed species/move tables and builds Pokemon on demand."""

    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        with open(data_dir / "pokemon.json") as f:
            raw_species = json.load(f)
        with open(data_dir / "moves.json") as f:
            raw_moves = json.load(f)
        with open(data_dir / "trainers.json") as f:
            self.raw_trainers = json.load(f)

        self.species: dict[str, Species] = {
            key: Species(name=key, types=v["types"], base_stats=v["base_stats"])
            for key, v in raw_species.items()
        }
        self.move_templates: dict[str, dict] = raw_moves

    def build_move(self, key: str) -> Move:
        """Always returns a FRESH Move instance (so PP tracking per-Pokemon
        doesn't leak between two Pokemon that both know the same move)."""
        if key not in self.move_templates:
            raise KeyError(f"Unknown move '{key}' -- add it to data/moves.json")
        t = self.move_templates[key]
        return Move(
            name=key,
            type=t["type"],
            category=t["category"],
            power=t.get("power", 0),
            accuracy=t.get("accuracy"),
            pp=t.get("pp", 10),
            priority=t.get("priority", 0),
            crit_ratio=t.get("crit_ratio", 0),
            effect=t.get("effect"),
            effect_chance=t.get("effect_chance", 100),
            effect_data=t.get("effect_data", {}),
        )

    def build_pokemon(self, spec: dict) -> Pokemon:
        species_key = spec["species"]
        if species_key not in self.species:
            raise KeyError(f"Unknown species '{species_key}' -- add it to data/pokemon.json")
        return Pokemon(
            species=self.species[species_key],
            level=spec["level"],
            nature=spec.get("nature", "hardy"),
            ivs={**DEFAULT_IVS, **spec.get("ivs", {})},
            evs={**DEFAULT_EVS, **spec.get("evs", {})},
            ability=spec.get("ability", ""),
            item=spec.get("item"),
            moves=[self.build_move(m) for m in spec["moves"]],
            nickname=spec.get("nickname"),
        )

    def build_team(self, trainer_key: str) -> list[Pokemon]:
        if trainer_key not in self.raw_trainers:
            raise KeyError(
                f"Unknown trainer '{trainer_key}' -- add it to data/trainers.json "
                f"(known: {list(self.raw_trainers)})"
            )
        return [self.build_pokemon(p) for p in self.raw_trainers[trainer_key]["team"]]
