import os
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv
from tastytrade import Session, Account
from tastytrade.order import OrderStatus
from loguru import logger

# Add parent directory to path for imports
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.utils.credential_manager import CredentialManager

load_dotenv()


class TastytradeClient:
    def __init__(self):
        # Try to get credentials from encrypted file first, then fall back to env vars
        credential_manager = CredentialManager()
        self.username, self.password = credential_manager.get_tastytrade_credentials()
        
        # If no encrypted credentials, fall back to environment variables
        if not self.username or not self.password:
            self.username = os.getenv('TASTYTRADE_USERNAME')
            self.password = os.getenv('TASTYTRADE_PASSWORD')
            
        self.session = None
        self.accounts = []
        self.current_account = None
        
    def authenticate(self) -> bool:
        """Authenticate with Tastytrade API"""
        try:
            if not self.username or not self.password:
                logger.error("Missing username or password")
                return False
                
            logger.info(f"Attempting to authenticate as {self.username}")
            self.session = Session(self.username, self.password)
            logger.info(f"Successfully authenticated as {self.username}")
            
            # Get all accounts
            self.accounts = Account.get(self.session)
            if self.accounts:
                self.current_account = self.accounts[0]  # Default to first account
                logger.info(f"Found {len(self.accounts)} accounts:")
                for account in self.accounts:
                    logger.info(f"  - {account.account_number}")
                logger.info(f"Using default account: {self.current_account.account_number}")
                return True
            else:
                logger.error("No accounts found")
                return False
                
        except Exception as e:
            logger.error(f"Authentication failed: {str(e)}")
            if "Invalid credentials" in str(e) or "authentication" in str(e).lower():
                logger.error("Please check your username and password")
            return False
    
    def get_all_accounts(self) -> List[Dict[str, Any]]:
        """Get all available accounts"""
        if not self.accounts:
            logger.error("Not authenticated")
            return []
        
        account_list = []
        for account in self.accounts:
            account_list.append({
                'account_number': account.account_number,
                'account_name': getattr(account, 'nickname', None) or account.account_number,
                'account_type': getattr(account, 'account_type', 'Unknown'),
                'is_closed': getattr(account, 'is_closed', False),
                'day_trader_status': getattr(account, 'day_trader_status', False),
            })
        
        return account_list
    
    def get_transactions(self, days_back: int = 30, account_number: str = None) -> List[Dict[str, Any]]:
        """Get transactions for the past N days from all accounts or specific account"""
        if not self.accounts:
            logger.error("Not authenticated")
            return []
        
        # Get transactions from all accounts or specific account
        accounts_to_process = []
        if account_number:
            # Find specific account
            for account in self.accounts:
                if account.account_number == account_number:
                    accounts_to_process = [account]
                    break
            if not accounts_to_process:
                logger.error(f"Account {account_number} not found")
                return []
        else:
            # Process all accounts
            accounts_to_process = self.accounts
        
        all_transactions = []
        
        for account in accounts_to_process:
            try:
                # Calculate date range
                end_date = datetime.now()
                start_date = end_date - timedelta(days=days_back)
                
                # Get transaction history using the correct method
                transactions = account.get_history(
                    self.session,
                    start_date=start_date,
                    end_date=end_date,
                    per_page=250
                )
                
                # Convert to list of dicts
                for tx in transactions:
                    # Convert to dict, handling optional fields
                    tx_dict = {
                        'id': tx.id,
                        'account_number': account.account_number,  # Add account info
                        'transaction_type': tx.transaction_type,
                        'transaction_sub_type': tx.transaction_sub_type,
                        'description': tx.description,
                        'executed_at': tx.executed_at.isoformat() if tx.executed_at else None,
                        'transaction_date': tx.transaction_date.isoformat() if tx.transaction_date else None,
                        'action': str(tx.action) if tx.action else None,
                        'symbol': tx.symbol,
                        'instrument_type': str(tx.instrument_type) if tx.instrument_type else None,
                        'underlying_symbol': tx.underlying_symbol,
                        'quantity': float(tx.quantity) if tx.quantity else None,
                        'price': float(tx.price) if tx.price else None,
                        'value': float(tx.value) if tx.value else 0,
                        'regulatory_fees': float(tx.regulatory_fees) if tx.regulatory_fees else 0,
                        'clearing_fees': float(tx.clearing_fees) if tx.clearing_fees else 0,
                        'commission': float(tx.commission) if tx.commission else 0,
                        'net_value': float(tx.net_value) if tx.net_value else 0,
                        'order_id': tx.order_id,
                        'is_estimated_fee': tx.is_estimated_fee,
                    }
                    all_transactions.append(tx_dict)
                
                logger.info(f"Retrieved {len(transactions)} transactions from account {account.account_number}")
                
            except Exception as e:
                logger.error(f"Failed to get transactions from account {account.account_number}: {str(e)}")
                continue
        
        logger.info(f"Retrieved {len(all_transactions)} total transactions from {len(accounts_to_process)} accounts")
        return all_transactions
    
    def get_positions(self, account_number: str = None) -> Dict[str, List[Dict[str, Any]]]:
        """Get current positions from all accounts or specific account"""
        if not self.accounts:
            logger.error("Not authenticated")
            return {}
        
        # Get positions from all accounts or specific account
        accounts_to_process = []
        if account_number:
            # Find specific account
            for account in self.accounts:
                if account.account_number == account_number:
                    accounts_to_process = [account]
                    break
            if not accounts_to_process:
                logger.error(f"Account {account_number} not found")
                return {}
        else:
            # Process all accounts
            accounts_to_process = self.accounts
        
        all_positions = {}
        
        for account in accounts_to_process:
            try:
                # Get positions with marks for current values
                positions = account.get_positions(self.session, include_marks=True)
                
                position_list = []
                for pos in positions:
                    # Calculate market value
                    quantity = float(pos.quantity) if pos.quantity else 0
                    close_price = float(pos.close_price) if pos.close_price else 0
                    
                    # For options, multiplier is typically 100, for stocks it's 1
                    # But Tastytrade API might already include the multiplier in the price
                    multiplier = float(pos.multiplier) if pos.multiplier else 100 if pos.instrument_type and 'option' in str(pos.instrument_type).lower() else 1
                    
                    # Get mark price (current price)
                    mark_price = float(pos.mark) if hasattr(pos, 'mark') and pos.mark else close_price
                    
                    # Get average open price (cost basis per unit)
                    average_open_price = float(pos.average_open_price) if pos.average_open_price else 0
                    
                    # For options, prices are typically quoted per share, so we need to multiply by 100
                    # For stocks, the price is already per share
                    if pos.instrument_type and 'option' in str(pos.instrument_type).lower():
                        # Option market value = quantity * mark_price * 100
                        market_value = quantity * mark_price * 100
                        # Option cost basis = quantity * average_open_price * 100
                        cost_basis = abs(quantity) * average_open_price * 100
                    else:
                        # Stock market value = quantity * mark_price
                        market_value = quantity * mark_price
                        # Stock cost basis = quantity * average_open_price
                        cost_basis = abs(quantity) * average_open_price
                    
                    # Calculate unrealized P&L
                    # For long positions (positive quantity), P&L = market_value - cost_basis
                    # For short positions (negative quantity), P&L = cost_basis - market_value
                    if quantity > 0:
                        unrealized_pnl = market_value - cost_basis
                    else:
                        unrealized_pnl = cost_basis - abs(market_value)
                    
                    # Calculate P&L percentage
                    pnl_percent = (unrealized_pnl / abs(cost_basis) * 100) if cost_basis != 0 else 0
                    
                    # Extract option-specific fields if available
                    strike_price = None
                    option_type = None
                    
                    if pos.instrument_type and 'option' in str(pos.instrument_type).lower():
                        # Try to get strike price from various possible fields
                        if hasattr(pos, 'strike_price'):
                            strike_price = float(pos.strike_price)
                        elif hasattr(pos, 'strike'):
                            strike_price = float(pos.strike)
                        
                        # Try to get option type from various possible fields
                        if hasattr(pos, 'option_type'):
                            option_type = str(pos.option_type)
                        elif hasattr(pos, 'right'):
                            option_type = 'C' if str(pos.right).upper() in ['CALL', 'C'] else 'P'
                        elif hasattr(pos, 'call_or_put'):
                            option_type = 'C' if str(pos.call_or_put).upper() in ['CALL', 'C'] else 'P'
                    
                    position_list.append({
                        'symbol': pos.symbol,
                        'instrument_type': str(pos.instrument_type) if pos.instrument_type else None,
                        'underlying_symbol': pos.underlying_symbol,
                        'quantity': quantity,
                        'quantity_direction': pos.quantity_direction,
                        'close_price': close_price,
                        'mark_price': mark_price,
                        'average_open_price': average_open_price,
                        'market_value': market_value,
                        'cost_basis': cost_basis,
                        'realized_day_gain': float(pos.realized_day_gain) if pos.realized_day_gain else 0,
                        'realized_today': float(pos.realized_today) if pos.realized_today else 0,
                        'unrealized_pnl': unrealized_pnl,
                        'pnl_percent': pnl_percent,
                        'multiplier': multiplier,
                        'expires_at': pos.expires_at.isoformat() if pos.expires_at else None,
                        'strike_price': strike_price,
                        'option_type': option_type,
                    })
                
                all_positions[account.account_number] = position_list
                logger.info(f"Retrieved {len(position_list)} positions from account {account.account_number}")
                
            except Exception as e:
                logger.error(f"Failed to get positions from account {account.account_number}: {str(e)}")
                all_positions[account.account_number] = []
                continue
        
        return all_positions
    
    def get_orders(self, status: Optional[OrderStatus] = None) -> List[Dict[str, Any]]:
        """Get orders with optional status filter"""
        if not self.current_account:
            logger.error("Not authenticated")
            return []
            
        try:
            # Get live orders by default if no status specified
            if status is None:
                orders = self.current_account.get_live_orders(self.session)
            else:
                # For historical orders, use order history
                orders = self.current_account.get_order_history(
                    self.session,
                    start_date=datetime.now() - timedelta(days=30),
                    end_date=datetime.now(),
                    per_page=250
                )
                # Filter by status if provided
                orders = [o for o in orders if str(o.status) == str(status)]
            
            order_list = []
            for order in orders:
                # Convert order to dict, handling all available fields
                order_dict = {
                    'id': order.id,
                    'account_number': order.account_number,
                    'time_in_force': str(order.time_in_force) if order.time_in_force else None,
                    'order_type': str(order.order_type) if order.order_type else None,
                    'size': float(order.size) if order.size else None,
                    'underlying_symbol': order.underlying_symbol,
                    'underlying_instrument_type': str(order.underlying_instrument_type) if order.underlying_instrument_type else None,
                    'status': str(order.status) if order.status else None,
                    'price': float(order.price) if order.price else None,
                    'value': float(order.value) if order.value else None,
                    'stop_trigger': order.stop_trigger,
                    'gtc_date': order.gtc_date.isoformat() if order.gtc_date else None,
                    'updated_at': order.updated_at.isoformat() if order.updated_at else None,
                    'received_at': order.received_at.isoformat() if order.received_at else None,
                    'live_at': order.live_at.isoformat() if order.live_at else None,
                    'in_flight_at': order.in_flight_at.isoformat() if order.in_flight_at else None,
                    'terminal_at': order.terminal_at.isoformat() if order.terminal_at else None,
                    'cancelled_at': order.cancelled_at.isoformat() if order.cancelled_at else None,
                    'cancellable': order.cancellable,
                    'editable': order.editable,
                    'edited': order.edited,
                    'username': order.username,
                    'reject_reason': order.reject_reason,
                    'complex_order_id': order.complex_order_id,
                    'complex_order_tag': order.complex_order_tag,
                    'legs': []  # Will populate legs below
                }
                
                # Add leg information if available
                if order.legs:
                    for leg in order.legs:
                        leg_dict = {
                            'instrument_type': str(leg.instrument_type) if leg.instrument_type else None,
                            'symbol': leg.symbol,
                            'action': str(leg.action) if leg.action else None,
                            'quantity': float(leg.quantity) if leg.quantity else None,
                            'remaining_quantity': float(leg.remaining_quantity) if leg.remaining_quantity else None,
                        }
                        order_dict['legs'].append(leg_dict)
                
                order_list.append(order_dict)
            
            logger.info(f"Retrieved {len(order_list)} orders")
            return order_list
            
        except Exception as e:
            logger.error(f"Failed to get orders: {str(e)}")
            return []
    
    def get_account_balances(self) -> Dict[str, Any]:
        """Get account balances and buying power"""
        if not self.current_account:
            logger.error("Not authenticated")
            return {}
            
        try:
            balance = self.current_account.get_balances(self.session)
            
            return {
                'account_number': self.current_account.account_number,
                'cash_balance': float(balance.cash_balance) if balance.cash_balance else 0,
                'net_liquidating_value': float(balance.net_liquidating_value) if balance.net_liquidating_value else 0,
                'equity_buying_power': float(balance.equity_buying_power) if balance.equity_buying_power else 0,
                'derivative_buying_power': float(balance.derivative_buying_power) if balance.derivative_buying_power else 0,
                'day_trading_buying_power': float(balance.day_trading_buying_power) if balance.day_trading_buying_power else 0,
                'cash_available_to_withdraw': float(balance.cash_available_to_withdraw) if balance.cash_available_to_withdraw else 0,
                'maintenance_requirement': float(balance.maintenance_requirement) if balance.maintenance_requirement else 0,
                'pending_cash': float(balance.pending_cash) if balance.pending_cash else 0,
                'long_equity_value': float(balance.long_equity_value) if balance.long_equity_value else 0,
                'short_equity_value': float(balance.short_equity_value) if balance.short_equity_value else 0,
                'margin_equity': float(balance.margin_equity) if balance.margin_equity else 0,
                'updated_at': datetime.now().isoformat(),
            }
            
        except Exception as e:
            logger.error(f"Failed to get account balances: {str(e)}")
            return {}