"""Chain service — cache checking, retrieval, and update for order chains."""

import json
from datetime import datetime
from typing import Dict, List, Optional

from loguru import logger

from src.dependencies import db, strategy_detector, lot_manager


async def should_use_cached_chains(account_number: Optional[str] = None, underlying: Optional[str] = None) -> bool:
    """Check if cached chain data exists for the requested account"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            if account_number == '' or account_number is None:
                # "All Accounts" → verify cache covers all accounts that have transactions
                cursor.execute("SELECT COUNT(DISTINCT account_number) FROM order_chains")
                cached_accounts = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(DISTINCT account_number) FROM raw_transactions")
                total_accounts = cursor.fetchone()[0]
                has_cache = cached_accounts > 0 and cached_accounts >= total_accounts
            elif account_number:
                # Specific account number → check for chains in that account
                cursor.execute("SELECT COUNT(*) FROM order_chains WHERE account_number = ? LIMIT 1", (account_number,))
                has_cache = cursor.fetchone()[0] > 0
            else:
                has_cache = False
            if has_cache:
                account_display = account_number if account_number is not None else "unspecified"
                logger.debug(f"Using cached chains for account {account_display} (derivation path temporarily disabled)")
            return has_cache
    except Exception as e:
        logger.error(f"Error checking cache: {e}")
        return False


async def get_cached_chains(account_number: Optional[str] = None, underlying: Optional[str] = None,
                          limit: int = 10000, offset: int = 0, chain_id: Optional[str] = None):
    """Get chains from cached data in order_chains table"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()

            # Build query with filters
            query = """
                SELECT oc.chain_id, oc.underlying, oc.strategy_type, oc.opening_date,
                       oc.closing_date, oc.chain_status, oc.order_count, oc.total_pnl,
                       oc.realized_pnl, oc.unrealized_pnl, oc.account_number
                FROM order_chains oc
            """
            params = []
            where_conditions = []

            if chain_id:
                where_conditions.append("oc.chain_id = ?")
                params.append(chain_id)

            # Only filter by account if it's a non-empty string (specific account)
            if account_number and account_number != '':
                where_conditions.append("oc.account_number = ?")
                params.append(account_number)

            if underlying:
                where_conditions.append("oc.underlying = ?")
                params.append(underlying)

            if where_conditions:
                query += " WHERE " + " AND ".join(where_conditions)

            query += " ORDER BY oc.opening_date DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor.execute(query, params)
            chain_rows = cursor.fetchall()

            if not chain_rows:
                return {"chains": [], "total": 0}

            # Get total count for pagination
            count_query = "SELECT COUNT(*) FROM order_chains oc"
            count_params = []
            if where_conditions:
                count_query += " WHERE " + " AND ".join(where_conditions)
                count_params = params[:-2]  # Remove limit and offset

            cursor.execute(count_query, count_params)
            total_count = cursor.fetchone()[0]

            # Format cached chains for frontend with complete order data
            formatted_chains = []
            for row in chain_rows:
                chain_id_val, underlying_val, strategy_type, opening_date, closing_date, chain_status = row[:6]
                order_count, total_pnl, realized_pnl, unrealized_pnl, account_number_val = row[6:]

                # Load complete order data from cache
                cursor.execute("""
                    SELECT order_data FROM order_chain_cache
                    WHERE chain_id = ?
                    ORDER BY order_id
                """, (chain_id_val,))

                order_rows = cursor.fetchall()
                orders = []

                for order_row in order_rows:
                    try:
                        order_data = json.loads(order_row[0])

                        # Clean up system-generated order IDs and types for display
                        order_id = order_data.get('order_id', '')
                        if order_id.startswith('SYSTEM_'):
                            if 'Expiration' in order_id:
                                order_data['display_type'] = 'EXPIRATION'
                                order_date = order_data.get('order_date', '')
                                if order_date:
                                    date_part = order_date[:10].replace('-', '')
                                    order_data['order_id'] = f"EXPIRATION_{date_part}"
                            elif 'Assignment' in order_id:
                                order_data['display_type'] = 'ASSIGNMENT'
                                order_date = order_data.get('order_date', '')
                                if order_date:
                                    date_part = order_date[:10].replace('-', '')
                                    order_data['order_id'] = f"ASSIGNMENT_{date_part}"
                            elif 'Exercise' in order_id:
                                order_data['display_type'] = 'EXERCISE'
                                order_date = order_data.get('order_date', '')
                                if order_date:
                                    date_part = order_date[:10].replace('-', '')
                                    order_data['order_id'] = f"EXERCISE_{date_part}"
                            else:
                                order_data['display_type'] = order_data.get('order_type', 'CLOSING')
                        else:
                            if 'display_type' not in order_data:
                                order_data['display_type'] = order_data.get('order_type', 'UNKNOWN')

                        orders.append(order_data)
                    except (json.JSONDecodeError, IndexError) as e:
                        logger.warning(f"Failed to parse cached order data for chain {chain_id_val}: {e}")
                        continue

                # If strategy is None, convert to Unknown for display
                if strategy_type is None:
                    strategy_type = "Unknown"

                # Calculate cost basis, net liquidity, and fees for cached chains
                cost_basis_total = 0.0
                cost_basis_per_unit = 0.0
                opening_quantity_total = 0
                total_commission = 0.0
                total_regulatory_fees = 0.0
                total_clearing_fees = 0.0
                net_liquidity = 0.0

                # Calculate metrics from cached order data
                if orders:
                    for order in orders:
                        if order.get('positions'):
                            for pos in order['positions']:
                                if pos.get('status') == 'OPEN' or not pos.get('closing_action'):
                                    opening_quantity_total = abs(pos.get('quantity', 0))
                                    break
                            if opening_quantity_total > 0:
                                break

                    total_credit = 0.0
                    total_debit = 0.0
                    for order in orders:
                        order_type = order.get('order_type', 'UNKNOWN')
                        for pos in order.get('positions', []):
                            qty = abs(pos.get('quantity', 0))

                            if order_type == 'CLOSING':
                                action = str(pos.get('opening_action', ''))
                                price = pos.get('opening_price', 0)

                                if price and qty > 0:
                                    amount = price * qty * 100 if pos.get('instrument_type') == 'EQUITY_OPTION' else price * qty
                                    if 'BTC' in action or 'BUY_TO_CLOSE' in action:
                                        total_debit += amount
                                    elif 'STC' in action or 'SELL_TO_CLOSE' in action:
                                        total_credit += amount
                            else:
                                if pos.get('opening_price') and qty > 0:
                                    amount = pos['opening_price'] * qty * 100 if pos.get('instrument_type') == 'EQUITY_OPTION' else pos['opening_price'] * qty
                                    action = str(pos.get('opening_action', ''))
                                    if 'BUY_TO_' in action or 'BTO' in action or action == 'BUY':
                                        total_debit += amount
                                    elif 'SELL_TO_' in action or 'STO' in action or action == 'SELL':
                                        total_credit += amount

                                if pos.get('closing_price') and pos.get('closing_action') and qty > 0:
                                    amount = pos['closing_price'] * qty * 100 if pos.get('instrument_type') == 'EQUITY_OPTION' else pos['closing_price'] * qty
                                    closing_action = str(pos.get('closing_action', ''))
                                    if 'BTC' in closing_action or 'BUY' in closing_action:
                                        total_debit += amount
                                    elif 'STC' in closing_action or 'SELL' in closing_action:
                                        total_credit += amount

                    if total_debit > 0 or total_credit > 0:
                        cost_basis_total = total_credit - total_debit
                        cost_basis_per_unit = 0.0
                        cost_basis_per_share = 0.0
                        pnl_per_share = 0.0
                        if opening_quantity_total > 0:
                            cost_basis_per_unit = cost_basis_total / opening_quantity_total
                            cost_basis_per_share = cost_basis_per_unit / 100
                            pnl_per_share = realized_pnl / opening_quantity_total / 100

                # Get net liquidity for open chains
                if chain_status == 'OPEN':
                    try:
                        chain_symbols = set()
                        for order in (orders or []):
                            for pos in order.get('positions', []):
                                if pos.get('symbol'):
                                    chain_symbols.add(pos['symbol'].strip())

                        positions = db.get_open_positions()
                        if positions and chain_symbols:
                            for pos in positions:
                                pos_symbol = (pos.get('symbol') or '').strip()
                                if (pos_symbol in chain_symbols and
                                    pos.get('account_number') == account_number_val):
                                    net_liquidity += float(pos.get('market_value', 0))
                    except Exception as e:
                        logger.warning(f"Could not calculate net liquidity for cached chain {chain_id_val}: {e}")

                formatted_chain = {
                    'chain_id': chain_id_val,
                    'underlying': underlying_val,
                    'strategy_type': strategy_type,
                    'opening_date': opening_date,
                    'closing_date': closing_date,
                    'status': chain_status,
                    'order_count': order_count,
                    'cost_basis_total': cost_basis_total,
                    'cost_basis_per_unit': cost_basis_per_unit,
                    'cost_basis_per_share': cost_basis_per_share,
                    'pnl_per_share': pnl_per_share,
                    'total_pnl': total_pnl or 0.0,
                    'realized_pnl': realized_pnl or 0.0,
                    'unrealized_pnl': unrealized_pnl or 0.0,
                    'net_liquidity': net_liquidity,
                    'total_commission': total_commission,
                    'total_regulatory_fees': total_regulatory_fees,
                    'total_clearing_fees': total_clearing_fees,
                    'total_fees': total_commission + total_regulatory_fees + total_clearing_fees,
                    'account_number': account_number_val,
                    'orders': orders
                }
                formatted_chains.append(formatted_chain)

            return {
                "chains": formatted_chains,
                "total": total_count,
                "cached": True
            }

    except Exception as e:
        logger.error(f"Error getting cached chains: {e}")
        return None


