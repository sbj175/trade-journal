"""Report routes — dashboard, performance, monthly stats."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from sqlalchemy import func

from src.database.models import (
    PnlEvent, PositionGroup, PositionGroupLot,
    PositionLot as PositionLotModel, LotClosing as LotClosingModel,
)
from src.database.db_manager import DatabaseManager
from src.dependencies import get_db, get_current_user_id
from src.services.report_service import calculate_max_risk_reward

router = APIRouter()


@router.get("/api/dashboard")
async def get_dashboard_data(
    account_number: Optional[str] = None,
    db: DatabaseManager = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Get dashboard summary data using pnl_events."""
    try:
        with db.get_session() as session:
            # Count groups by status
            q = session.query(PositionGroup)
            if account_number:
                q = q.filter(PositionGroup.account_number == account_number)
            groups = [
                {'group_id': g.group_id, 'status': g.status,
                 'strategy_label': g.strategy_label}
                for g in q.all()
            ]

            # Realized P&L from pnl_events
            pnl_q = session.query(
                PnlEvent.group_id,
                func.sum(PnlEvent.realized_pnl).label('pnl'),
            )
            if account_number:
                pnl_q = pnl_q.filter(PnlEvent.account_number == account_number)
            pnl_q = pnl_q.group_by(PnlEvent.group_id)
            pnl_map = {gid: float(pnl) for gid, pnl in pnl_q.all()}

        open_groups = [g for g in groups if g['status'] == 'OPEN']
        closed_groups = [g for g in groups if g['status'] == 'CLOSED']

        realized_pnl = sum(pnl_map.get(g['group_id'], 0) for g in groups)

        unrealized_pnl = 0
        position_data_source = "none"
        try:
            positions = db.get_open_positions()
            if positions:
                if account_number:
                    positions = [p for p in positions if p.get('account_number') == account_number]
                unrealized_pnl = sum(float(p.get('unrealized_pnl', 0)) for p in positions)
                position_data_source = "database"
        except Exception as e:
            logger.warning(f"Dashboard: Could not get position data for unrealized P&L: {e}")

        total_pnl = realized_pnl + unrealized_pnl

        profitable_closed = [
            g for g in closed_groups if pnl_map.get(g['group_id'], 0) > 0
        ]
        win_rate = len(profitable_closed) / len(closed_groups) * 100 if closed_groups else 0

        strategy_breakdown = {}
        for g in groups:
            strategy = g['strategy_label'] or 'Unknown'
            if strategy not in strategy_breakdown:
                strategy_breakdown[strategy] = {
                    'count': 0, 'total_pnl': 0, 'closed_count': 0, 'wins': 0,
                }
            pnl = pnl_map.get(g['group_id'], 0)
            strategy_breakdown[strategy]['count'] += 1
            strategy_breakdown[strategy]['total_pnl'] += pnl
            if g['status'] == 'CLOSED':
                strategy_breakdown[strategy]['closed_count'] += 1
                if pnl > 0:
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
                'win_rate': stats['wins'] / stats['closed_count'] * 100 if stats['closed_count'] > 0 else 0,
            })

        return {
            "summary": {
                "total_trades": len(groups),
                "open_trades": len(open_groups),
                "closed_trades": len(closed_groups),
                "total_pnl": total_pnl,
                "realized_pnl": realized_pnl,
                "unrealized_pnl": unrealized_pnl,
                "data_source": position_data_source,
                "win_rate": win_rate,
            },
            "strategy_breakdown": strategy_stats,
            "recent_trades": [],
        }
    except Exception as e:
        logger.error(f"Error fetching dashboard data: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/performance/monthly")
