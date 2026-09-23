"""Game-data registry for species, moves, and trainer templates.

The Dex is deliberately kept separate from battle mechanics. It turns the
JSON data under data/ into the engine's Species/Move/Pokemon objects.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .pokemon import Move, Pokemon, Species


class DexError(ValueError):
    """Raised when Dex data is missing or malformed."""


class Dex:
    """Read-only registry for the game's structured data files."""

    def __init__(self, data_dir: str | Path | None = None):
        if data_dir is None:
            data_dir = Path(__file__).resolve().parent.parent / "data"
        self.data_dir = Path(data_dir)
        self._pokemon_data = self._load_json("pokemon.json")
        self._move_data = self._load_json("moves.json")
        self._trainer_data = self._load_json("trainers.json")
        self._validate()

    def _load_json(self, filename: str) -> dict[str, Any]:
        path = self.data_dir / filename
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError as exc:
            raise DexError(f"Missing Dex file: {path}") from exc
        except json.JSONDecodeError as exc:
            raise DexError(f"Invalid JSON in {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise DexError(f"{path} must contain a JSON object")
        return data

    @staticmethod
    def _key(name: str) -> str:
        return name.strip().lower().replace(" ", "-").replace("_", "-")

    def _validate(self) -> None:
        required_stats = {"hp", "atk", "def", "spa", "spd", "spe"}
        for name, data in self._pokemon_data.items():
            if not isinstance(data, dict):
                raise DexError(f"Pokemon '{name}' must be an object")
            if not isinstance(data.get("types"), list) or not data["types"]:
                raise DexError(f"Pokemon '{name}' needs at least one type")
            stats = data.get("base_stats")
            if not isinstance(stats, dict) or set(stats) != required_stats:
                raise DexError(f"Pokemon '{name}' must define exactly {sorted(required_stats)}")

        for name, data in self._move_data.items():
            if not isinstance(data, dict):
                raise DexError(f"Move '{name}' must be an object")
            for field in ("type", "category", "power", "accuracy", "pp"):
                if field not in data:
                    raise DexError(f"Move '{name}' is missing '{field}'")

        for trainer, data in self._trainer_data.items():
            if not isinstance(data, dict) or not isinstance(data.get("team"), list):
                raise DexError(f"Trainer '{trainer}' needs a team list")

    def species(self, name: str) -> Species:
        key = self._key(name)
        try:
            data = self._pokemon_data[key]
        except KeyError as exc:
            raise DexError(f"Unknown Pokemon species: {name}") from exc
        return Species(key, list(data["types"]), dict(data["base_stats"]))

    def move(self, name: str) -> Move:
        key = self._key(name)
        try:
            data = self._move_data[key]
        except KeyError as exc:
            raise DexError(f"Unknown move: {name}") from exc
        return Move(
            name=key,
            type=data["type"],
            category=data["category"],
            power=data["power"],
            accuracy=data["accuracy"],
            pp=data["pp"],
            priority=data.get("priority", 0),
            crit_ratio=data.get("crit_ratio", 0),
            effect=data.get("effect"),
            effect_chance=data.get("effect_chance", 100),
            effect_data=dict(data.get("effect_data", {})),
            makes_contact=data.get("makes_contact", True),
            sound_based=data.get("sound_based", False),
            hits_min=data.get("hits_min", 1),
            hits_max=data.get("hits_max", 1),
        )

    def pokemon(
        self,
        species: str,
        level: int,
        nature: str,
        ivs: dict[str, int],
        evs: dict[str, int],
        ability: str,
        item: str | None,
        moves: list[str],
        *,
        nickname: str | None = None,
    ) -> Pokemon:
        return Pokemon(
            species=self.species(species),
            level=level,
            nature=nature,
            ivs=dict(ivs),
            evs=dict(evs),
            ability=ability,
            item=item,
            moves=[self.move(name) for name in moves],
            nickname=nickname,
        )

    def trainer(self, name: str) -> list[Pokemon]:
        key = self._key(name)
        try:
            data = self._trainer_data[key]
        except KeyError:
            # Trainer IDs in the source data may use underscores.
            try:
                data = self._trainer_data[name.strip().lower()]
            except KeyError as exc:
                raise DexError(f"Unknown trainer: {name}") from exc
        return [
            self.pokemon(
                species=entry["species"],
                level=entry["level"],
                nature=entry["nature"],
                ivs=entry["ivs"],
                evs=entry["evs"],
                ability=entry["ability"],
                item=entry.get("item"),
                moves=entry["moves"],
            )
            for entry in data["team"]
        ]

    def species_names(self) -> list[str]:
        return list(self._pokemon_data)

    def move_names(self) -> list[str]:
        return list(self._move_data)

    def trainer_names(self) -> list[str]:
        return list(self._trainer_data)
