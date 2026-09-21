"""
Hand-written evaluation function -- this is item #17 from the plan: build a
non-neural baseline before touching any ML. No training, no learning, just
"how good does this position look" using the same kind of features the plan
called out (team survival, HP remaining, alive count) -- PLUS, as of Phase 3,
how much each Pokemon's survival actually matters (see replaceability.py).
That last part is the direct answer to "sack Bidoof, not Garchomp": losing a
redundant Pokemon barely moves this score; losing the team's only special
attacker/only recovery/only answer to some type does.

This is intentionally simple and easy to argue with -- tune the weights
once you see how it plays, rather than trusting it blindly.
"""

from __future__ import annotations

from engine.state import BattleState
from search.replaceability import compute_replaceability

# Tunable weights. alive_weight >> hp_weight because in a Nuzlocke, a
# fainted Pokemon is categorically worse than a damaged one -- losing a
# nearly-full-health Pokemon is still infinitely worse than chip damage.
ALIVE_WEIGHT = 1.0
HP_WEIGHT = 0.5
STATUS_PENALTY = 0.1

# How much irreplaceability can amplify a Pokemon's contribution to the
# score. At IRREPLACEABLE_BONUS=1.0, a fully-irreplaceable mon (score 0.0)
# counts for roughly double a fully-redundant one (score 1.0) -- tune this
# once you've watched it make a few real sack/no-sack calls.
IRREPLACEABLE_BONUS = 1.0


def _side_score(state: BattleState, side: str) -> float:
    team = state.side_team(side)
    replaceability = compute_replaceability(team)
    score = 0.0
    for i, mon in enumerate(team):
        if mon.is_fainted:
            continue
        irreplaceability = 1.0 - replaceability.get(i, 0.5)
        importance = 1.0 + IRREPLACEABLE_BONUS * irreplaceability
        score += ALIVE_WEIGHT * importance
        score += HP_WEIGHT * mon.hp_fraction * importance
        if mon.status is not None:
            score -= STATUS_PENALTY
    return score


def evaluate(state: BattleState, watch: str = "player") -> float:
    """
    Returns a score in [-1, 1] from `watch`'s perspective:
      +1.0  = watch's opponent is fully wiped, watch is not
      -1.0  = watch is fully wiped
       0.0  = perfectly even position
    Anything in between is relative team health/count advantage.
    """
    other = state.other_side(watch)

    watch_wiped = state.team_wiped(watch)
    other_wiped = state.team_wiped(other)
    if watch_wiped and other_wiped:
        return -0.5  # a double-wipe is still very bad for a Nuzlocke run, not neutral
    if watch_wiped:
        return -1.0
    if other_wiped:
        return 1.0

    my_score = _side_score(state, watch)
    their_score = _side_score(state, other)
    total = my_score + their_score
    if total <= 0:
        return 0.0
    return (my_score - their_score) / total
