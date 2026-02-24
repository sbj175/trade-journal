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

load_dotenv()


class TastytradeClient:
    def __init__(self, provider_secret: str = None, refresh_token: str = None):
        """
        Initialize TastytradeClient with OAuth2 credentials.

        When called without arguments, reads from environment (backward compatible).
        When called with explicit credentials, uses those instead (per-user mode).
        """
        self.provider_secret = (provider_secret or os.getenv('TASTYTRADE_PROVIDER_SECRET') or '').strip()
        self.refresh_token = (refresh_token or os.getenv('TASTYTRADE_REFRESH_TOKEN') or '').strip()

        self.session = None
        self.accounts = []
        self.current_account = None

        # Quote caching
        self._quote_cache = {}
        self._quote_cache_time = {}
        self._quote_cache_duration = 30  # Cache quotes for 30 seconds

    def clear_quote_cache(self):
        """Clear the quote cache to force fresh data"""
        self._quote_cache.clear()
        self._quote_cache_time.clear()
        logger.info("Quote cache cleared")

    async def authenticate(self) -> bool:
        """Authenticate with Tastytrade API using OAuth2"""
        try:
            if not self.provider_secret or not self.refresh_token:
                logger.error("Missing OAuth credentials (TASTYTRADE_PROVIDER_SECRET / TASTYTRADE_REFRESH_TOKEN)")
                return False

            logger.info("Attempting to authenticate with Tastytrade OAuth2...")
            self.session = Session(self.provider_secret, self.refresh_token)
            logger.info("Successfully authenticated with Tastytrade")

            # Get all accounts
            self.accounts = await Account.get(self.session)
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

    async def get_transactions(self, days_back: int = 30, account_number: str = None, start_date: datetime = None) -> List[Dict[str, Any]]:
        """Get transactions from all accounts or a specific account.

        If *start_date* is provided it is used directly; otherwise the range
        is computed from *days_back*.
        """
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
        end_date = datetime.now()
        effective_start = start_date if start_date is not None else end_date - timedelta(days=days_back)

        for account in accounts_to_process:
            try:
                # Get transaction history - page_offset=None fetches all pages automatically
                transactions = await account.get_history(
                    self.session,
                    start_date=effective_start,
                    end_date=end_date,
                    per_page=250,
                    page_offset=None
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

    async def get_positions(self, account_number: str = None) -> Dict[str, List[Dict[str, Any]]]:
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
                positions = await account.get_positions(self.session, include_marks=True)

                position_list = []
                for pos in positions:
                    # Calculate market value
                    quantity = float(pos.quantity) if pos.quantity else 0
                    close_price = float(pos.close_price) if pos.close_price else 0

                    # For options, multiplier is typically 100, for stocks it's 1
                    # But Tastytrade API might already include the multiplier in the price
                    multiplier = float(pos.multiplier) if pos.multiplier else 100 if pos.instrument_type and 'option' in str(pos.instrument_type).lower() else 1

                    # Get mark value - pos.mark is the total position value, pos.mark_price is per-share
                    mark_value = float(pos.mark) if hasattr(pos, 'mark') and pos.mark else 0
                    mark_price_per_share = float(pos.mark_price) if hasattr(pos, 'mark_price') and pos.mark_price else 0

                    # Get average open price (cost basis per unit)
                    average_open_price = float(pos.average_open_price) if pos.average_open_price else 0

                    # Tastytrade API returns prices in cents for options, so no additional multiplier needed
                    # Check if this is a short position
                    is_short = (quantity < 0) or (pos.quantity_direction == 'Short')

                    if pos.instrument_type and 'option' in str(pos.instrument_type).lower():
                        # Option cost basis = abs(quantity) * average_open_price * 100
                        # Sign matters: negative for long (cost), positive for short (credit)
                        cost_basis_abs = abs(quantity) * average_open_price * 100
                        cost_basis = -cost_basis_abs if not is_short else cost_basis_abs

                        if is_short:
                            # For short positions: use negative of the total mark value
                            market_value = -abs(mark_value)
                        else:
                            # For long positions: use the total mark value directly
                            market_value = mark_value
                    else:
                        # Stock cost basis = abs(quantity) * average_open_price
                        # Sign matters: negative for long (cost), positive for short (credit)
                        cost_basis_abs = abs(quantity) * average_open_price
                        cost_basis = -cost_basis_abs if not is_short else cost_basis_abs

                        if is_short:
                            # For short positions: market value is negative
                            market_value = -abs(mark_value)
                        else:
                            # For long positions: market value is positive
                            market_value = mark_value

                    # Calculate unrealized P&L
                    unrealized_pnl = market_value - cost_basis

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
                        'mark_price': mark_price_per_share * 100,  # Convert to cents for consistency
                        'mark_value_total': mark_value,  # Total position mark value
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

    async def get_orders(self, status: Optional[OrderStatus] = None) -> List[Dict[str, Any]]:
        """Get orders with optional status filter"""
        if not self.current_account:
            logger.error("Not authenticated")
            return []

        try:
            # Get live orders by default if no status specified
            if status is None:
                orders = await self.current_account.get_live_orders(self.session)
            else:
                # For historical orders, use order history
                orders = await self.current_account.get_order_history(
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

    def _classify_symbols(self, symbols: List[str]) -> Dict[str, List[str]]:
        """Classify symbols into equities and options based on format"""
        equities = []
        options = []

        for symbol in symbols:
            # Option symbols have double spaces and end with C/P followed by strike
            # Format: "MSTR  250613C00400000" (underlying + double space + YYMMDDC/P + strike)
            if len(symbol) > 10 and '  ' in symbol:
                # Check if it looks like an option symbol
                parts = symbol.split('  ')
                if len(parts) == 2 and len(parts[1]) >= 9:
                    # Check for C or P in the expected position (7th character after space)
                    option_part = parts[1]
                    if len(option_part) >= 7 and option_part[6] in ['C', 'P']:
                        options.append(symbol)
                        continue

            # Default to equity
            equities.append(symbol)

        return {'equities': equities, 'options': options}

    async def get_quotes(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """Get current market quotes using Tastytrade market data API - NO MOCK DATA"""
        if not self.session:
            logger.error("Not authenticated")
            raise Exception("Not authenticated with Tastytrade")

        import time
        from tastytrade.market_data import get_market_data_by_type

        quotes = {}
        current_time = time.time()

        # Check cache first
        cached_symbols = []
        missing_symbols = []

        for symbol in symbols:
            if (symbol in self._quote_cache and
                symbol in self._quote_cache_time and
                current_time - self._quote_cache_time[symbol] < self._quote_cache_duration):
                quotes[symbol] = self._quote_cache[symbol]
                cached_symbols.append(symbol)
            else:
                missing_symbols.append(symbol)

        if cached_symbols:
            logger.info(f"Using cached quotes for: {cached_symbols}")

        # Only fetch missing symbols
        if missing_symbols:
            logger.info(f"Fetching new quotes for: {missing_symbols}")

            try:
                # Classify symbols by type
                symbol_types = self._classify_symbols(missing_symbols)
                logger.info(f"Symbol classification: {len(symbol_types['equities'])} equities, {len(symbol_types['options'])} options")

                market_data_list = []

                # Fetch equity quotes
                if symbol_types['equities']:
                    logger.info(f"Fetching equity quotes for: {symbol_types['equities']}")
                    equity_data = await get_market_data_by_type(
                        self.session,
                        equities=symbol_types['equities']
                    )
                    if equity_data:
                        market_data_list.extend(equity_data)

                # Fetch option quotes
                if symbol_types['options']:
                    logger.info(f"Fetching option quotes for: {symbol_types['options']}")
                    option_data = await get_market_data_by_type(
                        self.session,
                        options=symbol_types['options']
                    )
                    if option_data:
                        market_data_list.extend(option_data)

                # Process market data into quotes format
                for market_data in market_data_list:
                    symbol = market_data.symbol

                    # Calculate current price (use mark, or mid of bid/ask)
                    current_price = float(market_data.mark) if market_data.mark else 0.0
                    bid_price = float(market_data.bid) if market_data.bid else 0.0
                    ask_price = float(market_data.ask) if market_data.ask else 0.0

                    # Get previous close for change calculation
                    prev_close = float(market_data.prev_close) if market_data.prev_close else 0.0

                    # Calculate change and change percentage
                    change = 0.0
                    change_percent = 0.0
                    if current_price > 0 and prev_close > 0:
                        change = current_price - prev_close
                        change_percent = (change / prev_close) * 100

                    # Get day high/low from market data
                    day_high = float(market_data.day_high) if market_data.day_high else 0.0
                    day_low = float(market_data.day_low) if market_data.day_low else 0.0

                    # Look for IVR and IV data in market data
                    ivr = None
                    iv = None
                    iv_percentile = None

                    # Check for various IVR field names
                    ivr_fields = ['implied_volatility_index_rank', 'iv_rank', 'ivr', 'implied_volatility_rank', 'volatility_rank', 'iv_rank_30']
                    for field in ivr_fields:
                        if hasattr(market_data, field):
                            value = getattr(market_data, field)
                            if value is not None:
                                ivr = float(value)
                                logger.info(f"Found IVR for {symbol} in field '{field}': {ivr}")
                                break

                    # Check for IV fields
                    iv_fields = ['implied_volatility', 'iv', 'volatility', 'iv_30']
                    for field in iv_fields:
                        if hasattr(market_data, field):
                            value = getattr(market_data, field)
                            if value is not None:
                                iv = float(value) * 100  # Convert to percentage
                                logger.info(f"Found IV for {symbol} in field '{field}': {iv}")
                                break

                    # Check for IV percentile
                    percentile_fields = ['iv_percentile', 'implied_volatility_percentile', 'volatility_percentile']
                    for field in percentile_fields:
                        if hasattr(market_data, field):
                            value = getattr(market_data, field)
                            if value is not None:
                                iv_percentile = float(value)
                                logger.info(f"Found IV percentile for {symbol} in field '{field}': {iv_percentile}")
                                break

                    quote_data = {
                        'symbol': symbol,
                        'price': current_price,  # Frontend expects 'price' not 'mark'
                        'mark': current_price,
                        'bid': bid_price,
                        'ask': ask_price,
                        'last': float(market_data.last) if market_data.last else current_price,
                        'change': change,
                        'changePercent': change_percent,  # Frontend expects camelCase
                        'change_percent': change_percent,  # Keep snake_case for compatibility
                        'volume': int(market_data.volume) if market_data.volume else 0,
                        'prev_close': prev_close,
                        'day_high': day_high,
                        'day_low': day_low,
                    }

                    # Add IVR/IV data if found
                    if ivr is not None:
                        quote_data['ivr'] = ivr
                    if iv is not None:
                        quote_data['iv'] = iv
                    if iv_percentile is not None:
                        quote_data['iv_percentile'] = iv_percentile

                    # Update cache
                    self._quote_cache[symbol] = quote_data
                    self._quote_cache_time[symbol] = current_time
                    quotes[symbol] = quote_data

                    logger.info(f"Market data for {symbol}: price=${current_price:.2f}, change={change:+.2f} ({change_percent:+.2f}%), IVR={ivr}, IV={iv}")

                # Try to get market metrics (IV/IVR) for equity symbols
                if symbol_types['equities']:
                    try:
                        metrics = await self.get_market_metrics(symbol_types['equities'])

                        for symbol, metric_data in metrics.items():
                            if symbol in quotes:
                                quotes[symbol].update(metric_data)
                                logger.info(f"Added IV data to {symbol}: {metric_data}")
                    except Exception as metrics_error:
                        logger.warning(f"Failed to get market metrics: {metrics_error}")

            except Exception as e:
                logger.error(f"Failed to get market data: {str(e)}")
                # Fall back to streaming quotes if market data API fails
                logger.info("Falling back to streaming quotes...")
                streaming_quotes = await self._async_fetch_quotes(missing_symbols)

                for symbol, quote_data in streaming_quotes.items():
                    self._quote_cache[symbol] = quote_data
                    self._quote_cache_time[symbol] = current_time
                    quotes[symbol] = quote_data

        # Return only successfully retrieved quotes (real data only)
        logger.info(f"Returning {len(quotes)} real quotes for symbols: {list(quotes.keys())}")
        if len(quotes) < len(symbols):
            failed_symbols = [s for s in symbols if s not in quotes]
            logger.warning(f"Failed to get quotes for: {failed_symbols}")

        return quotes

    async def _async_fetch_quotes(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """Async method to fetch quotes using streaming API with enhanced change data"""
        from tastytrade import DXLinkStreamer
        from tastytrade.dxfeed import Quote, Trade, Greeks
        import asyncio
        import time

        quotes = {}
        greeks_data = {}

        # Try to get quotes via streaming
        try:
            logger.info("Creating async DXLinkStreamer...")
            async with DXLinkStreamer(self.session) as streamer:
                logger.info("DXLinkStreamer created and connected")

                # Subscribe to Quote events (reliable) and Trade events (for change data)
                logger.info(f"Subscribing to Quote and Trade events for symbols: {symbols}")
                await streamer.subscribe(Quote, symbols)  # For bid/ask

                # Try to subscribe to Trade events for change data (may not always work)
                has_trade_subscription = False
                try:
                    await streamer.subscribe(Trade, symbols)
                    logger.info("Successfully subscribed to Trade events")
                    has_trade_subscription = True
                except Exception as trade_error:
                    logger.warning(f"Could not subscribe to Trade events: {trade_error}")

                # Subscribe to Greeks events for IV data
                has_greeks_subscription = False
                try:
                    await streamer.subscribe(Greeks, symbols)
                    logger.info("Successfully subscribed to Greeks events")
                    has_greeks_subscription = True
                except Exception as greeks_error:
                    logger.warning(f"Could not subscribe to Greeks events: {greeks_error}")

                logger.info(f"Successfully subscribed to Quote events for {len(symbols)} symbols")

                # Collect quotes for a reasonable time period
                timeout = 6.0
                events_received = 0
                quotes_received = 0
                trade_events = 0

                logger.info("Listening for Quote and Trade events...")

                async def process_quotes():
                    nonlocal quotes_received, events_received
                    async for event in streamer.listen(Quote):
                        events_received += 1

                        # Get symbol from event
                        symbol = getattr(event, 'event_symbol', None)
                        if not symbol or symbol not in symbols:
                            continue

                        if isinstance(event, Quote):
                            quotes_received += 1

                            # Get bid/ask prices and other available data
                            bid_price = getattr(event, 'bid_price', None)
                            ask_price = getattr(event, 'ask_price', None)

                            # Calculate mark price
                            mark_price = 0.0
                            if bid_price and ask_price:
                                mark_price = (float(bid_price) + float(ask_price)) / 2
                            elif bid_price:
                                mark_price = float(bid_price)
                            elif ask_price:
                                mark_price = float(ask_price)

                            # Try to get additional fields that might be available
                            last_price = getattr(event, 'last_price', None) or getattr(event, 'price', None)
                            change = getattr(event, 'change', None) or getattr(event, 'daily_change', None)
                            change_percent = getattr(event, 'change_percent', None) or getattr(event, 'daily_change_percent', None)
                            volume = getattr(event, 'volume', None) or getattr(event, 'day_volume', None)

                            quotes[symbol] = {
                                'symbol': symbol,
                                'price': mark_price,
                                'mark': mark_price,
                                'bid': float(bid_price) if bid_price else 0.0,
                                'ask': float(ask_price) if ask_price else 0.0,
                                'last': float(last_price) if last_price else mark_price,
                                'change': float(change) if change else 0.0,
                                'changePercent': float(change_percent) if change_percent else 0.0,
                                'change_percent': float(change_percent) if change_percent else 0.0,
                                'volume': int(volume) if volume else 0,
                            }

                async def process_greeks():
                    nonlocal greeks_data
                    if not has_greeks_subscription:
                        return

                    async for event in streamer.listen(Greeks):
                        symbol = getattr(event, 'event_symbol', None)
                        if not symbol:
                            continue

                        # Check if this symbol or its underlying is in our list
                        relevant_symbol = None
                        if symbol in symbols:
                            relevant_symbol = symbol
                        else:
                            for s in symbols:
                                if symbol.startswith(s + '  '):
                                    relevant_symbol = s
                                    break

                        if not relevant_symbol:
                            continue

                        if isinstance(event, Greeks):
                            iv = getattr(event, 'volatility', None)
                            delta = getattr(event, 'delta', None)
                            gamma = getattr(event, 'gamma', None)
                            theta = getattr(event, 'theta', None)
                            vega = getattr(event, 'vega', None)
                            rho = getattr(event, 'rho', None)

                            ivr = None
                            ivr_fields = ['implied_volatility_index_rank', 'iv_rank', 'implied_volatility_rank', 'volatility_rank', 'ivr']
                            for field in ivr_fields:
                                if hasattr(event, field):
                                    value = getattr(event, field)
                                    if value is not None:
                                        ivr = float(value)
                                        break

                            greeks_data[relevant_symbol] = {
                                'iv': float(iv) * 100 if iv else None,
                                'ivr': ivr,
                                'delta': float(delta) if delta else None,
                                'gamma': float(gamma) if gamma else None,
                                'theta': float(theta) if theta else None,
                                'vega': float(vega) if vega else None,
                                'rho': float(rho) if rho else None,
                            }

                # Run both listeners concurrently with timeout
                tasks = [process_quotes()]
                if has_greeks_subscription:
                    tasks.append(process_greeks())

                try:
                    await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=True),
                        timeout=timeout
                    )
                except asyncio.TimeoutError:
                    logger.info(f"Streaming timeout reached after {timeout} seconds")
                except Exception as listen_error:
                    logger.warning(f"Error in streamer.listen(): {listen_error}")

                logger.info(f"Streaming completed - Events: {events_received}, Quotes: {quotes_received}, Trades: {trade_events}")

            # Merge Greeks data into quotes
            for symbol, greeks in greeks_data.items():
                if symbol in quotes:
                    quotes[symbol].update(greeks)
                else:
                    quotes[symbol] = greeks

            logger.info(f"Collected {len(quotes)} streaming quotes with {len(greeks_data)} Greeks")

        except Exception as streaming_error:
            logger.error(f"Async streaming quotes failed: {streaming_error}", exc_info=True)
            quotes = {}

        return quotes

    async def get_market_metrics(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Get market metrics including IV/IVR for symbols.
        Try multiple Tastytrade API endpoints to find volatility data.
        """
        if not self.session:
            logger.error("Not authenticated")
            return {}

        metrics = {}

        try:
            # Try market metrics API
            try:
                from tastytrade.metrics import get_market_metrics

                for symbol in symbols:
                    try:
                        metric_data = await get_market_metrics(self.session, [symbol])
                        if metric_data and len(metric_data) > 0:
                            data = metric_data[0]

                            iv = None
                            ivr = None

                            # Look for IV
                            iv_fields = ['implied_volatility_index', 'iv_index', 'volatility', 'implied_volatility', 'iv']
                            for field in iv_fields:
                                if hasattr(data, field):
                                    value = getattr(data, field)
                                    if value is not None:
                                        iv = float(value) * 100
                                        logger.debug(f"Found IV in market metrics for {symbol}.{field}: {iv}")
                                        break

                            # Look for IVR
                            ivr_fields = ['implied_volatility_index_rank', 'implied_volatility_rank', 'iv_rank', 'volatility_rank', 'ivr', 'iv_rank_30']
                            for field in ivr_fields:
                                if hasattr(data, field):
                                    value = getattr(data, field)
                                    if value is not None:
                                        ivr = float(value)
                                        logger.debug(f"Found IVR in market metrics for {symbol}.{field}: {ivr}")
                                        break

                            if iv is not None or ivr is not None:
                                metrics[symbol] = {
                                    'iv': iv,
                                    'ivr': ivr,
                                    'iv_percentile': getattr(data, 'iv_percentile', None),
                                    'historical_volatility': getattr(data, 'historical_volatility', None),
                                }
                    except Exception as e:
                        logger.warning(f"Failed to get market metrics for {symbol}: {e}")

            except ImportError:
                logger.info("Market metrics API not available")
            except Exception as e:
                logger.warning(f"Market metrics API failed: {e}")

        except Exception as e:
            logger.error(f"Error in get_market_metrics: {e}")

        return metrics

    def calculate_ivr(self, current_iv: float, symbol: str) -> Optional[float]:
        """
        Calculate IVR (Implied Volatility Rank) if historical data is available.
        For now, returns None as we need historical IV data.
        """
        return None

    async def get_account_balances(self) -> List[Dict[str, Any]]:
        """Get account balances and buying power for all accounts"""
        if not self.session:
            logger.error("Not authenticated")
            return []

        all_balances = []
        for account in self.accounts:
            try:
                balance = await account.get_balances(self.session)

                logger.info(f"Balance for {account.account_number}:")
                logger.info(f"  net_liquidating_value: {balance.net_liquidating_value}")
                logger.info(f"  margin_equity: {balance.margin_equity}")
                logger.info(f"  cash_balance: {balance.cash_balance}")
                logger.info(f"  cash_available_to_withdraw: {balance.cash_available_to_withdraw}")
                logger.info(f"  available_trading_funds: {balance.available_trading_funds}")
                logger.info(f"  long_equity_value: {balance.long_equity_value}")
                logger.info(f"  short_equity_value: {balance.short_equity_value}")
                logger.info(f"  long_derivative_value: {balance.long_derivative_value}")
                logger.info(f"  short_derivative_value: {balance.short_derivative_value}")
                logger.info(f"  pending_cash: {balance.pending_cash}")

                account_balance = {
                    'account_number': account.account_number,
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

                all_balances.append(account_balance)
                logger.info(f"Fetched balance for account {account.account_number}")

            except Exception as e:
                logger.error(f"Failed to get balance for account {account.account_number}: {str(e)}")
                continue

        return all_balances
