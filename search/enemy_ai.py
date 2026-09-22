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

def _score_self_destruct_move(state, attacker, defender, move, side, rng):
    name = _move_name(move)
    if name not in {"explosion", "self-destruct", "misty-explosion", "memento", "final-gambit"}:
        return None

    if name == "memento":
        if (defender.stat_stages.get("atk", 0) <= -6
                and defender.stat_stages.get("spa", 0) <= -6):
            return -20.0

    ai_last = _is_last_mon(state, side)
    player_last = _is_last_mon(state, state.other_side(side))
    if ai_last:
        return -10.0 if not player_last else -1.0

    if name == "final-gambit":
        faster = attacker.effective_stat("spe") >= defender.effective_stat("spe")
        if faster and attacker.current_hp >= defender.current_hp:
            return 8.0
        if faster and _player_kill_hits(defender, attacker, state.field) == 1:
            return 7.0
        return 6.0

    if attacker.current_hp < attacker.max_hp * 0.10:
        return 10.0
    if attacker.current_hp < attacker.max_hp * 0.33:
        return 8.0 if _random_chance(rng, 0.70) else 0.0
    if attacker.current_hp < attacker.max_hp * 0.66:
        return 7.0 if _random_chance(rng, 0.50) else 0.0
    return 7.0 if _random_chance(rng, 0.05) else 0.0


RECOVERY_MOVES = {
    "recover", "roost", "soft-boiled", "slack-off", "shore-up",
    "moonlight", "morning-sun", "synthesis", "rest", "strength-sap",
    "pain-split",
}

