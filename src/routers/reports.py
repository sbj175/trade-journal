"""Report routes — dashboard, performance, monthly stats."""

from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger

from src.database.models import OrderChain
from src.dependencies import db, order_manager, get_current_user_id
from src.services.report_service import calculate_max_risk_reward

router = APIRouter()


@router.get("/api/dashboard")
async def get_dashboard_data(account_number: Optional[str] = None, user_id: str = Depends(get_current_user_id)):
    """Get dashboard summary data using the new order-based system"""
    try:
        chains = order_manager.get_order_chains(account_number=account_number)

        processed_chains = []
        for chain in chains:
            try:
                chain_orders = chain.get('orders', [])

                has_options = False
                for order in chain_orders:
                    positions = order.get('positions', [])
                    if any(pos['instrument_type'] == 'InstrumentType.EQUITY_OPTION' for pos in positions):
                        has_options = True
                        break

                if has_options:
                    processed_chains.append(chain)

            except Exception as e:
                logger.warning(f"Error processing chain {chain.get('chain_id', 'unknown')}: {e}")
                continue

        open_chains = [c for c in processed_chains if c['chain_status'] == 'OPEN']
        closed_chains = [c for c in processed_chains if c['chain_status'] == 'CLOSED']

        chains_total_pnl = sum(c['total_pnl'] for c in processed_chains)
        chains_realized_pnl = sum(c['realized_pnl'] for c in processed_chains)

        unrealized_pnl = 0
        position_data_source = "none"
        try:
            positions = db.get_open_positions()
            if positions:
                if account_number:
                    positions = [p for p in positions if p.get('account_number') == account_number]

                unrealized_pnl = sum(float(p.get('unrealized_pnl', 0)) for p in positions)
                position_data_source = "database"
                logger.info(f"Dashboard: Using database positions data, unrealized P&L: ${unrealized_pnl:.2f}")
            else:
                logger.warning("Dashboard: No position data available")
        except Exception as e:
            logger.warning(f"Dashboard: Could not get position data for unrealized P&L: {e}")

        total_pnl = chains_realized_pnl + unrealized_pnl
        realized_pnl = chains_realized_pnl

        profitable_closed = [c for c in closed_chains if c['total_pnl'] > 0]
        win_rate = len(profitable_closed) / len(closed_chains) * 100 if closed_chains else 0

        try:
            order_stats = order_manager.get_order_statistics(account_number=account_number)
        except Exception as e:
            logger.warning(f"Could not get order statistics: {e}")
            order_stats = {}

        strategy_breakdown = {}
        for chain in processed_chains:
            strategy = chain.get('strategy_type', 'Unknown')
            if strategy not in strategy_breakdown:
                strategy_breakdown[strategy] = {
                    'count': 0,
                    'total_pnl': 0,
                    'closed_count': 0,
                    'wins': 0
                }

            strategy_breakdown[strategy]['count'] += 1
            strategy_breakdown[strategy]['total_pnl'] += chain['total_pnl']

            if chain['chain_status'] == 'CLOSED':
                strategy_breakdown[strategy]['closed_count'] += 1
                if chain['total_pnl'] > 0:
                    strategy_breakdown[strategy]['wins'] += 1

        strategy_stats = []
        for strategy, stats in strategy_breakdown.items():
            strategy_stats.append({
                'strategy_type': strategy,
                'count': stats['count'],
                'total_pnl': stats['total_pnl'],
                'avg_pnl': stats['total_pnl'] / stats['count'] if stats['count'] > 0 else 0,
                'wins': stats['wins'],
                'closed_count': stats['closed_count'],
                'win_rate': stats['wins'] / stats['closed_count'] * 100 if stats['closed_count'] > 0 else 0
            })

        return {
            "summary": {
                "total_trades": len(processed_chains),
                "open_trades": len(open_chains),
                "closed_trades": len(closed_chains),
                "total_pnl": total_pnl,
                "realized_pnl": realized_pnl,
                "unrealized_pnl": unrealized_pnl,
                "chains_only_pnl": chains_total_pnl,
                "position_based_total": unrealized_pnl != 0,
                "data_source": position_data_source,
                "win_rate": win_rate
            },
            "order_summary": order_stats,
            "strategy_breakdown": strategy_stats,
            "recent_trades": []
        }
    except Exception as e:
        logger.error(f"Error fetching dashboard data: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/performance/monthly")
async def get_monthly_performance(year: int = None, user_id: str = Depends(get_current_user_id)):
    """Get monthly performance data"""
    try:
        if year is None:
            year = date.today().year

        monthly_data = db.get_monthly_performance(year)
        return {"year": year, "months": monthly_data}
    except Exception as e:
        logger.error(f"Error fetching monthly performance: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/reports/strategies")
async def get_available_strategies(user_id: str = Depends(get_current_user_id)):
    """Get list of strategies that have been used in closed trades"""
    try:
        with db.get_session() as session:
            rows = session.query(OrderChain.strategy_type).filter(
                OrderChain.chain_status == "CLOSED",
                OrderChain.strategy_type.isnot(None),
            ).distinct().order_by(OrderChain.strategy_type).all()
            strategies = [row[0] for row in rows]

        return {"strategies": strategies}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching strategies: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/reports/performance")
