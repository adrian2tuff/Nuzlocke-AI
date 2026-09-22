"""Nuzlocke-aware position evaluator.

The simulator answers "what happens?" and the search answers "what can I
expect if both sides act?" This module answers the remaining question:
"how valuable is the resulting position for a Nuzlocke?"

The evaluator is deliberately decomposed into interpretable components rather
than one opaque heuristic. Each component is normalized before its weight is
applied.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.state import BattleState
from engine.mechanics import type_effectiveness
from search.replaceability import compute_replaceability


ALIVE_WEIGHT = 0.34
HP_WEIGHT = 0.24
REPLACEABILITY_WEIGHT = 0.18
STATUS_WEIGHT = 0.08
ACTIVE_MATCHUP_WEIGHT = 0.16

STATUS_VALUES = {
    "burn": 0.50,
    "poison": 0.55,
    "toxic": 0.75,
    "paralysis": 0.70,
    "sleep": 0.85,
    "freeze": 0.90,
}


@dataclass(frozen=True)
class EvaluationBreakdown:
    """Human-readable normalized components of a position evaluation."""
    alive: float
    hp: float
    replaceability: float
    status: float
    active_matchup: float
    total: float


def _ratio_advantage(my_value: float, their_value: float) -> float:
    total = my_value + their_value
    if total <= 0:
        return 0.0
    return (my_value - their_value) / total


def _alive_score(state: BattleState, side: str) -> float:
    team = state.side_team(side)
    return sum(not mon.is_fainted for mon in team) / len(team) if team else 0.0


def _hp_score(state: BattleState, side: str) -> float:
    team = state.side_team(side)
    return sum(mon.hp_fraction for mon in team) / len(team) if team else 0.0


def _replaceability_score(state: BattleState, side: str) -> float:
    team = state.side_team(side)
    if not team:
        return 0.0

    replaceability = compute_replaceability(team)
    contributions = []
    for i, mon in enumerate(team):
        if mon.is_fainted:
            contributions.append(0.0)
        else:
            # Nonlinear preservation value: losing a highly unique teammate
            # should hurt more than losing a moderately unique one. This
            # keeps the evaluator aligned with the Nuzlocke objective rather
            # than treating every surviving slot as interchangeable.
            irreplaceability = 1.0 - replaceability.get(i, 0.5)
            contributions.append(irreplaceability ** 2)
    return sum(contributions) / len(team)


def _status_score(state: BattleState, side: str) -> float:
    team = state.side_team(side)
    if not team:
        return 0.0

    penalty = sum(
        STATUS_VALUES.get(mon.status, 0.0)
        for mon in team
        if not mon.is_fainted
    )
    return 1.0 - penalty / len(team)


def _active_matchup_score(state: BattleState, side: str) -> float:
    """Position-only typing/coverage/speed signal; damage stays in simulator."""
    other = state.other_side(side)
    mine = state.active_mon(side)
    theirs = state.active_mon(other)

    if mine.is_fainted:
        return -1.0
    if theirs.is_fainted:
        return 1.0

    my_best = 1.0
    for move in mine.moves:
        if move.category != "status" and move.power > 0:
            my_best = max(
                my_best,
                type_effectiveness(move.type, theirs.species.types),
            )

    their_best = 1.0
    for move in theirs.moves:
        if move.category != "status" and move.power > 0:
            their_best = max(
                their_best,
                type_effectiveness(move.type, mine.species.types),
            )

    my_speed = mine.effective_stat("spe")
    their_speed = theirs.effective_stat("spe")
    speed_edge = 0.15 if my_speed > their_speed else -0.15 if my_speed < their_speed else 0.0
    type_edge = (my_best - their_best) / 2.0
    return max(-1.0, min(1.0, type_edge + speed_edge))


def evaluate_breakdown(state: BattleState, watch: str = "player") -> EvaluationBreakdown:
    """Return each normalized feature and the resulting weighted score."""
    other = state.other_side(watch)

    alive = _ratio_advantage(_alive_score(state, watch), _alive_score(state, other))
    hp = _ratio_advantage(_hp_score(state, watch), _hp_score(state, other))
    replaceability = _ratio_advantage(
        _replaceability_score(state, watch),
        _replaceability_score(state, other),
    )
    status = _ratio_advantage(
        _status_score(state, watch),
        _status_score(state, other),
    )
    active_matchup = _active_matchup_score(state, watch)

    total = (
        ALIVE_WEIGHT * alive
        + HP_WEIGHT * hp
        + REPLACEABILITY_WEIGHT * replaceability
        + STATUS_WEIGHT * status
        + ACTIVE_MATCHUP_WEIGHT * active_matchup
    )

    return EvaluationBreakdown(
        alive=alive,
        hp=hp,
        replaceability=replaceability,
        status=status,
        active_matchup=active_matchup,
        total=max(-1.0, min(1.0, total)),
    )


def evaluate(state: BattleState, watch: str = "player") -> float:
    """Return a Nuzlocke-aware score in [-1, 1]."""
    other = state.other_side(watch)

    watch_wiped = state.team_wiped(watch)
    other_wiped = state.team_wiped(other)

    if watch_wiped and other_wiped:
        return -0.5
    if watch_wiped:
        return -1.0
    if other_wiped:
        return 1.0

    return evaluate_breakdown(state, watch).total
