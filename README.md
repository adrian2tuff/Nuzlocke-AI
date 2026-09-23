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

## Current AI roadmap

The project is moving from a battle simulator into a **Nuzlocke-aware search AI**. The long-term goal is not simply to find the highest-damage move; it is to search for good lines through an entire Nuzlocke while modeling the opponent's actual trainer behavior and the cost of losing irreplaceable Pokemon.

### Phase 4 — Null trainer AI

The enemy policy is being built to approximate the documented **Null battle AI** rather than treating the opponent as a perfect minimax player.

Current coverage includes:

- Move scoring and kill tiers.
- Status, setup, recovery, pivot, phazing, and tactical-move scoring.
- Reactive moves such as Counter, Mirror Coat, and Metal Burst.
- Move-history-dependent behavior such as Encore and Disable.
- Swagger / Flatter synergies.
- Speed, offensive/defensive-stat, and accuracy-lowering behavior.
- Hazard, weather, terrain, Tailwind, and Trick Room considerations.
- Protect / Endure and other tactical edge cases.
- Configurable enemy policies in expectiminimax.

The Null AI is implemented as a policy layer on top of the battle engine. This keeps battle mechanics separate from the question of what an enemy trainer chooses to do.

### Phase 4.5 — Null mechanics and data integration

Null uses Generation 9 mechanics unless the Null mechanic document explicitly overrides them. The battle engine is being updated with a dedicated `engine/null_mechanics.py` layer so these overrides stay separate from the Gen 9 baseline.

Current Null-specific mechanics implemented or being integrated:

- AI/player critical-hit rates.
- 75% paralysis Speed reduction.
- 50% matching-type Electric / Grassy / Psychic Terrain damage boost.
- Sleep turn count resets when a sleeping Pokemon re-enters battle.
- Sheer Force retains its normal 1.3× damage boost while suppressing eligible secondary effects.
- Null battle PP: Player moves have 1 PP; AI moves have 8 PP. This is enabled through the explicit `BattleState(ruleset="null")` ruleset so existing baseline tests and tooling remain unchanged.
- Leaf Guard and Magma Armor prevent critical hits under the Null ruleset.
- Micle Berry gives a one-time 1.5× accuracy multiplier when the holder is at or below 1/4 HP, then is consumed.

A recent regression check also ensures Null terrain/ability/item modifiers remain isolated from unrelated damage modifiers.

Null battle PP is now wired into the battle-state ruleset with regression coverage. Next mechanics are being added incrementally with regression tests, followed by NullDex data integration. The mechanic source also defines Null-specific abilities, held-item behavior, IV generation, Rotom forms/moves, and progression level caps.

### Phase 5 — Doubles battle foundation

Before implementing the Null doubles rules, the engine needs a proper doubles model while preserving the existing 1v1 API.

Planned foundation:

1. Two active Pokemon per side.
2. Independent actions for each active Pokemon.
3. Move targeting: opponent, ally, self, and spread targets.
4. Priority and speed ordering across all actions.
5. Fainting and replacement behavior for individual slots.
6. Doubles-compatible field effects, hazards, weather, and terrain.
7. Backward compatibility with all existing singles behavior.

Once this foundation exists, implement the documented doubles Null AI behavior:

- Helping Hand
- Follow Me / Rage Powder
- Heal Pulse / Floral Healing / Pollen Puff
- Instruct
- Coaching
- Dragon Cheer
- Ally Switch
- Beat Up
- partner ability synergies
- spread-move scoring
- priority / Weakness Policy interactions
- partner-targeted status and utility behavior

### Phase 6 — Stronger expectiminimax

Once the simulator and enemy policy are sufficiently complete:

- Search player actions against the Null enemy policy.
- Preserve exact or bounded RNG probabilities.
- Improve transposition caching and move ordering.
- Add deeper-search performance benchmarks.
- Make search depth adaptive to the tactical position.

### Phase 7 — Nuzlocke-specific strategy

This is where the project becomes more than a battle bot.

The AI should reason about:

- Pokemon replaceability and team roles.
- Future encounters and available replacements.
- Trainer teams and upcoming boss fights.
- Death risk versus expected progress.
- Resource preservation across a route/run.
- When a safe line is preferable to a higher-damage line.
- Long-term value of moves, items, and team members.

The eventual objective is a planner that can answer questions like:

> "Given my current team, available encounters, opponent team, and Nuzlocke rules, what line gives me the best chance of progressing without losing critical team members?"

### Phase 8 — Full Nuzlocke planner

Final integration:

game state → candidate lines → battle simulation → enemy response → RNG branches → long-term evaluation → recommended line

The planner should be able to search across multiple battles rather than treating each fight as an isolated encounter.

## Immediate priority

The next implementation step is **Null mechanics completeness and NullDex integration**. We will finish the battle-relevant Null overrides in small tested slices before starting the doubles foundation. Do not add individual doubles AI rules until the engine can represent and resolve doubles battles correctly.

Mechanics completeness and correctness come before deeper search optimization. Every major engine change should add regression tests and preserve the existing single-battle test suite.
