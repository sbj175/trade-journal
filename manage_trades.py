#!/usr/bin/env python3
"""
Trade Management CLI
Interactive interface for managing trade notes and status
"""

import sys
import os
from datetime import datetime

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.models.trade_manager import TradeManager, TradeStatus, StrategyType


def display_trade_summary(trade):
    """Display a summary of a trade"""
    print(f"\n{'='*60}")
    print(f"Trade ID: {trade.trade_id}")
    print(f"Underlying: {trade.underlying}")
    print(f"Strategy: {trade.strategy_type.value}")
    print(f"Status: {trade.status.value}")
    print(f"Entry Date: {trade.entry_date}")
    print(f"Exit Date: {trade.exit_date or 'Still Open'}")
    print(f"Days in Trade: {trade.days_in_trade}")
    print(f"Net Premium: ${trade.net_premium:,.2f}")
    print(f"Current P&L: ${trade.current_pnl:,.2f}")
    
    # Option legs
    if trade.option_legs:
        print(f"\nOption Legs:")
        for i, leg in enumerate(trade.option_legs, 1):
            direction = "Long" if leg.is_long else "Short"
            print(f"  {i}. {direction} {leg.quantity} {leg.option_type} ${leg.strike} {leg.expiration}")
    
    # Stock legs
    if trade.stock_legs:
        print(f"\nStock Legs:")
        for i, leg in enumerate(trade.stock_legs, 1):
            direction = "Long" if leg.quantity > 0 else "Short"
            print(f"  {i}. {direction} {abs(leg.quantity)} shares @ ${leg.entry_price}")
    
    print(f"\nOriginal Notes: {trade.original_notes or '(None)'}")
    print(f"Current Notes: {trade.current_notes or '(None)'}")
    if trade.tags:
        print(f"Tags: {', '.join(trade.tags)}")
    print(f"{'='*60}")


def list_trades(trade_manager, filter_type=None):
    """List trades with optional filtering"""
    
    if filter_type == "open":
        trades = trade_manager.get_open_trades()
        title = "Open Trades"
    elif filter_type == "closed":
        trades = trade_manager.get_closed_trades()
        title = "Closed Trades"
    else:
        trades = list(trade_manager.trades.values())
        title = "All Trades"
    
    print(f"\n{title} ({len(trades)} trades):")
    print("-" * 80)
    
    if not trades:
        print("No trades found.")
        return
    
    # Sort by entry date (newest first)
    trades.sort(key=lambda x: x.entry_date, reverse=True)
    
    print(f"{'ID':<20} {'Underlying':<8} {'Strategy':<15} {'Status':<8} {'Entry':<12} {'P&L':<10}")
    print("-" * 80)
    
    for trade in trades:
        print(f"{trade.trade_id:<20} {trade.underlying:<8} {trade.strategy_type.value:<15} "
              f"{trade.status.value:<8} {trade.entry_date:<12} ${trade.current_pnl:>8.2f}")


def add_trade_notes(trade_manager):
    """Add or update notes for a trade"""
    
    trade_id = input("Enter Trade ID: ").strip()
    
    if trade_id not in trade_manager.trades:
        print(f"Trade {trade_id} not found.")
        return
    
    trade = trade_manager.trades[trade_id]
    display_trade_summary(trade)
    
    print("\nWhat would you like to update?")
    print("1. Original Notes (your initial thesis)")
    print("2. Current Notes (latest analysis)")
    print("3. Both")
    
    choice = input("Enter choice (1-3): ").strip()
    
    if choice in ["1", "3"]:
        print(f"\nCurrent Original Notes: {trade.original_notes}")
        new_original = input("Enter new original notes (or press Enter to keep current): ").strip()
        if new_original:
            trade_manager.add_trade_notes(trade_id, original_notes=new_original)
            print("✓ Original notes updated")
    
    if choice in ["2", "3"]:
        print(f"\nCurrent Notes: {trade.current_notes}")
        new_current = input("Enter new current notes (or press Enter to keep current): ").strip()
        if new_current:
            trade_manager.add_trade_notes(trade_id, current_notes=new_current)
            print("✓ Current notes updated")