def _score_recovery_move(state, attacker, defender, move, rng):
    name = _move_name(move)
    if name not in RECOVERY_MOVES:
        return None

    if name == "pain-split":
        gain = (defender.current_hp - attacker.current_hp) // 2
        return 1.0 if gain > attacker.max_hp * 0.30 else -1.0

    gain = attacker.max_hp - attacker.current_hp
    if gain <= 0:
        return -1.0

    if name == "rest":
        if attacker.status == "toxic":
            return -1.0
        heal = attacker.max_hp
    else:
        heal = max(1, attacker.max_hp // 2)
        if name in {"moonlight", "morning-sun", "synthesis"} and state.field.weather in {"sun", "harsh-sun"}:
            heal = max(heal, (attacker.max_hp * 2) // 3)

    after_hp = min(attacker.max_hp, attacker.current_hp + heal)
    player_can_ko_now = _player_kill_hits(defender, attacker, state.field) == 1
    player_can_ko_after = _best_damage(defender, attacker, state.field) >= after_hp

    if attacker.effective_stat("spe") >= defender.effective_stat("spe"):
        if player_can_ko_now and not player_can_ko_after:
            return 1.0
        if not player_can_ko_now:
            if attacker.current_hp < attacker.max_hp * 0.40:
                return 1.0
            if attacker.current_hp < attacker.max_hp * 0.66:
                return 1.0 if _random_chance(rng, 0.50) else 0.0
        return -1.0

    if attacker.current_hp < attacker.max_hp * 0.50:
        return 1.0
    if attacker.current_hp < attacker.max_hp * 0.70:
        return 1.0 if _random_chance(rng, 0.75) else 0.0
    return -1.0

PIVOT_MOVES = {"u-turn", "volt-switch", "flip-turn", "parting-shot"}

def _has_phazing_move(pokemon):
    return _has_move_named(pokemon, {"roar", "whirlwind", "dragon-tail", "circle-throw"})

def _score_pivot_move(state, attacker, defender, move, rng):
    name = _move_name(move)
    if name == "baton-pass":
        if _has_phazing_move(defender):
            has_boost = any(v > 0 for v in attacker.stat_stages.values())
            if not has_boost:
                return -20.0
        return -1.0 if _random_chance(rng, 0.25) else 0.0

    if name not in PIVOT_MOVES:
        return None

    if attacker.ability.lower().replace(" ", "-") == "zero-to-hero" and name == "flip-turn":
        return 12.0

    if _has_phazing_move(defender):
        base = 6.0
        return -1.0

    hits = _player_kill_hits(attacker, defender, state.field)
    if hits > 3:
        return 6.0

    # Parting Shot starts at the ordinary utility baseline.
    if name == "parting-shot":
        return 6.0

    return 6.0

PROTECTION_MOVES = {"protect", "detect", "baneful-bunker", "kings-shield", "silk-trap", "obstruct", "spiky-shield", "burning-bulwark", "endure"}

def _end_turn_damage_estimate(mon):
    if mon.status == "toxic":
        return max(1, (mon.max_hp * (mon.status_turns + 1)) // 16)
    if mon.status == "poison":
        return max(1, mon.max_hp // 8)
    if mon.status == "burn":
        return max(1, mon.max_hp // 16)
    return 0

def _score_protection_move(state, attacker, defender, move, rng):
    name = _move_name(move)
    if name not in PROTECTION_MOVES:
        return None
    if _is_incapacitated(attacker):
        return -20.0
    if attacker.current_hp <= _end_turn_damage_estimate(attacker):
        return -10.0
    if attacker.protect_streak >= 2:
        return -10.0
    if attacker.protect_streak >= 1 and _random_chance(rng, 0.50):
        return -10.0

    if name == "endure":
        player_can_faint = _player_kill_hits(defender, attacker, state.field) == 1
        if player_can_faint:
            bonus = 0.0
            if attacker.item in {"salac-berry", "liechi-berry", "petaya-berry", "ganlon-berry", "apicot-berry", "starf-berry"} or _has_move_named(attacker, {"flail", "reversal", "endeavor", "rage-fist"}):
                bonus += 2.0
            if attacker.ability.lower().replace(" ", "-") == "speed-boost":
                bonus += 1.0
                if _has_move_named(attacker, {"baton-pass"}):
                    bonus += 1.0
            return bonus if bonus else (-1.0 if _random_chance(rng, 0.50) else 0.0)
        return -1.0 if _random_chance(rng, 0.50) else 0.0
    return 0.0

def _score_status_move(state, attacker, defender, move, rng=None):
    """Null scoring for sleep, poison, paralysis, burn/frostbite, and confusion."""
    name = _move_name(move)

    if _best_damage(attacker, defender, state.field) >= defender.current_hp:
        return 0.0

    target_can_status = defender.status is None

    # A move with no modeled effect is still generic utility. Tests and
    # partially-populated move data may identify Toxic by name without
    # attaching the poison effect.
    if name == "toxic" and move.effect is None:
        return 6.0

    if move.effect == "sleep" or name in {"dark-void", "hypnosis", "sing", "sleep-powder", "spore", "yawn"}:
        if not target_can_status:
            return -20.0
        score = 1.0
        if _has_move_named(attacker, {"dream-eater", "nightmare", "snore", "sleep-talk"}):
            score += 1.0
        if name == "dark-void" and _random_chance(rng, 0.80):
            score += 2.0
        return score

    if move.effect in {"poison", "toxic"}:
        if not target_can_status or defender.current_hp <= defender.max_hp * 0.20:
            return -20.0
        score = 0.0
        if not any(m.category != "status" and m.power > 0 for m in defender.moves):
            score += 1.0
        if _has_move_named(defender, {"protect"}):
            score += 1.0
        if _has_move_named(attacker, {"venoshock", "hex", "infernal-parade", "venom-drench"}) or attacker.ability.lower().replace(" ", "-") == "merciless":
            score += 1.0
        return score

    if move.effect == "paralysis" or name in {"thunder-wave", "glare", "nuzzle", "stun-spore"}:
        if not target_can_status:
            return -20.0
        score = 2.0 if attacker.effective_stat("spe") < defender.effective_stat("spe") else 1.0
        if _has_move_named(attacker, {"hex", "infernal-parade"}) or _has_move_named(attacker, {"fake-out", "bite", "air-slash", "iron-head", "rock-slide"}):
            score += 2.0
        if defender.status in {"confusion", "infatuation"} or "confusion" in defender.volatile:
            score += 2.0
        return score

    if move.effect in {"burn", "frostbite"} or name in {"will-o-wisp", "scald", "flame-wheel", "ice-burn", "freezing-glare"}:
        if not target_can_status:
            return -20.0
        score = 1.0
        physical = _player_has_attack_category(defender, "physical")
        special = _player_has_attack_category(defender, "special")
        if move.effect == "frostbite":
            if special:
                score += 1.0
        elif physical:
            score += 1.0
        if _has_move_named(attacker, {"hex", "infernal-parade"}):
            score += 1.0
        return score

    if move.effect == "confusion" or name in {"confuse-ray", "supersonic", "teeter-dance", "swagger", "flatter"}:
        if "confusion" in defender.volatile:
            return -20.0
        score = 1.0
        if defender.status in {"paralysis", "infatuation"}:
            score += 1.0
        if attacker.ability.lower().replace(" ", "-") == "serene-grace" and _has_move_named(attacker, {"air-slash", "iron-head", "rock-slide"}):
            score += 1.0
        return score

    return 6.0

SETUP_HARD_COUNTER_MOVES = {"haze", "clear-smog", "freezy-frost", "topsy-turvy"}
PHASING_MOVES = {"roar", "whirlwind", "dragon-tail", "circle-throw"}
OFFENSIVE_SETUP_MOVES = {"tidy-up", "dragon-dance", "shift-gear", "howl", "meditate", "sharpen", "swords-dance", "growth", "nasty-plot", "tail-glow", "hone-claws", "work-up", "power-up-punch", "mystical-power", "torch-song", "contrary-leaf-storm", "contrary-overheat", "contrary-draco-meteor"}
DEFENSIVE_SETUP_MOVES = {"stuff-cheeks", "harden", "withdraw", "barrier", "acid-armor", "iron-defense", "cotton-guard", "shelter", "amnesia", "defense-curl", "stockpile", "cosmic-power", "psyshield-bash"}
SPEED_SETUP_MOVES = {"autotomize", "agility", "rock-polish", "trailblaze", "flame-charge", "aqua-step", "esper-wing", "scale-shot"}
MIXED_SETUP_MOVES = {"no-retreat", "victory-dance", "coil", "bulk-up", "curse", "contrary-superpower", "calm-mind", "quiver-dance"}
EVASION_SETUP_MOVES = {"double-team", "minimize"}
SHELL_SMASH_SETUP_MOVES = {"shell-smash", "belly-drum", "fillet-away", "clangorous-soul"}
SPECIAL_SETUP_MOVES = {"rapid-spin", "order-up", "charge", "defense-curl", "stockpile", "fell-stinger", "meteor-beam", "electro-shot", "geomancy", "acupressure"}

def _has_move_named(pokemon, names):
    return any(_move_name(move) in names for move in pokemon.moves)

def _player_has_attack_category(pokemon, category):
    return any(move.category == category and move.power > 0 for move in pokemon.moves)

def _player_has_phazing(pokemon):
    return _has_move_named(pokemon, PHASING_MOVES)

def _player_has_hard_setup_counter(pokemon):
    return pokemon.ability.lower().replace(" ", "-") == "unaware" or _has_move_named(pokemon, SETUP_HARD_COUNTER_MOVES)

def _player_has_confusion_move(pokemon):
    return _has_move_named(pokemon, {"confuse-ray", "supersonic", "teeter-dance", "swagger", "flatter", "dynamic-punch", "hurricane", "rock-climb", "signal-beam", "sweet-kiss", "chatter", "psybeam", "water-pulse", "dizzy-punch"})

def _ai_has_other_living_mon(state, side):
    return sum(not mon.is_fainted for mon in state.side_team(side) if mon is not state.active_mon(side)) > 0

def _is_incapacitated(pokemon):
    return pokemon.status in {"sleep", "freeze"} or "flinch" in pokemon.volatile

def _player_kill_hits(attacker, defender, field):
    return _ko_hits(attacker, defender, field)

def _player_fast_kills_in_two(attacker, defender, field):
    hits = _player_kill_hits(attacker, defender, field)
    return hits == 2 and attacker.effective_stat("spe") >= defender.effective_stat("spe")

def _random_chance(rng, probability):
    roller = rng if rng is not None else random.Random()
    return roller.random() < probability

def _setup_base_penalty(state, mon, player):
    if _player_has_hard_setup_counter(player):
        return -20.0
    if _player_kill_hits(player, mon, state.field) == 1:
        return -20.0
    if _player_fast_kills_in_two(player, mon, state.field):
        return -5.0
    if _player_has_phazing(player) and _ai_has_other_living_mon(state, "enemy"):
        return -5.0
    return None

def _score_offensive_setup(state, mon, player, move, rng):
    penalty = _setup_base_penalty(state, mon, player)
    if penalty is not None:
        return penalty
    if _is_incapacitated(player) and _random_chance(rng, 0.90):
        return 3.0
    hits = _player_kill_hits(player, mon, state.field)
    score = 0.0
    if hits is not None and hits >= 4:
        score = 1.0 if player.effective_stat("spe") >= mon.effective_stat("spe") else 2.0
    stat = move.effect_data.get("stat") if move.effect == "stat_change" else None
    stages = move.effect_data.get("stages", 0) if move.effect == "stat_change" else 0
    if stat == "atk" and mon.effective_stat("spe") > player.effective_stat("spe") and _has_move_named(player, {"burning-jealousy", "alluring-voice"}):
        score -= 5.0
    if stat == "atk" and (_has_move_named(player, {"foul-play"}) or _player_has_confusion_move(player)):
        score -= 5.0
    if stat in {"atk", "spa"} and mon.stat_stages.get(stat, 0) + stages >= 2 and _random_chance(rng, 0.80):
        score -= 1.0
    return score

def _score_defensive_setup(state, mon, player, move, rng):
    penalty = _setup_base_penalty(state, mon, player)
    if penalty is not None:
        return penalty
    if not _random_chance(rng, 0.80):
        return 0.0
    if _is_incapacitated(player) and _random_chance(rng, 0.90):
        return 2.0
    stat = move.effect_data.get("stat") if move.effect == "stat_change" else None
    score = 0.0
    if stat == "def":
        if _player_has_attack_category(player, "physical") and not _player_has_attack_category(player, "special"):
            score = 1.0
        if mon.stat_stages.get("def", 0) + move.effect_data.get("stages", 0) >= 2 and not _has_move_named(mon, {"body-press"}):
            score -= 1.0
    elif stat in {"spd", "spdef"}:
        if _player_has_attack_category(player, "special") and not _player_has_attack_category(player, "physical"):
            score = 1.0
        if mon.stat_stages.get("spd", 0) + move.effect_data.get("stages", 0) >= 2 and not _has_move_named(mon, {"stored-power"}):
            score -= 1.0
    elif stat is None:
        if mon.stat_stages.get("def", 0) < 1 or mon.stat_stages.get("spd", 0) < 1:
            score = 2.0
    if _has_move_named(mon, {"stored-power", "body-press"}) and _random_chance(rng, 0.50):
        score += 1.0
    return score

def _score_speed_setup(state, mon, player, move, rng):
    if _player_has_hard_setup_counter(player) or _player_has_phazing(player):
        return -20.0
    if mon.effective_stat("spe") >= player.effective_stat("spe"):
        return -20.0
    return 1.0 if _random_chance(rng, 0.80) else 0.0

def _score_evasion_setup(state, mon, player, move, rng):
    if _player_has_hard_setup_counter(player) or _player_has_phazing(player):
        return -20.0
    if mon.current_hp > mon.max_hp * 0.90:
        return 1.0 if _random_chance(rng, 0.80) else 0.0
    if mon.current_hp > mon.max_hp * 0.60:
        return 1.0 if _random_chance(rng, 0.60) else 0.0
    return 0.0

def _setup_category(move):
    name = _move_name(move)
    if name in SPEED_SETUP_MOVES: return "speed"
    if name in EVASION_SETUP_MOVES: return "evasion"
    if name in MIXED_SETUP_MOVES: return "mixed"
    if name in OFFENSIVE_SETUP_MOVES: return "offensive"
    if name in DEFENSIVE_SETUP_MOVES: return "defensive"
    return None

FIELD_CONTROL_MOVES = {"tailwind", "trick-room"}

def _score_field_control_move(state, attacker, defender, move, side, rng):
    name = _move_name(move)
    if name not in FIELD_CONTROL_MOVES:
        return None
    if name == "tailwind":
        if state.field.tailwind_turns.get(side, 0) > 0:
            return -20.0
        if _has_move_named(attacker, {"trick-room"}) and state.field.trick_room_turns > 0:
            return -1.0 if _random_chance(rng, 0.50) else 0.0
        target_team = state.side_team(state.other_side(side))
        faster_than_any = any(
            not mon.is_fainted and attacker.effective_stat("spe") < mon.effective_stat("spe")
            for mon in target_team
        )
        return 3.0 if faster_than_any else 0.0
    if state.field.trick_room_turns > 0:
        return -1.0 if _random_chance(rng, 0.50) else 0.0
    target_team = state.side_team(state.other_side(side))
    slower_than_any = any(
        not mon.is_fainted and attacker.effective_stat("spe") > mon.effective_stat("spe")
        for mon in target_team
    )
    return 4.0 if slower_than_any else -1.0

HAZARD_MOVES = {
    "stealth_rock": {"stealth-rock", "stone-axe"},
    "spikes": {"spikes", "ceaseless-edge"},
    "toxic_spikes": {"toxic-spikes"},
    "sticky_web": {"sticky-web"},
}

def _is_last_mon(state, side):
    return sum(not mon.is_fainted for mon in state.side_team(side)) == 1

def _score_hazard_move(state, attacker, defender, move, side, rng):
    name = _move_name(move)
    hazard = next((kind for kind, names in HAZARD_MOVES.items() if name in names), None)
    if hazard is None:
        return None

    target_side = state.other_side(side)
    hazards = state.field.hazards[target_side]
    if _is_last_mon(state, target_side):
        return -10.0

    if hazard == "stealth_rock" and hazards.get("stealth_rock", False):
        return -20.0
    if hazard == "spikes" and hazards.get("spikes", 0) >= 3:
        return -20.0
    if hazard == "toxic_spikes" and hazards.get("toxic_spikes", 0) >= 2:
        return -20.0
    if hazard == "sticky_web" and hazards.get("sticky_web", False):
        return -20.0

    score = 0.0
    if state.turn == 0:
        score += 2.0 if _random_chance(rng, 0.98) else 0.0
        if hazard == "sticky_web":
            score += 1.0
    alive = sum(not mon.is_fainted for mon in state.side_team(side))
    total = len(state.side_team(side))
    if total and _random_chance(rng, 0.75 * alive / total):
        score += 1.0

    if hazard == "toxic_spikes" and hazards.get("toxic_spikes", 0) >= 1:
        score -= 1.0 if _random_chance(rng, 0.98) else 0.0
    return score

def _score_stat_lowering_move(state, attacker, defender, move, rng):
    """Null scoring for speed, stat, and accuracy-lowering moves."""
    stat = move.effect_data.get("stat") if move.effect == "stat_change" else None
    stages = move.effect_data.get("stages", 0) if move.effect == "stat_change" else 0
    if stages >= 0:
        return None

    if stat == "spe":
        if attacker.effective_stat("spe") < defender.effective_stat("spe"):
            score = 1.0 if defender.status is not None else 0.0
        else:
            score = -2.0
        if move.hits_min > 1 or move.hits_max > 1:
            score += 1.0
        return score

    if stat == "accuracy":
        if defender.stat_stages.get("accuracy", 0) <= -2 and _random_chance(rng, 0.80):
            return -2.0
        if attacker.current_hp > attacker.max_hp * 0.90:
            return 2.0 if _random_chance(rng, 0.80) else 0.0
        if attacker.current_hp > attacker.max_hp * 0.60:
            return 1.0 if _random_chance(rng, 0.80) else 0.0
        return -1.0

    if stat in {"atk", "def", "spa", "spd"}:
        if stat in {"atk", "spa"}:
            category = "physical" if stat == "atk" else "special"
            if not _player_has_attack_category(defender, category):
                return -2.0
        if defender.stat_stages.get(stat, 0) <= -1:
            return -2.0 if _random_chance(rng, 0.80) else 0.0
        return 1.0 if _random_chance(rng, 0.20) else 0.0

    return None

def _score_setup_move(state, mon, player, move, rng):
    name = _move_name(move)

    if name == "rapid-spin":
        score = _score_speed_setup(state, mon, player, move, rng)
        hazards = state.field.hazards.get("enemy", {})
        if hazards.get("stealth_rock") or hazards.get("spikes", 0) or hazards.get("toxic_spikes", 0) or hazards.get("sticky_web"):
            if _random_chance(rng, 0.50):
                score += 2.0
        if "leech-seed" in mon.volatile or "wrapped" in mon.volatile:
            score += 1.0
        return score

    if name == "charge":
        if _player_kill_hits(player, mon, state.field) == 1 or _player_has_phazing(player):
            return -20.0
        return 1.0 if any(m.category != "status" and m.power > 0 and m.type == "electric" for m in mon.moves) else 0.0

    if name == "defense-curl":
        if _has_move_named(mon, {"rollout", "ice-ball"}) and "defense-curled" not in mon.volatile:
            return 1.0
        return _score_defensive_setup(state, mon, player, move, rng)

    if name == "stockpile":
        if _has_move_named(mon, {"spit-up", "swallow"}):
            return 1.0
        return _score_defensive_setup(state, mon, player, move, rng)

    if name == "fell-stinger":
        if _player_kill_hits(mon, player, state.field) == 1:
            return 9.0 if mon.effective_stat("spe") >= player.effective_stat("spe") else 6.0
        return -20.0

    if name in {"meteor-beam", "electro-shot"}:
        return 9.0 if _random_chance(rng, 0.80) else -20.0

    if name == "geomancy":
        if _player_kill_hits(player, mon, state.field) == 1 or _player_has_hard_setup_counter(player):
            return -20.0
        return 9.0 if _random_chance(rng, 0.80) else -20.0

    if name in SHELL_SMASH_SETUP_MOVES:
        if ((_player_has_hard_setup_counter(player) or _player_has_phazing(player))
                and _ai_has_other_living_mon(state, "enemy")):
            return -20.0
        if _is_incapacitated(player) and _random_chance(rng, 0.90):
            return 3.0
        if _player_kill_hits(player, mon, state.field) == 1:
            return -20.0
        return -2.0 if _player_kill_hits(mon, player, state.field) == 1 else 2.0

    if name == "acupressure":
        if _player_has_hard_setup_counter(player) or _player_has_phazing(player):
            return -20.0
        if _player_kill_hits(player, mon, state.field) == 1:
            return -20.0
        if _player_fast_kills_in_two(player, mon, state.field):
            return -5.0
        if _is_incapacitated(player) and _random_chance(rng, 0.90):
            return 3.0
        hits = _player_kill_hits(player, mon, state.field)
        if hits is not None and hits >= 4:
            return 1.0 if player.effective_stat("spe") >= mon.effective_stat("spe") else 2.0
        return 0.0

    category = _setup_category(move)
    if category == "offensive": return _score_offensive_setup(state, mon, player, move, rng)
    if category == "defensive": return _score_defensive_setup(state, mon, player, move, rng)
    if category == "speed": return _score_speed_setup(state, mon, player, move, rng)
    if category == "evasion": return _score_evasion_setup(state, mon, player, move, rng)
    if category == "mixed":
        stat = move.effect_data.get("stat") if move.effect == "stat_change" else None
        if stat in {"def", "spd"} and _player_has_attack_category(player, "physical" if stat == "def" else "special") and not _player_has_attack_category(player, "special" if stat == "def" else "physical"):
            return _score_defensive_setup(state, mon, player, move, rng)
        return _score_offensive_setup(state, mon, player, move, rng)
    return None

def score_enemy_move(state, action, *, side="enemy", rng=None):
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

    self_destruct_score = _score_self_destruct_move(state, mon, opponent, move, side, rng)
    if self_destruct_score is not None:
        return self_destruct_score

    pivot_score = _score_pivot_move(state, mon, opponent, move, rng)
    if pivot_score is not None:
        return pivot_score

    protection_score = _score_protection_move(state, mon, opponent, move, rng)
    if protection_score is not None:
        return protection_score

    recovery_score = _score_recovery_move(state, mon, opponent, move, rng)
    if recovery_score is not None:
        return recovery_score

    if move.category == "status" or move.power <= 0:
        field_score = _score_field_control_move(state, mon, opponent, move, side, rng)
        if field_score is not None:
            return field_score
        hazard_score = _score_hazard_move(state, mon, opponent, move, side, rng)
        if hazard_score is not None:
            return hazard_score
        stat_score = _score_stat_lowering_move(state, mon, opponent, move, rng)
        if stat_score is not None:
            return stat_score
        setup_score = _score_setup_move(state, mon, opponent, move, rng)
        if setup_score is not None:
            return setup_score
        return _score_status_move(state, mon, opponent, move, rng)

    hazard_score = _score_hazard_move(state, mon, opponent, move, side, rng)
    if hazard_score is not None:
        return hazard_score

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
