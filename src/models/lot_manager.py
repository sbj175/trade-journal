"""
Lot Manager for V3 Position Tracking
Implements lot-based position tracking with FIFO matching and assignment/exercise handling
"""

from dataclasses import dataclass
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple
import logging

from sqlalchemy import func
from src.database.models import (
    PositionLot as PositionLotModel,
    LotClosing as LotClosingModel,
    PositionGroup,
    PositionGroupLot,
)

logger = logging.getLogger(__name__)


@dataclass
class Lot:
    """Represents a position lot"""
    id: int
    transaction_id: str
    account_number: str
    symbol: str
    underlying: str
    instrument_type: str
    option_type: Optional[str]
    strike: Optional[float]
    expiration: Optional[date]
    quantity: int  # Original quantity (negative for short)
    entry_price: float
    entry_date: datetime
    remaining_quantity: int
    original_quantity: int
    chain_id: Optional[str]
    leg_index: int
    opening_order_id: Optional[str]
    derived_from_lot_id: Optional[int]
    derivation_type: Optional[str]  # ASSIGNMENT, EXERCISE
    status: str  # OPEN, CLOSED, PARTIAL

    @property
    def is_short(self) -> bool:
        return self.quantity < 0

    @property
    def is_long(self) -> bool:
        return self.quantity > 0

    @property
    def is_closed(self) -> bool:
        return self.remaining_quantity == 0

    @property
    def is_option(self) -> bool:
        return self.option_type is not None


@dataclass
class LotClosing:
    """Represents a closing record for a lot"""
    closing_id: int
    lot_id: int
    closing_order_id: str
    closing_transaction_id: Optional[str]
    quantity_closed: int
    closing_price: float
    closing_date: datetime
    closing_type: str  # MANUAL, EXPIRATION, ASSIGNMENT, EXERCISE
    realized_pnl: float
    resulting_lot_id: Optional[int]  # For assignment: stock lot created


