"""
Expectiminimax search with configurable enemy behavior.

The default enemy policy remains perfect MIN for backwards compatibility.
A Null policy can instead model the documented trainer-AI behavior: the enemy
selects its highest-scoring legal action, with random selection among ties.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from engine.state import BattleState
from engine.simulator import enumerate_turn_outcomes, summarize_risk
from search.evaluator import evaluate
from search.enemy_ai import enemy_action_distribution


@dataclass
class ActionResult:
    action: dict
    value: float
    worst_case_enemy_action: dict
    immediate_risk: dict


@dataclass
class SearchResult:
    best_action: dict
    ranked: list[ActionResult] = dc_field(default_factory=list)
    nodes_evaluated: int = 0
    cache_hits: int = 0
    depth: int = 0


def _pokemon_key(mon) -> tuple:
    return (
        mon.species.name, mon.level, mon.current_hp, mon.status,
        mon.status_turns, frozenset(mon.volatile), mon.choice_lock,
        tuple(mon.stat_stages.values()),
        tuple(mv.pp for mv in mon.moves), mon.ability, mon.item,
    )


def _state_key(state: BattleState, depth: int, damage_buckets: int, enemy_policy: str) -> tuple:
    field = state.field
    return (
        depth, damage_buckets, enemy_policy,
        state.player_active, state.enemy_active,
        tuple(_pokemon_key(mon) for mon in state.player_team),
        tuple(_pokemon_key(mon) for mon in state.enemy_team),
        field.weather, field.weather_turns, field.terrain, field.terrain_turns,
        field.trick_room_turns,
        (
            field.hazards["player"]["stealth_rock"],
            field.hazards["player"]["spikes"],
            field.hazards["player"]["toxic_spikes"],
            field.hazards["enemy"]["stealth_rock"],
            field.hazards["enemy"]["spikes"],
            field.hazards["enemy"]["toxic_spikes"],
        ),
        (
            field.screens["player"]["reflect"],
            field.screens["player"]["light_screen"],
            field.screens["enemy"]["reflect"],
            field.screens["enemy"]["light_screen"],
        ),
    )


def _quick_action_heuristic(state: BattleState, side: str, action: dict) -> float:
    if action["type"] == "switch":
        target = state.side_team(side)[action["target_index"]]
        entry_fraction = 0.0
        hazards = state.field.hazards[side]

        if hazards["stealth_rock"]:
            entry_fraction += 0.125 * type_effectiveness("rock", target.species.types)

        grounded = "flying" not in target.species.types and target.ability != "levitate"
        if grounded:
            spike_damage = {1: 1 / 8, 2: 1 / 6, 3: 1 / 4}
            entry_fraction += spike_damage.get(hazards["spikes"], 0.0)
            if hazards["toxic_spikes"] and target.status is None:
                entry_fraction += 0.08

        effective_hp = max(0.0, target.hp_fraction - entry_fraction)
        return 0.3 * effective_hp

    mon = state.active_mon(side)
    move = mon.moves[action["move_index"]]
    if move.category == "status":
        return 0.1
    from engine.mechanics import type_effectiveness
    other = state.other_side(side)
    defender = state.active_mon(other)
    mult = type_effectiveness(move.type, defender.species.types)
    acc = (move.accuracy or 100) / 100
    return move.power * mult * acc / 100


def _ordered(state: BattleState, side: str, actions: list[dict], *, descending: bool) -> list[dict]:
    scored = [(a, _quick_action_heuristic(state, side, a)) for a in actions]
    scored.sort(key=lambda pair: pair[1], reverse=descending)
    return [a for a, _ in scored]


def _enemy_distribution(state: BattleState, policy: str):
    if policy == "minimax":
        actions = state.legal_actions("enemy")
        if not actions:
            return []
        probability = 1.0 / len(actions)
        # The caller handles minimax specially; probabilities are not used.
        return [(action, probability) for action in actions]
    if policy == "null":
        return enemy_action_distribution(state, side="enemy")
    raise ValueError(f"unknown enemy_policy: {policy!r}")


def _value(
    state: BattleState,
    depth: int,
    damage_buckets: int,
    nodes: list[int],
    transposition: dict[tuple, float],
    cache_hits: list[int],
    enemy_policy: str,
) -> float:
    key = _state_key(state, depth, damage_buckets, enemy_policy)
    if key in transposition:
        cache_hits[0] += 1
        return transposition[key]
    nodes[0] += 1

    if state.is_terminal() or depth == 0:
        value = evaluate(state, watch="player")
        transposition[key] = value
        return value

    player_actions = state.legal_actions("player")
    enemy_actions = state.legal_actions("enemy")
    if not player_actions or not enemy_actions:
        value = evaluate(state, watch="player")
        transposition[key] = value
        return value

    player_actions = _ordered(state, "player", player_actions, descending=True)
    alpha, beta = -float("inf"), float("inf")
    best = -float("inf")

    for pa in player_actions:
        if enemy_policy == "minimax":
            enemy_actions_ordered = _ordered(state, "enemy", enemy_actions, descending=True)
            worst = float("inf")
            local_beta = beta
            for ea in enemy_actions_ordered:
                outcomes = enumerate_turn_outcomes(
                    state, pa, ea, damage_buckets=damage_buckets, include_descriptions=False,
                )
                expected = sum(
                    o.probability * _value(
                        o.state, depth - 1, damage_buckets, nodes,
                        transposition, cache_hits, enemy_policy,
                    )
                    for o in outcomes
                )
                worst = min(worst, expected)
                local_beta = min(local_beta, worst)
                if local_beta <= alpha:
                    break
        else:
            distribution = _enemy_distribution(state, enemy_policy)
            worst = sum(
                probability * sum(
                    o.probability * _value(
                        o.state, depth - 1, damage_buckets, nodes,
                        transposition, cache_hits, enemy_policy,
                    )
                    for o in enumerate_turn_outcomes(
                        state, pa, ea,
                        damage_buckets=damage_buckets,
                        include_descriptions=False,
                    )
                )
                for ea, probability in distribution
            )

        best = max(best, worst)
        alpha = max(alpha, best)
        if alpha >= beta:
            break

    transposition[key] = best
    return best


def search_best_action(
    state: BattleState,
    depth: int = 2,
    damage_buckets: int = 3,
    *,
    enemy_policy: str = "minimax",
) -> SearchResult:
    """
    Search the player's actions.

    enemy_policy="minimax" preserves the original adversarial behavior.
    enemy_policy="null" uses the Null trainer policy, including random
    selection among equal-scoring enemy actions.
    """
    player_actions = state.legal_actions("player")
    enemy_actions = state.legal_actions("enemy")
    nodes = [0]
    cache_hits = [0]
    transposition: dict[tuple, float] = {}

    results: list[ActionResult] = []
    for pa in player_actions:
        if enemy_policy == "minimax":
            worst_value = float("inf")
            worst_enemy_action = None
            for ea in enemy_actions:
                outcomes = enumerate_turn_outcomes(
                    state, pa, ea, damage_buckets=damage_buckets,
                    include_descriptions=False,
                )
                expected = sum(
                    o.probability * _value(
                        o.state, depth - 1, damage_buckets, nodes,
                        transposition, cache_hits, enemy_policy,
                    )
                    for o in outcomes
                )
                if expected < worst_value:
                    worst_value = expected
                    worst_enemy_action = ea
        else:
            distribution = _enemy_distribution(state, enemy_policy)
            if not distribution:
                worst_value = evaluate(state, watch="player")
                worst_enemy_action = None
            else:
                values = []
                for ea, probability in distribution:
                    outcomes = enumerate_turn_outcomes(
                        state, pa, ea, damage_buckets=damage_buckets,
                        include_descriptions=False,
                    )
                    expected = sum(
                        o.probability * _value(
                            o.state, depth - 1, damage_buckets, nodes,
                            transposition, cache_hits, enemy_policy,
                        )
                        for o in outcomes
                    )
                    values.append((ea, probability, expected))
                worst_value = sum(probability * expected for _, probability, expected in values)
                # This field is retained for compatibility/transparency; under
                # Null it reports the most damaging action among the tied policy actions.
                worst_enemy_action = min(values, key=lambda item: item[2])[0]

        exact_outcomes = (
            enumerate_turn_outcomes(state, pa, worst_enemy_action, damage_buckets=None)
            if worst_enemy_action is not None else []
        )
        risk = summarize_risk(exact_outcomes, watch="player") if exact_outcomes else {}

        results.append(ActionResult(
            action=pa,
            value=worst_value,
            worst_case_enemy_action=worst_enemy_action,
            immediate_risk=risk,
        ))

    results.sort(key=lambda r: -r.value)
    return SearchResult(
        best_action=results[0].action if results else None,
        ranked=results,
        nodes_evaluated=nodes[0],
        cache_hits=cache_hits[0],
        depth=depth,
    )


def describe_action(state: BattleState, side: str, action: dict) -> str:
    mon = state.active_mon(side)
    if action["type"] == "switch":
        target = state.side_team(side)[action["target_index"]]
        return f"switch to {target.display_name()}"
    move = mon.moves[action["move_index"]]
    return f"{mon.display_name()} uses {move.name}"
