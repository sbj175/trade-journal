"""OPT-294 inspection helpers — load opt294_state_partial.json and locate the
suspect Trad IRA IBIT 41.5 group(s).

Run from project root (no DB connection needed):
  python3 scripts/opt294_inspect.py
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path


def main(path: str) -> None:
    state = json.loads(Path(path).read_text())

    groups = state["position_groups"]
    lots = state["position_lots"]
    links = state["position_group_lots"]
    closings = state["lot_closings"]

    print(f"groups       : {len(groups)}")
    print(f"  with rolled_from set    : {sum(1 for g in groups if g.get('rolled_from_group_id'))}")
    print(f"  with rolled_from NULL   : {sum(1 for g in groups if not g.get('rolled_from_group_id'))}")
    print(f"lots         : {len(lots)}")
    print(f"  with parent_lot_id      : {sum(1 for l in lots if l.get('parent_lot_id'))}")
    print(f"  parent_lot_id NULL      : {sum(1 for l in lots if not l.get('parent_lot_id'))}")
    print(f"links        : {len(links)}")
    print(f"closings     : {len(closings)}")

    lots_by_id = {l["id"]: l for l in lots}
    lots_by_txn = {l["transaction_id"]: l for l in lots}

    by_group_txns = defaultdict(list)
    for link in links:
        by_group_txns[link["group_id"]].append(link["transaction_id"])

    def group_lot_ids(group_id):
        return [
            lots_by_txn[t]["id"]
            for t in by_group_txns.get(group_id, [])
            if t in lots_by_txn
        ]

    groups_by_id = {g["group_id"]: g for g in groups}

    print("\n=== Accounts ===")
    for a in state["accounts"]:
        print(f"  {a.get('account_number')} type={a.get('account_type')} nick={a.get('nickname')}")

    print("\n=== ALL 41.5-strike short-call lots (any account) ===")
    found = False
    for lot in lots:
        if (
            lot.get("strike") == 41.5
            and lot.get("option_type") in ("C", "Call")
            and lot.get("quantity", 0) < 0
        ):
            found = True
            print(
                f"  acct={lot.get('account_number')} lot_id={lot['id']} qty={lot['quantity']} "
                f"entry={lot['entry_date']} expiration={lot.get('expiration')} "
                f"parent_lot_id={lot.get('parent_lot_id')} status={lot.get('status')}"
            )
    if not found:
        print("  (none)")

    print("\n=== Activity on 2026-05-18 — groups opened or closed today ===")
    for g in groups:
        opened = (g.get("opening_date") or "")[:10]
        closed = (g.get("closing_date") or "")[:10]
        if opened == "2026-05-18" or closed == "2026-05-18":
            print(
                f"  acct={g.get('account_number')} group={g['group_id'][:8]} "
                f"opened={g.get('opening_date')} closed={g.get('closing_date')} "
                f"rolled_from={(g.get('rolled_from_group_id') or '')[:8] or 'NULL'}"
            )

    print("\n=== Closings on 2026-05-18 ===")
    closings_today = [c for c in closings if str(c.get("closing_date", ""))[:10] == "2026-05-18"]
    for c in closings_today:
        lot = lots_by_id.get(c["lot_id"], {})
        print(
            f"  acct={lot.get('account_number')} lot_id={c['lot_id']} "
            f"strike={lot.get('strike')} type={lot.get('option_type')} "
            f"closing_type={c.get('closing_type')} qty_closed={c.get('quantity_closed')} "
            f"closing_order={c.get('closing_order_id')}"
        )

    print("\n=== Groups containing the open 41.5 short-call lots ===")
    target_lots = [l for l in lots if l.get("strike") == 41.5 and l.get("option_type") in ("C", "Call") and l.get("quantity", 0) < 0]
    for lot in target_lots:
        print(f"\n  -- lot_id={lot['id']} acct={lot.get('account_number')} status={lot.get('status')} parent={lot.get('parent_lot_id')}")
        for link in links:
            if link["transaction_id"] == lot["transaction_id"]:
                g = groups_by_id.get(link["group_id"], {})
                print(
                    f"     group={g.get('group_id','')[:8]} opened={g.get('opening_date')} "
                    f"closed={g.get('closing_date')} rolled_from={(g.get('rolled_from_group_id') or '')[:8] or 'NULL'} "
                    f"status_flag={g.get('status')}"
                )
                # Walk back through the chain via parent_lot_id
                p = lot.get("parent_lot_id")
                seen = set()
                depth = 0
                while p and p not in seen and depth < 6:
                    seen.add(p)
                    plot = lots_by_id.get(p, {})
                    plinks = [ln for ln in links if ln["transaction_id"] == plot.get("transaction_id")]
                    if plinks:
                        pg = groups_by_id.get(plinks[0]["group_id"], {})
                        print(
                            f"     ↑ parent lot_id={p} strike={plot.get('strike')} status={plot.get('status')} "
                            f"in group={pg.get('group_id','')[:8]} closed={pg.get('closing_date')} "
                            f"status_flag={pg.get('status')}"
                        )
                    else:
                        print(f"     ↑ parent lot_id={p} (no group link found)")
                    p = plot.get("parent_lot_id")
                    depth += 1

    print("\n=== Original full-loop (kept for reference) ===")
    for lot in lots:
        if (
            lot.get("account_number") == "5WZ28644"
            and lot.get("strike") == 41.5
            and lot.get("option_type") == "C"
            and lot.get("quantity", 0) < 0
        ):
            print(
                f"  lot_id={lot['id']} qty={lot['quantity']} "
                f"entry={lot['entry_date']} expiration={lot.get('expiration')} "
                f"parent_lot_id={lot.get('parent_lot_id')} status={lot.get('status')}"
            )
            for link in links:
                if link["transaction_id"] == lot["transaction_id"]:
                    g = groups_by_id.get(link["group_id"], {})
                    print(
                        f"    in group_id={link['group_id']} "
                        f"opened={g.get('opening_date')} "
                        f"closed={g.get('closing_date')} "
                        f"rolled_from={g.get('rolled_from_group_id')}"
                    )

    print("\n=== Groups in 5WZ28644 opened on/after 2026-05-15 ===")
    for g in groups:
        if g.get("account_number") != "5WZ28644":
            continue
        opened = g.get("opening_date", "")
        if not opened or opened < "2026-05-15":
            continue
        lot_ids = group_lot_ids(g["group_id"])
        strikes = sorted(
            {lots_by_id[lid].get("strike") for lid in lot_ids if lid in lots_by_id and lots_by_id[lid].get("strike") is not None}
        )
        print(
            f"  group_id={g['group_id']} opened={opened} "
            f"closed={g.get('closing_date')} "
            f"strikes={strikes} "
            f"rolled_from={g.get('rolled_from_group_id')}"
        )
        for lid in lot_ids:
            lot = lots_by_id.get(lid, {})
            print(
                f"    lot_id={lid} strike={lot.get('strike')} "
                f"qty={lot.get('quantity')} type={lot.get('option_type')} "
                f"entry={lot.get('entry_date')} expiration={lot.get('expiration')} "
                f"parent_lot_id={lot.get('parent_lot_id')} status={lot.get('status')}"
            )


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "scripts/opt294_state_partial.json")
