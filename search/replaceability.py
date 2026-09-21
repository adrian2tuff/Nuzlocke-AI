"""
"How replaceable is this Pokemon?" -- the piece that turns the evaluator
from "count alive Pokemon" into something closer to the plan's actual ask:
sacrificing a redundant Pokemon should cost far less than sacrificing one
that's uniquely covering a role your team has no other answer for.

Deliberately scoped to what's knowable from stats/movepool alone (no future
trainer data, no box) -- that was the explicit choice for this phase. This
means it answers "is this Pokemon redundant WITHIN THIS TEAM", not "will I
need this specific Pokemon for the next gym" -- that second question needs
future-trainer data and is a natural extension once you're ready to feed
that in.
"""

from __future__ import annotations

from engine.pokemon import Pokemon

# How much each redundancy signal can move the score. These are tunable --
# treat them as a first guess, not gospel, once you see this play out
# against real teams.
STYLE_REDUNDANCY_WEIGHT = 0.35
TYPE_OVERLAP_WEIGHT = 0.35
BASELINE_REPLACEABILITY = 0.2   # every Pokemon starts here before adjustments
UNIQUE_UTILITY_PENALTY = 0.35   # per unique utility tag, up to a cap


def attacking_style(mon: Pokemon) -> str:
    """Physical / special / mixed, based on BASE stats (not battle-state
    stages) -- this is a team-composition property, not a battle-state one."""
    atk, spa = mon.base_stat("atk"), mon.base_stat("spa")
    if atk > spa * 1.15:
        return "physical"
    if spa > atk * 1.15:
        return "special"
    return "mixed"


def damaging_move_types(mon: Pokemon) -> set[str]:
    return {m.type for m in mon.moves if m.category != "status" and m.power > 0}


def utility_tags(mon: Pokemon) -> set[str]:
    """What non-damaging roles this Pokemon's moveset covers. Extend this
    set as your move data grows (e.g. hazard removal, screens, phazing)."""
    tags = set()
    for m in mon.moves:
        if m.effect == "heal":
            tags.add("recovery")
        elif m.effect == "stat_change" and m.effect_data.get("target") == "self" and m.effect_data.get("stages", 0) > 0:
            tags.add("setup")
        elif m.effect in ("burn", "paralysis", "poison", "toxic"):
            tags.add("status_infliction")
        elif m.name == "stealth-rock":
            tags.add("hazard_setting")
        elif m.priority > 0 and m.category != "status":
            tags.add("priority_attack")
    return tags


def compute_replaceability(team: list[Pokemon]) -> dict[int, float]:
    """
    Returns {team_index: replaceability} for every Pokemon in `team`, where
    1.0 = fully redundant (losing it changes nothing the team can do) and
    0.0 = irreplaceable (it's the team's only answer for something).

    Fainted Pokemon score 0.0 -- not because they're "irreplaceable", but
    because they've already been lost, so this value is about to be
    multiplied by "is this mon alive" in the evaluator anyway; the number
    itself is moot for them.

    Computed against the OTHER CURRENTLY-ALIVE teammates, so this reflects
    "how much does losing this Pokemon hurt the team as it stands right
    now" -- not the original 6-mon roster, and not accounting for Pokemon
    already lost (they're already gone; they don't make anyone else more
    or less replaceable going forward).
    """
    alive = [(i, p) for i, p in enumerate(team) if not p.is_fainted]
    scores: dict[int, float] = {i: 0.0 for i, p in enumerate(team) if p.is_fainted}

    for i, mon in alive:
        others = [p for j, p in alive if j != i]
        if not others:
            scores[i] = 0.0  # sole survivor -- irreplaceable by definition right now
            continue

        style = attacking_style(mon)
        style_is_redundant = any(attacking_style(o) == style for o in others)

        my_types = damaging_move_types(mon)
        overlapping_teammates = sum(1 for o in others if damaging_move_types(o) & my_types)
        type_overlap_fraction = min(overlapping_teammates / len(others), 1.0)

        my_tags = utility_tags(mon)
        unique_tag_count = sum(
            1 for t in my_tags if not any(t in utility_tags(o) for o in others)
        )

        score = BASELINE_REPLACEABILITY
        score += STYLE_REDUNDANCY_WEIGHT * (1.0 if style_is_redundant else 0.0)
        score += TYPE_OVERLAP_WEIGHT * type_overlap_fraction
        score -= UNIQUE_UTILITY_PENALTY * min(unique_tag_count, 2)

        scores[i] = max(0.0, min(1.0, score))

    return scores


def explain(team: list[Pokemon]) -> list[str]:
    """Human-readable breakdown -- use this for debugging/diagnostics
    (exactly the kind of visibility the plan's diagnostic-separation point
    called for: is a weird decision an evaluator problem or something else)."""
    scores = compute_replaceability(team)
    lines = []
    for i, mon in enumerate(team):
        if mon.is_fainted:
            lines.append(f"{mon.display_name():15s} FAINTED")
            continue
        r = scores[i]
        style = attacking_style(mon)
        types = ", ".join(sorted(damaging_move_types(mon))) or "(no damaging moves)"
        tags = ", ".join(sorted(utility_tags(mon))) or "(none)"
        lines.append(
            f"{mon.display_name():15s} replaceability={r:.2f}  "
            f"style={style:8s} move-types=[{types}]  utility=[{tags}]"
        )
    return lines
