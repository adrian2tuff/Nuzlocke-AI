# nuzlocke_ai — Phase 1: the battle engine

Pure Python, no dependencies. Run `python demo.py` to see it work.

## What Phase 1 actually delivers

The concrete milestone from the plan:

```
state + action → exact resulting state
```

That's `engine/simulator.py::step()`. Give it a `BattleState`, an action for
each side, and a *seeded* `random.Random` — you get a brand-new state back,
and the same seed always produces the same result. That reproducibility is
what makes this usable as ground truth later (for search, and eventually
for training data).

The second piece — the actual point of a "near-riskless line" finder — is
`enumerate_turn_outcomes()`. Instead of rolling the dice once, it walks
*every* combination of hit/miss, crit/no-crit, and damage roll for both
Pokémon's moves, and hands back the full probability distribution over
resulting states. `summarize_risk()` turns that into the guaranteed /
robust / risky / catastrophic language from your plan — specifically, it
distinguishes "this Pokémon might faint" from "this run-ends-here", because
those are very different things in a Nuzlocke.

## Structure

```
nuzlocke_ai/
├── engine/
│   ├── mechanics.py   type chart, natures, stat-stage tables, status constants
│   ├── pokemon.py     Species / Move / Pokemon data model + stat calculation
│   ├── damage.py       damage formula, 16-roll damage distribution
│   ├── state.py         BattleState, Field, legal-action generation
│   └── simulator.py    step() [exact+seeded] and enumerate_turn_outcomes() [exact distribution]
├── environment/
│   └── loader.py        JSON → engine objects (the ONLY file that touches file I/O)
├── data/
│   ├── pokemon.json     species base stats/types
│   ├── moves.json        move data
│   └── trainers.json     trainer teams  <-- edit this to change a trainer
├── search/               empty — this is Phase 2
├── mcp/                  empty — this is Phase 4
└── demo.py               runnable proof of the two milestones above
```

## Updating a trainer's team

No code. Open `data/trainers.json` and edit the team, e.g.:

```json
"rival_1": {
  "team": [
    { "species": "nidoking", "level": 45, "nature": "adamant",
      "ability": "sheer-force", "item": "life-orb",
      "ivs": {"hp": 31, "atk": 31, "def": 31, "spa": 31, "spd": 31, "spe": 31},
      "evs": {"hp": 4, "atk": 252, "def": 0, "spa": 0, "spd": 0, "spe": 252},
      "moves": ["earthquake", "stone-edge", "sludge-wave", "ice-beam"] }
  ]
}
```

If a species or move isn't in `data/pokemon.json` / `data/moves.json` yet,
`loader.py` will raise a clear `KeyError` telling you which one to add and
where — it won't fail silently or guess.

Adding a new species/move is the same pattern — one JSON entry, no engine
changes:

```json
// data/pokemon.json
"dragonite": {"types": ["dragon", "flying"], "base_stats": {"hp": 91, "atk": 134, "def": 95, "spa": 100, "spd": 100, "spe": 80}}

// data/moves.json
"outrage": {"type": "dragon", "category": "physical", "power": 120, "accuracy": 100, "pp": 10}
```

## What's deliberately stubbed for Phase 1

