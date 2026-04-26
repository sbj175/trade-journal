"""Test fixtures: reusable transaction sequences representing canonical
real-world (or carefully-constructed) trading scenarios.

Each fixture module exposes a function that returns a list of
raw_transaction dicts compatible with `reprocess()`. Tests import these
instead of building the same scenario inline, so:
  - the same scenario is exercised by multiple tests (regression +
    label + chain + summary checks all reuse one input),
  - bug repros become reusable assets — when we fix a bug we drop a
    fixture here so the regression test reads cleanly,
  - real-world account dumps (anonymized) can become fixtures for
    end-to-end golden-snapshot tests.

See OPT-278 for the broader test-depth strategy.
"""
