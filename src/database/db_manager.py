"""
Database Manager for Trade Journal
Handles all database operations via SQLAlchemy ORM.
"""

from datetime import datetime, date
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import json
import time
import logging

from src.database import engine as sa_engine

logger = logging.getLogger(__name__)

# Add parent directory to path
import sys
sys.path.append(str(Path(__file__).parent.parent.parent))


class DatabaseManager:
    def __init__(self, db_url: str = None):
        self.db_url = db_url  # None → engine.py reads DATABASE_URL or defaults to SQLite
        self._initialized = False
        # Note: initialize_database() is called explicitly by FastAPI startup event

    def ensure_initialized(self):
        """Ensure database is initialized (for standalone scripts)"""
        if not self._initialized:
            self.initialize_database()

    def get_session(self, user_id: str = None):
        """Context manager for SQLAlchemy sessions (delegates to engine module)."""
        return sa_engine.get_session(user_id=user_id)
    
    def initialize_database(self):
        """Create all necessary tables using SQLAlchemy models + legacy migration support."""
        from sqlalchemy import func as sa_func, inspect
        from src.database.models import Base, StrategyTarget, User
        from src.database.tenant import DEFAULT_USER_ID

        start_time = time.time()
        logger.info("Starting database initialization...")
        sa_engine.init_engine(self.db_url)

        # Create all tables from ORM models (IF NOT EXISTS semantics)
        engine = sa_engine._engine
        Base.metadata.create_all(engine)

        # Seed default user if not present
        with self.get_session() as session:
            if not session.get(User, DEFAULT_USER_ID):
                session.add(User(
                    id=DEFAULT_USER_ID,
                    display_name="Default User",
                    is_active=True,
                ))

        # Seed default strategy targets if table is empty
        with self.get_session() as session:
            count = session.query(sa_func.count()).select_from(StrategyTarget).scalar()
            if count == 0:
                self._seed_default_strategy_targets_orm(session)

        self._initialized = True
        elapsed_time = time.time() - start_time
        logger.info(f"Database initialized successfully in {elapsed_time:.2f} seconds")

    def _seed_default_strategy_targets_orm(self, session):
        """Seed default strategy targets using SQLAlchemy ORM."""
        from src.database.models import StrategyTarget

        defaults = [
            ('Bull Put Spread', 50.0, 100.0), ('Bear Call Spread', 50.0, 100.0),
            ('Iron Condor', 50.0, 100.0), ('Cash Secured Put', 50.0, 100.0),
            ('Covered Call', 50.0, 100.0), ('Short Put', 50.0, 100.0),
            ('Short Call', 50.0, 100.0), ('Short Strangle', 50.0, 100.0),
            ('Iron Butterfly', 25.0, 100.0), ('Short Straddle', 25.0, 100.0),
            ('Bull Call Spread', 100.0, 50.0), ('Bear Put Spread', 100.0, 50.0),
            ('Long Call', 100.0, 50.0), ('Long Put', 100.0, 50.0),
            ('Long Strangle', 100.0, 50.0), ('Long Straddle', 100.0, 50.0),
            ('Shares', 20.0, 10.0),
        ]
        for name, profit, loss in defaults:
            session.add(StrategyTarget(
                strategy_name=name, profit_target_pct=profit, loss_target_pct=loss,
            ))
    
    def save_account(self, account_number: str, account_name: str = None, account_type: str = None) -> bool:
        """Save account information"""
        from src.database.engine import dialect_insert
        from src.database.models import Account
        from src.database.tenant import DEFAULT_USER_ID

        try:
            with self.get_session() as session:
                user_id = session.info.get("user_id", DEFAULT_USER_ID)
                stmt = dialect_insert(Account).values(
                    account_number=account_number, account_name=account_name,
                    account_type=account_type, user_id=user_id,
                    updated_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                )
                session.execute(stmt.on_conflict_do_update(
                    index_elements=['account_number'],
                    set_={
                        'account_name': stmt.excluded.account_name,
                        'account_type': stmt.excluded.account_type,
                        'updated_at': stmt.excluded.updated_at,
                    },
                ))
                return True
        except Exception as e:
            logger.error(f"Error saving account {account_number}: {str(e)}")
            return False
    
    def get_accounts(self) -> List[Dict[str, Any]]:
        """Get all accounts"""
        from src.database.models import Account
        self.ensure_initialized()
        with self.get_session() as session:
            rows = (
                session.query(Account)
                .filter(Account.is_active == True)
                .order_by(Account.account_number)
                .all()
            )
            return [row.to_dict() for row in rows]

    def get_account(self, account_number: str) -> Optional[Dict[str, Any]]:
        """Get specific account"""
        from src.database.models import Account
        with self.get_session() as session:
            row = session.get(Account, account_number)
            return row.to_dict() if row else None
    
    # Legacy trade methods removed - use order system instead

    def save_raw_transactions(self, transactions: List[Dict]) -> int:
        """Save raw transactions to database for order-based grouping"""
        from src.database.engine import dialect_insert
        from src.database.models import RawTransaction
        from src.database.tenant import DEFAULT_USER_ID
        self.ensure_initialized()
        saved_count = 0

        with self.get_session() as session:
            user_id = session.info.get("user_id", DEFAULT_USER_ID)
            for txn in transactions:
                try:
                    stmt = dialect_insert(RawTransaction).values(
                        id=txn.get('id'), account_number=txn.get('account_number'),
                        order_id=txn.get('order_id'), transaction_type=txn.get('transaction_type'),
                        transaction_sub_type=txn.get('transaction_sub_type'),
                        description=txn.get('description'), executed_at=txn.get('executed_at'),
                        transaction_date=txn.get('transaction_date'), action=txn.get('action'),
                        symbol=txn.get('symbol'), instrument_type=txn.get('instrument_type'),
                        underlying_symbol=txn.get('underlying_symbol'),
                        quantity=txn.get('quantity'), price=txn.get('price'),
                        value=txn.get('value'), regulatory_fees=txn.get('regulatory_fees'),
                        clearing_fees=txn.get('clearing_fees'), commission=txn.get('commission'),
                        net_value=txn.get('net_value'), is_estimated_fee=txn.get('is_estimated_fee'),
                        user_id=user_id,
                    )
                    # Skip duplicates (on conflict do nothing)
                    session.execute(stmt.on_conflict_do_nothing(index_elements=['id']))
                    saved_count += 1
                except Exception as e:
                    logger.error(f"Failed to save transaction {txn.get('id')}: {e}")
                    continue

            logger.info(f"Saved {saved_count} raw transactions to database")

        return saved_count
    
    def get_raw_transactions(
        self,
        account_number: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        underlying: Optional[str] = None
    ) -> List[Dict]:
        """Get raw transactions with optional filters"""
        from src.database.models import RawTransaction

        with self.get_session() as session:
            q = session.query(RawTransaction)
            if account_number:
                q = q.filter(RawTransaction.account_number == account_number)
            if start_date:
                q = q.filter(RawTransaction.executed_at >= start_date)
            if end_date:
                q = q.filter(RawTransaction.executed_at <= end_date)
            if underlying:
                q = q.filter(RawTransaction.underlying_symbol == underlying)
            q = q.order_by(RawTransaction.executed_at.desc())
            return [row.to_dict() for row in q.all()]
    
    def get_open_positions(self) -> List[Dict[str, Any]]:
        """Get current open positions"""
        from src.database.models import Position as PositionModel
        with self.get_session() as session:
            rows = session.query(PositionModel).order_by(PositionModel.market_value.desc()).all()
            return [row.to_dict() for row in rows]
    
    def save_positions(self, positions: List[Dict[str, Any]], account_number: str) -> bool:
        """Save current positions for an account - batch insert via ORM"""
        from src.database.models import Position as PositionModel
        try:
            with self.get_session() as session:
                # Clear existing positions for this account
                session.query(PositionModel).filter(
                    PositionModel.account_number == account_number,
                ).delete()

                for pos in positions:
                    session.add(PositionModel(
                        account_number=account_number,
                        symbol=pos.get('symbol'),
                        underlying=pos.get('underlying_symbol'),
                        instrument_type=pos.get('instrument_type'),
                        quantity=pos.get('quantity'),
                        quantity_direction=pos.get('quantity_direction'),
                        average_open_price=pos.get('average_open_price'),
                        close_price=pos.get('close_price'),
                        market_value=pos.get('market_value'),
                        cost_basis=pos.get('cost_basis'),
                        realized_day_gain=pos.get('realized_day_gain'),
                        unrealized_pnl=pos.get('unrealized_pnl'),
                        pnl_percent=pos.get('pnl_percent'),
                        opened_at=pos.get('opened_at'),
                        expires_at=pos.get('expires_at'),
                        strike_price=pos.get('strike_price'),
                        option_type=pos.get('option_type'),
                        chain_id=pos.get('chain_id'),
                        strategy_type=pos.get('strategy_type'),
                    ))

                return True

        except Exception as e:
            logger.error(f"Error saving positions: {str(e)}")
            return False
    
    # Legacy statistics methods removed - use order/chain system for analytics

    def save_account_balance(self, balance: Dict[str, Any]) -> bool:
        """Save account balance snapshot"""
        from src.database.models import AccountBalance
        try:
            with self.get_session() as session:
                session.add(AccountBalance(
                    account_number=balance.get('account_number'),
                    cash_balance=balance.get('cash_balance'),
                    net_liquidating_value=balance.get('net_liquidating_value'),
                    margin_equity=balance.get('margin_equity'),
                    equity_buying_power=balance.get('equity_buying_power'),
                    derivative_buying_power=balance.get('derivative_buying_power'),
                    day_trading_buying_power=balance.get('day_trading_buying_power'),
                    maintenance_requirement=balance.get('maintenance_requirement'),
                ))
                return True
        except Exception as e:
            logger.error(f"Error saving account balance: {str(e)}")
            return False
    
    def get_sync_metadata(self, key: str) -> Optional[str]:
        """Get a sync metadata value by key"""
        from src.database.models import SyncMetadata
        with self.get_session() as session:
            row = session.query(SyncMetadata).filter(SyncMetadata.key == key).first()
            return row.value if row else None

    def set_sync_metadata(self, key: str, value: str) -> bool:
        """Set a sync metadata value"""
        from src.database.engine import dialect_insert
        from src.database.models import SyncMetadata
        from src.database.tenant import DEFAULT_USER_ID
        try:
            with self.get_session() as session:
                user_id = session.info.get("user_id", DEFAULT_USER_ID)
                stmt = dialect_insert(SyncMetadata).values(
                    key=key, value=value, user_id=user_id,
                    updated_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                )
                session.execute(stmt.on_conflict_do_update(
                    constraint='uq_sync_metadata_user_key',
                    set_={'value': stmt.excluded.value, 'updated_at': stmt.excluded.updated_at},
                ))
                return True
        except Exception as e:
            logger.error(f"Error setting sync metadata: {str(e)}")
            return False
    
    def get_last_sync_timestamp(self) -> Optional[datetime]:
        """Get the last sync timestamp"""
        timestamp_str = self.get_sync_metadata('last_sync_timestamp')
        if timestamp_str:
            try:
                return datetime.fromisoformat(timestamp_str)
            except ValueError:
                logger.warning(f"Invalid timestamp format: {timestamp_str}")
        return None
    
    def update_last_sync_timestamp(self, timestamp: datetime = None) -> bool:
        """Update the last sync timestamp"""
        if timestamp is None:
            timestamp = datetime.now()
        return self.set_sync_metadata('last_sync_timestamp', timestamp.isoformat())
    
    def is_initial_sync_completed(self) -> bool:
        """Check if initial sync has been completed"""
        return self.get_sync_metadata('initial_sync_completed') == 'true'
    
    def mark_initial_sync_completed(self) -> bool:
        """Mark initial sync as completed"""
        return self.set_sync_metadata('initial_sync_completed', 'true')
    
    def reset_sync_metadata(self) -> bool:
        """Reset sync metadata (for initial sync)"""
        from src.database.models import SyncMetadata
        try:
            with self.get_session() as session:
                session.query(SyncMetadata).delete()
                return True
        except Exception as e:
            logger.error(f"Error resetting sync metadata: {str(e)}")
            return False
    
    def cache_quote(self, symbol: str, quote_data: Dict[str, Any]) -> bool:
        """Cache a quote in the database"""
        from src.database.engine import dialect_insert
        from src.database.models import QuoteCache
        try:
            with self.get_session() as session:
                vals = dict(
                    symbol=symbol, mark=quote_data.get('mark'),
                    bid=quote_data.get('bid'), ask=quote_data.get('ask'),
                    last=quote_data.get('last'), change=quote_data.get('change'),
                    change_percent=quote_data.get('change_percent'),
                    volume=quote_data.get('volume'), prev_close=quote_data.get('prev_close'),
                    day_high=quote_data.get('day_high'), day_low=quote_data.get('day_low'),
                    iv=quote_data.get('iv'), ivr=quote_data.get('ivr'),
                    iv_percentile=quote_data.get('iv_percentile'),
                    updated_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                )
                stmt = dialect_insert(QuoteCache).values(**vals)
                update_vals = {k: v for k, v in vals.items() if k != 'symbol'}
                session.execute(stmt.on_conflict_do_update(
                    index_elements=['symbol'], set_=update_vals,
                ))
                return True
        except Exception as e:
            logger.error(f"Error caching quote for {symbol}: {str(e)}")
            return False
    
    def get_cached_quotes(self, symbols: List[str] = None) -> Dict[str, Dict[str, Any]]:
        """Get cached quotes from database"""
        from src.database.models import QuoteCache
        try:
            with self.get_session() as session:
                q = session.query(QuoteCache)
                if symbols:
                    q = q.filter(QuoteCache.symbol.in_(symbols))
                quotes = {}
                for row in q.all():
                    d = row.to_dict()
                    sym = d.pop('symbol')
                    quotes[sym] = d
                return quotes
        except Exception as e:
            logger.error(f"Error getting cached quotes: {str(e)}")
            return {}
    
    def get_strategy_targets(self) -> List[Dict[str, Any]]:
        """Get all strategy P&L targets"""
        from src.database.models import StrategyTarget
        with self.get_session() as session:
            rows = session.query(StrategyTarget).order_by(StrategyTarget.id).all()
            return [row.to_dict() for row in rows]

    def save_strategy_targets(self, targets: List[Dict[str, Any]]) -> bool:
        """Save strategy targets (upsert pattern)"""
        from src.database.engine import dialect_insert
        from src.database.models import StrategyTarget
        from src.database.tenant import DEFAULT_USER_ID
        try:
            with self.get_session() as session:
                user_id = session.info.get("user_id", DEFAULT_USER_ID)
                for target in targets:
                    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    stmt = dialect_insert(StrategyTarget).values(
                        strategy_name=target['strategy_name'],
                        profit_target_pct=target['profit_target_pct'],
                        loss_target_pct=target['loss_target_pct'],
                        updated_at=now, user_id=user_id,
                    )
                    session.execute(stmt.on_conflict_do_update(
                        constraint='uq_strategy_targets_user_name',
                        set_={
                            'profit_target_pct': stmt.excluded.profit_target_pct,
                            'loss_target_pct': stmt.excluded.loss_target_pct,
                            'updated_at': now,
                        },
                    ))
                return True
        except Exception as e:
            logger.error(f"Error saving strategy targets: {str(e)}")
            return False

    def reset_strategy_targets(self) -> bool:
        """Reset strategy targets to defaults"""
        from src.database.models import StrategyTarget
        try:
            with self.get_session() as session:
                session.query(StrategyTarget).delete()
                self._seed_default_strategy_targets_orm(session)
                return True
        except Exception as e:
            logger.error(f"Error resetting strategy targets: {str(e)}")
            return False

    def save_order_comment(self, order_id: str, comment: str) -> bool:
        """Save or delete a comment for an order"""
        from src.database.engine import dialect_insert
        from src.database.models import OrderComment
        from src.database.tenant import DEFAULT_USER_ID
        try:
            with self.get_session() as session:
                user_id = session.info.get("user_id", DEFAULT_USER_ID)
                if comment.strip():
                    stmt = dialect_insert(OrderComment).values(
                        order_id=order_id, comment=comment, user_id=user_id,
                        updated_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    )
                    session.execute(stmt.on_conflict_do_update(
                        index_elements=['order_id'],
                        set_={'comment': stmt.excluded.comment, 'updated_at': stmt.excluded.updated_at},
                    ))
                else:
                    session.query(OrderComment).filter(OrderComment.order_id == order_id).delete()
                return True
        except Exception as e:
            logger.error(f"Error saving order comment: {str(e)}")
            return False

    def get_all_order_comments(self) -> Dict[str, str]:
        """Get all order comments as a dict of order_id -> comment"""
        from src.database.models import OrderComment
        try:
            with self.get_session() as session:
                rows = session.query(OrderComment.order_id, OrderComment.comment).all()
                return {oid: c for oid, c in rows}
        except Exception as e:
            logger.error(f"Error getting order comments: {str(e)}")
            return {}

    def save_position_note(self, note_key: str, note: str) -> bool:
        """Save or delete a note for a position"""
        from src.database.engine import dialect_insert
        from src.database.models import PositionNote
        from src.database.tenant import DEFAULT_USER_ID
        try:
            with self.get_session() as session:
                user_id = session.info.get("user_id", DEFAULT_USER_ID)
                if note.strip():
                    stmt = dialect_insert(PositionNote).values(
                        note_key=note_key, note=note, user_id=user_id,
                        updated_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    )
                    session.execute(stmt.on_conflict_do_update(
                        index_elements=['note_key'],
                        set_={'note': stmt.excluded.note, 'updated_at': stmt.excluded.updated_at},
                    ))
                else:
                    session.query(PositionNote).filter(PositionNote.note_key == note_key).delete()
                return True
        except Exception as e:
            logger.error(f"Error saving position note: {str(e)}")
            return False

    def get_all_position_notes(self) -> Dict[str, str]:
        """Get all position notes as a dict of note_key -> note"""
        from src.database.models import PositionNote
        try:
            with self.get_session() as session:
                rows = session.query(PositionNote.note_key, PositionNote.note).all()
                return {nk: n for nk, n in rows}
        except Exception as e:
            logger.error(f"Error getting position notes: {str(e)}")
            return {}

