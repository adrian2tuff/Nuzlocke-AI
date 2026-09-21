"""
Data model for Pokemon and Moves. These are pure data + stat-calculation --
no battle logic lives here (that's damage.py / simulator.py). Keeping this
split means adding a new Pokemon or move is just adding data, never touching
engine code.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .mechanics import NATURES, NATURE_MULTIPLIER, clamp_stage


@dataclass
class Move:
    name: str
    type: str
    category: str          # "physical" | "special" | "status"
    power: int              # 0 for status moves
    accuracy: int | None    # None = never misses (e.g. Swift, status moves w/ no accuracy check)
    pp: int
    priority: int = 0
    crit_ratio: int = 0     # 0 = normal crit chance, 1 = high crit ratio move
    effect: str | None = None          # e.g. "burn", "paralyze", "stat_change", "recoil"
    effect_chance: int = 100           # percent chance secondary effect triggers
    effect_data: dict = field(default_factory=dict)  # e.g. {"stat": "atk", "stages": -1, "target": "self"}
    makes_contact: bool = True
    sound_based: bool = False
    hits_min: int = 1
    hits_max: int = 1


@dataclass
class Species:
    """Base-stat template for a species -- shared across every individual."""
    name: str
    types: list[str]
    base_stats: dict[str, int]   # hp, atk, def, spa, spd, spe


@dataclass
class Pokemon:
    species: Species
    level: int
    nature: str
    ivs: dict[str, int]              # 0-31 each
    evs: dict[str, int]              # 0-252 each, <=510 total (not enforced here)
    ability: str
    item: str | None
    moves: list[Move]

    current_hp: int = field(default=-1)      # -1 sentinel => "not yet initialized"
    status: str | None = None                 # major status: burn/poison/toxic/paralysis/sleep/freeze
    status_turns: int = 0                      # e.g. sleep counter, toxic counter
    volatile: set[str] = field(default_factory=set)   # confusion, flinch, etc.
    stat_stages: dict[str, int] = field(default_factory=lambda: {
        "atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0, "accuracy": 0, "evasion": 0,
    })
    nickname: str | None = None

    # -- derived, computed once and cached -------------------------------
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

        hp = ((2 * base["hp"] + iv["hp"] + ev["hp"] // 4) * lvl) // 100 + lvl + 10
        self._max_hp = hp

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
        """Stat value with nature/IV/EV applied, but WITHOUT stage/status modifiers."""
        if stat == "hp":
            return self._max_hp
        return self._stats[stat]

    def effective_stat(self, stat: str) -> float:
        """Stat value with stat-stages and status penalties applied. Used by damage calc."""
        from .mechanics import STAT_STAGE_MULTIPLIER, STATUS_ATK_MULTIPLIER, STATUS_SPEED_MULTIPLIER

        if stat == "hp":
            return self.max_hp

        value = self.base_stat(stat) * STAT_STAGE_MULTIPLIER[clamp_stage(self.stat_stages.get(stat, 0))]

        if stat == "atk" and self.status == "burn":
            value *= STATUS_ATK_MULTIPLIER["burn"]
        if stat == "spe" and self.status == "paralysis":
            value *= STATUS_SPEED_MULTIPLIER["paralysis"]

        return value

    @property
    def is_fainted(self) -> bool:
        return self.current_hp <= 0

    @property
    def hp_fraction(self) -> float:
        return max(0.0, self.current_hp / self.max_hp)

    def clone(self) -> "Pokemon":
        """Copy only battle-mutable data without invoking generic copy machinery."""
        clone = object.__new__(Pokemon)
        clone.__dict__ = self.__dict__.copy()

        # Move PP is mutable during simulation, so each hypothetical Pokemon
        # needs independent Move objects. The rest of Move is treated as
        # immutable battle data, so copying its __dict__ is much cheaper than
        # rebuilding the dataclass field-by-field.
        clone.moves = []
        for mv in self.moves:
            move_clone = object.__new__(Move)
            move_clone.__dict__ = mv.__dict__.copy()
            clone.moves.append(move_clone)

        clone.stat_stages = self.stat_stages.copy()
        clone.volatile = self.volatile.copy()
        return clone

    def display_name(self) -> str:
        return self.nickname or self.species.name
