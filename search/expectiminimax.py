"""
The Phase 2 search algorithm: expectiminimax.

Why this shape, specifically (this is the "how do I actually beat
everything" answer):

  - MAX over the player's legal actions      -> we pick our best move
  - MIN over the enemy's legal actions        -> we assume the opponent
                                                  picks whatever is WORST
                                                  for us, not just "typical"
  - EXPECTATION over RNG (hit/miss/crit/roll) -> averaged the honest way

The MIN-over-enemy-actions part is the important design choice for a
Nuzlocke solver specifically. The real in-game trainer AI is not a perfect
adversary -- but if you search assuming it might as well be, any line the
search calls "safe" is safe against the actual (weaker) AI too. That's what
"near-riskless" has to mean if you actually want guarantees rather than
"usually fine."

This trades runtime for that guarantee: the search space grows fast with
depth, which is exactly why `enumerate_turn_outcomes` supports bucketed
damage rolls (see engine/simulator.py) for anything beyond depth 1, and why
`_value()` below uses alpha-beta pruning.

A note on WHERE the pruning is (and isn't) applied, because getting this
wrong silently breaks correctness rather than erroring:

  - Pruning happens across sibling ACTIONS at a given decision point (e.g.
    "enemy action B can't possibly beat enemy action A, stop considering
    B's siblings") -- that's standard, provably-safe alpha-beta, because
    each sibling's value being compared is a complete, fully-computed
    number.
  - Pruning bounds are NOT threaded across the expectation (RNG) boundary
    into recursive calls. Each recursive `_value()` call starts fresh at
    (-inf, +inf) for its own action search. Threading bounds through a
    probability-weighted sum requires real care (this is "star-minimax" in
    the literature) to stay exact rather than approximate, and that's more
    machinery than Phase 2 needs -- this version stays simple and provably
    correct, at the cost of leaving some prunable work on the table.
  - `search_best_action()`'s own top-level loop is deliberately left
    UNPRUNED, so every action gets a real, exact-for-its-depth score in the
    ranked output -- pruning there would leave some rows as bounds rather
    than numbers, which would make the ranking table misleading.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from engine.state import BattleState
from engine.simulator import enumerate_turn_outcomes, summarize_risk
from search.evaluator import evaluate


@dataclass
class ActionResult:
    action: dict
    value: float                     # expectiminimax score (higher = better for us)
    worst_case_enemy_action: dict    # which enemy reply produced that worst-case value
    immediate_risk: dict             # summarize_risk() at depth 1, exact (16 rolls), for this action
                                      # against the SAME worst-case enemy reply


@dataclass
class SearchResult:
    best_action: dict
    ranked: list[ActionResult] = dc_field(default_factory=list)
    nodes_evaluated: int = 0
    cache_hits: int = 0
    depth: int = 0


def _pokemon_key(mon) -> tuple:
    """Hashable battle-relevant snapshot for the transposition table."""
    return (
        mon.species.name, mon.level, mon.current_hp, mon.status,
        mon.status_turns, frozenset(mon.volatile), mon.choice_lock,
        tuple(mon.stat_stages.values()),
        tuple(mv.pp for mv in mon.moves), mon.ability, mon.item,
    )


def _state_key(state: BattleState, depth: int, damage_buckets: int) -> tuple:
    """Key a battle position without including its narration/log."""
    field = state.field
    return (
        depth, damage_buckets, state.player_active, state.enemy_active,
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
    """
    Cheap (no recursion) estimate of how good an action looks, used only to
    DECIDE WHAT ORDER to try actions in. Move ordering doesn't change the
    search's answer -- it only changes how fast alpha-beta finds the cutoffs.
    A good move tried first prunes far more than a bad move tried first.
    """
    if action["type"] == "switch":
        target = state.side_team(side)[action["target_index"]]
        return 0.3 * target.hp_fraction  # mild preference for switching in a healthy mon
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


def _value(
    state: BattleState,
    depth: int,
    damage_buckets: int,
    nodes: list[int],
    transposition: dict[tuple, float],
    cache_hits: list[int],
) -> float:
    key = _state_key(state, depth, damage_buckets)
    if key in transposition:
        cache_hits[0] += 1
        return transposition[key]
    nodes[0] += 1

    if state.is_terminal():
        value = evaluate(state, watch="player")
        transposition[key] = value
        return value
    if depth == 0:
        value = evaluate(state, watch="player")
        transposition[key] = value
        return value

    player_actions = state.legal_actions("player")
    enemy_actions = state.legal_actions("enemy")

    if not player_actions or not enemy_actions:
        # Shouldn't normally happen (a non-terminal state always has a legal
        # action -- forced switch if active fainted) but guard anyway.
        value = evaluate(state, watch="player")
        transposition[key] = value
        return value

    # Move ordering only affects pruning speed, never the result: try our
    # most-promising actions first (tightens alpha fast), and the enemy's
    # most-threatening replies first (tightens beta fast).
    player_actions = _ordered(state, "player", player_actions, descending=True)
    enemy_actions = _ordered(state, "enemy", enemy_actions, descending=True)

    alpha, beta = -float("inf"), float("inf")
    best = -float("inf")
    for pa in player_actions:
        worst = float("inf")
        local_beta = beta
        for ea in enemy_actions:
            outcomes = enumerate_turn_outcomes(
                state, pa, ea, damage_buckets=damage_buckets, include_descriptions=False,
            )
            # NOTE: each recursive _value() call below starts with fresh
            # (-inf, +inf) bounds -- see module docstring on why bounds
            # aren't threaded across this expectation/RNG boundary.
            expected = sum(
                o.probability * _value(o.state, depth - 1, damage_buckets, nodes, transposition, cache_hits)
                for o in outcomes
            )
            worst = min(worst, expected)
            local_beta = min(local_beta, worst)
            if local_beta <= alpha:
                break  # opponent already has a reply bad enough -- this action can't win
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
) -> SearchResult:
    """
    Top-level entry point. Evaluates every legal player action, assuming
    worst-case enemy play, `depth` turns deep, and returns them ranked
    best-first.

    depth=1 with damage_buckets left high (or None inside enumerate calls)
    is exact and fast. depth>=2 uses bucketed rolls for tractability -- see
    the module docstring.

    This loop is intentionally NOT pruned (unlike `_value`, which prunes its
    own internal search) -- every action gets a fully computed score so the
    ranked output is trustworthy end-to-end, not a mix of exact numbers and
    early-exit bounds.

    `nodes_evaluated` is reported so you can see how search cost scales --
    useful for deciding how deep you can afford to go on a real ROM.
    """
    player_actions = state.legal_actions("player")
    enemy_actions = state.legal_actions("enemy")
    nodes = [0]
    cache_hits = [0]
    transposition: dict[tuple, float] = {}

    results: list[ActionResult] = []
    for pa in player_actions:
        worst_value = float("inf")
        worst_enemy_action = None
        for ea in enemy_actions:
            outcomes = enumerate_turn_outcomes(state, pa, ea, damage_buckets=damage_buckets, include_descriptions=False)
            expected = sum(
                o.probability * _value(
                    o.state,
                    depth - 1,
                    damage_buckets,
                    nodes,
                    transposition,
                    cache_hits,
                )
                for o in outcomes
            )
            if expected < worst_value:
                worst_value = expected
                worst_enemy_action = ea

        # For transparency, also report the EXACT (unbucketed) immediate risk
        # for this action against the enemy reply that made it look worst.
        exact_outcomes = enumerate_turn_outcomes(state, pa, worst_enemy_action, damage_buckets=None)
        risk = summarize_risk(exact_outcomes, watch="player")

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
