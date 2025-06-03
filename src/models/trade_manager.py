"""
Trade Management System
Handles trade notes, status updates, and persistence
"""

import json
import os
from datetime import datetime, date
from typing import List, Dict, Optional
from dataclasses import asdict
from .trade_strategy import Trade, StrategyType, TradeStatus, StrategyRecognizer


class TradeManager:
    """Manages trades, notes, and persistence"""
    
    def __init__(self, data_file: str = "trade_data.json"):
        self.data_file = data_file
        self.trades: Dict[str, Trade] = {}
        self.load_trades()
    
    def process_transactions(self, transactions: List[Dict]) -> List[Trade]:
        """Process transactions and group them into trades"""
        
        # Use strategy recognizer to create trades
        new_trades = StrategyRecognizer.group_transactions_into_trades(transactions)
        
        # Merge with existing trades (update if exists, add if new)
        for trade in new_trades:
            existing_trade = self.trades.get(trade.trade_id)
            
            if existing_trade:
                # Update existing trade while preserving notes
                self._update_existing_trade(existing_trade, trade)
            else:
                # Add new trade
                self.trades[trade.trade_id] = trade
        
        # Save updated trades
        self.save_trades()
        
        return list(self.trades.values())
    
    def _update_existing_trade(self, existing: Trade, updated: Trade):
        """Update existing trade while preserving user data"""
        
        # Preserve user-entered data
        preserved_original_notes = existing.original_notes
        preserved_current_notes = existing.current_notes
        preserved_tags = existing.tags
        
        # Update with new data
        existing.option_legs = updated.option_legs
        existing.stock_legs = updated.stock_legs
        existing.status = updated.status
        existing.exit_date = updated.exit_date
        existing.strategy_type = updated.strategy_type
        
        # Restore preserved data
        existing.original_notes = preserved_original_notes
        existing.current_notes = preserved_current_notes
        existing.tags = preserved_tags
    
    def add_trade_notes(self, trade_id: str, original_notes: str = None, current_notes: str = None):
        """Add or update notes for a trade"""
        
        if trade_id not in self.trades:
            raise ValueError(f"Trade {trade_id} not found")
        
        trade = self.trades[trade_id]
        
        if original_notes is not None:
            trade.original_notes = original_notes
        
        if current_notes is not None:
            trade.current_notes = current_notes
        
        self.save_trades()
    
    def update_trade_status(self, trade_id: str, status: TradeStatus):
        """Update trade status"""
        
        if trade_id not in self.trades:
            raise ValueError(f"Trade {trade_id} not found")
        
        self.trades[trade_id].status = status
        
        if status == TradeStatus.CLOSED and not self.trades[trade_id].exit_date:
            self.trades[trade_id].exit_date = date.today()
        
        self.save_trades()
    
    def add_trade_tags(self, trade_id: str, tags: List[str]):
        """Add tags to a trade"""
        
        if trade_id not in self.trades:
            raise ValueError(f"Trade {trade_id} not found")
        
        trade = self.trades[trade_id]
        trade.tags.extend([tag for tag in tags if tag not in trade.tags])
        
        self.save_trades()
    
    def get_trades_by_status(self, status: TradeStatus) -> List[Trade]:
        """Get all trades with a specific status"""
        return [trade for trade in self.trades.values() if trade.status == status]
    
    def get_trades_by_strategy(self, strategy: StrategyType) -> List[Trade]:
        """Get all trades of a specific strategy type"""
        return [trade for trade in self.trades.values() if trade.strategy_type == strategy]
    
    def get_trades_by_underlying(self, underlying: str) -> List[Trade]:
        """Get all trades for a specific underlying"""
        return [trade for trade in self.trades.values() if trade.underlying == underlying]
    
    def get_open_trades(self) -> List[Trade]:
        """Get all open trades"""
        return self.get_trades_by_status(TradeStatus.OPEN)
    
    def get_closed_trades(self) -> List[Trade]:
        """Get all closed trades"""
        return self.get_trades_by_status(TradeStatus.CLOSED)
    
    def calculate_strategy_performance(self) -> Dict[str, Dict]:
        """Calculate performance metrics by strategy type"""
        
        performance = {}
        
        for strategy in StrategyType:
            trades = self.get_trades_by_strategy(strategy)
            closed_trades = [t for t in trades if t.status == TradeStatus.CLOSED]
            
            if not closed_trades:
                continue
            
            total_pnl = sum(t.current_pnl for t in closed_trades)
            win_count = sum(1 for t in closed_trades if t.current_pnl > 0)
            loss_count = len(closed_trades) - win_count
            
            winning_trades = [t.current_pnl for t in closed_trades if t.current_pnl > 0]
            losing_trades = [t.current_pnl for t in closed_trades if t.current_pnl <= 0]
            
            performance[strategy.value] = {
                'total_trades': len(closed_trades),
                'total_pnl': total_pnl,
                'win_count': win_count,
                'loss_count': loss_count,
                'win_rate': win_count / len(closed_trades) if closed_trades else 0,
                'avg_win': sum(winning_trades) / len(winning_trades) if winning_trades else 0,
                'avg_loss': sum(losing_trades) / len(losing_trades) if losing_trades else 0,
                'avg_days_in_trade': sum(t.days_in_trade for t in closed_trades if t.days_in_trade) / len(closed_trades),
            }
        
        return performance
    
    def save_trades(self):
        """Save trades to JSON file"""
        
        # Convert trades to serializable format
        trade_data = {}
        
        for trade_id, trade in self.trades.items():
            trade_dict = asdict(trade)
            
            # Convert dates to strings
            if trade_dict['entry_date']:
                trade_dict['entry_date'] = trade_dict['entry_date'].isoformat()
            if trade_dict['exit_date']:
                trade_dict['exit_date'] = trade_dict['exit_date'].isoformat()
            
            # Convert enums to strings
            trade_dict['strategy_type'] = trade_dict['strategy_type'].value
            trade_dict['status'] = trade_dict['status'].value
            
            # Handle option legs
            for leg in trade_dict['option_legs']:
                if leg['expiration']:
                    leg['expiration'] = leg['expiration'].isoformat()
            
            trade_data[trade_id] = trade_dict
        
        with open(self.data_file, 'w') as f:
            json.dump(trade_data, f, indent=2)
    
    def load_trades(self):
        """Load trades from JSON file"""
        
        if not os.path.exists(self.data_file):
            return
        
        try:
            with open(self.data_file, 'r') as f:
                trade_data = json.load(f)
            
            for trade_id, trade_dict in trade_data.items():
                # Convert strings back to dates
                if trade_dict['entry_date']:
                    trade_dict['entry_date'] = date.fromisoformat(trade_dict['entry_date'])
                if trade_dict['exit_date']:
                    trade_dict['exit_date'] = date.fromisoformat(trade_dict['exit_date'])
                
                # Convert strings back to enums
                trade_dict['strategy_type'] = StrategyType(trade_dict['strategy_type'])
                trade_dict['status'] = TradeStatus(trade_dict['status'])
                
                # Handle option legs
                for leg in trade_dict['option_legs']:
                    if leg['expiration']:
                        leg['expiration'] = date.fromisoformat(leg['expiration'])
                
                # Create Trade object
                trade = Trade(**trade_dict)
                self.trades[trade_id] = trade
                
        except Exception as e:
            print(f"Error loading trades: {e}")
            # Continue with empty trades dict
    
    def export_for_sheets(self) -> Dict[str, List[List]]:
        """Export trades in format suitable for Google Sheets"""
        
        # Trades summary sheet
        trades_data = []
        trades_headers = [
            'Trade ID', 'Underlying', 'Strategy', 'Entry Date', 'Exit Date',
            'Status', 'Days in Trade', 'Net Premium', 'Current P&L',
            'Original Notes', 'Current Notes', 'Tags'
        ]
        trades_data.append(trades_headers)
        
        for trade in self.trades.values():
            row = [
                trade.trade_id,
                trade.underlying,
                trade.strategy_type.value,
                trade.entry_date.isoformat() if trade.entry_date else '',
                trade.exit_date.isoformat() if trade.exit_date else '',
                trade.status.value,
                trade.days_in_trade or 0,
                trade.net_premium,
                trade.current_pnl,
                trade.original_notes,
                trade.current_notes,
                ', '.join(trade.tags)
            ]
            trades_data.append(row)
        
        # Trade legs detail sheet
        legs_data = []
        legs_headers = [
            'Trade ID', 'Leg Type', 'Symbol', 'Option Type', 'Strike',
            'Expiration', 'Quantity', 'Entry Price', 'Exit Price', 'Transaction IDs'
        ]
        legs_data.append(legs_headers)
        
        for trade in self.trades.values():
            # Option legs
            for leg in trade.option_legs:
                row = [
                    trade.trade_id,
                    'Option',
                    leg.symbol,
                    leg.option_type,
                    leg.strike,
                    leg.expiration.isoformat() if leg.expiration else '',
                    leg.quantity,
                    leg.entry_price,
                    leg.exit_price or '',
                    ', '.join(leg.transaction_ids)
                ]
                legs_data.append(row)
            
            # Stock legs
            for leg in trade.stock_legs:
                row = [
                    trade.trade_id,
                    'Stock',
                    leg.symbol,
                    '',  # No option type
                    '',  # No strike
                    '',  # No expiration
                    leg.quantity,
                    leg.entry_price,
                    leg.exit_price or '',
                    ', '.join(leg.transaction_ids)
                ]
                legs_data.append(row)
        
        return {
            'trades': trades_data,
            'trade_legs': legs_data
        }