class LotManager:
    """Centralized lot operations for V3 position tracking"""

    def __init__(self, db_manager):
        self.db = db_manager

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    @staticmethod
    def _orm_to_lot(row: PositionLotModel) -> Lot:
        """Convert an ORM PositionLot to a Lot dataclass."""
        expiration = row.expiration
        if expiration and isinstance(expiration, str):
            expiration = datetime.strptime(expiration, '%Y-%m-%d').date()

        entry_date = row.entry_date
        if isinstance(entry_date, str):
            entry_date = datetime.fromisoformat(entry_date.replace('Z', '+00:00'))

        return Lot(
            id=row.id,
            transaction_id=row.transaction_id,
            account_number=row.account_number,
            symbol=row.symbol,
            underlying=row.underlying or '',
            instrument_type=row.instrument_type or '',
            option_type=row.option_type,
            strike=row.strike,
            expiration=expiration,
            quantity=row.quantity,
            entry_price=row.entry_price,
            entry_date=entry_date,
            remaining_quantity=row.remaining_quantity,
            original_quantity=row.original_quantity or abs(row.quantity),
            chain_id=row.chain_id,
            leg_index=row.leg_index or 0,
            opening_order_id=row.opening_order_id,
            derived_from_lot_id=row.derived_from_lot_id,
            derivation_type=row.derivation_type,
            status=row.status or 'OPEN',
        )

    @staticmethod
    def _orm_to_closing(row: LotClosingModel) -> LotClosing:
        """Convert an ORM LotClosing to a LotClosing dataclass."""
        closing_date = row.closing_date
        if isinstance(closing_date, str):
            closing_date = datetime.fromisoformat(closing_date.replace('Z', '+00:00'))

        return LotClosing(
            closing_id=row.closing_id,
            lot_id=row.lot_id,
            closing_order_id=row.closing_order_id,
            closing_transaction_id=row.closing_transaction_id,
            quantity_closed=row.quantity_closed,
            closing_price=row.closing_price,
            closing_date=closing_date,
            closing_type=row.closing_type,
            realized_pnl=row.realized_pnl,
            resulting_lot_id=row.resulting_lot_id,
        )

    # -------------------------------------------------------------------
    # Create
    # -------------------------------------------------------------------

    def create_lot(
        self,
        transaction: Dict,
        chain_id: str,
        leg_index: int = 0,
        opening_order_id: Optional[str] = None
    ) -> int:
        """
        Create a new lot from an opening transaction.

        Returns:
            The ID of the created lot
        """
        symbol = transaction.get('symbol', '')
        underlying = transaction.get('underlying_symbol', '')
        if not underlying and ' ' in symbol:
            underlying = symbol.split()[0]
        elif not underlying:
            underlying = symbol

        quantity = int(transaction.get('quantity', 0))
        action = (transaction.get('action') or '').upper()

        if 'SELL_TO_OPEN' in action:
            quantity = -abs(quantity)
        else:
            quantity = abs(quantity)

        # Parse option details from symbol
        option_type = None
        strike = None
        expiration = None
        instrument_type = transaction.get('instrument_type', '')

        if 'OPTION' in instrument_type.upper() and ' ' in symbol:
            parts = symbol.split()
            if len(parts) >= 2:
                option_part = parts[1]
                if len(option_part) >= 8:
                    date_str = option_part[:6]
                    try:
                        expiration = datetime.strptime('20' + date_str, '%Y%m%d').date()
                    except:
                        pass
                    if len(option_part) > 6:
                        option_type = 'Call' if option_part[6] == 'C' else 'Put'
                    if len(option_part) > 7:
                        try:
                            strike = float(option_part[7:]) / 1000
                        except:
                            pass

        with self.db.get_session() as session:
            new_lot = PositionLotModel(
                transaction_id=transaction.get('id', ''),
                account_number=transaction.get('account_number', ''),
                symbol=symbol,
                underlying=underlying,
                instrument_type=instrument_type,
                option_type=option_type,
                strike=strike,
                expiration=expiration.isoformat() if expiration else None,
                quantity=quantity,
                entry_price=float(transaction.get('price', 0)),
                entry_date=transaction.get('executed_at', ''),
                remaining_quantity=quantity,
                original_quantity=abs(quantity),
                chain_id=chain_id,
                leg_index=leg_index,
                opening_order_id=opening_order_id,
                status='OPEN',
            )
            session.add(new_lot)
            session.flush()
            lot_id = new_lot.id
            logger.debug(f"Created lot {lot_id}: {symbol} qty={quantity} chain={chain_id}")
            return lot_id

    def close_lot_fifo(
        self,
        account_number: str,
        symbol: str,
        quantity_to_close: int,
        closing_price: float,
        closing_order_id: str,
        closing_transaction_id: Optional[str],
        closing_date: datetime,
        closing_type: str = 'MANUAL',
        chain_id: Optional[str] = None,
        close_long: Optional[bool] = None
    ) -> Tuple[float, List[int]]:
        """
        Close lots using FIFO matching.

        Returns:
            Tuple of (total realized P&L, list of affected lot IDs)
        """
        total_pnl = 0.0
        affected_lots = []
        remaining_to_close = abs(quantity_to_close)

        with self.db.get_session() as session:
            q = session.query(PositionLotModel).filter(
                PositionLotModel.account_number == account_number,
                PositionLotModel.symbol == symbol,
                PositionLotModel.remaining_quantity != 0,
                PositionLotModel.status != 'CLOSED',
            )

            if close_long is True:
                q = q.filter(PositionLotModel.quantity > 0)
            elif close_long is False:
                q = q.filter(PositionLotModel.quantity < 0)

            if chain_id:
                q = q.filter(PositionLotModel.chain_id == chain_id)

            lots = q.order_by(PositionLotModel.entry_date.asc()).all()

            for lot in lots:
                if remaining_to_close <= 0:
                    break

                lot_available = abs(lot.remaining_quantity)
                close_amount = min(remaining_to_close, lot_available)

                multiplier = 100 if lot.option_type else 1

                if lot.quantity > 0:
                    pnl = (closing_price - lot.entry_price) * close_amount * multiplier
                else:
                    pnl = (lot.entry_price - closing_price) * close_amount * multiplier

                total_pnl += pnl

                new_remaining = abs(lot.remaining_quantity) - close_amount
                if lot.quantity < 0:
                    new_remaining = -new_remaining

                new_status = 'CLOSED' if new_remaining == 0 else 'PARTIAL'
                lot.remaining_quantity = new_remaining
                lot.status = new_status

                # Create lot_closings record
                closing_record = LotClosingModel(
                    lot_id=lot.id,
                    closing_order_id=closing_order_id,
                    closing_transaction_id=closing_transaction_id,
                    quantity_closed=close_amount,
                    closing_price=closing_price,
                    closing_date=(closing_date.isoformat()
                                  if isinstance(closing_date, datetime) else str(closing_date)),
                    closing_type=closing_type,
                    realized_pnl=pnl,
                )
                session.add(closing_record)

                affected_lots.append(lot.id)
                remaining_to_close -= close_amount

                logger.debug(f"Closed {close_amount} from lot {lot.id}, P&L: ${pnl:.2f}")

        return total_pnl, affected_lots

    def create_derived_lot(
        self,
        source_lot_id: int,
        stock_transaction: Dict,
        derivation_type: str,
        chain_id: str,
        override_quantity: Optional[int] = None
    ) -> int:
        """
        Create a derived lot (stock from option assignment/exercise).

        Returns:
            ID of the newly created stock lot
        """
        symbol = stock_transaction.get('symbol', '')
        underlying = stock_transaction.get('underlying_symbol', symbol)
        raw_quantity = abs(int(stock_transaction.get('quantity', 0)))

        with self.db.get_session() as session:
            source_lot = session.get(PositionLotModel, source_lot_id)
            entry_price = (float(source_lot.strike)
                           if source_lot and source_lot.strike
                           else float(stock_transaction.get('price', 0)))

            if override_quantity is not None:
                quantity = override_quantity
            else:
                source_option_type = source_lot.option_type if source_lot else None
                if source_option_type and source_option_type.upper() == 'CALL':
                    quantity = -raw_quantity
                else:
                    quantity = raw_quantity

            new_lot = PositionLotModel(
                transaction_id=stock_transaction.get('id', ''),
                account_number=stock_transaction.get('account_number', ''),
                symbol=symbol,
                underlying=underlying,
                instrument_type='EQUITY',
                option_type=None,
                strike=None,
                expiration=None,
                quantity=quantity,
                entry_price=entry_price,
                entry_date=stock_transaction.get('executed_at', ''),
                remaining_quantity=quantity,
                original_quantity=abs(quantity),
                chain_id=chain_id,
                leg_index=0,
                opening_order_id=None,
                derived_from_lot_id=source_lot_id,
                derivation_type=derivation_type,
                status='OPEN',
            )
            session.add(new_lot)
            session.flush()
            lot_id = new_lot.id

            # Update the lot_closings to reference the resulting lot
            latest_closing = session.query(LotClosingModel).filter(
                LotClosingModel.lot_id == source_lot_id,
                LotClosingModel.closing_type == derivation_type,
            ).order_by(LotClosingModel.closing_id.desc()).first()

            if latest_closing:
                latest_closing.resulting_lot_id = lot_id

            logger.info(f"Created derived lot {lot_id} from lot {source_lot_id} via {derivation_type}")
            return lot_id

    # -------------------------------------------------------------------
    # Queries
    # -------------------------------------------------------------------

    def get_open_lots(
        self,
        account_number: str,
        symbol: Optional[str] = None,
        chain_id: Optional[str] = None,
        underlying: Optional[str] = None
    ) -> List[Lot]:
        """Get all open lots matching criteria."""
        with self.db.get_session() as session:
            q = session.query(PositionLotModel).filter(
                PositionLotModel.account_number == account_number,
                PositionLotModel.remaining_quantity != 0,
                PositionLotModel.status != 'CLOSED',
            )
            if symbol:
                q = q.filter(PositionLotModel.symbol == symbol)
            if chain_id:
                q = q.filter(PositionLotModel.chain_id == chain_id)
            if underlying:
                q = q.filter(PositionLotModel.underlying == underlying)

            q = q.order_by(PositionLotModel.entry_date.asc())
            return [self._orm_to_lot(row) for row in q.all()]

    def get_lots_for_groups_batch(self, group_ids: List[str]) -> Dict[str, List[Lot]]:
        """
        Get lots for multiple position groups in a single query.
        Joins position_lots with position_group_lots using transaction_id.
        """
        if not group_ids:
            return {}

        result = {gid: [] for gid in group_ids}

        with self.db.get_session() as session:
            rows = (
                session.query(PositionGroupLot.group_id, PositionLotModel)
                .join(PositionLotModel,
                      PositionGroupLot.transaction_id == PositionLotModel.transaction_id)
                .filter(PositionGroupLot.group_id.in_(group_ids))
                .order_by(PositionLotModel.entry_date.asc(),
                          PositionLotModel.leg_index.asc())
                .all()
            )
            for group_id, lot_row in rows:
                result[group_id].append(self._orm_to_lot(lot_row))

        return result

    def get_lot_closings_batch(self, lot_ids: List[int]) -> Dict[int, List[LotClosing]]:
        """Get closings for multiple lots in a single query."""
        if not lot_ids:
            return {}

        result = {lid: [] for lid in lot_ids}

        with self.db.get_session() as session:
            rows = session.query(LotClosingModel).filter(
                LotClosingModel.lot_id.in_(lot_ids),
            ).order_by(LotClosingModel.closing_date.asc()).all()

            for row in rows:
                result[row.lot_id].append(self._orm_to_closing(row))

        return result

    def get_unassigned_lots(self, account_number: Optional[str] = None) -> List[Lot]:
        """Find lots whose transaction_id is NOT in position_group_lots."""
        with self.db.get_session() as session:
            q = (
                session.query(PositionLotModel)
                .outerjoin(PositionGroupLot,
                           PositionLotModel.transaction_id == PositionGroupLot.transaction_id)
                .filter(PositionGroupLot.transaction_id.is_(None))
            )
            if account_number:
                q = q.filter(PositionLotModel.account_number == account_number)

            q = q.order_by(PositionLotModel.entry_date.asc())
            return [self._orm_to_lot(row) for row in q.all()]

    def get_lots_for_chain(self, chain_id: str, include_derived: bool = True) -> List[Lot]:
        """Get all lots belonging to a chain."""
        with self.db.get_session() as session:
            q = session.query(PositionLotModel).filter(
                PositionLotModel.chain_id == chain_id,
            )
            if not include_derived:
                q = q.filter(PositionLotModel.derived_from_lot_id.is_(None))

            q = q.order_by(PositionLotModel.entry_date.asc(),
                           PositionLotModel.leg_index.asc())
            return [self._orm_to_lot(row) for row in q.all()]

    def get_lot_by_id(self, lot_id: int) -> Optional[Lot]:
        """Get a specific lot by ID"""
        with self.db.get_session() as session:
            row = session.get(PositionLotModel, lot_id)
            if row:
                return self._orm_to_lot(row)
            return None

    def get_lot_closings(self, lot_id: int) -> List[LotClosing]:
        """Get all closing records for a lot"""
        with self.db.get_session() as session:
            rows = session.query(LotClosingModel).filter(
                LotClosingModel.lot_id == lot_id,
            ).order_by(LotClosingModel.closing_date.asc()).all()

            return [self._orm_to_closing(row) for row in rows]

    def get_realized_pnl_for_chain(self, chain_id: str) -> float:
        """Calculate total realized P&L for a chain from lot closings"""
        with self.db.get_session() as session:
            result = (
                session.query(func.coalesce(func.sum(LotClosingModel.realized_pnl), 0))
                .join(PositionLotModel, LotClosingModel.lot_id == PositionLotModel.id)
                .filter(PositionLotModel.chain_id == chain_id)
                .scalar()
            )
            return float(result) if result else 0.0

    def update_lot_chain(self, lot_id: int, chain_id: str):
        """Update the chain_id for a lot"""
        with self.db.get_session() as session:
            lot = session.get(PositionLotModel, lot_id)
            if lot:
                lot.chain_id = chain_id

    def clear_all_lots(self, underlyings: set = None):
        """Clear lots and their groups. If underlyings is provided, only clear for those symbols."""
        from src.database.tenant import DEFAULT_USER_ID
        with self.db.get_session() as session:
            user_id = session.info.get("user_id", DEFAULT_USER_ID)
            if underlyings:
                underlying_list = list(underlyings)
                # Delete group links for matching lots first
                lot_txn_ids_sub = session.query(PositionLotModel.transaction_id).filter(
                    PositionLotModel.underlying.in_(underlying_list),
                    PositionLotModel.user_id == user_id,
                ).scalar_subquery()
                session.query(PositionGroupLot).filter(
                    PositionGroupLot.transaction_id.in_(lot_txn_ids_sub),
                    PositionGroupLot.user_id == user_id,
                ).delete(synchronize_session='fetch')
                # Delete groups for matching underlyings
                session.query(PositionGroup).filter(
                    PositionGroup.underlying.in_(underlying_list),
                    PositionGroup.user_id == user_id,
                ).delete(synchronize_session='fetch')
                # Delete closings for matching lots
                lot_ids_sub = session.query(PositionLotModel.id).filter(
                    PositionLotModel.underlying.in_(underlying_list),
                    PositionLotModel.user_id == user_id,
                ).scalar_subquery()
                session.query(LotClosingModel).filter(
                    LotClosingModel.lot_id.in_(lot_ids_sub),
                    LotClosingModel.user_id == user_id,
                ).delete(synchronize_session='fetch')
                # Then delete the lots themselves
                session.query(PositionLotModel).filter(
                    PositionLotModel.underlying.in_(underlying_list),
                    PositionLotModel.user_id == user_id,
                ).delete(synchronize_session='fetch')
                logger.info(f"Cleared lots, closings, and groups for {len(underlyings)} underlyings")
            else:
                session.query(PositionGroupLot).filter(PositionGroupLot.user_id == user_id).delete()
                session.query(PositionGroup).filter(PositionGroup.user_id == user_id).delete()
                session.query(LotClosingModel).filter(LotClosingModel.user_id == user_id).delete()
                session.query(PositionLotModel).filter(PositionLotModel.user_id == user_id).delete()
                logger.warning("Cleared all lots, closings, and groups (user-scoped)")