async def get_performance_report(
    account_number: Optional[str] = None,
    days: str = "90",
    strategies: str = "",
    user_id: str = Depends(get_current_user_id),
):
    """Get performance report data for closed trades"""
    try:
        strategy_list = [s.strip() for s in strategies.split(',') if s.strip()] if strategies else []

        with db.get_session() as session:
            q = session.query(OrderChain).filter(OrderChain.chain_status == 'CLOSED')

            if account_number:
                q = q.filter(OrderChain.account_number == account_number)

            if days != 'all':
                try:
                    days_int = int(days)
                    cutoff_date = (datetime.now() - timedelta(days=days_int)).strftime('%Y-%m-%d')
                    q = q.filter(OrderChain.closing_date >= cutoff_date)
                except ValueError:
                    pass

            chains = [row.to_dict() for row in q.all()]

            chain_risk_reward = {}
            for chain in chains:
                max_risk, max_reward = calculate_max_risk_reward(
                    session, chain['chain_id'], chain['strategy_type']
                )
                chain_risk_reward[chain['chain_id']] = (max_risk, max_reward)

        if strategy_list:
            chains = [c for c in chains if c['strategy_type'] in strategy_list]

        total_pnl = 0.0
        wins = 0
        losses = 0
        win_pnls = []
        loss_pnls = []
        max_risks = []
        max_rewards = []

        strategy_stats = {}

        for chain in chains:
            pnl = chain['total_pnl'] or 0.0
            strategy = chain['strategy_type'] or 'Unknown'
            chain_id = chain['chain_id']

            max_risk, max_reward = chain_risk_reward.get(chain_id, (None, None))

            total_pnl += pnl

            if max_risk is not None:
                max_risks.append(max_risk)
            if max_reward is not None:
                max_rewards.append(max_reward)

            if pnl >= 0:
                wins += 1
                win_pnls.append(pnl)
            else:
                losses += 1
                loss_pnls.append(pnl)

            if strategy not in strategy_stats:
                strategy_stats[strategy] = {
                    'strategy': strategy,
                    'totalPnl': 0.0,
                    'wins': 0,
                    'losses': 0,
                    'winPnls': [],
                    'lossPnls': [],
                    'maxRisks': [],
                    'maxRewards': []
                }

            strategy_stats[strategy]['totalPnl'] += pnl
            if max_risk is not None:
                strategy_stats[strategy]['maxRisks'].append(max_risk)
            if max_reward is not None:
                strategy_stats[strategy]['maxRewards'].append(max_reward)

            if pnl >= 0:
                strategy_stats[strategy]['wins'] += 1
                strategy_stats[strategy]['winPnls'].append(pnl)
            else:
                strategy_stats[strategy]['losses'] += 1
                strategy_stats[strategy]['lossPnls'].append(pnl)

        total_trades = len(chains)

        summary = {
            'totalPnl': total_pnl,
            'totalTrades': total_trades,
            'wins': wins,
            'losses': losses,
            'winRate': (wins / total_trades * 100) if total_trades > 0 else 0,
            'avgPnl': (total_pnl / total_trades) if total_trades > 0 else 0,
            'avgWin': (sum(win_pnls) / len(win_pnls)) if win_pnls else 0,
            'avgLoss': (sum(loss_pnls) / len(loss_pnls)) if loss_pnls else 0,
            'largestWin': max(win_pnls) if win_pnls else 0,
            'largestLoss': min(loss_pnls) if loss_pnls else 0,
            'avgMaxRisk': (sum(max_risks) / len(max_risks)) if max_risks else 0,
            'avgMaxReward': (sum(max_rewards) / len(max_rewards)) if max_rewards else 0
        }

        breakdown = []
        for strategy, stats in strategy_stats.items():
            total = stats['wins'] + stats['losses']
            breakdown.append({
                'strategy': strategy,
                'totalTrades': total,
                'wins': stats['wins'],
                'losses': stats['losses'],
                'winRate': (stats['wins'] / total * 100) if total > 0 else 0,
                'totalPnl': stats['totalPnl'],
                'avgPnl': (stats['totalPnl'] / total) if total > 0 else 0,
                'avgWin': (sum(stats['winPnls']) / len(stats['winPnls'])) if stats['winPnls'] else 0,
                'avgLoss': (sum(stats['lossPnls']) / len(stats['lossPnls'])) if stats['lossPnls'] else 0,
                'largestWin': max(stats['winPnls']) if stats['winPnls'] else 0,
                'largestLoss': min(stats['lossPnls']) if stats['lossPnls'] else 0,
                'avgMaxRisk': (sum(stats['maxRisks']) / len(stats['maxRisks'])) if stats['maxRisks'] else 0,
                'avgMaxReward': (sum(stats['maxRewards']) / len(stats['maxRewards'])) if stats['maxRewards'] else 0
            })

        return {
            'summary': summary,
            'breakdown': breakdown
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating performance report: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
