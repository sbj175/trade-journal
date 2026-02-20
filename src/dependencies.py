"""Singleton instances shared across routers and services."""

from fastapi.templating import Jinja2Templates

from src.database.db_manager import DatabaseManager
from src.models.order_models import OrderManager
from src.models.position_inventory import PositionInventoryManager
from src.models.order_processor import OrderProcessor
from src.models.strategy_detector import StrategyDetector
from src.models.pnl_calculator import PnLCalculator
from src.models.lot_manager import LotManager
from src.utils.auth_manager import ConnectionManager

db = DatabaseManager()
order_manager = OrderManager(db)
position_manager = PositionInventoryManager(db)
lot_manager = LotManager(db)
order_processor = OrderProcessor(db, position_manager, lot_manager)
strategy_detector = StrategyDetector(db)
pnl_calculator = PnLCalculator(db, position_manager, lot_manager)
connection_manager = ConnectionManager()
templates = Jinja2Templates(directory="static")
