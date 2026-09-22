"""
The core Phase-1 milestone lives here:

    new_state = step(state, player_action, enemy_action, rng)

is exact and reproducible for a given seeded `random.Random` -- run it twice
with the same seed and you get bit-identical results. That's what makes this
usable as ground truth for search/training later.

`enumerate_turn_outcomes` is the other half: instead of rolling the dice
once, it walks every possible combination of (hit/miss, crit/no-crit, damage
roll) for both Pokemon's moves and returns the full probability distribution
over resulting states. That's what lets you ask "is this line guaranteed
safe, or just usually safe?" -- the central ask in the brief.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from itertools import product

from .damage import damage_rolls, DAMAGE_ROLL_MULTIPLIERS
from .mechanics import (
    clamp_stage, STAT_STAGE_MULTIPLIER, STATUS_DAMAGE_FRACTION, type_effectiveness,
)
from .pokemon import Pokemon, Move
from .state import BattleState

CRIT_CHANCE = 1 / 24        # standard (non-high-crit-ratio) crit chance, Gen 6+
HIGH_CRIT_CHANCE = 1 / 8
FULL_PARALYSIS_CHANCE = 0.25   # chance a paralyzed Pokemon fails to act, Gen 3+

# Enumeration forces every random outcome explicitly, so resolve_move does not
# draw from this RNG in that path. Reuse one instead of constructing a new
# random.Random(0) object for every enumerated branch.
_ENUM_RNG = random.Random(0)


# ===========================================================================
# Deterministic single-path resolution (used by step())
# ===========================================================================

def _crit_chance(move: Move) -> float:
    return HIGH_CRIT_CHANCE if move.crit_ratio > 0 else CRIT_CHANCE


def _accuracy_check(move: Move, attacker: Pokemon, defender: Pokemon, rng: random.Random) -> bool:
    if move.accuracy is None:
        return True
    from .mechanics import ACCURACY_STAGE_MULTIPLIER
    stage = clamp_stage(attacker.stat_stages.get("accuracy", 0) - defender.stat_stages.get("evasion", 0))
    chance = move.accuracy * ACCURACY_STAGE_MULTIPLIER[stage] / 100
    return rng.random() < chance


def _apply_stat_change(target: Pokemon, stat: str, stages: int, log: list[str]) -> None:
    old = target.stat_stages.get(stat, 0)
    new = clamp_stage(old + stages)
    target.stat_stages[stat] = new
    if new != old:
        direction = "rose" if stages > 0 else "fell"
        log.append(f"{target.display_name()}'s {stat} {direction} to {new:+d}!")
    else:
        log.append(f"{target.display_name()}'s {stat} won't go {'higher' if stages > 0 else 'lower'}!")


def _apply_status_damage(mon: Pokemon, log: list[str]) -> None:
    if mon.is_fainted or mon.status is None:
        return
    if mon.status in ("burn", "poison"):
        dmg = max(1, mon.max_hp // 16 if mon.status == "burn" else mon.max_hp // 8)
        mon.current_hp = max(0, mon.current_hp - dmg)
        log.append(f"{mon.display_name()} is hurt by {mon.status}! (-{dmg} HP)")
    elif mon.status == "toxic":
        mon.status_turns += 1
        dmg = max(1, (mon.max_hp * mon.status_turns) // 16)
        mon.current_hp = max(0, mon.current_hp - dmg)
        log.append(f"{mon.display_name()} is badly poisoned! (-{dmg} HP)")


def resolve_move(
    attacker: Pokemon,
    defender: Pokemon,
    move: Move,
    field,
    rng: random.Random,
    log: list[str],
    *,
    force_hit: bool | None = None,
    force_crit: bool | None = None,
    force_roll_index: int | None = None,
    force_effect: bool | None = None,
    force_full_para: bool | None = None,
    force_protect_success: bool | None = None,
    force_hit_count: int | None = None,
    force_status_resolution: str | None = None,
    attacker_side: str | None = None,
) -> None:
    """Mutates attacker/defender/field in place. All randomness is drawn from
    `rng`, OR overridden by the force_* params -- that override is what lets
    enumerate_turn_outcomes() walk every branch deterministically.

    NOTE: `force_hit` controls ONLY whether the move hits. Whether a
    secondary effect (e.g. Thunderbolt's 10% paralysis chance) triggers is
    controlled independently by `force_effect`, and whether paralysis stops
    the attacker from acting at all is controlled independently by
    `force_full_para` -- these three used to be conflated (a real bug fixed
    in Phase 2 testing), and keeping them separate here is what keeps that
    bug from coming back."""

    pp_cost = 2 if defender.ability == "pressure" and move.effect_data.get("target") != "self" else 1
    move.pp = max(0, move.pp - pp_cost)

    # Choice items lock onto the selected move until the Pokemon switches.
    if attacker.item in ("choice-band", "choice-specs", "choice-scarf") and attacker.choice_lock is None and move.category != "status":
        attacker.choice_lock = attacker.moves.index(move)

    if attacker.is_fainted:
        return

    if move.effect == "protect":
        chance = 1.0 / (2 ** attacker.protect_streak)
        success = force_protect_success if force_protect_success is not None else (rng.random() < chance)
        if not success:
            attacker.protect_streak = 0
            log.append(f"{attacker.display_name()} failed to protect itself!")
            return
        attacker.protect_streak += 1
    else:
        attacker.protect_streak = 0

    # Protect blocks targeted moves after the protected Pokemon has acted.
    # It is a one-turn volatile condition, cleared at end of turn or switch.
    if "protect" in defender.volatile and move.effect != "protect":
        log.append(f"{defender.display_name()} protected itself from {move.name}!")
        return

    # Gen VI+ sleep/freeze resolution. Enumeration supplies an explicit
    # outcome; step() rolls the same randomness directly.
    if force_status_resolution == "sleep":
        attacker.status_turns = max(0, attacker.status_turns - 1)
        log.append(f"{attacker.display_name()} is fast asleep!")
        return
    if force_status_resolution == "wake":
        attacker.status = None
        attacker.status_turns = 0
        log.append(f"{attacker.display_name()} woke up!")
    elif force_status_resolution == "frozen":
        log.append(f"{attacker.display_name()} is frozen solid!")
        return
    elif force_status_resolution == "thaw":
        attacker.status = None
        attacker.status_turns = 0
        log.append(f"{attacker.display_name()} thawed out!")
    else:
        if attacker.status == "sleep":
            if attacker.status_turns > 0:
                attacker.status_turns -= 1
                log.append(f"{attacker.display_name()} is fast asleep!")
                return
            attacker.status = None
            log.append(f"{attacker.display_name()} woke up!")
        elif attacker.status == "freeze":
            if rng.random() >= 0.20:
                log.append(f"{attacker.display_name()} is frozen solid!")
                return
            attacker.status = None
            log.append(f"{attacker.display_name()} thawed out!")

    # Electric Terrain prevents grounded Pokemon from falling asleep.
    if attacker.status == "sleep" and field.terrain == "electric" and "flying" not in attacker.species.types and attacker.ability != "levitate":
        log.append(f"{attacker.display_name()} is protected from sleep by Electric Terrain!")
        return
    if "flinch" in attacker.volatile:
        attacker.volatile.discard("flinch")
        log.append(f"{attacker.display_name()} flinched and couldn't move!")
        return

    if move.type == "ground" and defender.ability == "levitate":
        log.append(f"{defender.display_name()} is immune to {move.name} because of Levitate!")
        return

    if attacker.status == "paralysis":
        full_para = force_full_para if force_full_para is not None else (rng.random() < FULL_PARALYSIS_CHANCE)
        if full_para:
            log.append(f"{attacker.display_name()} is paralyzed and can't move!")
            return

    hit = force_hit if force_hit is not None else _accuracy_check(move, attacker, defender, rng)
    if not hit:
        log.append(f"{attacker.display_name()}'s {move.name} missed!")
        return

    if move.category == "status":
        log.append(f"{attacker.display_name()} used {move.name}!")
        _apply_move_effect(move, attacker, defender, log, field=field, attacker_side=attacker_side, rng=rng)
        return

    is_crit = force_crit if force_crit is not None else (rng.random() < _crit_chance(move))
    rolls = damage_rolls(attacker, defender, move, field, is_crit=is_crit)
    if force_hit_count is not None:
        hit_count = force_hit_count
    elif move.hits_min == move.hits_max:
        hit_count = move.hits_min
    elif move.hits_min == 2 and move.hits_max == 5:
        hit_count = rng.choices([2, 3, 4, 5], weights=[35, 35, 15, 15], k=1)[0]
    else:
        hit_count = rng.randint(move.hits_min, move.hits_max)

    total_damage = 0
    for hit_number in range(hit_count):
        if defender.is_fainted:
            break
        roll_idx = force_roll_index if force_roll_index is not None else rng.randrange(len(rolls))
        dmg = rolls[roll_idx]
        defender.current_hp = max(0, defender.current_hp - dmg)
        total_damage += dmg

        if move.makes_contact and defender.ability == "rough-skin" and dmg > 0:
            rough_damage = max(1, defender.max_hp // 8)
            attacker.current_hp = max(0, attacker.current_hp - rough_damage)
            log.append(f"{attacker.display_name()} was hurt by Rough Skin! (-{rough_damage} HP)")
            if attacker.is_fainted:
                log.append(f"{attacker.display_name()} fainted!")
                break

        log.append(
            f"{attacker.display_name()} used {move.name}! "
            f"{'A critical hit! ' if is_crit else ''}"
            f"Hit {hit_number + 1}/{hit_count}: {defender.display_name()} took {dmg} damage "
            f"({defender.current_hp}/{defender.max_hp} HP left)."
        )

        if defender.is_fainted:
            log.append(f"{defender.display_name()} fainted!")
            break

        # Per-hit secondary effects can trigger independently.
        sheer_force = (
            attacker.ability == "sheer-force"
            and move.category != "status"
            and move.effect is not None
            and move.effect_chance > 0
        )
        if move.effect and move.effect != "hazard_removal" and not sheer_force and (force_effect if force_effect is not None else rng.random() * 100 < move.effect_chance):
            _apply_move_effect(move, attacker, defender, log, damage_dealt=dmg, rng=rng)

    # Rapid Spin-style effects remove hazards after the move connects. This
    # is deliberately outside the per-hit loop so a KO does not prevent the
    # successful move from clearing the field.
    if (
        move.effect == "hazard_removal"
        and total_damage > 0
        and not attacker.is_fainted
    ):
        _apply_move_effect(move, attacker, defender, log, field=field, attacker_side=attacker_side, damage_dealt=total_damage, rng=rng)

    sheer_force = (
        attacker.ability == "sheer-force"
        and move.category != "status"
        and move.effect is not None
        and move.effect_chance > 0
    )
    if attacker.item == "life-orb" and total_damage > 0 and not sheer_force:
        life_damage = max(1, attacker.max_hp // 10)
        attacker.current_hp = max(0, attacker.current_hp - life_damage)
        log.append(f"{attacker.display_name()} lost HP from Life Orb! (-{life_damage} HP)")
        if attacker.is_fainted:
            log.append(f"{attacker.display_name()} fainted!")

    return

def _apply_move_effect(
    move: Move, attacker: Pokemon, defender: Pokemon, log: list[str],
    *, field=None, attacker_side: str | None = None, damage_dealt: int = 0,
    rng: random.Random | None = None,
) -> None:
    eff = move.effect
    data = move.effect_data
    if eff is None:
        return
    target = attacker if data.get("target") == "self" else defender
    if eff == "recoil":
        fraction = data.get("fraction", 0)
        recoil = max(1, int(damage_dealt * fraction)) if damage_dealt > 0 else 0
        attacker.current_hp = max(0, attacker.current_hp - recoil)
        if recoil:
            log.append(f"{attacker.display_name()} took {recoil} recoil damage!")
            if attacker.is_fainted:
                log.append(f"{attacker.display_name()} fainted!")
        return
    if eff == "drain":
        fraction = data.get("fraction", 0)
        healing = max(1, int(damage_dealt * fraction)) if damage_dealt > 0 else 0
        attacker.current_hp = min(attacker.max_hp, attacker.current_hp + healing)
        if healing:
            log.append(f"{attacker.display_name()} restored {healing} HP!")
        return
    if eff == "sleep":
        if target.status is None:
            target.status = "sleep"
            target.status_turns = (rng.randint(1, 3) if rng is not None else 1)
            log.append(f"{target.display_name()} fell asleep for {target.status_turns} turn(s)!")
        return
    if eff == "freeze":
        if target.status is None:
            target.status = "freeze"
            target.status_turns = 0
            log.append(f"{target.display_name()} was frozen solid!")
        return
    if eff == "flinch":
        if not defender.is_fainted:
            defender.volatile.add("flinch")
            log.append(f"{defender.display_name()} flinched!")
        return
    if eff == "weather":
        if field is not None:
            weather = data["weather"]
            field.weather = weather
            field.weather_turns = data.get("turns", 5)
            log.append(f"The weather changed to {weather}!")
        return
    if eff == "terrain":
        if field is not None:
            terrain = data["terrain"]
            field.terrain = terrain
            field.terrain_turns = data.get("turns", 5)
            log.append(f"The battlefield became {terrain} terrain!")
        return
    if eff == "protect":
        attacker.volatile.add("protect")
        log.append(f"{attacker.display_name()} protected itself!")
        return
    if eff == "hazard_removal":
        if field is not None and attacker_side is not None:
            hazards = field.hazards[attacker_side]
            removed = []
            if hazards["stealth_rock"]:
                removed.append("Stealth Rock")
            if hazards["spikes"]:
                removed.append("Spikes")
            if hazards["toxic_spikes"]:
                removed.append("Toxic Spikes")
            hazards["stealth_rock"] = False
            hazards["spikes"] = 0
            hazards["toxic_spikes"] = 0
            if removed:
                log.append(f"{attacker.display_name()} cleared {', '.join(removed)} from its side!")
        return
    if eff == "stealth_rock":
        if field is not None and attacker_side is not None:
            field.hazards[attacker_side]["stealth_rock"] = True
            log.append("Pointed stones float in the air around the opposing team!")
        return
    if eff == "spikes":
        if field is not None and attacker_side is not None:
            current = field.hazards[attacker_side]["spikes"]
            field.hazards[attacker_side]["spikes"] = min(3, current + 1)
            log.append(f"Spikes were scattered around the opposing team's feet! ({field.hazards[attacker_side]['spikes']} layer(s))")
        return
    if eff == "toxic_spikes":
        if field is not None and attacker_side is not None:
            current = field.hazards[attacker_side]["toxic_spikes"]
            field.hazards[attacker_side]["toxic_spikes"] = min(2, current + 1)
            log.append(f"Toxic Spikes were scattered around the opposing team! ({field.hazards[attacker_side]['toxic_spikes']} layer(s))")
        return
    if eff == "stat_change":
        _apply_stat_change(target, data["stat"], data["stages"], log)
    elif eff in ("burn", "paralysis", "poison", "toxic"):
        if target.status is None:
            target.status = eff
            log.append(f"{target.display_name()} was afflicted with {eff}!")
    elif eff == "heal":
        amount = int(attacker.max_hp * data.get("fraction", 0.5))
        attacker.current_hp = min(attacker.max_hp, attacker.current_hp + amount)
        log.append(f"{attacker.display_name()} restored HP!")
    elif eff == "self_faint":
        attacker.current_hp = 0
        log.append(f"{attacker.display_name()} fainted from using {move.name}!")


def _order_or_tie(state: BattleState, player_action: dict, enemy_action: dict) -> tuple[list[str] | None, bool]:
    """Returns (order, False) if resolution order is determined, or
    (None, True) if it comes down to a genuine speed tie that needs to be
    decided randomly (by step()) or branched over (by enumerate_turn_outcomes)."""
    p_switch = player_action["type"] == "switch"
    e_switch = enemy_action["type"] == "switch"
    if p_switch and not e_switch:
        return ["player", "enemy"], False
    if e_switch and not p_switch:
        return ["enemy", "player"], False
    if p_switch and e_switch:
        return ["player", "enemy"], False  # arbitrary; both are switches, order doesn't affect outcome

    p_move = state.player_mon.moves[player_action["move_index"]]
    e_move = state.enemy_mon.moves[enemy_action["move_index"]]

    if p_move.priority != e_move.priority:
        return (["player", "enemy"] if p_move.priority > e_move.priority else ["enemy", "player"]), False

    p_spe = state.player_mon.effective_stat("spe")
    e_spe = state.enemy_mon.effective_stat("spe")
    if p_spe != e_spe:
        return (["player", "enemy"] if p_spe > e_spe else ["enemy", "player"]), False

    return None, True  # genuine speed tie


def turn_order(
    state: BattleState, player_action: dict, enemy_action: dict, rng: random.Random | None = None,
) -> list[str]:
    """Return ['player','enemy'] or ['enemy','player'] for resolution order.
    On a genuine speed tie, resolves it as a real 50/50 using `rng` if given
    (this is what step() passes, so tie-breaks are part of the seeded,
    reproducible randomness) -- falls back to player-first only when no rng
    is available (e.g. quick heuristics that don't care about exactness)."""
    order, tied = _order_or_tie(state, player_action, enemy_action)
    if not tied:
        return order
    if rng is not None:
        return ["player", "enemy"] if rng.random() < 0.5 else ["enemy", "player"]
    return ["player", "enemy"]


def order_branches(state: BattleState, player_action: dict, enemy_action: dict) -> list[tuple[float, list[str]]]:
    """Like turn_order, but for enumeration: returns [(1.0, order)] when
    order is determined, or [(0.5, [player,enemy]), (0.5, [enemy,player])]
    on a genuine speed tie -- so enumerate_turn_outcomes can branch over it
    instead of silently picking one side."""
    order, tied = _order_or_tie(state, player_action, enemy_action)
    if not tied:
        return [(1.0, order)]
    return [(0.5, ["player", "enemy"]), (0.5, ["enemy", "player"])]


def _apply_switch(state: BattleState, side: str, target_index: int, log: list[str]) -> None:
    outgoing = state.active_mon(side)
    incoming = state.side_team(side)[target_index]

    # It's the Pokemon LEAVING the field whose stat stages/volatile status
    # clear -- not the one coming in. (Getting this backwards means a boost
    # like Swords Dance incorrectly "sticks" on a benched Pokemon and
    # reappears next time it's sent out, instead of resetting like it should
    # the moment it leaves the field.)
    outgoing.stat_stages = {k: 0 for k in outgoing.stat_stages}
    outgoing.volatile = set()
    outgoing.protect_streak = 0
    outgoing.choice_lock = None

    state.set_active_index(side, target_index)
    log.append(f"{'You' if side == 'player' else 'Opponent'} sent out {incoming.display_name()}!")

    hazards = state.field.hazards[side]
    if incoming.is_fainted:
        return

    # Stealth Rock deals 1/8 max HP, modified by Rock effectiveness.
    if hazards["stealth_rock"]:
        multiplier = type_effectiveness("rock", incoming.species.types)
        if multiplier > 0:
            damage = max(1, int(incoming.max_hp * multiplier / 8))
            incoming.current_hp = max(0, incoming.current_hp - damage)
            log.append(f"{incoming.display_name()} was hurt by Stealth Rock! (-{damage} HP)")

    if incoming.is_fainted:
        log.append(f"{incoming.display_name()} fainted!")
        return

    # Spikes only affect grounded Pokemon. One, two, and three layers deal
    # 1/8, 1/6, and 1/4 of max HP respectively.
    grounded = "flying" not in incoming.species.types and incoming.ability != "levitate"
    if grounded:
        layers = hazards["spikes"]
        if layers:
            fractions = {1: 1/8, 2: 1/6, 3: 1/4}
            damage = max(1, int(incoming.max_hp * fractions[layers]))
            incoming.current_hp = max(0, incoming.current_hp - damage)
            log.append(f"{incoming.display_name()} was hurt by Spikes! (-{damage} HP)")

    if incoming.is_fainted:
        log.append(f"{incoming.display_name()} fainted!")
        return

    # Toxic Spikes only affect grounded Pokemon. Poison types absorb the
    # hazard when they switch in, removing all Toxic Spikes on that side.
    if grounded:
        toxic_layers = hazards["toxic_spikes"]
        if toxic_layers:
            if "poison" in incoming.species.types:
                hazards["toxic_spikes"] = 0
                log.append(f"{incoming.display_name()} absorbed the Toxic Spikes!")
            elif incoming.status is None:
                incoming.status = "toxic" if toxic_layers >= 2 else "poison"
                log.append(f"{incoming.display_name()} was afflicted with {incoming.status} by Toxic Spikes!")


def _apply_end_of_turn_field(state: BattleState, log) -> None:
    """Apply weather/terrain residual effects and decrement their timers."""
    field = state.field

    if field.weather in ("sand", "hail"):
        for mon in (state.player_mon, state.enemy_mon):
            if mon.is_fainted:
                continue
            immune = ("rock", "ground", "steel") if field.weather == "sand" else ("ice",)
            if not any(t in immune for t in mon.species.types):
                damage = max(1, mon.max_hp // 16)
                mon.current_hp = max(0, mon.current_hp - damage)
                log.append(f"{mon.display_name()} was hurt by {field.weather}! (-{damage} HP)")

    if field.weather == "sun":
        for mon in (state.player_mon, state.enemy_mon):
            if not mon.is_fainted and mon.ability == "solar-power":
                damage = max(1, mon.max_hp // 8)
                mon.current_hp = max(0, mon.current_hp - damage)
                log.append(f"{mon.display_name()} was hurt by Solar Power! (-{damage} HP)")

    if field.terrain == "grassy":
        for mon in (state.player_mon, state.enemy_mon):
            if mon.is_fainted:
                continue
            grounded = "flying" not in mon.species.types and mon.ability != "levitate"
            if grounded:
                healing = max(1, mon.max_hp // 16)
                mon.current_hp = min(mon.max_hp, mon.current_hp + healing)
                log.append(f"{mon.display_name()} restored {healing} HP from Grassy Terrain!")

    if field.weather is not None:
        field.weather_turns = max(0, field.weather_turns - 1)
        if field.weather_turns == 0:
            log.append(f"The {field.weather} weather faded.")
            field.weather = None

    # Protect only lasts for the current turn.
    for mon in (state.player_mon, state.enemy_mon):
        mon.volatile.discard("protect")

    if field.terrain is not None:
        field.terrain_turns = max(0, field.terrain_turns - 1)
        if field.terrain_turns == 0:
            log.append(f"The {field.terrain} terrain faded.")
            field.terrain = None


def step(
    state: BattleState,
    player_action: dict,
    enemy_action: dict,
    rng: random.Random,
) -> BattleState:
    """
    Exact, reproducible turn resolution: state + actions + seeded rng ->
    a brand-new resulting BattleState. Does not mutate the input state.
    """
    new_state = state.clone()
    log = new_state.log

    order = turn_order(new_state, player_action, enemy_action, rng=rng)
    actions = {"player": player_action, "enemy": enemy_action}

    for side in order:
        action = actions[side]
        other = new_state.other_side(side)

        if new_state.active_mon(side).is_fainted:
            continue  # already fainted earlier this turn, can't act

        if action["type"] == "switch":
            _apply_switch(new_state, side, action["target_index"], log)
            continue

        attacker = new_state.active_mon(side)
        defender = new_state.active_mon(other)
        move = attacker.moves[action["move_index"]]
        resolve_move(attacker, defender, move, new_state.field, rng, log, attacker_side=side)

        if new_state.team_wiped(other):
            break  # battle over, no point resolving further

    # End-of-turn status damage (only if battle isn't already decided)
    if not new_state.is_terminal():
        _apply_status_damage(new_state.player_mon, log)
        _apply_status_damage(new_state.enemy_mon, log)
        _apply_end_of_turn_field(new_state, log)
        for mon in (new_state.player_mon, new_state.enemy_mon):
            if not mon.is_fainted and mon.item == "leftovers":
                healing = max(1, mon.max_hp // 16)
                mon.current_hp = min(mon.max_hp, mon.current_hp + healing)
                log.append(f"{mon.display_name()} restored {healing} HP with Leftovers!")

    new_state.turn += 1
    return new_state


# ===========================================================================
# Exact outcome enumeration (the "near-riskless line" tool)
# ===========================================================================

@dataclass
class Outcome:
    probability: float
    state: BattleState
    description: str


class _NullLog:
    """Drop-in log sink for search enumeration, where narration is unused."""
    __slots__ = ()

    def append(self, _message: str) -> None:
        pass


def _bucket_roll_indices(n_rolls: int, n_buckets: int | None) -> list[tuple[float, int]]:
    """
    Reduce the 16 exact damage-roll indices down to `n_buckets` representative
    ones for tractable multi-turn lookahead. Pass n_buckets=None to keep all
    16 exact rolls (used for single-turn certification).

    HONEST LABELING: this is a representative-roll APPROXIMATION, not an
    exact aggregate probability preserved from the real 16-roll distribution.
    It splits the 16 rolls into `n_buckets` contiguous groups and assigns
    each representative roll the probability mass of its whole group (so
    group sizes, not a flat 1/n_buckets, determine the weight) -- that's
    closer to correct than a flat split, but it still collapses each group
    to a single representative value rather than modeling the group's
    internal spread. Good enough for "does this line risk going badly a
    few turns out", not a substitute for the exact n_buckets=None case.
    """
    if n_buckets is None or n_buckets >= n_rolls:
        return [(1 / n_rolls, i) for i in range(n_rolls)]
    if n_buckets == 1:
        return [(1.0, n_rolls // 2)]

    # Split indices 0..n_rolls-1 into n_buckets contiguous groups, as close
    # to equal size as possible; representative = the group's middle index.
    base, remainder = divmod(n_rolls, n_buckets)
    groups: list[list[int]] = []
    start = 0
    for b in range(n_buckets):
        size = base + (1 if b < remainder else 0)
        groups.append(list(range(start, start + size)))
        start += size

    return [(len(g) / n_rolls, g[len(g) // 2]) for g in groups]


def _single_move_branches(
    attacker: Pokemon, defender: Pokemon, move: Move, field,
    damage_buckets: int | None = None,
) -> list[tuple[float, bool, bool, int | None]]:
    """
    Enumerate (probability, hit, crit, roll_index) branches for one move use,
    ignoring status-prevents-action for simplicity in Phase 1 (add later).
    Status/switch moves collapse roll_index to None.

    `damage_buckets`: None = exact (all 16 damage rolls). An int = reduce to
    that many representative rolls, for tractable multi-turn search -- see
    `_bucket_roll_indices`.
    """
    if move.accuracy is None:
        hit_branches = [(1.0, True)]
    else:
        from .mechanics import ACCURACY_STAGE_MULTIPLIER
        stage = clamp_stage(attacker.stat_stages.get("accuracy", 0) - defender.stat_stages.get("evasion", 0))
        p_hit = min(1.0, move.accuracy * ACCURACY_STAGE_MULTIPLIER[stage] / 100)
        hit_branches = [(p_hit, True), (1 - p_hit, False)]

    branches = []
    for p_hit, hit in hit_branches:
        if p_hit == 0:
            continue
        if not hit or move.category == "status" or move.power == 0:
            branches.append((p_hit, hit, False, None))
            continue
        crit_p = _crit_chance(move)
        for p_crit, crit in ((crit_p, True), (1 - crit_p, False)):
            if p_crit == 0:
                continue
            n_rolls = len(DAMAGE_ROLL_MULTIPLIERS)
            for p_roll, roll_idx in _bucket_roll_indices(n_rolls, damage_buckets):
                branches.append((p_hit * p_crit * p_roll, hit, crit, roll_idx))
    return branches



def _multi_hit_state_key(state: BattleState) -> tuple:
    """Hash only battle state, not narration, for sequential RNG-state merging."""
    def mon_key(mon: Pokemon) -> tuple:
        return (
            mon.species.name, mon.current_hp, mon.status, mon.status_turns,
            frozenset(mon.volatile), tuple(sorted(mon.stat_stages.items())),
            tuple(mv.pp for mv in mon.moves), mon.ability, mon.item,
            mon.protect_streak,
        )

    field = state.field
    return (
        state.player_active, state.enemy_active,
        tuple(mon_key(mon) for mon in state.player_team),
        tuple(mon_key(mon) for mon in state.enemy_team),
        field.weather, field.weather_turns, field.terrain, field.terrain_turns,
        field.trick_room_turns,
        tuple(
            field.hazards[side][kind]
            for side in ("player", "enemy")
            for kind in ("stealth_rock", "spikes", "toxic_spikes")
        ),
    )


def _enumerate_multi_hit_move(
    state: BattleState,
    side: str,
    action: dict,
    hit_count: int,
    *,
    damage_buckets: int | None,
    include_descriptions: bool,
) -> list[tuple[float, BattleState, str]]:
    """Enumerate a multi-hit move one strike at a time.

    Each strike gets its own crit roll, damage roll, and secondary-effect roll.
    States are merged after every strike when they are identical, avoiding the
    full Cartesian explosion that would result from enumerating complete
    crit/roll/effect sequences up front.
    """
    working = state.clone()
    log = [] if include_descriptions else _NullLog()
    attacker = working.active_mon(side)
    defender = working.active_mon(working.other_side(side))
    move = attacker.moves[action["move_index"]]

    move.pp = max(0, move.pp - 1)
    attacker.protect_streak = 0

    # These checks occur once for the whole move, before the individual hits.
    if "protect" in defender.volatile and move.effect != "protect":
        log.append(f"{defender.display_name()} protected itself from {move.name}!")
        return [(1.0, working, "; ".join(log) if include_descriptions else "")]

    if move.type == "ground" and defender.ability == "levitate":
        log.append(f"{defender.display_name()} is immune to {move.name} because of Levitate!")
        return [(1.0, working, "; ".join(log) if include_descriptions else "")]

    states: list[tuple[float, BattleState, str]] = [
        (1.0, working, "; ".join(log) if include_descriptions else "")
    ]

    for hit_number in range(hit_count):
        next_states: dict[tuple, tuple[float, BattleState, str]] = {}

        for base_probability, base_state, base_description in states:
            if base_state.active_mon(side).is_fainted or base_state.active_mon(base_state.other_side(side)).is_fainted:
                key = _multi_hit_state_key(base_state)
                old = next_states.get(key)
                if old is None:
                    next_states[key] = (base_probability, base_state, base_description)
                else:
                    next_states[key] = (old[0] + base_probability, old[1], old[2])
                continue

            a = base_state.active_mon(side)
            d = base_state.active_mon(base_state.other_side(side))
            m = a.moves[action["move_index"]]

            crit_branches = [
                (1.0, False),
            ]
            crit_probability = _crit_chance(m)
            if crit_probability > 0:
                crit_branches = [
                    (1.0 - crit_probability, False),
                    (crit_probability, True),
                ]

            for p_crit, is_crit in crit_branches:
                rolls = damage_rolls(a, d, m, base_state.field, is_crit=is_crit)
                for p_roll, roll_index in _bucket_roll_indices(len(rolls), damage_buckets):
                    effect_branches = [(1.0, False)]
                    if m.effect and m.effect_chance > 0:
                        effect_probability = m.effect_chance / 100
                        effect_branches = [(1.0 - effect_probability, False), (effect_probability, True)]

                    for p_effect, effect_triggers in effect_branches:
                        effect_resolution_branches = [(1.0, None)]
                        if effect_triggers and m.effect == "sleep":
                            effect_resolution_branches = [(1 / 3, 1), (1 / 3, 2), (1 / 3, 3)]

                        for p_resolution, sleep_turns in effect_resolution_branches:
                            branch = base_state.clone()
                            branch_log = base_description
                            attacker_b = branch.active_mon(side)
                            defender_b = branch.active_mon(branch.other_side(side))
                            move_b = attacker_b.moves[action["move_index"]]
                            dmg = rolls[roll_index]
                            defender_b.current_hp = max(0, defender_b.current_hp - dmg)

                            if branch_log:
                                branch_log += "; "
                            branch_log += (
                                f"{attacker_b.display_name()} used {move_b.name}! "
                                f"{'A critical hit! ' if is_crit else ''}"
                                f"Hit {hit_number + 1}/{hit_count}: "
                                f"{defender_b.display_name()} took {dmg} damage "
                                f"({defender_b.current_hp}/{defender_b.max_hp} HP left)."
                            )

                            if move_b.makes_contact and defender_b.ability == "rough-skin" and dmg > 0:
                                rough_damage = max(1, defender_b.max_hp // 8)
                                attacker_b.current_hp = max(0, attacker_b.current_hp - rough_damage)
                                branch_log += f" {attacker_b.display_name()} was hurt by Rough Skin! (-{rough_damage} HP)"
                                if attacker_b.is_fainted:
                                    branch_log += f" {attacker_b.display_name()} fainted!"
                                    key = _multi_hit_state_key(branch)
                                    probability = base_probability * p_crit * p_roll * p_effect * p_resolution
                                    old = next_states.get(key)
                                    next_states[key] = (
                                        (old[0] if old else 0.0) + probability,
                                        branch,
                                        old[2] if old else branch_log,
                                    )
                                    continue

                            if not defender_b.is_fainted and effect_triggers:
                                if move_b.effect == "sleep" and sleep_turns is not None:
                                    if defender_b.status is None:
                                        defender_b.status = "sleep"
                                        defender_b.status_turns = sleep_turns
                                        branch_log += f" {defender_b.display_name()} fell asleep for {sleep_turns} turn(s)!"
                                else:
                                    before_log_len = len(branch_log)
                                    effect_log = []
                                    _apply_move_effect(
                                        move_b, attacker_b, defender_b, effect_log,
                                        field=branch.field, attacker_side=side,
                                        damage_dealt=dmg, rng=_ENUM_RNG,
                                    )
                                    if effect_log:
                                        branch_log += " " + " ".join(effect_log)

                            if defender_b.is_fainted:
                                branch_log += f" {defender_b.display_name()} fainted!"

                            probability = base_probability * p_crit * p_roll * p_effect * p_resolution
                            key = _multi_hit_state_key(branch)
                            old = next_states.get(key)
                            if old is None:
                                next_states[key] = (probability, branch, branch_log)
                            else:
                                next_states[key] = (old[0] + probability, old[1], old[2])

        states = list(next_states.values())

    finalized = []
    for probability, branch, description in states:
        attacker_b = branch.active_mon(side)
        m = attacker_b.moves[action["move_index"]]
        sheer_force = (
            attacker_b.ability == "sheer-force"
            and m.category != "status"
            and m.effect is not None
            and m.effect_chance > 0
        )
        if attacker_b.item == "life-orb" and not sheer_force and not attacker_b.is_fainted:
            life_damage = max(1, attacker_b.max_hp // 10)
            attacker_b.current_hp = max(0, attacker_b.current_hp - life_damage)
            if include_descriptions:
                description = (description + "; " if description else "") + f"{attacker_b.display_name()} lost HP from Life Orb! (-{life_damage} HP)"
        finalized.append((probability, branch, description))

    return finalized


def enumerate_turn_outcomes(
    state: BattleState,
    player_action: dict,
    enemy_action: dict,
    *,
    max_branches: int = 5000,
    damage_buckets: int | None = None,
    include_descriptions: bool = True,
) -> list[Outcome]:
    """
    Full exact-under-the-modeled-randomness probability distribution over
    resulting states for this turn. Use this to answer "does ANY branch
    result in my Pokemon fainting?" -- i.e. to certify a line as
    guaranteed-safe rather than just usually-safe.

    IMPORTANT SCOPE NOTE (read this before trusting "guaranteed" anywhere
    downstream): this enumerates accuracy/crit/damage-roll/secondary-effect/
    full-paralysis randomness for both moves, AND branches over genuine
    speed ties as a real 50/50 (see `order_branches`). It does NOT yet
    enumerate sleep/freeze thaw -- there's no move in the current data that
    inflicts either, so that's a documented gap rather than guessed-at code
    (see README). `summarize_risk()`'s `exact` flag and
    `unmodeled_randomness` list reflect this scope.

    The second mover's move is evaluated against the state AFTER the first
    mover's action resolves (s1), not the original state -- this matters
    whenever the first action changes what the second move is checking
    against: a switch changes the defender's typing/stats entirely (e.g. a
    Ground move that would hit the old defender but is now facing a
    Flying-type immune to it), and stat-changing or status-inflicting first
    moves change the second move's accuracy/crit/damage math too.

    Secondary effects (e.g. Thunderbolt's 10% paralysis chance) and full
    paralysis (25% chance a paralyzed Pokemon can't act) are each their own
    branch, independent of the hit/miss branch.
    """
    actions = {"player": player_action, "enemy": enemy_action}

    def branches_for(acting_state: BattleState, side: str) -> list[tuple[float, bool, bool, int | None, bool, bool, bool | None, int | None, str | None]]:
        """(probability, hit, crit, roll_index, effect_triggers, full_para)
        branches, computed against `acting_state` -- i.e. always call this
        AFTER any earlier action this turn has already been applied."""
        action = actions[side]
        if action["type"] == "switch" or acting_state.active_mon(side).is_fainted:
            return [(1.0, True, False, None, False, False, None, None, None)]

        attacker = acting_state.active_mon(side)
        other = acting_state.other_side(side)
        defender = acting_state.active_mon(other)
        move = attacker.moves[action["move_index"]]
        if move.effect == "protect":
            chance = 1.0 / (2 ** attacker.protect_streak)
            if chance >= 1.0:
                return [(1.0, True, False, None, True, False, True, 1, None)]
            return [
                (chance, True, False, None, True, False, True, 1, None),
                (1.0 - chance, True, False, None, False, False, False, 0, None),
            ]
        # Standard 2-5-hit moves use 35/35/15/15% for 2/3/4/5 hits.
        if move.hits_min != 1 or move.hits_max != 1:
            if move.hits_min == 2 and move.hits_max == 5:
                hit_counts = [(0.35, 2), (0.35, 3), (0.15, 4), (0.15, 5)]
            else:
                count = move.hits_max - move.hits_min + 1
                hit_counts = [(1 / count, n) for n in range(move.hits_min, move.hits_max + 1)]
        else:
            hit_counts = [(1.0, None)]

        if attacker.status == "sleep":
            if attacker.status_turns > 0:
                return [(1.0, True, False, None, False, False, None, None, "sleep")]
            return [(1.0, True, False, None, False, False, None, None, "wake")]
        if attacker.status == "freeze":
            return [
                (0.20, True, False, None, False, False, None, None, "thaw"),
                (0.80, True, False, None, False, False, None, None, "frozen"),
            ]

        if (move.category != "status" and move.power > 0 and (move.hits_min != 1 or move.hits_max != 1)):
            # Multi-hit moves are enumerated strike-by-strike below. Keeping
            # only the hit-count branch here prevents a Cartesian explosion
            # across independent crit/damage/effect rolls.
            return [(p, True, False, None, False, False, None, hit_count, None)
                    for p, hit_count in hit_counts]

        move_branches = _single_move_branches(attacker, defender, move, acting_state.field, damage_buckets=damage_buckets)

        # Fan each (hit/crit/roll) branch out over the secondary-effect chance.
        fanned: list[tuple[float, bool, bool, int | None, bool, int | None]] = []
        for p, hit, crit, roll_idx in move_branches:
            for hit_count_p, hit_count in hit_counts:
                if not hit or move.effect is None:
                    fanned.append((p * hit_count_p, hit, crit, roll_idx, False, hit_count))
                    continue
                chance = move.effect_chance / 100
                if chance >= 1.0:
                    fanned.append((p * hit_count_p, hit, crit, roll_idx, True, hit_count))
                elif chance <= 0.0:
                    fanned.append((p * hit_count_p, hit, crit, roll_idx, False, hit_count))
                else:
                    fanned.append((p * hit_count_p * chance, hit, crit, roll_idx, True, hit_count))
                    fanned.append((p * hit_count_p * (1 - chance), hit, crit, roll_idx, False, hit_count))

        # Fan out again over full-paralysis, if applicable: a paralyzed
        # attacker either fails to act entirely (its own branch, whatever
        # it would have done is irrelevant) or acts normally with the
        # remaining probability mass.
        if attacker.status == "paralysis":
            out = [(p * (1 - FULL_PARALYSIS_CHANCE), hit, crit, roll_idx, effect, False, None, hit_count, None)
                   for (p, hit, crit, roll_idx, effect, hit_count) in fanned]
            out.append((FULL_PARALYSIS_CHANCE, True, False, None, False, True, None, None, None))
            return out

        return [(p, hit, crit, roll_idx, effect, False, None, hit_count, None) for (p, hit, crit, roll_idx, effect, hit_count) in fanned]

    def enumerate_for_order(order: list[str], order_weight: float) -> list[Outcome]:
        first, second = order[0], order[1]
        outs: list[Outcome] = []

        for p1, hit1, crit1, roll1, effect1, para1, protect1, hits1, status1 in branches_for(state, first):
            s1 = state.clone()
            log1 = [] if include_descriptions else _NullLog()
            a1 = actions[first]
            if a1["type"] == "switch":
                _apply_switch(s1, first, a1["target_index"], log1)
            elif not s1.active_mon(first).is_fainted:
                attacker = s1.active_mon(first)
                defender = s1.active_mon(s1.other_side(first))
                move = attacker.moves[a1["move_index"]]
                if hits1 is not None and (move.hits_min != 1 or move.hits_max != 1) and move.category != "status":
                    multi_states = _enumerate_multi_hit_move(
                        s1, first, a1, hits1,
                        damage_buckets=damage_buckets,
                        include_descriptions=include_descriptions,
                    )
                    # Defer this branch to the normal second-mover loop below.
                    for multi_p, multi_state, multi_desc in multi_states:
                        first_wiped = multi_state.team_wiped(multi_state.other_side(first))
                        if first_wiped:
                            _apply_status_damage(multi_state.player_mon, log1 if include_descriptions else _NullLog())
                            _apply_status_damage(multi_state.enemy_mon, log1 if include_descriptions else _NullLog())
                            multi_state.turn += 1
                            outs.append(Outcome(order_weight * p1 * multi_p, multi_state, multi_desc))
                            continue

                        for p2, hit2, crit2, roll2, effect2, para2, protect2, hits2, status2 in branches_for(multi_state, second):
                            s2 = multi_state.clone()
                            log2 = list(log1) if include_descriptions else _NullLog()
                            a2 = actions[second]
                            if s2.active_mon(second).is_fainted:
                                pass
                            elif a2["type"] == "switch":
                                _apply_switch(s2, second, a2["target_index"], log2)
                            else:
                                attacker2 = s2.active_mon(second)
                                defender2 = s2.active_mon(s2.other_side(second))
                                move2 = attacker2.moves[a2["move_index"]]
                                if hits2 is not None and (move2.hits_min != 1 or move2.hits_max != 1) and move2.category != "status":
                                    multi2 = _enumerate_multi_hit_move(
                                        s2, second, a2, hits2,
                                        damage_buckets=damage_buckets,
                                        include_descriptions=include_descriptions,
                                    )
                                    for p_multi2, s_multi2, desc_multi2 in multi2:
                                        final = s_multi2
                                        final_log = desc_multi2
                                        if not final.is_terminal():
                                            endlog = []
                                            _apply_status_damage(final.player_mon, endlog)
                                            _apply_status_damage(final.enemy_mon, endlog)
                                            _apply_end_of_turn_field(final, endlog)
                                            final_log = (final_log + "; " + "; ".join(endlog)) if final_log and endlog else final_log + "; ".join(endlog)
                                        final.turn += 1
                                        outs.append(Outcome(order_weight * p1 * multi_p * p2 * p_multi2, final, final_log))
                                else:
                                    resolve_move(
                                        attacker2, defender2, move2, s2.field,
                                        rng=_ENUM_RNG, log=log2,
                                        force_hit=hit2, force_crit=crit2, force_roll_index=roll2,
                                        force_effect=effect2, force_full_para=para2, force_protect_success=protect2, force_hit_count=hits2, force_status_resolution=status2, attacker_side=second,
                                    )
                                    if not s2.is_terminal():
                                        _apply_status_damage(s2.player_mon, log2)
                                        _apply_status_damage(s2.enemy_mon, log2)
                                        _apply_end_of_turn_field(s2, log2)
                                    s2.turn += 1
                                    outs.append(Outcome(order_weight * p1 * multi_p * p2, s2, "; ".join(log2) if include_descriptions else ""))
                    continue

                resolve_move(
                    attacker, defender, move, s1.field,
                    rng=_ENUM_RNG, log=log1,
                    force_hit=hit1, force_crit=crit1, force_roll_index=roll1,
                    force_effect=effect1, force_full_para=para1, force_protect_success=protect1, force_hit_count=hits1, force_status_resolution=status1, attacker_side=first,
                )

            first_wiped = s1.team_wiped(s1.other_side(first))

            if first_wiped:
                _apply_status_damage(s1.player_mon, log1)
                _apply_status_damage(s1.enemy_mon, log1)
                s1.turn += 1
                outs.append(Outcome(
                    order_weight * p1, s1,
                    "; ".join(log1) if include_descriptions else "",
                ))
                continue

            # Second mover's branches are computed from s1 -- the state
            # AFTER the first move resolved -- not from the original
            # `state`. This is what makes switches-into-immunity and
            # stat/status-changing first moves evaluate correctly.
            for p2, hit2, crit2, roll2, effect2, para2, protect2, hits2, status2 in branches_for(s1, second):
                s2 = s1.clone()
                log2 = list(log1) if include_descriptions else _NullLog()
                a2 = actions[second]
                if s2.active_mon(second).is_fainted:
                    pass
                elif a2["type"] == "switch":
                    _apply_switch(s2, second, a2["target_index"], log2)
                else:
                    attacker = s2.active_mon(second)
                    defender = s2.active_mon(s2.other_side(second))
                    move = attacker.moves[a2["move_index"]]
                    if hits2 is not None and (move.hits_min != 1 or move.hits_max != 1) and move.category != "status":
                        multi_states = _enumerate_multi_hit_move(
                            s2, second, a2, hits2,
                            damage_buckets=damage_buckets,
                            include_descriptions=include_descriptions,
                        )
                        for multi_p, multi_state, multi_desc in multi_states:
                            if not multi_state.is_terminal():
                                endlog = []
                                _apply_status_damage(multi_state.player_mon, endlog)
                                _apply_status_damage(multi_state.enemy_mon, endlog)
                                _apply_end_of_turn_field(multi_state, endlog)
                                if endlog:
                                    multi_desc = (multi_desc + "; " if multi_desc else "") + "; ".join(endlog)
                            multi_state.turn += 1
                            outs.append(Outcome(
                                order_weight * p1 * p2 * multi_p,
                                multi_state,
                                multi_desc if include_descriptions else "",
                            ))
                        continue

                    resolve_move(
                        attacker, defender, move, s2.field,
                        rng=_ENUM_RNG, log=log2,
                        force_hit=hit2, force_crit=crit2, force_roll_index=roll2,
                        force_effect=effect2, force_full_para=para2, force_protect_success=protect2, force_hit_count=hits2, force_status_resolution=status2, attacker_side=second,
                    )

                if not s2.is_terminal():
                    _apply_status_damage(s2.player_mon, log2)
                    _apply_status_damage(s2.enemy_mon, log2)
                    _apply_end_of_turn_field(s2, log2)
                s2.turn += 1

                outs.append(Outcome(
                    order_weight * p1 * p2, s2,
                    "; ".join(log2) if include_descriptions else "",
                ))

                if len(outs) > max_branches:
                    raise RuntimeError(
                        f"enumerate_turn_outcomes exceeded {max_branches} branches -- "
                        "reduce roll granularity or bucket damage rolls for this use case."
                    )
        return outs

    outcomes: list[Outcome] = []
    for weight, order in order_branches(state, player_action, enemy_action):
        outcomes.extend(enumerate_for_order(order, weight))
    return outcomes


# ===========================================================================
# Risk summary helpers -- these turn a raw Outcome list into the
# guaranteed / robust / risky / catastrophic language from the plan.
# ===========================================================================

def summarize_risk(outcomes: list[Outcome], watch: str = "player", *, exact: bool = True) -> dict:
    """
    Given enumerate_turn_outcomes() output, compute the probability that the
    watched side's active Pokemon faints, and the team-wipe probability.

    `exact`: pass True only when this was called with damage_buckets=None.
    Even then, "exact" means exact with respect to the randomness this
    engine currently models -- accuracy, crit, damage-roll, secondary-effect,
    full-paralysis, and speed ties are all branched now. Sleep/freeze thaw
    are the one remaining gap (no move in the current data inflicts either,
    so there's nothing yet to test that logic against -- see README).
    """
    p_active_faints = 0.0
    p_team_wiped = 0.0
    p_win = 0.0  # watched side wins the whole battle this turn
    other = "enemy" if watch == "player" else "player"

    for o in outcomes:
        mon = o.state.active_mon(watch)
        if mon.is_fainted:
            p_active_faints += o.probability
        if o.state.team_wiped(watch):
            p_team_wiped += o.probability
        if o.state.team_wiped(other) and not o.state.team_wiped(watch):
            p_win += o.probability

    if p_team_wiped == 0:
        tier = "guaranteed"
    elif p_team_wiped < 0.02:
        tier = "robust"
    elif p_team_wiped < 0.15:
        tier = "risky"
    else:
        tier = "catastrophic"

    return {
        "active_faint_probability": round(p_active_faints, 4),
        "team_wipe_probability": round(p_team_wiped, 4),
        "win_probability_this_turn": round(p_win, 4),
        "risk_tier": tier,
        "branch_count": len(outcomes),
        "exact": exact,
        "unmodeled_randomness": [
            "sleep_freeze_thaw",  # no move in current data inflicts either -- nothing to test against yet
        ],
    }
