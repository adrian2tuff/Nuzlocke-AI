"""
Damage calculation. The key design point for your "near-riskless lines"
goal: `damage_rolls()` returns the FULL set of 16 possible damage values
(the game's actual random-multiplier spread: 0.85..1.00 in 16 steps),
each with equal probability. Nothing here collapses to a single "expected
damage" number -- that collapsing is something the caller (search/risk
code) chooses to do, not something the engine decides for you.
"""

from __future__ import annotations

from .mechanics import type_effectiveness
from .pokemon import Pokemon, Move

# The 16 damage-roll multipliers the mainline games use (85..100, /100).
DAMAGE_ROLL_MULTIPLIERS = [(85 + i) / 100 for i in range(16)]

STAB_MULTIPLIER = 1.5
CRIT_MULTIPLIER = 1.5  # Gen 6+ value


def base_power(move: Move, attacker: Pokemon, defender: Pokemon, field: dict) -> int:
    """Hook point for power-modifying effects (weather boosts, abilities, etc.).
    Kept trivial for Phase 1 -- extend as you add mechanics."""
    return move.power


def is_stab(move: Move, attacker: Pokemon) -> bool:
    return move.type in attacker.species.types


def damage_rolls(
    attacker: Pokemon,
    defender: Pokemon,
    move: Move,
    field: dict | None = None,
    is_crit: bool = False,
) -> list[int]:
    """
    Return the 16 possible integer damage values for this attacker/defender/move,
    each equally likely (assuming the move hits and, if relevant, the crit roll
    already resolved to `is_crit`). Status moves and 0-power moves return [0].
    """
    field = field or {}

    if move.category == "status" or move.power == 0:
        return [0]

    atk_stat = "atk" if move.category == "physical" else "spa"
    def_stat = "def" if move.category == "physical" else "spd"

    atk = attacker.effective_stat(atk_stat)
    if attacker.ability == "solar-power" and atk_stat == "spa" and field.weather == "sun":
        atk *= 1.5
    # Crits ignore the attacker's negative stage / defender's positive stage (Gen 6+ rule),
    # simplified here to: crit uses the higher of (stage-adjusted, base) stat on each side.
    if is_crit:
        atk = max(atk, attacker.base_stat(atk_stat))
    defense = defender.effective_stat(def_stat)
    if is_crit:
        defense = min(defense, defender.base_stat(def_stat))

    power = base_power(move, attacker, defender, field)
    level = attacker.level

    base = (((2 * level / 5 + 2) * power * atk / max(defense, 1)) / 50) + 2

    modifier = 1.0
    sheer_force = (
        attacker.ability == "sheer-force"
        and move.category != "status"
        and move.effect is not None
        and move.effect_chance > 0
    )
    if sheer_force:
        modifier *= 1.3
    if is_stab(move, attacker):
        modifier *= STAB_MULTIPLIER
    if is_crit:
        modifier *= CRIT_MULTIPLIER

    weather = field.weather if hasattr(field, "weather") else field.get("weather")
    if weather == "rain":
        if move.type == "water":
            modifier *= 1.5
        elif move.type == "fire":
            modifier *= 0.5
    elif weather == "sun":
        if move.type == "fire":
            modifier *= 1.5
        elif move.type == "water":
            modifier *= 0.5

    terrain = field.terrain if hasattr(field, "terrain") else field.get("terrain")
    grounded = "flying" not in attacker.species.types and attacker.ability != "levitate"
    if grounded:
        if terrain == "electric" and move.type == "electric":
            modifier *= 1.3
        elif terrain == "grassy" and move.type == "grass":
            modifier *= 1.3
        elif terrain == "psychic" and move.type == "psychic":
            modifier *= 1.3

    if attacker.item == "life-orb":
        modifier *= 1.3

    type_mult = type_effectiveness(move.type, defender.species.types)
    modifier *= type_mult

    rolls = []
    for rand in DAMAGE_ROLL_MULTIPLIERS:
        dmg = int(base * modifier * rand)
        dmg = max(1, dmg) if type_mult > 0 and power > 0 else 0
        rolls.append(dmg)
    return rolls


def type_effectiveness_label(move: Move, defender: Pokemon) -> str:
    mult = type_effectiveness(move.type, defender.species.types)
    if mult == 0:
        return "immune"
    if mult < 1:
        return "not very effective"
    if mult > 1:
        return "super effective"
    return "neutral"
