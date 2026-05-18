"""OPT-294: Snapshot the broken IBIT chain state in Postgres.

Captures, for sbj175@gmail.com:
  - All IBIT-related position_groups (any account) with rolled_from_group_id
  - All IBIT position_lots with parent_lot_id, entry_date, account, strike, etc.
  - All lot_closings for IBIT lots
  - position_group_lots links

Writes a single JSON file (scripts/opt294_state_partial.json) suitable for
diffing against a post-full-reprocess snapshot.

Run from project root:
  docker compose exec app python scripts/opt294_snapshot.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from src.database.engine import get_session, init_engine

init_engine(os.getenv("DATABASE_URL"))

USER_EMAIL = "sbj175@gmail.com"
USER_ID = "fe3a93df-3714-4f0c-98de-a4c030ae8e44"


def _jsonable(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


def _row_to_dict(row):
    return {c.name: _jsonable(getattr(row, c.name)) for c in row.__table__.columns}


def main(out_path: str) -> None:
    from src.database.models import (
        Account,
        LotClosing,
        PositionGroup,
        PositionGroupLot,
        PositionLot,
    )

    state = {"user_id": USER_ID, "underlying": "IBIT", "captured_at": datetime.utcnow().isoformat()}

    with get_session(user_id=USER_ID) as session:
        accounts = session.query(Account).filter(Account.user_id == USER_ID).all()
        state["accounts"] = [_row_to_dict(a) for a in accounts]

        groups = (
            session.query(PositionGroup)
            .filter(PositionGroup.user_id == USER_ID, PositionGroup.underlying == "IBIT")
            .order_by(PositionGroup.account_number, PositionGroup.opening_date, PositionGroup.group_id)
            .all()
        )
        state["position_groups"] = [_row_to_dict(g) for g in groups]
        group_ids = [g.group_id for g in groups]

        lots = (
            session.query(PositionLot)
            .filter(PositionLot.user_id == USER_ID, PositionLot.underlying == "IBIT")
            .order_by(PositionLot.account_number, PositionLot.entry_date, PositionLot.id)
            .all()
        )
        state["position_lots"] = [_row_to_dict(l) for l in lots]
        lot_ids = [l.id for l in lots]

        if group_ids:
            links = (
                session.query(PositionGroupLot)
                .filter(
                    PositionGroupLot.user_id == USER_ID,
                    PositionGroupLot.group_id.in_(group_ids),
                )
                .all()
            )
        else:
            links = []
        state["position_group_lots"] = [_row_to_dict(x) for x in links]

        if lot_ids:
            closings = (
                session.query(LotClosing)
                .filter(LotClosing.user_id == USER_ID, LotClosing.lot_id.in_(lot_ids))
                .order_by(LotClosing.lot_id, LotClosing.closing_date, LotClosing.closing_id)
                .all()
            )
        else:
            closings = []
        state["lot_closings"] = [_row_to_dict(c) for c in closings]

    Path(out_path).write_text(json.dumps(state, indent=2, default=str))

    print(f"Wrote {out_path}")
    print(f"  accounts        : {len(state['accounts'])}")
    print(f"  position_groups : {len(state['position_groups'])}")
    print(f"  position_lots   : {len(state['position_lots'])}")
    print(f"  group_lot_links : {len(state['position_group_lots'])}")
    print(f"  lot_closings    : {len(state['lot_closings'])}")

    rolled = [g for g in state["position_groups"] if g.get("rolled_from_group_id")]
    print(f"\nGroups with rolled_from_group_id set: {len(rolled)}")
    for g in rolled:
        print(
            f"  group_id={g['group_id']} account={g['account_number']} "
            f"opened={g['opening_date']} strategy={g.get('strategy')} "
            f"rolled_from={g['rolled_from_group_id']}"
        )


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "scripts/opt294_state_partial.json"
    main(out)
