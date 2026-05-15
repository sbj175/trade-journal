---
id: OPT-59
title: DSL for testing
status: Canceled
priority: High
assignee: Steve Johnson
created: 2026-02-15
canceled: 2026-03-01
labels: [Research]
related: []
linear_url: https://linear.app/optionedge/issue/OPT-59/dsl-for-testing
---

# OPT-59: DSL for testing


## Comments

### 2026-02-15 — Steve Johnson

What you need isn’t just “more test cases” — it’s a **systematic way to generate evil trades** and prove your invariants hold.

Let’s build you a testing methodology that fits *OptionLedger* specifically.

---

## Step 1: Write down your **non-negotiable invariants**

Before any code, you want a short list of things that must *always* be true, no matter how weird the trade is.

Examples (adjust to taste):

### Chain invariants

* A chain has exactly **one underlying**
* Every order belongs to exactly **one chain**
* Chain net credit = sum(all fills)
* Chain realized P/L only changes on closes
* Rolls never create or destroy money

### Position invariants

* Positions are derived from chains
* Open positions reflect only **currently open legs**
* Position P/L = broker P/L (within rounding)
* A closed chain has zero open legs

These become your *assertions*, not just expectations.

---

## Step 2: Build a **Trade Scenario DSL** (this is the big unlock)

You need a way to say:

> “Create *this* trade, then roll it *like this*, then partially close it, then do something cursed.”

Not via the UI. Via code.

### Example (pseudo-DSL)

```js
scenario("Rolled bull put spread twice", s => {
  s.open("SPY", "2026-03-20", [
    sellPut(450),
    buyPut(440)
  ], credit=2.10)
  s.rollTo("2026-04-17", [
    sellPut(445),
    buyPut(435)
  ], netCredit=0.65)
  s.partialClose([
    buyPut(445)
  ], debit=0.40)
  s.closeAll(debit=1.10)
})
```

This gives you:

* Deterministic setup
* Human-readable intent
* Repeatability

This is *way* more powerful than mocking raw broker fills.

---

## Step 3: Define a **Trade Matrix** (coverage, not anecdotes)

Now you enumerate axes of pain:

### Structure axis

* Single-leg long
* Vertical spread
* Iron condor
* Broken-wing
* Ratio
* Calendar
* Diagonal

### Lifecycle axis

* No adjustment
* 1 roll
* Multiple rolls
* Partial closes
* Leg-only closes
* Flip from credit → debit

### Accounting axis

* Net credit → net debit
* Debit → credit
* Zero-cost rolls
* Close for exactly $0.00
* Tiny residuals ($0.01)

### Time axis

* Same-day open/close
* Across expirations
* Assignment / expiration
* Early close before assignment

You don’t test *every* combo.

You pick **one representative from each row**, then mix axes deliberately.

That gives you confidence *fast*.

---

## Step 4: Property-based testing (this catches bugs you didn’t imagine)

Once you have a DSL, you can go one level deeper.

Instead of saying *what* the trade is, you say:

> “For all valid trades…”

Examples:

* Net P/L of a chain = sum(realized + unrealized)
* Closing all legs → zero positions
* Replaying fills in any order produces same final P/L
* Rolling preserves exposure continuity

This is where things like:

* Sign errors
* Double-counted credits
* Phantom positions

  get caught.

Even a light version of this pays off.

---

## Step 5: Snapshot testing for UI sanity

Once the math is right, lock it in visually.

For a given scenario:

* Positions table snapshot
* Chain summary snapshot
* Timeline view snapshot

If a refactor breaks something, you’ll *see* it immediately.

This is especially important with roll logic — regressions love to hide there.

---

## Step 6: Keep “Steve’s Real Trades” — but demote them

Your actual trades are still valuable, just not sufficient.

They become:

* Regression tests
* “Does this still match reality?”
* Sanity checks for broker parity

But **never** your only coverage.

---

## Minimal starting point (if you want this lightweight)

If this feels like a lot, start here:

1. Write **5 canonical scenarios** by hand
2. Encode them with a simple scenario builder
3. Assert:
   * Chain P/L
   * Open legs
   * Position rows
4. Run them on every build

You’ll catch 80% of future bugs with 20% of the work.

---

## Why this matters for OptionLedger *specifically*

You’re not just tracking trades — you’re making **implicit promises**:

* “Rolls are accounted correctly”
* “This number means what you think it means”
* “You can trust this more than your memory”

Testing is how you keep those promises *after* the codebase grows.

If you want next:

* I can help you design the exact DSL shape
* Or help you pick the 10 “must never break” scenarios
* Or translate this into your current JS stack

This is the point where a side project quietly turns into a *serious* product.

---

### 2026-03-01 — Steve Johnson

I don't think this will be needed. Canceling.
