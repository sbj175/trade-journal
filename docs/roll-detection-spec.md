# Roll Detection Spec

This is the canonical written definition of what counts as a "roll" in
OptionLedger. The implementation in `src/pipeline/group_manager.py`
(`_detect_roll_links`, `_route_lot_to_group`) follows this spec; the
`RollChainModal` "learn more" UI is the user-facing summary of it.

When a real-world case doesn't match user intuition, **the first
question is "where does this case fit in the spec?"** — not "what code
do we change?" If a case isn't covered, the spec is amended (with a
worked example) before the code is touched.

Each rule below has a one-line statement, a rationale, and a worked
example or named scenario fixture under `tests/fixtures/`.

---

## 1. What a roll is

A **roll** is a deliberate position adjustment a trader makes to either
capture more profit or reduce risk, by closing all or part of an
existing position and opening a similar new position the same day. The
trade idea persists; only the strikes, expiration, or both change.

Three conditions must all be true for two position groups to be linked
as a roll:

1. **Same account.** Cross-account links are out of scope.
2. **Same underlying.** Always.
3. **Same calendar day.** The source group's `closing_date` must fall on
   the same calendar day as the target group's `opening_date`. Intra-day
   timing (hours apart) is fine; cross-day is not.

Plus a structural condition (one of):

4. **Chain overlap.** Source and target share at least one `lot.chain_id`
   — i.e., Stage 3 (`position_ledger`) inherited the chain from a
   ROLLING broker order. This captures rolls where a single broker
   action closed the old position and opened the new one.
5. **Leg-shape signature match.** When chain overlap doesn't fire (e.g.,
   the trader closed and re-opened in separate broker orders), the
   source's *active-at-close* lots and the target's lots share the same
   multiset of `(option_type, sign-of-quantity)`. Captures the
   documented "legged out and back in" case (`tests/fixtures/non_roll_*`
   and `roll_*` modules will codify this).

If none of (4)/(5) holds, the groups are independent — no link.

## 2. What a roll is NOT

The following are **not** rolls, even when same-day, same-account, and
same-underlying are all true:

- **Cross-direction shifts.** Iron Condor (neutral) → Bull Call Spread
  (bullish) is a new trade, not a roll. The directional thesis must
  match. Encoded structurally via the leg-shape signature: a bullish
  spread has a different multiset than a neutral one.

- **Risk-profile shifts.** Iron Condor → Short Strangle (drops the
  protective wings — defined-risk to undefined-risk) is a new trade.
  Same direction, but a fundamentally different risk posture.
  Symmetrically: Short Put → Bull Put Spread (adds protection through a
  *full close + reopen*) is also a new trade.

- **Closes via expiration, assignment, or exercise.** A roll requires a
  **manual** closing event (BTC/STC). When the contract finishes itself
  — expires worthless, gets assigned, or is exercised — and the trader
  later opens a new position the same day, the new position is a fresh
  trade, not a roll. *Expiration and roll are mutually exclusive.*

- **Equity-only positions.** Shares can be sold and re-bought; that's
  not modeled as a "roll" in OptionLedger. Out of scope.

## 3. Adjustments (a separate concept)

An **adjustment** modifies a still-open position without fully closing
it. Adjustments are not rolls — they don't produce a new group, and they
don't increment any roll counter. The position group stays the same; its
shape evolves.

Examples:

- **Adding protection.** You hold a Short Put and later open a long put
  at a lower strike (no closing event). The group's `strategy_label`
  evolves from `Short Put` to `Bull Put Spread`. No roll.

- **Partial-leg roll.** You hold an Iron Condor and roll *only* the put
  wing — close the put spread, open a new put spread at different
  strikes — leaving the call spread untouched. The group still has open
  lots (the calls), so the new puts merge into the existing group as
  the next chapter of that position. No roll.

- **Sizing up by adding contracts.** You hold a 5x position and open 5
  more contracts at the same strikes. No closing event → adjustment.

The discriminator is **structural, not interpretive**: source still has
open lots → adjustment; source fully closed → potential roll candidate.
The routing rules in `_route_lot_to_group` encode this directly via the
"any existing lot shares state" check on Rule 0.

## 4. The unified group model

A `position_group` represents **one logical position at one expiration**.
Two simultaneous similar positions on the same expiration are
**two groups**. The system never tries to fuse parallel positions of the
same shape on the same expiration into one group.

This is the same rule for both same-expiration rolls and different-
expiration rolls:

- **Source fully closes** at time T1.
- **New position opens** at time T2 (same calendar day, T2 > T1).
- New position becomes a new group; `rolled_from_group_id` points at the
  source group.

