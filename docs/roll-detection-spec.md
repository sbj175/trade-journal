# Roll Detection Spec

This is the canonical written definition of what counts as a "roll" in
OptionLedger. The implementation in `src/pipeline/lot_lineage.py`
(`detect_lot_lineage`, `derive_rolled_from_group_id`) follows this
spec; the `RollChainModal` "learn more" UI is the user-facing summary
of it.

When a real-world case doesn't match user intuition, **the first
question is "where does this case fit in the spec?"** — not "what code
do we change?" If a case isn't covered, the spec is amended (with a
worked example) before the code is touched.

Each rule below has a one-line statement, a rationale, and a worked
example or named scenario fixture under `tests/fixtures/`.

---

## 0. Foundational principles

Two principles sit above the detection rules and override them when
they conflict.

### 0.1 Broker order/ticket structure is not authoritative

We **do not** treat the broker's `order_id`, ticket structure, or any
field derived from them (including `lot.chain_id`, which Stage 3
propagates from a ROLLING broker order) as the structural truth of
whether something is a roll. Different brokers bundle multi-leg trades
differently; tastytrade in particular emits a single ROLLING ticket
when a trader fills a "close + open" net-credit order, even when the
opens exceed the closes (a roll-plus-add). Trusting the ticket would
mislabel the add as a roll continuation.

The structural truth is **same-day, lot-level pairing of compatible
closes and opens** (rule §1). Chain identity is at most a hint that
may speed lookup; it cannot be the deciding factor.

### 0.2 A lot is in at most one chain

Every closed lot pairs with at most one newly-opened lot of compatible
shape on the same day; that pair is a roll. Lots that don't pair are
new business, not a chain continuation. This guarantees portfolio
totals are additive across chains: total realized P&L = sum of
chain P&Ls, with no overlap.

When the trader closes N contracts and opens M of compatible shape on
the same day, the smaller of (N, M) lots are paired (roll); any
excess on either side is independent (closes that aren't paired with
an open are simple closes; opens that aren't paired with a close are
new positions).

---

## 1. What a roll is

A **roll** is a deliberate position adjustment a trader makes to
either capture more profit or reduce risk, by closing an existing lot
and opening a similar new lot the same day. The trade idea persists;
only the strikes, expiration, or both change.

Rolls live at the **lot level**: each newly-opened lot can have at
most one parent lot (`position_lots.parent_lot_id`), the closing lot
it continued from. Group-level chain lineage (`position_groups.
rolled_from_group_id`) is a derived view of synchronized lot rolls
(§4).

### 1.1 Lot-level pairing rule

Two lots — a closed source lot and a newly-opened target lot — pair
as a roll if and only if **all** of:

1. **Same account.** Cross-account links are out of scope.
2. **Same underlying.** Always.
3. **Same calendar day.** The source lot's MANUAL closing event falls
   on the same calendar day as the target lot's `entry_date`.
   Intra-day timing (hours apart) is fine; cross-day is not.
4. **Same shape.** Both lots share the same `(option_type,
   sign-of-quantity)` — e.g., a closed short Call pairs only with a
   newly-opened short Call.

Within a same-day, same-(account, underlying, shape) **bucket**, the
algorithm pairs greedily by closest strike: at each step, the
remaining (close, open) pair with the smallest `|close.strike -
open.strike|` is bound, then both are removed from the pool. A close
or an open that has no remaining counterpart in its bucket is
unpaired — that lot is independent (a simple close or a new open).

Per spec §0.2, each lot pairs at most once. The greedy match is the
default partition rule; manual link/split (§6) lets the trader
override at the lot-pair level.

---

## 2. What a roll is NOT

The following are **not** rolls, even when same-day, same-account, and
same-underlying are all true:

- **Cross-direction shifts.** A closed long Put cannot pair with a
  newly-opened short Put — the shape rule (§1.1.4) keeps the directional
  thesis intact. Iron Condor (neutral) → Bull Call Spread (bullish) is
  a new trade, not a roll: the multiset of lot shapes is different,
  so most lots have no compatible counterparts and stay unpaired.

- **Risk-profile shifts.** Iron Condor → Short Strangle (drops the
  protective wings — defined-risk to undefined-risk) is a new trade.
  Same direction overall, but the wing-leg lots have no closes to
  pair with (or vice versa), so those lots stand alone.
  Symmetrically: Short Put → Bull Put Spread (adds protection through
  a *full close + reopen*) is also a new trade — the added long-put
  leg has no closing counterpart and starts a fresh chain.

