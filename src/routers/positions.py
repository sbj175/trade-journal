"""Position routes — current positions and open chains."""

import json as _json
from datetime import date, datetime
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger

from sqlalchemy import func

from src.database.models import OrderChainCache, PositionGroup, PositionGroupLot, PositionGroupTag, PositionLot as PositionLotModel, Tag
from src.dependencies import db, lot_manager, order_manager, get_current_user_id
from src.services.ledger_service import seed_position_groups

router = APIRouter()


@router.get("/api/positions/cached")
async def get_cached_positions(account_number: Optional[str] = None, user_id: str = Depends(get_current_user_id)):
    """Get cached positions immediately without sync - chain_id already persisted"""
    try:
        positions = db.get_open_positions()

        if account_number:
            positions = [p for p in positions if p.get('account_number') == account_number]

        last_sync = db.get_last_sync_timestamp()
        data_age_minutes = None
        if last_sync:
            data_age_minutes = (datetime.now() - last_sync).total_seconds() / 60

        positions_by_account = {}
        for position in positions:
            account = position.get('account_number', 'unknown')
            if account not in positions_by_account:
                positions_by_account[account] = []
            positions_by_account[account].append(position)

        cached_quotes = db.get_cached_quotes()

        return {
            "positions": positions_by_account,
            "quotes": cached_quotes,
            "cache_info": {
                "last_sync": last_sync.isoformat() if last_sync else None,
                "data_age_minutes": data_age_minutes,
                "is_fresh": data_age_minutes < 60 if data_age_minutes else False,
                "cached": True,
                "quotes_count": len(cached_quotes)
            }
        }
    except Exception as e:
        logger.error(f"Error fetching cached positions: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/positions")
async def get_positions(account_number: Optional[str] = None, user_id: str = Depends(get_current_user_id)):
    """Get current open positions - chain_id/strategy_type already persisted at sync time"""
    try:
        positions = db.get_open_positions()

        if account_number:
            positions = [p for p in positions if p.get('account_number') == account_number]

        positions_by_account = {}
        for position in positions:
            account = position.get('account_number', 'unknown')
            if account not in positions_by_account:
                positions_by_account[account] = []
            positions_by_account[account].append(position)

        logger.info(f"/api/positions: Returning {len(positions)} positions grouped by {len(positions_by_account)} accounts")
        return positions_by_account
    except Exception as e:
        logger.error(f"Error fetching positions: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/open-chains")
