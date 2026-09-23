"""Pokemon Null-specific overrides to the Generation 9 baseline.

Keep Null changes isolated here so the simulator does not accumulate
game-specific conditionals throughout otherwise standard mechanics.
"""

from __future__ import annotations

PLAYER = "player"
AI = "enemy"

# Null crit rates by crit stage. Stages not explicitly changed by Null use
# the normal Gen 9 rates.
GEN9_CRIT_RATES = {
    0: 1 / 24,
    1: 1 / 8,
    2: 1 / 2,
    3: 1.0,
}

NULL_CRIT_RATES = {
    PLAYER: {
        0: 1 / 16,
        1: 1 / 8,
    },
    AI: {
        0: 1 / 8,
        1: 1 / 4,
    },
}


def crit_chance(side: str, crit_stage: int) -> float:
    """Return Null's critical-hit chance for a side and crit stage."""
    if side in NULL_CRIT_RATES and crit_stage in NULL_CRIT_RATES[side]:
        return NULL_CRIT_RATES[side][crit_stage]
    return GEN9_CRIT_RATES[min(crit_stage, 3)]


def paralysis_speed_multiplier() -> float:
    """Null paralysis reduces Speed by 75%, leaving 25% of normal Speed."""
    return 0.25


def terrain_damage_multiplier() -> float:
    """Null matching-type terrain damage boost."""
    return 1.5
