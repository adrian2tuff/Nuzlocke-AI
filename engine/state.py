"""
BattleState: everything needed to fully determine what happens next.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from .pokemon import Pokemon


@dataclass
class Field:
    weather: str | None = None
    weather_turns: int = 0
    terrain: str | None = None
    terrain_turns: int = 0
    hazards: dict = dc_field(default_factory=lambda: {
        "player": {"stealth_rock": False, "spikes": 0, "toxic_spikes": 0, "sticky_web": False},
        "enemy": {"stealth_rock": False, "spikes": 0, "toxic_spikes": 0, "sticky_web": False},
    })
    screens: dict = dc_field(default_factory=lambda: {
        "player": {"reflect": 0, "light_screen": 0},
        "enemy": {"reflect": 0, "light_screen": 0},
    })
    trick_room_turns: int = 0
    tailwind_turns: dict = dc_field(default_factory=lambda: {"player": 0, "enemy": 0})


@dataclass
class BattleState:
    player_team: list[Pokemon]
    enemy_team: list[Pokemon]
    player_active: int = 0
    enemy_active: int = 0
    field: Field = dc_field(default_factory=Field)
    turn: int = 0
    log: list[str] = dc_field(default_factory=list)

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
        return self.side_team(side)[self.active_index(side)]

    def set_active_index(self, side: str, idx: int) -> None:
        if side == "player":
            self.player_active = idx
        else:
            self.enemy_active = idx

    def other_side(self, side: str) -> str:
        return "enemy" if side == "player" else "player"

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

    def legal_actions(self, side: str) -> list[dict]:
        actions = []
        mon = self.active_mon(side)
        team = self.side_team(side)

        if not mon.is_fainted:
            if mon.item in ("choice-band", "choice-specs", "choice-scarf") and mon.choice_lock is not None:
                mv = mon.moves[mon.choice_lock]
                if mv.pp > 0:
                    actions.append({"type": "move", "move_index": mon.choice_lock})
            else:
                for i, mv in enumerate(mon.moves):
                    if mv.pp > 0:
                        # Choice items cannot select status moves.
                        if mon.item in ("choice-band", "choice-specs", "choice-scarf") and mv.category == "status":
                            continue
                        actions.append({"type": "move", "move_index": i})

        # Trapping effects such as Mean Look prevent a voluntary switch.
        # A fainted active still gets forced-switch actions above.
        if "trapped" not in mon.volatile:
            for i, p in enumerate(team):
                if i != self.active_index(side) and not p.is_fainted:
                    actions.append({"type": "switch", "target_index": i})

        return actions

    def clone(self) -> "BattleState":
        clone = object.__new__(BattleState)
        clone.__dict__ = self.__dict__.copy()
        clone.player_team = [p.clone() for p in self.player_team]
        clone.enemy_team = [p.clone() for p in self.enemy_team]
        clone.field = object.__new__(Field)
        clone.field.__dict__ = self.field.__dict__.copy()
        clone.field.hazards = {
            side: values.copy() for side, values in self.field.hazards.items()
        }
        clone.field.screens = {
            side: values.copy() for side, values in self.field.screens.items()
        }
        clone.log = self.log.copy()
        return clone

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
