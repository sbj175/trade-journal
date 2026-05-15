---
id: OPT-45
title: Roll helper
status: Done
priority: None
assignee: Steve Johnson
created: 2026-02-08
completed: 2026-02-12
labels: [Feature]
related: []
linear_url: https://linear.app/optionedge/issue/OPT-45/roll-helper
---

# OPT-45: Roll helper

Core indicators your app should track (ranked by usefulness)

1️⃣ % of Max Value Captured (MOST IMPORTANT)

This is the primary roll trigger.

Indicator

Copy code

Current Spread Value ÷ Max Spread Value

Suggested alerts

🟡 65–70% → “Prepare to roll”

🔴 75–85% → “High roll probability zone”

Why

Once you’re past \~70%, gamma collapses

Remaining upside rarely compensates for theta risk

This is true even if price hasn’t hit the short strike yet

📌 This indicator works better than price alone.

2️⃣ Net Delta of the Spread (Gamma Exhaustion Signal)

Indicator

Copy code

Net Delta approaching maximum possible delta

For a bull call spread:

Max delta ≈ width of the spread × 100

Practical exhaustion often occurs around 0.65–0.75 delta

Suggested alerts

🟡 Delta ≥ 0.60

🔴 Delta ≥ 0.70

Why

High delta means you’re already “acting like stock”

Upside acceleration is gone

Pullbacks hurt more than rallies help

📌 This pairs extremely well with % max value.

3️⃣ Distance to Short Strike (Price-Based Confirmation)

This should be secondary, not primary.

Indicator

Copy code

Underlying price within X% or Y ATR of short strike

Suggested triggers

Within 1–1.5 ATR

Or within 2–4%, depending on volatility

Why

Near the short strike, gains flatten

Rolling before price pins the strike gives you better fills

📌 Use this to confirm, not decide.

4️⃣ Theta-to-Delta Ratio (Advanced, Powerful)

This is an excellent “silent killer” indicator.

Indicator

Copy code

|Theta| ÷ Delta

Alert condition

Theta cost per $1 of delta exceeds a threshold you define (e.g. 0.15–0.25)

Why

Tells you when time decay overwhelms directional benefit

Especially useful 21–30 DTE

This is advanced, but it’s a huge edge if implemented.

Roll decision logic (what kind of roll?)

Your app should recommend the roll type, not just say “roll”.

🔁 Roll UP (same expiration)

Trigger when:

% max value ≥ 70%

Delta ≥ 0.60

DTE still healthy (≥ 25–30 days)

Logic:

You’ve captured the move

Time is still working for you

Underlying momentum intact

Goal:

Reset gamma

Stay in the same trend

🔁 Roll UP AND OUT

Trigger when:

% max value ≥ 70%

Delta ≥ 0.60

DTE ≤ 21–28

Momentum intact

Logic:

Spread is “done”

Theta is accelerating

You want more time + more room

Goal:

Restore convexity

Avoid the flat P&L zone

🛑 Consider Exit (not roll)

Trigger when:

% max value ≥ 75–80%

Delta high

IV contracting

Weak momentum / resistance nearby

Your app should explicitly say:

“Expected additional return does not justify theta risk.”

This is huge — most apps never say this.

Ideal “Roll Readiness” composite score (very implementable)

If you were building OptionEdge (😉), I’d suggest a single score:

Copy code

Roll Score =

  (0.4 × %MaxValue)

\+ (0.3 × DeltaNormalized)

\+ (0.2 × ThetaPressure)

\+ (0.1 × ProximityToShortStrike)

Display it as:

🟢 < 0.50 → Hold

🟡 0.50–0.65 → Monitor

🔴 > 0.65 → Roll likely optimal

This is exactly the kind of thing that differentiates a serious tool from a basic journal.

One-sentence mental model

Roll bull call spreads when the spread has stopped behaving like an option and started behaving like stock.

If you want, next we can:

Tune this specifically for 45 DTE vs 60–90 DTE entries

Compare rolling vs laddering spreads

Translate this into exact tastytrade-style rules or your own OptionEdge presets
