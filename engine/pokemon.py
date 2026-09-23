"""
Data model for Pokemon and Moves. These are pure data + stat-calculation --
no battle logic lives here (that's damage.py / simulator.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .mechanics import NATURES, NATURE_MULTIPLIER, clamp_stage\nfrom .null_mechanics import paralysis_speed_multiplier


@dataclass
class Move:
    name: str
    type: str
    category: str
    power: int
    accuracy: int | None
    pp: int
    priority: int = 0
    crit_ratio: int = 0
    effect: str | None = None
    effect_chance: int = 100
    effect_data: dict = field(default_factory=dict)
    makes_contact: bool = True
    sound_based: bool = False
    hits_min: int = 1
    hits_max: int = 1


@dataclass
class Species:
    name: str
    types: list[str]
    base_stats: dict[str, int]


@dataclass
class Pokemon:
    species: Species
    level: int
    nature: str
    ivs: dict[str, int]
    evs: dict[str, int]
    ability: str
    item: str | None
    moves: list[Move]

    current_hp: int = field(default=-1)
    status: str | None = None
    status_turns: int = 0
    volatile: set[str] = field(default_factory=set)
    protect_streak: int = 0
    last_damage_taken: int = 0
    last_damage_category: str | None = None
    choice_lock: int | None = None
    stat_stages: dict[str, int] = field(default_factory=lambda: {
        "atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0, "accuracy": 0, "evasion": 0,
    })
    nickname: str | None = None

    _max_hp: int | None = field(default=None, repr=False)
    _stats: dict[str, int] | None = field(default=None, repr=False)

    def __post_init__(self):
        self._compute_stats()
        if self.current_hp == -1:
            self.current_hp = self._max_hp

    def _compute_stats(self) -> None:
        base = self.species.base_stats
        iv = self.ivs
        ev = self.evs
        lvl = self.level
        self._max_hp = ((2 * base["hp"] + iv["hp"] + ev["hp"] // 4) * lvl) // 100 + lvl + 10

        boosted, lowered = NATURES.get(self.nature, (None, None))
        stats = {}
        for stat in ("atk", "def", "spa", "spd", "spe"):
            raw = ((2 * base[stat] + iv[stat] + ev[stat] // 4) * lvl) // 100 + 5
            if stat == boosted:
                raw = int(raw * NATURE_MULTIPLIER["boost"])
            elif stat == lowered:
                raw = int(raw * NATURE_MULTIPLIER["hinder"])
            stats[stat] = raw
        self._stats = stats

    @property
    def max_hp(self) -> int:
        return self._max_hp

    def base_stat(self, stat: str) -> int:
        if stat == "hp":
            return self._max_hp
        return self._stats[stat]

    def effective_stat(self, stat: str) -> float:
        from .mechanics import STAT_STAGE_MULTIPLIER, STATUS_ATK_MULTIPLIER, STATUS_SPEED_MULTIPLIER
        if stat == "hp":
            return self.max_hp
        value = self.base_stat(stat) * STAT_STAGE_MULTIPLIER[clamp_stage(self.stat_stages.get(stat, 0))]
        if stat == "atk" and self.status == "burn":
            value *= STATUS_ATK_MULTIPLIER["burn"]
        if stat == "spe" and self.status == "paralysis":
            value *= STATUS_SPEED_MULTIPLIER["paralysis"]
        if self.item == "choice-band" and stat == "atk":
            value *= 1.5
        elif self.item == "choice-specs" and stat == "spa":
            value *= 1.5
        elif self.item == "choice-scarf" and stat == "spe":
            value *= 1.5
        return value

    @property
    def is_fainted(self) -> bool:
        return self.current_hp <= 0

    @property
    def hp_fraction(self) -> float:
        return max(0.0, self.current_hp / self.max_hp)

    def clone(self) -> "Pokemon":
        clone = object.__new__(Pokemon)
        clone.__dict__ = self.__dict__.copy()
        clone.moves = []
        for mv in self.moves:
            move_clone = object.__new__(Move)
            move_clone.__dict__ = mv.__dict__.copy()
            clone.moves.append(move_clone)
        clone.stat_stages = self.stat_stages.copy()
        clone.volatile = self.volatile.copy()
        clone.protect_streak = self.protect_streak
        return clone

    def display_name(self) -> str:
        return self.nickname or self.species.name