async def update_chain_cache(chains, affected_underlyings: set = None, affected_account: str = None):
    """Update the order_chains table with fresh derivation results

    Args:
        chains: List of Chain objects to cache
        affected_underlyings: Optional set of underlyings to update incrementally.
                             If None and no affected_account, clears and rebuilds entire cache.
        affected_account: Optional account number to scope the cache update.
                         Only clears/rebuilds chains for this account.
    """
    if affected_underlyings:
        logger.info(f"[CACHE UPDATE] Incremental update for {len(affected_underlyings)} underlyings: {affected_underlyings}")
    if affected_account:
        logger.info(f"[CACHE UPDATE] Account-scoped update for account: {affected_account}")
    logger.info(f"[CACHE UPDATE] Starting update with {len(chains)} chains")
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()

            # Preserve existing working strategies before clearing cache
            cursor.execute("""
                CREATE TEMP TABLE IF NOT EXISTS preserved_strategies AS
                SELECT chain_id, strategy_type
                FROM order_chains
                WHERE strategy_type IS NOT NULL AND strategy_type != 'Unknown' AND strategy_type != 'None'
                AND chain_id LIKE '%MERGED%'
            """)

            if affected_underlyings:
                placeholders = ','.join('?' * len(affected_underlyings))
                cursor.execute(f"""
                    DELETE FROM order_chain_cache WHERE chain_id IN (
                        SELECT chain_id FROM order_chains WHERE underlying IN ({placeholders})
                    )
                """, tuple(affected_underlyings))
                cursor.execute(f"""
                    DELETE FROM order_chain_members WHERE chain_id IN (
                        SELECT chain_id FROM order_chains WHERE underlying IN ({placeholders})
                    )
                """, tuple(affected_underlyings))
                cursor.execute(f"DELETE FROM order_chains WHERE underlying IN ({placeholders})",
                              tuple(affected_underlyings))
                logger.info(f"[CACHE UPDATE] Cleared cache for underlyings: {affected_underlyings}")
            elif affected_account:
                cursor.execute("""
                    DELETE FROM order_chain_cache WHERE chain_id IN (
                        SELECT chain_id FROM order_chains WHERE account_number = ?
                    )
                """, (affected_account,))
                cursor.execute("""
                    DELETE FROM order_chain_members WHERE chain_id IN (
                        SELECT chain_id FROM order_chains WHERE account_number = ?
                    )
                """, (affected_account,))
                cursor.execute("DELETE FROM order_chains WHERE account_number = ?",
                              (affected_account,))
                logger.info(f"[CACHE UPDATE] Cleared cache for account: {affected_account}")
            else:
                cursor.execute("DELETE FROM order_chains")
                cursor.execute("DELETE FROM order_chain_members")
                cursor.execute("DELETE FROM order_chain_cache")

            current_time = datetime.now()

            for chain in chains:
                # Check for preserved strategy first
                cursor.execute("SELECT strategy_type FROM preserved_strategies WHERE chain_id = ?", (chain.chain_id,))
                preserved_result = cursor.fetchone()

                if preserved_result:
                    detected_strategy = preserved_result[0]
                    logger.info(f"Using preserved strategy for chain {chain.chain_id}: {detected_strategy}")
                else:
                    try:
                        detected_strategy = strategy_detector.detect_chain_strategy(chain)

                        if detected_strategy is None:
                            detected_strategy = "Unknown"
                    except Exception as e:
                        logger.warning(f"Strategy detection failed for chain {chain.chain_id}: {e}")
                        import traceback
                        logger.error(traceback.format_exc())
                        detected_strategy = "Unknown"

                # Calculate P&L values
                total_pnl = 0.0
                realized_pnl = 0.0
                unrealized_pnl = 0.0
                has_rolls = False

                for order in chain.orders:
                    order_pnl = 0.0
                    for tx in order.transactions:
                        if tx.is_cash_settlement:
                            order_pnl += tx.value
                        else:
                            value = tx.price * abs(tx.quantity) * 100
                            if tx.is_sell:
                                order_pnl += value
                            else:
                                order_pnl -= value

                    total_pnl += order_pnl

                    if order.order_type.value == 'CLOSING':
                        realized_pnl += order_pnl
                    elif order.order_type.value == 'ROLLING':
                        has_rolls = True
                    else:
                        unrealized_pnl += order_pnl

                if has_rolls:
                    realized_pnl = total_pnl
                    unrealized_pnl = 0.0

                # V3: Calculate lot-based chain metadata
                has_assignment = any(
                    any(tx.is_assignment for tx in order.transactions)
                    for order in chain.orders
                )

                assignment_date = None
                if has_assignment:
                    for order in chain.orders:
                        for tx in order.transactions:
                            if tx.is_assignment:
                                assignment_date = tx.executed_at.date() if tx.executed_at else None
                                break
                        if assignment_date:
                            break

                # Get leg count and quantity info from lots
                leg_count = 1
                original_quantity = None
                remaining_quantity = None

                try:
                    lots = lot_manager.get_lots_for_chain(chain.chain_id, include_derived=False)
                    if lots:
                        leg_count = max(lot.leg_index + 1 for lot in lots)
                        original_quantity = sum(lot.original_quantity for lot in lots)
                        remaining_quantity = sum(abs(lot.remaining_quantity) for lot in lots if lot.status != 'CLOSED')
                except Exception as lot_err:
                    logger.debug(f"Could not get lot metadata for chain {chain.chain_id}: {lot_err}")

                # Insert chain data with V3 columns
                cursor.execute("""
                    INSERT OR REPLACE INTO order_chains (
                        chain_id, underlying, account_number, opening_order_id,
                        strategy_type, opening_date, closing_date, chain_status,
                        order_count, total_pnl, realized_pnl, unrealized_pnl,
                        leg_count, original_quantity, remaining_quantity,
                        has_assignment, assignment_date,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    chain.chain_id,
                    chain.underlying,
                    chain.account_number,
                    chain.orders[0].order_id if chain.orders else None,
                    detected_strategy,
                    chain.opening_date,
                    chain.closing_date,
                    chain.status,
                    len(chain.orders),
                    total_pnl,
                    realized_pnl,
                    unrealized_pnl,
                    leg_count,
                    original_quantity,
                    remaining_quantity,
                    has_assignment,
                    assignment_date,
                    current_time,
                    current_time
                ))

                # Insert chain membership links and cache complete order data
                for order in chain.orders:
                    cursor.execute("""
                        INSERT OR REPLACE INTO order_chain_members (chain_id, order_id)
                        VALUES (?, ?)
                    """, (chain.chain_id, order.order_id))

                    # Calculate total P&L for this order
                    order_pnl = 0.0
                    for tx in order.transactions:
                        if tx.is_cash_settlement:
                            order_pnl += tx.value
                        else:
                            multiplier = 100 if tx.strike is not None else 1
                            amount = tx.price * abs(tx.quantity) * multiplier
                            if tx.is_opening:
                                order_pnl += amount if 'SELL' in tx.action else -amount
                            else:
                                order_pnl += amount if 'SELL' in tx.action else -amount

                    order_data = {
                        "order_id": order.order_id,
                        "order_type": order.order_type.value,
                        "order_date": order.executed_at.isoformat() if order.executed_at else None,
                        "strategy_type": detected_strategy,
                        "status": "FILLED",
                        "total_pnl": order_pnl,
                        "positions": []
                    }

                    # Add positions from transactions with lot data (V3)
                    for idx, tx in enumerate(order.transactions):
                        if tx.is_cash_settlement:
                            tx_pnl = tx.value
                        else:
                            multiplier = 100 if tx.strike is not None else 1
                            tx_amount = tx.price * abs(tx.quantity) * multiplier
                            tx_pnl = tx_amount if 'SELL' in tx.action else -tx_amount

                        # V3: Try to find lot data for this transaction
                        lot_data = None
                        derived_positions = []

                        if tx.is_opening:
                            with db.get_connection() as lot_conn:
                                lot_cursor = lot_conn.cursor()
                                lot_cursor.execute("""
                                    SELECT id, remaining_quantity, original_quantity, status, leg_index
                                    FROM position_lots
                                    WHERE transaction_id = ?
                                """, (tx.id,))
                                lot_row = lot_cursor.fetchone()

                                if lot_row:
                                    lot_id = lot_row[0]
                                    lot_data = {
                                        "lot_id": lot_id,
                                        "leg_index": lot_row[4] or idx,
                                        "original_quantity": lot_row[2] or abs(tx.quantity),
                                        "remaining_quantity": lot_row[1] or abs(tx.quantity),
                                        "status": lot_row[3] or "OPEN"
                                    }

                                    # Check for derived positions (from assignment/exercise)
                                    lot_cursor.execute("""
                                        SELECT id, symbol, underlying, quantity, entry_price,
                                               remaining_quantity, status, derivation_type
                                        FROM position_lots
                                        WHERE derived_from_lot_id = ?
                                    """, (lot_id,))

                                    for derived_row in lot_cursor.fetchall():
                                        derived_positions.append({
                                            "lot_id": derived_row[0],
                                            "symbol": derived_row[1],
                                            "underlying": derived_row[2],
                                            "derivation_type": derived_row[7],
                                            "quantity": derived_row[3],
                                            "entry_price": derived_row[4],
                                            "remaining_quantity": derived_row[5],
                                            "status": derived_row[6]
                                        })

                        position_data = {
                            "position_id": f"{order.order_id}_{len(order_data['positions']) + 1}",
                            "symbol": tx.symbol,
                            "underlying": tx.underlying_symbol,
                            "instrument_type": "EQUITY_OPTION" if tx.strike else "EQUITY",
                            "option_type": tx.option_type,
                            "strike": tx.strike,
                            "expiration": tx.expiration.isoformat() if tx.expiration else None,
                            "quantity": tx.quantity,
                            "opening_action": tx.action,
                            "opening_price": tx.price,
                            "closing_action": None,
                            "closing_price": None,
                            "status": "OPEN" if order.order_type.value == "OPENING" else "CLOSED",
                            "opening_transaction_id": tx.id,
                            "closing_transaction_id": None,
                            "pnl": tx_pnl
                        }

                        # V3: Add lot data if available
                        if lot_data:
                            position_data["lot_id"] = lot_data["lot_id"]
                            position_data["leg_index"] = lot_data["leg_index"]
                            position_data["original_quantity"] = lot_data["original_quantity"]
                            position_data["remaining_quantity"] = lot_data["remaining_quantity"]

                            if lot_data["status"] == "CLOSED":
                                position_data["status"] = "CLOSED"
                            elif lot_data["status"] == "PARTIAL":
                                position_data["status"] = "PARTIAL"

                        if derived_positions:
                            position_data["derived_positions"] = derived_positions

                        order_data["positions"].append(position_data)

                    cursor.execute("""
                        INSERT OR REPLACE INTO order_chain_cache (chain_id, order_id, order_data)
                        VALUES (?, ?, ?)
                    """, (chain.chain_id, order.order_id, json.dumps(order_data)))

            conn.commit()
            logger.info(f"[CACHE UPDATE] Successfully updated cache with {len(chains)} chains")

    except Exception as e:
        logger.error(f"[CACHE UPDATE] Error updating chain cache: {e}")
        import traceback
        logger.error(traceback.format_exc())
