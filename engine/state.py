"""
BattleState: everything needed to fully determine what happens next.
Deliberately a plain, deep-copyable object (no engine logic lives on it) so
the simulator can freely branch into hypothetical futures via `.clone()`.
"""

from __future__ import annotations

import copy
# NOTE: aliased to avoid a name collision -- BattleState has an attribute
# literally called `field` (the battlefield conditions), which would shadow
# dataclasses.field() if imported under its normal name.
from dataclasses import dataclass, field as dc_field

from .pokemon import Pokemon


@dataclass
class Field:
    weather: str | None = None          # "rain" | "sun" | "sand" | "hail" | None
    weather_turns: int = 0
    terrain: str | None = None
    terrain_turns: int = 0
    # Per-side hazards/screens: side is "player" or "enemy"
    hazards: dict = dc_field(default_factory=lambda: {
        "player": {"stealth_rock": False, "spikes": 0, "toxic_spikes": 0},
        "enemy": {"stealth_rock": False, "spikes": 0, "toxic_spikes": 0},
    })
    screens: dict = dc_field(default_factory=lambda: {
        "player": {"reflect": 0, "light_screen": 0},
        "enemy": {"reflect": 0, "light_screen": 0},
    })
    trick_room_turns: int = 0


@dataclass
class BattleState:
    player_team: list[Pokemon]
    enemy_team: list[Pokemon]
    player_active: int = 0
    enemy_active: int = 0
    field: Field = dc_field(default_factory=Field)
    turn: int = 0
    log: list[str] = dc_field(default_factory=list)

    # -- convenience accessors -------------------------------------------
    @property
    def player_mon(self) -> Pokemon:
        return self.player_team[self.player_active]

    @property
    def enemy_mon(self) -> Pokemon:
        return self.enemy_team[self.enemy_active]

    def side_team(self, side: str) -> list[Pokemon]:
        return self.player_team if side == "player" else self.enemy_team

    def active_index(self, side: str) -> int:
        return self.player_active if side == "player" else self.enemy_active

    def active_mon(self, side: str) -> Pokemon:
        team = self.side_team(side)
        return team[self.active_index(side)]

    def set_active_index(self, side: str, idx: int) -> None:
        if side == "player":
            self.player_active = idx
        else:
            self.enemy_active = idx

    def other_side(self, side: str) -> str:
        return "enemy" if side == "player" else "player"

    # -- terminal checks ---------------------------------------------------
    def team_wiped(self, side: str) -> bool:
        return all(p.is_fainted for p in self.side_team(side))

    def is_terminal(self) -> bool:
        return self.team_wiped("player") or self.team_wiped("enemy")

    def winner(self) -> str | None:
        if self.team_wiped("enemy") and not self.team_wiped("player"):
            return "player"
        if self.team_wiped("player") and not self.team_wiped("enemy"):
            return "enemy"
        if self.team_wiped("player") and self.team_wiped("enemy"):
            return "draw"
        return None

    # -- legal actions -------------------------------------------------
    def legal_actions(self, side: str) -> list[dict]:
        """
        Returns a list of legal action dicts:
          {"type": "move", "move_index": i}
          {"type": "switch", "target_index": i}
        A fainted active Pokemon can only switch (forced switch).
        """
        actions = []
        mon = self.active_mon(side)
        team = self.side_team(side)

        if not mon.is_fainted:
            for i, mv in enumerate(mon.moves):
                if mv.pp > 0:
                    actions.append({"type": "move", "move_index": i})
            # If no PP left anywhere, Struggle would apply -- omitted in Phase 1.

        for i, p in enumerate(team):
            if i != self.active_index(side) and not p.is_fainted:
                actions.append({"type": "switch", "target_index": i})

        return actions

    def clone(self) -> "BattleState":
        return copy.deepcopy(self)

    def describe_active(self) -> str:
        p = self.player_mon
        e = self.enemy_mon
        return (
            f"Turn {self.turn} | "
            f"YOU: {p.display_name()} {p.current_hp}/{p.max_hp}HP"
            f"{f' [{p.status}]' if p.status else ''} vs "
            f"OPP: {e.display_name()} {e.current_hp}/{e.max_hp}HP"
            f"{f' [{e.status}]' if e.status else ''}"
        )
