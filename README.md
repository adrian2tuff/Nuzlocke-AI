# nuzlocke_ai — Battle Engine + Search

Pure Python, no dependencies. Run `python demo.py` to see the engine in action.

## What the engine delivers

The core milestone is:

```
state + action → exact resulting state
```

That's `engine/simulator.py::step()`. Give it a `BattleState`, an action for each side, and a seeded `random.Random` — you get a new state back, and the same seed produces the same result.

The second major piece is `enumerate_turn_outcomes()`. Instead of rolling the dice once, it enumerates the modeled RNG outcomes and returns their probability distribution over resulting states. `summarize_risk()` turns those outcomes into guaranteed / robust / risky / catastrophic risk information.

## Structure

```
nuzlocke_ai/
├── engine/
│   ├── mechanics.py   type chart, natures, stat-stage tables, status constants
│   ├── pokemon.py     Species / Move / Pokemon data model + stat calculation
│   ├── damage.py      damage formula + exact 16-roll damage distribution
│   ├── state.py       BattleState, Field, legal-action generation
│   └── simulator.py   seeded step() + probabilistic outcome enumeration
├── environment/
│   └── loader.py      JSON → engine objects
├── data/
│   ├── pokemon.json   species base stats/types
│   ├── moves.json     move data
│   └── trainers.json  trainer teams
├── search/
│   ├── evaluator.py
│   ├── expectiminimax.py
│   └── replaceability.py
├── demo.py
├── demo_search.py
└── demo_replaceability.py
```

## Mechanics currently implemented

The engine now models substantially more than the original Phase 1 prototype:

- Accuracy, critical hits, exact damage rolls, type effectiveness, STAB, stat stages, weather and terrain modifiers.
- Major statuses including burn, paralysis, sleep, and freeze.
- Full paralysis branching during outcome enumeration.
- Sleep turn progression and freeze thaw branching.
- Genuine speed ties: 50/50 in `step()` and in outcome enumeration.
- Secondary effects with their configured probabilities.
- Multi-hit moves with 2–5 hit distributions.
- Recoil and HP drain.
- Flinching.
- Protect, including consecutive-use failure chances and one-turn protection.
- Hazards including Stealth Rock, Spikes, and Toxic Spikes.
- Weather and terrain-setting moves.
- Relevant implemented abilities/items including Levitate, Rough Skin, Life Orb, and Leftovers.
- Switching, hazards on switch-in, and stat-stage reset behavior.

### Multi-hit modeling

Multi-hit moves use the standard modeled 2–5 hit probability distribution:

| Hits | Probability |
|------|-------------|
| 2    | 35%         |
| 3    | 35%         |
| 4    | 15%         |
| 5    | 15%         |

The simulator resolves hits sequentially, so a defender can faint before later hits occur. Multi-hit moves are also represented in `enumerate_turn_outcomes()` rather than being treated as a single lump-sum damage event.

The remaining work is to make every per-hit random component fully independent in exact enumeration: each hit should have its own crit roll, damage roll, and secondary-effect roll. The implementation should preserve early-KO behavior without creating an unmanageable Cartesian-product explosion.

## Updating a trainer's team

No code changes are required. Edit `data/trainers.json`:

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

If a species or move isn't in `data/pokemon.json` / `data/moves.json`, `loader.py` raises a clear `KeyError` rather than silently guessing.

Adding a new species or move follows the same JSON-only pattern.

## Phase 2 — search

`search/evaluator.py` provides a hand-written, non-learning position score.

`search/expectiminimax.py` implements expectiminimax search: the enemy action is treated adversarially, while the game's actual RNG is averaged according to its probabilities.

The search also uses alpha-beta-style pruning, move ordering, transposition caching, and optimized state cloning. These substantially reduce the cost of deeper search compared with the original implementation.

### Current performance direction

Depth 1 is fast enough for interactive analysis. Depth 2 has been reduced dramatically from the original ~180-second baseline through pruning, caching, cloning, and RNG-related optimizations.

The current priority is mechanics completeness and correct probability modeling rather than micro-optimizing small remaining hotspots. Once the model is more complete, deeper-search optimizations can be evaluated against real benchmarks.

## Phase 3 — replaceability

`search/replaceability.py` scores how replaceable each Pokemon is within the current team.

It considers:

- attacking-style redundancy
- type-coverage overlap
- unique utility such as recovery, hazards, or status
- the effect of losing a Pokemon on the evaluator's team score

The goal is Nuzlocke-specific decision support: losing a redundant Pokemon can be materially different from losing the team's only answer to an important role.

Run:

```bash
python demo_replaceability.py
```

## Phase 3.5 — randomness and status coverage

The major previously-unmodeled randomness gaps have been substantially closed:

- **Full paralysis:** 25% fail-to-act / 75% act normally.
- **Speed ties:** 50/50 when both sides have equal effective speed and priority.
- **Sleep:** remaining sleep turns are tracked and wake-up is represented during enumeration.
- **Freeze:** thawing is represented with a 20% per-turn thaw branch.
- **Multi-hit:** hit count is probabilistic and sequentially resolved.

`summarize_risk()` reports whether its result is exact relative to the randomness currently modeled and identifies any remaining unmodeled randomness.

## Testing

Run the simulator tests from the repository root:

```bash
python -m unittest tests.test_simulator -v
```

Run the replaceability tests with:

```bash
python -m unittest tests.test_replaceability -v
```

The test suite is intended to protect mechanics as the engine grows, especially around RNG branching, status timing, switching, hazards, and multi-hit resolution.

## Current next steps

1. Finish exact per-hit multi-hit RNG enumeration:
   - independent crits
   - independent damage rolls
   - independent secondary-effect rolls
   - exact early-KO behavior
2. Expand move/ability/item coverage.
3. Improve exact probability handling for more complex interactions.
4. Continue search optimization after mechanics are stable.
5. Expand Nuzlocke-specific evaluation using future encounters/trainers and run-level value.
