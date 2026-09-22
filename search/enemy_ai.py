"""Null AI Support classification, switch scoring, and move selection."""
from __future__ import annotations
import math
import random
from engine.damage import damage_rolls
from engine.mechanics import type_effectiveness

SUPPORT_UTILITY_MOVES = {
    "fake-out", "feint", "upper-hand", "endeavor", "super-fang",
    "dragon-tail", "circle-throw", "knock-off", "foul-play", "future-sight",
    "bug-bite", "pollen-puff",
}
SPEED_CONTROL_MOVES = {
    "rock-tomb", "glaciate", "electroweb", "icy-wind", "string-shot",
    "scary-face", "syrup-bomb",
}
CRAMORANT_UTILITY_MOVES = {"surf", "dive"}

def _move_name(move):
    return move.name.lower().replace(" ", "-")

def _is_support_utility(move, pokemon):
    name = _move_name(move)
    if name in SUPPORT_UTILITY_MOVES or name in SPEED_CONTROL_MOVES:
        return True
    return pokemon.species.name.lower() == "cramorant" and name in CRAMORANT_UTILITY_MOVES

def is_support(pokemon) -> bool:
    """Null Support: at most one damaging move, no move above 75 BP, no Imposter."""
    if pokemon.ability.lower().replace(" ", "-") == "imposter":
        return False
    damaging = 0
    for move in pokemon.moves:
        if move.power > 75:
            return False
        if move.category != "status" and move.power > 0 and not _is_support_utility(move, pokemon):
            damaging += 1
            if damaging > 1:
                return False
    return True

def _max_damage(attacker, defender, move, field):
    if move.category == "status" or move.power <= 0:
        return 0
    return max(damage_rolls(attacker, defender, move, field))

def _best_damage(attacker, defender, field):
    return max((_max_damage(attacker, defender, move, field)
                for move in attacker.moves
                if move.category != "status" and move.power > 0), default=0)

def _ko_hits(attacker, defender, field):
    best = None
    for move in attacker.moves:
        if move.category == "status" or move.power <= 0:
            continue
        damage = _max_damage(attacker, defender, move, field)
        if damage <= 0:
            continue
        hits = math.ceil(defender.current_hp / damage)
        best = hits if best is None else min(best, hits)
    return best

def _entry_damage_fraction(state, side, candidate):
    hazards = state.field.hazards[side]
    fraction = 0.0
    if hazards["stealth_rock"]:
        fraction += 0.125 * type_effectiveness("rock", candidate.species.types)
    grounded = "flying" not in candidate.species.types and candidate.ability != "levitate"
    if grounded:
        fraction += {1: 1 / 8, 2: 1 / 6, 3: 1 / 4}.get(hazards["spikes"], 0.0)
    return min(1.0, fraction)

def switch_in_score(state, candidate_index, *, side="enemy", rng=None, immediate_damage=0):
    """Core Null post-KO switch score."""
    team = state.side_team(side)
    candidate = team[candidate_index]
    target = state.active_mon(state.other_side(side))
    if candidate.is_fainted:
        return -999
    if target.is_fainted:
        return 0

    candidate_damage = _best_damage(candidate, target, state.field)
    target_damage = _best_damage(target, candidate, state.field)
    ko_hits = _ko_hits(candidate, target, state.field)
    faster = candidate.effective_stat("spe") >= target.effective_stat("spe")
    candidate_ohko = candidate_damage >= target.current_hp
    target_ohko = target_damage >= candidate.current_hp

    if target_ohko and not faster:
        score = -1
    elif candidate_ohko and faster:
        score = 5
    elif candidate_ohko:
        score = 4
    elif ko_hits is not None and faster:
        score = 3
    elif ko_hits is not None:
        score = 2
    elif faster:
        score = 1
    else:
        score = 0

    if score >= 0 and is_support(candidate):
        roller = rng if rng is not None else random.Random()
        if roller.random() < 0.10:
            score += 2

    entry_fraction = _entry_damage_fraction(state, side, candidate)
    if immediate_damage > 0:
        entry_fraction = min(1.0, entry_fraction + immediate_damage / candidate.max_hp)

    if entry_fraction > 0 and not faster:
        incoming = _best_damage(target, candidate, state.field)
        remaining = max(0, candidate.current_hp - int(candidate.max_hp * entry_fraction))
        if incoming >= candidate.current_hp:
            score -= 2
        elif incoming > 0 and math.ceil(max(1, remaining) / incoming) <= 2:
            score -= 1
    return score

def choose_switch_in(state, *, side="enemy", rng=None):
    """Choose the highest-scoring living candidate; ties keep party order."""
    team = state.side_team(side)
    candidates = [i for i, mon in enumerate(team)
                  if i != state.active_index(side) and not mon.is_fainted]
    if not candidates:
        return None
    best = candidates[0]
    best_score = switch_in_score(state, best, side=side, rng=rng)
    for index in candidates[1:]:
        score = switch_in_score(state, index, side=side, rng=rng)
        if score > best_score:
            best, best_score = index, score
    return best

def _score_status_move(attacker, defender, move):\n    """Documented Null baseline for non-damaging moves.\n\n    Move-specific exceptions will be layered on separately once their exact\n    rules are encoded; the baseline is +6.\n    """\n    return 6.0\n\ndef score_enemy_move(state, action, *, side="enemy", rng=None):
    """Generic Null move score.

    The documented Null baseline is:
      non-attacking utility: +6
      high-damage move: +6, occasionally +8
      slow kill (2HKO): +9/+11
      fast kill (OHKO): +12/+14

    For the first implementation, speed determines the lower/higher kill tier.
    """
    if action["type"] == "switch":
        return float(switch_in_score(state, action["target_index"], side=side, rng=rng))

    mon = state.active_mon(side)
    opponent = state.active_mon(state.other_side(side))
    move = mon.moves[action["move_index"]]

    if move.category == "status" or move.power <= 0:
        return 6.0

    damage = _max_damage(mon, opponent, move, state.field)
    if damage <= 0:
        return 0.0

    faster = mon.effective_stat("spe") >= opponent.effective_stat("spe")

    if damage >= opponent.current_hp:
        return 14.0 if faster else 12.0

    hits = math.ceil(opponent.current_hp / damage)
    if hits == 2:
        return 11.0 if faster else 9.0

    # Generic high-damage baseline. "High damage" is represented by the
    # strongest available damaging move on the active Pokemon.
    best_damage = _best_damage(mon, opponent, state.field)
    if damage == best_damage:
        roller = rng if rng is not None else random.Random()
        return 8.0 if roller.random() < 0.25 else 6.0

    effectiveness = type_effectiveness(move.type, opponent.species.types)
    return 3.0 + 2.0 * effectiveness

def enemy_action_distribution(state, *, side="enemy", rng=None):
    """Return the highest-scoring Null actions with uniform tie probability."""
    actions = state.legal_actions(side)
    if not actions:
        return []
    scores = [score_enemy_move(state, action, side=side, rng=rng) for action in actions]
    best = max(scores)
    tied = [action for action, score in zip(actions, scores) if score == best]
    probability = 1.0 / len(tied)
    return [(action, probability) for action in tied]

def choose_enemy_action(state, *, side="enemy", rng=None):
    """Sample one action from the current Null AI policy."""
    distribution = enemy_action_distribution(state, side=side, rng=rng)
    if not distribution:
        return None
    roller = rng if rng is not None else random.Random()
    pick = roller.random()
    cumulative = 0.0
    for action, probability in distribution:
        cumulative += probability
        if pick < cumulative:
            return action
    return distribution[-1][0]