async def get_open_chains(account_number: Optional[str] = None, user_id: str = Depends(get_current_user_id)):
    """Get open position groups for the Positions page — position_groups as single source of truth."""

    try:
        # Auto-seed position_groups if empty
        with db.get_session() as session:
            group_count = session.query(func.count()).select_from(PositionGroup).scalar()
            if group_count == 0:
                lot_count = session.query(func.count()).select_from(PositionLotModel).scalar()
                if lot_count > 0:
                    seed_position_groups()

        # Query open position groups
        with db.get_session() as session:
            q = session.query(PositionGroup).filter(
                PositionGroup.status.in_(['OPEN', 'ASSIGNED']),
            )
            if account_number and account_number != '':
                q = q.filter(PositionGroup.account_number == account_number)
            q = q.order_by(PositionGroup.underlying.asc(), PositionGroup.opening_date.desc())
            groups_raw = [row.to_dict() for row in q.all()]

        if not groups_raw:
            result = {}
        else:
            group_ids = [g['group_id'] for g in groups_raw]

            # Batch-load tags for all groups
            tags_by_group: Dict[str, list] = {gid: [] for gid in group_ids}
            with db.get_session() as session:
                tag_rows = session.query(
                    PositionGroupTag.group_id, Tag.id, Tag.name, Tag.color,
                ).join(Tag, PositionGroupTag.tag_id == Tag.id).filter(
                    PositionGroupTag.group_id.in_(group_ids),
                ).all()
                for gid, tid, tname, tcolor in tag_rows:
                    tags_by_group[gid].append({"id": tid, "name": tname, "color": tcolor or "#3B82F6"})

            # Batch-load lots for all groups
            lots_by_group = lot_manager.get_lots_for_groups_batch(group_ids)

            # Batch-load closings for all lots
            all_lot_ids = []
            for lots in lots_by_group.values():
                for lot in lots:
                    all_lot_ids.append(lot.id)
            closings_by_lot = lot_manager.get_lot_closings_batch(all_lot_ids) if all_lot_ids else {}

            # Batch-load order data from cache for roll_count/order_count
            all_order_ids = set()
            group_order_ids: Dict[str, set] = {gid: set() for gid in group_ids}
            for gid, lots in lots_by_group.items():
                for lot in lots:
                    if lot.opening_order_id:
                        all_order_ids.add(lot.opening_order_id)
                        group_order_ids[gid].add(lot.opening_order_id)
                    for closing in closings_by_lot.get(lot.id, []):
                        if closing.closing_order_id:
                            all_order_ids.add(closing.closing_order_id)
                            group_order_ids[gid].add(closing.closing_order_id)

            order_cache: Dict[str, Dict] = {}
            if all_order_ids:
                with db.get_session() as session:
                    rows = session.query(
                        OrderChainCache.order_id, OrderChainCache.order_data,
                    ).filter(
                        OrderChainCache.order_id.in_(list(all_order_ids)),
                    ).all()
                    for row in rows:
                        try:
                            order_cache[row[0]] = _json.loads(row[1])
                        except Exception:
                            pass

            result = {}

            for g in groups_raw:
                gid = g['group_id']
                acct = g['account_number']

                if acct not in result:
                    result[acct] = {"chains": []}

                lots = lots_by_group.get(gid, [])

                open_option_legs = []
                open_equity_legs = []
                cost_basis_total = 0.0
                realized_pnl = 0.0
                has_assignment = False

                for lot in lots:
                    lot_closings = closings_by_lot.get(lot.id, [])
                    lot_realized = sum(c.realized_pnl for c in lot_closings)
                    realized_pnl += lot_realized

                    for c in lot_closings:
                        if c.closing_type in ('ASSIGNMENT', 'EXERCISE'):
                            has_assignment = True

                    if lot.derivation_type in ('ASSIGNMENT', 'EXERCISE'):
                        has_assignment = True

                    multiplier = 100 if lot.instrument_type == 'EQUITY_OPTION' else 1

                    if lot.entry_price and lot.original_quantity:
                        amount = abs(lot.entry_price) * abs(lot.original_quantity) * multiplier
                        if lot.quantity < 0:
                            cost_basis_total += amount
                        else:
                            cost_basis_total -= amount

                    for c in lot_closings:
                        if c.closing_price and c.quantity_closed:
                            c_amount = abs(c.closing_price) * abs(c.quantity_closed) * multiplier
                            if lot.quantity < 0:
                                cost_basis_total -= c_amount
                            else:
                                cost_basis_total += c_amount

                    if lot.remaining_quantity != 0 and lot.status != 'CLOSED':
                        qty = abs(lot.remaining_quantity)
                        qty_direction = 'Short' if lot.quantity < 0 else 'Long'
                        price = abs(lot.entry_price) if lot.entry_price else 0

                        if lot.instrument_type == 'EQUITY_OPTION':
                            # Skip expired option legs (they'll vanish on next sync)
                            if lot.expiration and lot.expiration < date.today():
                                continue
                            leg_amount = price * qty * 100 if price else 0
                            leg_cost = leg_amount if qty_direction == 'Short' else -leg_amount
                            open_option_legs.append({
                                "symbol": lot.symbol,
                                "underlying": lot.underlying or g['underlying'],
                                "instrument_type": lot.instrument_type,
                                "option_type": lot.option_type,
                                "strike": lot.strike,
                                "expiration": str(lot.expiration) if lot.expiration else None,
                                "quantity": qty,
                                "quantity_direction": qty_direction,
                                "opening_price": price,
                                "cost_basis": leg_cost,
                                "lot_id": lot.id,
                            })
                        elif lot.instrument_type == 'EQUITY':
                            leg_cost = (price * qty) if qty_direction == 'Short' else -(price * qty)
                            open_equity_legs.append({
                                "symbol": lot.symbol,
                                "underlying": lot.underlying or g['underlying'],
                                "instrument_type": "EQUITY",
                                "quantity": qty,
                                "quantity_direction": qty_direction,
                                "entry_price": price,
                                "cost_basis": leg_cost,
                                "lot_id": lot.id,
                                "derivation_type": lot.derivation_type,
                            })

                roll_count = 0
                order_ids = group_order_ids.get(gid, set())
                for oid in order_ids:
                    od = order_cache.get(oid, {})
                    if od.get('order_type') == 'ROLLING':
                        roll_count += 1

                equity_summary = None
                if open_equity_legs:
                    total_eq_qty = sum(
                        l['quantity'] * (1 if l['quantity_direction'] == 'Long' else -1)
                        for l in open_equity_legs
                    )
                    total_eq_cost = sum(abs(l['cost_basis']) for l in open_equity_legs)
                    equity_summary = {
                        "quantity": total_eq_qty,
                        "average_price": total_eq_cost / abs(total_eq_qty) if total_eq_qty != 0 else 0,
                        "cost_basis": total_eq_cost,
                    }

                strategy_type = g['strategy_label'] or 'Unknown'
                if not open_option_legs and open_equity_legs:
                    strategy_type = "Shares"

                group_obj = {
                    "chain_id": gid,
                    "group_id": gid,
                    "source_chain_id": g.get('source_chain_id'),
                    "underlying": g['underlying'],
                    "account_number": acct,
                    "strategy_type": strategy_type,
                    "opening_date": g['opening_date'],
                    "chain_status": g['status'],
                    "realized_pnl": realized_pnl,
                    "cost_basis_total": cost_basis_total,
                    "roll_count": roll_count,
                    "order_count": len(order_ids),
                    "has_assignment": has_assignment,
                    "open_legs": open_option_legs,
                    "equity_legs": open_equity_legs,
                    "equity_summary": equity_summary,
                    "tags": tags_by_group.get(gid, []),
                }
                if open_option_legs or open_equity_legs:
                    result[acct]["chains"].append(group_obj)

        logger.info(f"/api/open-chains: Returning {sum(len(a['chains']) for a in result.values())} groups across {len(result)} accounts")
        return result

    except Exception as e:
        logger.error(f"Error in /api/open-chains: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/orders/{order_id}")
async def get_order(order_id: str, user_id: str = Depends(get_current_user_id)):
    """Get a specific order with all positions"""
    try:
        order = order_manager.get_order_by_id(order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        return order
    except Exception as e:
        logger.error(f"Error fetching order {order_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
