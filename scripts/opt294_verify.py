"""OPT-294 verification: run GroupPersister.process_groups() against the live
DB to exercise the new self-heal pass, then re-snapshot the IBIT 41.5 chain
in 5WZ26959 and confirm the Rolled tag is restored.

Run from project root inside the app container:
  docker compose exec -e PYTHONPATH=/app app python scripts/opt294_verify.py
"""
from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
load_dotenv()

from src.database.engine import get_session, init_engine
from src.database.tenant import set_current_user_id

init_engine(os.getenv("DATABASE_URL"))

USER_ID = "fe3a93df-3714-4f0c-98de-a4c030ae8e44"
TARGET_LOT_TXN_HINT = 41.5  # strike to look for in 5WZ26959


def _summarize_41p5_state(label: str) -> None:
    from src.database.models import (
        PositionGroup,
        PositionGroupLot,
        PositionLot,
    )

    print(f"\n=== {label} ===")
    with get_session(user_id=USER_ID) as session:
        lot = (
            session.query(PositionLot)
            .filter(
                PositionLot.user_id == USER_ID,
                PositionLot.account_number == "5WZ26959",
                PositionLot.underlying == "IBIT",
                PositionLot.strike == 41.5,
                PositionLot.option_type == "Call",
                PositionLot.quantity < 0,
            )
            .order_by(PositionLot.entry_date.desc())
            .first()
        )
        if lot is None:
            print("  (no 41.5 short-call lot found)")
            return
        link = (
            session.query(PositionGroupLot)
            .filter(
                PositionGroupLot.user_id == USER_ID,
                PositionGroupLot.transaction_id == lot.transaction_id,
            )
            .first()
        )
        if link is None:
            print(f"  lot_id={lot.id} has no group link")
            return
        group = (
            session.query(PositionGroup)
            .filter(PositionGroup.group_id == link.group_id)
            .first()
        )

        sibling_links = (
            session.query(PositionGroupLot)
            .filter(
                PositionGroupLot.user_id == USER_ID,
                PositionGroupLot.group_id == link.group_id,
            )
            .all()
        )
        sibling_lots = []
        for sl in sibling_links:
            slot = (
                session.query(PositionLot)
                .filter(
                    PositionLot.user_id == USER_ID,
                    PositionLot.transaction_id == sl.transaction_id,
                )
                .first()
            )
            if slot:
                sibling_lots.append(slot)

        print(f"  41.5 lot_id={lot.id} status={lot.status} parent_lot_id={lot.parent_lot_id}")
        print(f"  group_id={link.group_id}")
        print(f"    rolled_from={group.rolled_from_group_id}")
        print(f"    status={group.status} opening_date={group.opening_date}")
        print(f"    sibling lots ({len(sibling_lots)}):")
        for s in sibling_lots:
            print(
                f"      lot_id={s.id} strike={s.strike} qty={s.quantity} "
                f"status={s.status} parent_lot_id={s.parent_lot_id}"
            )


def main() -> None:
    from src.database.db_manager import DatabaseManager
    from src.models.lot_manager import LotManager
    from src.pipeline.group_manager import GroupPersister
    from src.pipeline.lot_lineage import derive_rolled_from_group_id

    set_current_user_id(USER_ID)

    _summarize_41p5_state("BEFORE self-heal")

    db = DatabaseManager()
    lot_mgr = LotManager(db)
    persister = GroupPersister(db, lot_mgr)
    count = persister.process_groups()
    print(f"\nprocess_groups returned: {count}")

    derived = derive_rolled_from_group_id(db)
    print(f"derive_rolled_from_group_id updated: {derived} groups")

    _summarize_41p5_state("AFTER self-heal")


if __name__ == "__main__":
    main()