This is a ~10-species/~20-move demo engine meant to prove the architecture,
not a complete mechanics implementation. Things intentionally left out or
simplified (all localized to `simulator.py`/`damage.py`, so extending them
doesn't require restructuring anything):

- **Abilities and items have no effects yet.** They're stored on the
  Pokémon but nothing reads them. (Intimidate, Sturdy, Life Orb recoil,
  Choice lock, weather-setting abilities, etc. all go here next.)
- **Weather/terrain/hazards/screens** exist as fields on `Field` but nothing
  sets or applies them yet (Stealth Rock is defined as a move but doesn't
  do anything on switch-in).
- **Full paralysis, sleep turns, freeze-thaw chance, and confusion** are
  either not implemented or use expected-value logic instead of branching
  in `enumerate_turn_outcomes` (noted in that function's docstring) —
  branching them in is straightforward but increases the branch count.
- **Speed ties** always resolve player-first rather than being 50/50 —
  one line to fix once you decide whether to branch or randomize it.
- **Multi-hit moves, recoil, drain, flinching** aren't wired up.
- **`enumerate_turn_outcomes` branch count** grows fast (currently ~1024 for
  two attacking moves). Fine for single-decision risk-checking; for a full
  search tree you'll want to bucket the 16 damage rolls down to a handful
  (e.g. min/low/mid/high/max) rather than enumerating all of them at every
  node — flagged in the docstring.

None of these require touching `state.py`, `loader.py`, or the data files —
they're additions to `resolve_move()` / `_apply_move_effect()` in
`simulator.py` and `base_power()` in `damage.py`.

## Phase 2 — the search

`search/evaluator.py` — a hand-written, no-learning position score (item #17
from the plan: get a non-neural baseline working first). `+1` = opponent
wiped, `-1` = you're wiped, in between = relative team health/count.

`search/expectiminimax.py` — the actual search. Run `python demo_search.py`.

The key design choice, worth understanding even though you didn't write the
code: for every one of *your* legal actions, it assumes the opponent picks
whichever *their* legal action is worst for you (not just "typical" or
"AI-like" play), then averages over the real RNG on top of that. That's what
makes a result the search calls "safe" an actual guarantee rather than a
"probably fine" — it holds up against the real, weaker in-game AI too,
since the real AI can only be less adversarial than the worst case searched.

### Performance reality check

This is expensive, and it's worth seeing the actual numbers rather than
assuming it'll be fine:

| depth | nodes evaluated | time (3v2 demo matchup) |
|-------|-----------------|--------------------------|
| 1     | 572             | ~1.7s                    |
| 2     | 204,802         | ~91s                     |

That's worst-case-over-enemy-actions × RNG-buckets × turn, compounding every
ply — exactly the blowup flagged in the original plan. `damage_buckets`
(default 3) is already keeping this from being far worse; `enumerate_turn_outcomes(..., damage_buckets=None)`
is still used for the exact immediate-risk numbers reported alongside each
ranked action, so you're not losing precision on "how risky is the very
next turn", only on the approximate lookahead beyond it.

This is usable today at depth 1 (fast, exact) for "what's my best move right
now". Depth 2+ needs one more piece before it's practical on a full team:
**alpha-beta-style pruning** (skip enemy replies that can't possibly change
which player action wins) and/or **caching** (many action orderings reach
the same resulting state). Neither requires restructuring anything here —
they'd go directly into `_value()` in `expectiminimax.py`. Flagging this
rather than building it blind, since it's worth deciding together whether
that's the next step or whether Phase 3 (Nuzlocke-specific run value) is a
better use of time first.

## Bugs found and fixed during Phase 2 testing (worth knowing about)

Real-world testing (switching in Corviknight against a Ground move) caught
the second mover's move being evaluated against the *pre-first-move* state
instead of the state after the first move resolved. Concretely: switching
into a type immunity was being scored as if the *old* Pokemon were still
active, so an immune matchup could show real damage that should've been
zero. Fixed in `enumerate_turn_outcomes` -- the second mover's branches are
now always computed from the state *after* the first mover's action
resolves. Two smaller fixes went in with it: a secondary effect (like
Thunderbolt's 10% paralysis chance) was being forced to 100% during
enumeration instead of respecting its real odds, and switching was
resetting the *incoming* Pokemon's stat stages instead of the *outgoing*
one's. All three now have regression tests -- run:

```
python -m unittest tests.test_simulator -v
```
from inside `nuzlocke_ai/`.

### What "guaranteed" honestly means right now

`summarize_risk()`'s guaranteed/robust/risky/catastrophic tiers are exact
with respect to the randomness this engine currently models (accuracy,
crit, damage roll, secondary-effect chance) -- **not yet a full-game
guarantee**. Not yet branched: full-paralysis (25% miss-turn), sleep/freeze
thaw, and speed ties (currently always resolved player-first instead of
50/50). Every risk result now carries `"exact"` and `"unmodeled_randomness"`
fields so this scope is visible in the returned data, not just in a
comment -- worth closing before leaning on "guaranteed" for anything status-
or speed-tie-heavy.

## Phase 3 — replaceability ("sack Bidoof, not Garchomp")

`search/replaceability.py` scores every Pokemon on a team from 0.0
(irreplaceable -- team has no other answer for what it does) to 1.0
(fully redundant -- losing it changes nothing), using only stats/movepool
already on the team:

- **attacking-style redundancy** -- is this the only physical/special attacker?
- **type-coverage overlap** -- do teammates already hit what this Pokemon hits?
- **unique utility** -- only Recover-user? Only hazard-setter? Only status-inflicter?

`search/evaluator.py` now weights each alive Pokemon's contribution to the
score by its irreplaceability, instead of treating every Pokemon as equal.
Run `python demo_replaceability.py` to see the breakdown for the demo team
and a concrete "which faint hurts the score more" comparison.

This is deliberately scoped to the CURRENT team only (no future trainers,
no box) -- see the module docstring for why, and for the natural extension
(feeding in upcoming trainers so "counters the next 3 gyms" becomes part of
the score) once you're ready for that.

`tests/test_replaceability.py` locks in the core claims: the team's sole
special attacker scores as least replaceable, adding a redundant clone
makes the original MORE replaceable, and losing the least-replaceable
Pokemon costs the evaluator more than losing an equally-healthy but more
redundant one.

## Known gap, next up: Phase 3.5 — full-para / sleep-freeze thaw / speed ties

Not done yet, flagged rather than silently skipped (see `unmodeled_randomness`
in `summarize_risk()`'s output). Worth closing before leaning on "guaranteed"
against a real boss with heavier status usage or closer speed stats than
this toy demo team has.

## Phase 3.5 — full paralysis + speed ties (sleep/freeze still open)

Two of the three previously-flagged randomness gaps are closed:

- **Full paralysis**: a paralyzed attacker now branches into "fails to act"
  (25% probability mass) vs. "acts normally" (75%), instead of only being
  handled in the single-sample `step()` path.
- **Speed ties**: a genuine speed tie (equal effective speed, equal
  priority, neither side switching) now branches 50/50 over who acts
  first, both in `enumerate_turn_outcomes` (`order_branches`) and in
  `step()` (via a seeded `rng.random() < 0.5`, so it's still exactly
  reproducible for a given seed -- it just now actually uses that seed to
  decide, instead of always resolving player-first).

**Sleep/freeze thaw is still open, on purpose.** No move in the current
`data/moves.json` inflicts either status, so there's nothing to test that
logic against yet, and the exact turn-counter formula differs across game
generations. Add a sleep- or freeze-inflicting move when you need this, and
we can pick the right formula for whichever game's mechanics you're
targeting and add it with real test coverage -- same pattern as the two
gaps just closed.

`summarize_risk()`'s `unmodeled_randomness` field now only lists
`sleep_freeze_thaw`, reflecting this.
