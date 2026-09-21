"""
Shared game-mechanics constants: type chart, natures, stat-stage multipliers,
status definitions. Nothing here depends on the rest of the engine, so it's
safe to import from anywhere without circular-import issues.

This is deliberately a SUBSET of the real type chart / nature list, covering
enough types and natures for the Phase 1 demo roster. Extend TYPE_CHART and
NATURES as you add more Pokemon/moves -- nothing else in the engine needs to
change when you do.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Type effectiveness chart.
# TYPE_CHART[attacking_type][defending_type] = multiplier
# Any pair not listed defaults to 1.0 (see `type_effectiveness` below).
# ---------------------------------------------------------------------------
TYPE_CHART: dict[str, dict[str, float]] = {
    "normal":   {"rock": 0.5, "ghost": 0.0, "steel": 0.5},
    "fire":     {"fire": 0.5, "water": 0.5, "grass": 2.0, "ice": 2.0,
                 "bug": 2.0, "rock": 0.5, "dragon": 0.5, "steel": 2.0},
    "water":    {"fire": 2.0, "water": 0.5, "grass": 0.5, "ground": 2.0,
                 "rock": 2.0, "dragon": 0.5},
    "electric": {"water": 2.0, "electric": 0.5, "grass": 0.5, "ground": 0.0,
                 "flying": 2.0, "dragon": 0.5},
    "grass":    {"fire": 0.5, "water": 2.0, "grass": 0.5, "poison": 0.5,
                 "ground": 2.0, "flying": 0.5, "bug": 0.5, "rock": 2.0,
                 "dragon": 0.5, "steel": 0.5},
    "ice":      {"fire": 0.5, "water": 0.5, "grass": 2.0, "ice": 0.5,
                 "ground": 2.0, "flying": 2.0, "dragon": 2.0, "steel": 0.5},
    "fighting": {"normal": 2.0, "ice": 2.0, "poison": 0.5, "flying": 0.5,
                 "psychic": 0.5, "bug": 0.5, "rock": 2.0, "ghost": 0.0,
                 "dark": 2.0, "steel": 2.0, "fairy": 0.5},
    "poison":   {"grass": 2.0, "poison": 0.5, "ground": 0.5, "rock": 0.5,
                 "ghost": 0.5, "steel": 0.0, "fairy": 2.0},
    "ground":   {"fire": 2.0, "electric": 2.0, "grass": 0.5, "poison": 2.0,
                 "flying": 0.0, "bug": 0.5, "rock": 2.0, "steel": 2.0},
    "flying":   {"electric": 0.5, "grass": 2.0, "fighting": 2.0, "bug": 2.0,
                 "rock": 0.5, "steel": 0.5},
    "psychic":  {"fighting": 2.0, "poison": 2.0, "psychic": 0.5, "dark": 0.0,
                 "steel": 0.5},
    "bug":      {"fire": 0.5, "grass": 2.0, "fighting": 0.5, "poison": 0.5,
                 "flying": 0.5, "psychic": 2.0, "ghost": 0.5, "dark": 2.0,
                 "steel": 0.5, "fairy": 0.5},
    "rock":     {"fire": 2.0, "ice": 2.0, "fighting": 0.5, "ground": 0.5,
                 "flying": 2.0, "bug": 2.0, "steel": 0.5},
    "ghost":    {"normal": 0.0, "psychic": 2.0, "ghost": 2.0, "dark": 0.5},
    "dragon":   {"dragon": 2.0, "steel": 0.5, "fairy": 0.0},
    "dark":     {"fighting": 0.5, "psychic": 2.0, "ghost": 2.0, "dark": 0.5,
                 "fairy": 0.5},
    "steel":    {"fire": 0.5, "water": 0.5, "electric": 0.5, "ice": 2.0,
                 "rock": 2.0, "steel": 0.5, "fairy": 2.0},
    "fairy":    {"fire": 0.5, "fighting": 2.0, "poison": 0.5, "dragon": 2.0,
                 "dark": 2.0, "steel": 0.5},
}


def type_effectiveness(attack_type: str, defend_types: list[str]) -> float:
    """Multiply the chart entries across all of the defender's types."""
    mult = 1.0
    chart = TYPE_CHART.get(attack_type, {})
    for dt in defend_types:
        mult *= chart.get(dt, 1.0)
    return mult


# ---------------------------------------------------------------------------
# Natures: (boosted_stat, lowered_stat). Neutral natures map to (None, None).
# ---------------------------------------------------------------------------
NATURES: dict[str, tuple[str | None, str | None]] = {
    "hardy": (None, None), "docile": (None, None), "serious": (None, None),
    "bashful": (None, None), "quirky": (None, None),
    "adamant": ("atk", "spa"), "lonely": ("atk", "def"),
    "brave": ("atk", "spe"), "naughty": ("atk", "spd"),
    "bold": ("def", "atk"), "impish": ("def", "spa"),
    "relaxed": ("def", "spe"), "lax": ("def", "spd"),
    "modest": ("spa", "atk"), "mild": ("spa", "def"),
    "quiet": ("spa", "spe"), "rash": ("spa", "spd"),
    "calm": ("spd", "atk"), "gentle": ("spd", "def"),
    "sassy": ("spd", "spe"), "careful": ("spd", "spa"),
    "timid": ("spe", "atk"), "hasty": ("spe", "def"),
    "jolly": ("spe", "spa"), "naive": ("spe", "spd"),
}

NATURE_MULTIPLIER = {"boost": 1.1, "hinder": 0.9, "neutral": 1.0}


# ---------------------------------------------------------------------------
# Stat stages run from -6 to +6. Standard main-series multipliers.
# ---------------------------------------------------------------------------
STAT_STAGE_MULTIPLIER = {
    -6: 2 / 8, -5: 2 / 7, -4: 2 / 6, -3: 2 / 5, -2: 2 / 4, -1: 2 / 3,
    0: 2 / 2,
    1: 3 / 2, 2: 4 / 2, 3: 5 / 2, 4: 6 / 2, 5: 7 / 2, 6: 8 / 2,
}

# Accuracy/evasion stages use a different table.
ACCURACY_STAGE_MULTIPLIER = {
    -6: 3 / 9, -5: 3 / 8, -4: 3 / 7, -3: 3 / 6, -2: 3 / 5, -1: 3 / 4,
    0: 3 / 3,
    1: 4 / 3, 2: 5 / 3, 3: 6 / 3, 4: 7 / 3, 5: 8 / 3, 6: 9 / 3,
}


def clamp_stage(stage: int) -> int:
    return max(-6, min(6, stage))


# ---------------------------------------------------------------------------
# Status conditions. "major" statuses are mutually exclusive (a Pokemon can
# only have one at a time); volatile statuses (confusion etc.) stack with them.
# ---------------------------------------------------------------------------
MAJOR_STATUSES = {"burn", "poison", "toxic", "paralysis", "sleep", "freeze", None}

STATUS_DAMAGE_FRACTION = {
    "burn": 1 / 16,
    "poison": 1 / 8,
    # toxic damage escalates; handled specially in mechanics logic
}

STATUS_ATK_MULTIPLIER = {"burn": 0.5}     # physical attack halved when burned (Gen>=6 rule)
STATUS_SPEED_MULTIPLIER = {"paralysis": 0.5}