- **Closes via expiration, assignment, or exercise.** A roll requires
  a **manual** closing event (BTC/STC). When the contract finishes
  itself — expires worthless, gets assigned, or is exercised — and
  the trader later opens a new lot the same day, the new lot has no
  manual closing to pair against and starts a fresh chain.
  *Expiration and roll are mutually exclusive.* Encoded directly: the
  pairing pool only contains closings of `closing_type == 'MANUAL'`.

- **Equity-only positions.** Shares can be sold and re-bought; that's
  not modeled as a "roll" in OptionLedger. Out of scope.

- **Quantity overflow on the open side.** When closes-of-shape-X have
  fewer lots than opens-of-shape-X on the same day, the greedy match
  consumes the closes; the leftover opens are new business (the
  IBIT-class "roll + add" case). Symmetrically, when there are more
  closes than opens, the leftover closes are simple closes that
  weren't rolled into anything.

## 3. Adjustments (a separate concept)

An **adjustment** modifies a still-open position without fully closing
it. Adjustments are not rolls — at the *group* level, no new group
is produced. Individual leg lots may still have lot-level lineage
(see §4), but the position group itself stays alive and its shape
evolves.

Examples:

- **Adding protection.** You hold a Short Put and later open a long
  put at a lower strike (no closing event on the existing leg). The
  group's `strategy_label` evolves from `Short Put` to `Bull Put
  Spread`. The new long-put lot has no parent (nothing closed); the
  short-put lot is unchanged. No group-level roll.

- **Partial-leg roll.** You hold an Iron Condor and roll *only* the
  put wing — close the put spread, open a new put spread at different
  strikes — leaving the call spread untouched. The new put lots get
  `parent_lot_id` set (lot-level continuation), but because the call
  legs are still open, the group itself is not fully closed. The new
  put lots merge into the existing group as the next chapter of that
  position. No group-level roll, even though there's lot-level
  lineage.

- **Sizing up by adding contracts.** You hold a 5x position and open
  5 more contracts at the same strikes. No closing event → the new
  lots have no parent → adjustment.

The discriminator for *group-level* roll is in
`derive_rolled_from_group_id`: a target group has `rolled_from = source`
iff every lot in the target has a `parent_lot_id` pointing into the
same source group AND that source group is fully CLOSED. Otherwise
NULL — partial coverage means an adjustment, not a roll.

## 4. The unified group model

A `position_group` represents **one logical position at one
expiration**. A group is a *view* of co-occurring lots that share
state (account, underlying, expiration); chain identity lives at the
lot level, and the group's `rolled_from_group_id` is derived from the
lot-level lineage under §3's all-lots-paired-into-one-closed-source
rule.

**Same-shape lots at the same (account, underlying, expiration) merge
into one group.** This covers broker multi-fill (one order filled at
multiple prices generates multiple lots), sizing-up (adding contracts
to an existing position), and any same-day-or-later add at the same
shape. Auto-detection treats all of these as one logical position,
matching how brokers (TastyTrade, etc.) display the position.

Genuinely parallel positions of the same shape — two distinct trade
ideas held simultaneously at the same strike and expiration — are
exotic and out of scope for auto-detection. The user can split them
explicitly via manual link/split (§6).

Roll dynamics are the same for same-expiration rolls and different-
expiration rolls:

- **Source fully closes** at time T1 (every lot has a manual closing).
- **New position opens** at time T2 (same calendar day, T2 > T1) with
  every lot pairing into the source.
- New position becomes a new group; `rolled_from_group_id` points at
  the source group.

The roll-counter badge in the UI counts the length of the
`rolled_from` chain — i.e., the number of synchronized full
close-and-reopen events.

(Historical note: a previous design merged same-exp full-close-and-
reopen sequences into a single group with a counter. That was retired
in favor of the lot-lineage model in OPT-284. A separate earlier rule
"two simultaneous positions = two groups" applied the same merge-
prevention to same-shape opens at same expiration; that was reversed
when it was found to split multi-fill orders into spurious sibling
groups, contradicting §3's adjustment semantics.)

## 5. Multi-roll dynamics

### 5.1 Cascade — multiple rolls in one day

10am: BTC Jul IC, STO Aug IC. 2pm: BTC Aug IC, STO Sep IC.

Three groups, two links: `Jul → Aug → Sep`. At the lot level, each
of the four IC legs has a chain `Jul-leg → Aug-leg → Sep-leg`, so
the group-level lineage is a clean derivation. The `Aug` group was
open for ~4 hours — that's fine; its lifetime is the only thing that
matters for the model.

### 5.2 Branching — one source, multiple children

Branching at the **lot** level is impossible by construction: each
lot has at most one parent (spec §0.2). Branching at the **group**
level is possible when a single source group's lots split into
multiple new groups.

Worked example: you close a 5x IC at one expiration. Same day you
open 3x IC at a new expiration AND 2x IC at a different new
expiration. At the lot level, the 5 closes pair with the 5 opens
(3 to one new group, 2 to the other) under closest-strike greedy
match within each (option_type, direction) bucket. At the group
level, both new groups have every-lot-paired-into-source, so both
get `rolled_from_group_id = source`. The group graph branches.

The roll-chain summary handles this correctly: one summary row per
leaf group, with `cumulative_realized_pnl` computed by walking
**lot-level** lineage from the leaf-group's lots back to roots
(`src/pipeline/roll_chain_summary.py`). Each lot is in exactly one
chain's lineage, so summed cumulative P&L is additive across all
chains — `Σ chain.cumulative_realized_pnl = Σ lot.realized_pnl`,
no double-counting of the trunk.

If the trader's intent was different — e.g., they *meant* one branch
to be the roll continuation and the other to be a fresh trade —
manual link/split (§6) is the override.

### 5.3 No active-at-close filter is needed

Under the lot-level model, a "mid-life rolled-out" leg of a source
group naturally falls out of the pairing pool: its closing event is
on a day other than the target's entry day, so they never enter the
same bucket. Earlier versions of this spec called for an explicit
"active-at-close filter" at the group level; the lot model handles
it automatically.

## 6. User overrides (manual link / split)

Auto-detection aims for ~95% correctness. The remaining edges are
covered by two manual escape hatches at the lot-pair level:

- **Manual link.** The user explicitly designates two lots as a
  roll pair, even if the auto-pairing left them unmatched (e.g.,
  cross-day, partition into a non-default branch, etc.). System
  writes `parent_lot_id` and marks it as user-overridden so subsequent
  reprocesses don't undo it.

- **Manual split.** The user breaks an auto-detected lot pair, marking
  the two lots as independent.

Both interactions are first-class data: stored in a separate column
or table alongside `position_lots`, read by `detect_lot_lineage` but
never overwritten by it. (Same model as
`strategy_label_user_override`.)

The UI offers two granularities:
- **System suggestion.** When the auto-pairing is uncertain (e.g., a
  partition with strike-distance ties), it surfaces the candidates
  as a "looks like a roll — confirm?" prompt.
- **Direct user action.** The user can link or split any two lots
  themselves, regardless of what the system thinks.

(Implementation status: not yet built. Tracked separately.)

## 7. Default policy

When ambiguous, **default to "roll."** A roll classification means
the system tracks cumulative P&L across the chain automatically.
Marking something as a new trade puts that work back on the user.
The override direction is "I disagree with the auto-pair" (rare); the
default direction is "auto-pair is right" (common).

## 8. Out of scope

These cases are explicitly not handled by the roll spec:

- Equity-only "rolls" (selling shares and re-buying)
- Cross-account roll detection
- Corporate actions (stock split, ticker change, mergers) — handled
  at the symbol-change layer in `order_assembler.py`, not the roll
  layer

## 9. Test coverage

Each rule above has at least one test in `tests/unit/test_lot_lineage.py`
(detection rules) and `tests/unit/test_roll_chain_summary.py`
(group-level derivation and additivity). Worked examples like the
IBIT roll+add (`test_roll_plus_add_pairs_only_closest_strike`) and
the 5→3+2 partition (`test_partition_5_into_3_plus_2_cumulative_is_additive`)
are encoded directly as test fixtures. Adding a new spec branch means
adding a fixture and a test row — no new test class needed.

(See OPT-281 for the foundational principles §0.1/§0.2, OPT-284 for
the lot-level migration this spec describes, and OPT-278 for the
broader test-depth program this spec sits inside.)