The roll-counter badge in the UI counts the length of the
`rolled_from` chain.

(Historical note: a previous design merged same-exp full-close-and-
reopen sequences into a single group with a counter. This was retired
in favor of the unified model; the structural rule "two simultaneous
positions = two groups" implies that even sequential same-exp
positions are two groups since each is the position at its moment in
time.)

## 5. Multi-roll dynamics

### 5.1 Cascade — multiple rolls in one day

10am: BTC Jul IC, STO Aug IC. 2pm: BTC Aug IC, STO Sep IC.

Three groups, two links: `Jul → Aug → Sep`. Each close+reopen creates a
separate generation. The `Aug` group was open for ~4 hours — that's
fine; its lifetime is the only thing that matters for the model.

### 5.2 Branching — one source, many children

You close a 5x IC at one expiration. Same day you open 3x IC at a new
expiration AND 2x IC at a different new expiration. Both children
match the source's signature (same shape, neutral direction).

Both link as rolls of the source. The `rolled_from_group_id` graph is
a *tree*, not a linked list.

### 5.3 Tie-breaking among multiple sources

When a target has more than one qualifying source candidate (e.g.,
during a cascade), the algorithm prefers:

1. **Chain-overlap** candidates over signature-only candidates
2. **Most recently closed** source (by `closing_date` timestamp) before
   falling back to lot count
3. **Closest lot count** as a final tie-break

## 6. Active-at-close signature filter

When computing the signature for a source candidate (rule 5 above), only
lots that **closed on the source's `closing_day`** are included.
Mid-life rolled-out legs (closed earlier in the source's lifetime) do
not contribute to the signature.

Worked example (real, from USO history):

The source group's lifetime included a put-wing roll mid-way:

```
Jun 2:  long Put 58 (entry)            ┓
Jun 2:  short Put 63 (entry)           ┃ original 4-leg IC
Jun 2:  short Call 75 (entry)          ┃
Jun 2:  long Call 80 (entry)           ┛
Jun 17: STC long Put 58, BTC short Put 63   ← put wing rolled out
Jun 17: BTO long Put 70, STO short Put 75   ← new put wing opens
                                            (merged into same group as adjustment)
Jun 27: BTC short Call 75, STC long Call 80 ┓
Jun 27: BTC short Put 75, STC long Put 70   ┛ all 4 active legs close
```

At Jun 27 close, the *active* legs were Put 70 long, Put 75 short, Call
75 short, Call 80 long — multiset `{(P,L):1, (P,S):1, (C,S):1, (C,L):1}`,
which matches a fresh 4-leg IC opened the same day. The rolled-out Put
58/63 spread is excluded from the signature.

Without this filter the signature would inflate to `{(P,L):2, (P,S):2,
(C,S):1, (C,L):1}` and the link would not form.

## 7. User overrides (manual link / split)

Auto-detection aims for ~95% correctness. The remaining edges are
covered by two manual escape hatches:

- **Manual link.** The user explicitly designates two groups as a roll
  chain. System writes the `rolled_from_group_id` and marks it as
  user-overridden so subsequent reprocesses don't undo it.

- **Manual split.** The user breaks an auto-detected roll link, marking
  the two groups as independent.

Both interactions are first-class data: stored in a separate column or
table alongside `position_groups`, read by `_detect_roll_links` but
never overwritten by it. (Same model as `strategy_label_user_override`.)

The UI offers two granularities:
- **System suggestion.** When the auto-detector is uncertain (e.g., a
  signature match with a low-confidence tie-break), it surfaces the
  candidates as a "looks like a roll — confirm?" prompt.
- **Direct user action.** The user can link or split any two groups
  themselves, regardless of what the system thinks.

## 8. Default policy

When ambiguous, **default to "roll."** A roll classification means the
system tracks cumulative P&L across the chain automatically. Marking
something as a new trade puts that work back on the user. The override
direction is "I disagree with the auto-link" (rare); the default
direction is "auto-link is right" (common).

## 9. Out of scope

These cases are explicitly not handled by the roll spec:

- Equity-only "rolls" (selling shares and re-buying)
- Cross-account roll detection
- Corporate actions (stock split, ticker change, mergers) — handled at
  the symbol-change layer in `order_assembler.py`, not the roll layer

## 10. Test coverage

Each rule above has at least one fixture under `tests/fixtures/` and a
parameterized assertion in `tests/integration/test_roll_detection_spec.py`.
Adding a new spec branch means adding a fixture and a row in the test
matrix — no new test class needed.

(See OPT-281 for the test-matrix scaffolding and OPT-278 for the broader
test-depth program this spec sits inside.)