async def get_monthly_performance(
    account_number: Optional[str] = None,
    year: int = None,
    db: DatabaseManager = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Get monthly performance data from pnl_events."""
    try:
        if year is None:
            year = date.today().year

        year_prefix = str(year)

        with db.get_session() as session:
            q = session.query(
                func.substr(PnlEvent.closing_date, 1, 7).label('month'),
                func.sum(PnlEvent.realized_pnl).label('pnl'),
                func.count(PnlEvent.id).label('trade_count'),
            ).filter(
                PnlEvent.closing_date.like(f"{year_prefix}%"),
            )
            if account_number:
                q = q.filter(PnlEvent.account_number == account_number)
            q = q.group_by(func.substr(PnlEvent.closing_date, 1, 7))
            rows = q.all()

        # Build full 12-month structure
        months = []
        for m in range(1, 13):
            month_key = f"{year}-{m:02d}"
            months.append({
                'month': month_key,
                'pnl': 0.0,
                'trade_count': 0,
            })

        for row in rows:
            month_key = row.month
            for entry in months:
                if entry['month'] == month_key:
                    entry['pnl'] = float(row.pnl)
                    entry['trade_count'] = int(row.trade_count)
                    break

        return {"year": year, "months": months}
    except Exception as e:
        logger.error(f"Error fetching monthly performance: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/reports/strategies")
async def get_available_strategies(
    db: DatabaseManager = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Get list of strategies that have been used in closed groups"""
    try:
        with db.get_session() as session:
            rows = session.query(PositionGroup.strategy_label).filter(
                PositionGroup.status == "CLOSED",
                PositionGroup.strategy_label.isnot(None),
            ).distinct().order_by(PositionGroup.strategy_label).all()
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
    exit_from: Optional[str] = None,
    exit_to: Optional[str] = None,
    strategies: str = "",
    db: DatabaseManager = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Get performance report data from pnl_events.

    Date params are ISO date strings (YYYY-MM-DD).
    exit_from/exit_to filter on pnl_events.closing_date (the event date).
    """
    try:
        strategy_list = [s.strip() for s in strategies.split(',') if s.strip()] if strategies else []

        with db.get_session() as session:
            # Query pnl_events aggregated by group_id
            q = session.query(
                PnlEvent.group_id,
                func.sum(PnlEvent.realized_pnl).label('pnl'),
            )

            if account_number:
                q = q.filter(PnlEvent.account_number == account_number)
            if exit_from:
                q = q.filter(PnlEvent.closing_date >= exit_from)
            if exit_to:
                q = q.filter(PnlEvent.closing_date <= exit_to + "T23:59:59")

            q = q.group_by(PnlEvent.group_id)
            pnl_rows = q.all()

            # Build group_id -> pnl map
            pnl_map = {}
            group_ids_with_events = set()
            for group_id, pnl in pnl_rows:
                if group_id is not None:
                    pnl_map[group_id] = float(pnl)
                    group_ids_with_events.add(group_id)

            # Fetch strategy labels for these groups
            group_labels = {}
            if group_ids_with_events:
                label_rows = session.query(
                    PositionGroup.group_id,
                    PositionGroup.strategy_label,
                ).filter(
                    PositionGroup.group_id.in_(list(group_ids_with_events)),
                ).all()
                group_labels = {gid: label for gid, label in label_rows}

            # Calculate risk/reward per group
            group_risk_reward = {}
            for gid in group_ids_with_events:
                label = group_labels.get(gid)
                max_risk, max_reward = calculate_max_risk_reward(session, gid, label)
                group_risk_reward[gid] = (max_risk, max_reward)

        # Apply strategy filter
        groups = []
        for gid in group_ids_with_events:
            label = group_labels.get(gid) or 'Unknown'
            if strategy_list and label not in strategy_list:
                continue
            groups.append({'group_id': gid, 'strategy_label': label})

        total_pnl = 0.0
        wins = 0
        losses = 0
        win_pnls = []
        loss_pnls = []
        max_risks = []
        max_rewards = []
        strategy_stats = {}

        for g in groups:
            pnl = pnl_map.get(g['group_id'], 0)
            strategy = g['strategy_label'] or 'Unknown'
            max_risk, max_reward = group_risk_reward.get(g['group_id'], (None, None))

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
                    'wins': 0, 'losses': 0,
                    'winPnls': [], 'lossPnls': [],
                    'maxRisks': [], 'maxRewards': [],
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

        total_trades = len(groups)

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
            'avgMaxReward': (sum(max_rewards) / len(max_rewards)) if max_rewards else 0,
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
                'avgMaxReward': (sum(stats['maxRewards']) / len(stats['maxRewards'])) if stats['maxRewards'] else 0,
            })

        return {
            'summary': summary,
            'breakdown': breakdown,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating performance report: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