def update_trade_status(trade_manager):
    """Update trade status"""
    
    trade_id = input("Enter Trade ID: ").strip()
    
    if trade_id not in trade_manager.trades:
        print(f"Trade {trade_id} not found.")
        return
    
    trade = trade_manager.trades[trade_id]
    display_trade_summary(trade)
    
    print(f"\nCurrent Status: {trade.status.value}")
    print("\nAvailable statuses:")
    for i, status in enumerate(TradeStatus, 1):
        print(f"{i}. {status.value}")
    
    try:
        choice = int(input("Enter choice (1-6): ").strip())
        statuses = list(TradeStatus)
        if 1 <= choice <= len(statuses):
            new_status = statuses[choice - 1]
            trade_manager.update_trade_status(trade_id, new_status)
            print(f"✓ Status updated to {new_status.value}")
        else:
            print("Invalid choice")
    except ValueError:
        print("Invalid input")


def search_trades(trade_manager):
    """Search trades by various criteria"""
    
    print("\nSearch by:")
    print("1. Underlying symbol")
    print("2. Strategy type")
    print("3. Notes content")
    
    choice = input("Enter choice (1-3): ").strip()
    
    if choice == "1":
        symbol = input("Enter underlying symbol: ").strip().upper()
        trades = trade_manager.get_trades_by_underlying(symbol)
        print(f"\nTrades for {symbol}:")
        
    elif choice == "2":
        print("\nAvailable strategies:")
        for i, strategy in enumerate(StrategyType, 1):
            print(f"{i}. {strategy.value}")
        
        try:
            strategy_choice = int(input("Enter choice: ").strip())
            strategies = list(StrategyType)
            if 1 <= strategy_choice <= len(strategies):
                strategy = strategies[strategy_choice - 1]
                trades = trade_manager.get_trades_by_strategy(strategy)
                print(f"\nTrades using {strategy.value}:")
            else:
                print("Invalid choice")
                return
        except ValueError:
            print("Invalid input")
            return
            
    elif choice == "3":
        search_term = input("Enter search term: ").strip().lower()
        trades = []
        for trade in trade_manager.trades.values():
            if (search_term in trade.original_notes.lower() or 
                search_term in trade.current_notes.lower()):
                trades.append(trade)
        print(f"\nTrades containing '{search_term}':")
        
    else:
        print("Invalid choice")
        return
    
    if trades:
        for trade in trades:
            display_trade_summary(trade)
    else:
        print("No trades found.")


def show_performance_summary(trade_manager):
    """Show performance summary by strategy"""
    
    performance = trade_manager.calculate_strategy_performance()
    
    print("\n" + "="*80)
    print("PERFORMANCE SUMMARY BY STRATEGY")
    print("="*80)
    
    for strategy, metrics in performance.items():
        print(f"\n{strategy}:")
        print(f"  Total Trades: {metrics['total_trades']}")
        print(f"  Total P&L: ${metrics['total_pnl']:,.2f}")
        print(f"  Win Rate: {metrics['win_rate']:.1%}")
        print(f"  Average Win: ${metrics['avg_win']:,.2f}")
        print(f"  Average Loss: ${metrics['avg_loss']:,.2f}")
        print(f"  Avg Days in Trade: {metrics['avg_days_in_trade']:.1f}")


def main():
    """Main CLI interface"""
    
    trade_manager = TradeManager()
    
    print("="*60)
    print("           TRADE MANAGEMENT INTERFACE")
    print("="*60)
    
    while True:
        print(f"\nTrade Manager - {len(trade_manager.trades)} total trades")
        print("-" * 40)
        print("1. List all trades")
        print("2. List open trades")
        print("3. List closed trades")
        print("4. View specific trade")
        print("5. Add/update trade notes")
        print("6. Update trade status")
        print("7. Search trades")
        print("8. Performance summary")
        print("9. Refresh from Tastytrade")
        print("0. Exit")
        
        choice = input("\nEnter choice (0-9): ").strip()
        
        if choice == "0":
            print("Goodbye!")
            break
            
        elif choice == "1":
            list_trades(trade_manager)
            
        elif choice == "2":
            list_trades(trade_manager, "open")
            
        elif choice == "3":
            list_trades(trade_manager, "closed")
            
        elif choice == "4":
            trade_id = input("Enter Trade ID: ").strip()
            if trade_id in trade_manager.trades:
                display_trade_summary(trade_manager.trades[trade_id])
            else:
                print("Trade not found.")
                
        elif choice == "5":
            add_trade_notes(trade_manager)
            
        elif choice == "6":
            update_trade_status(trade_manager)
            
        elif choice == "7":
            search_trades(trade_manager)
            
        elif choice == "8":
            show_performance_summary(trade_manager)
            
        elif choice == "9":
            print("Refreshing from Tastytrade...")
            # This would run the sync process
            print("Run: python3 src/sync_trades.py --days 30")
            
        else:
            print("Invalid choice. Please try again.")


if __name__ == "__main__":
    main()