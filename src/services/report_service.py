"""Report service — risk/reward calculations for performance reports."""

from loguru import logger

from src.database.models import PositionGroupLot, PositionLot as PositionLotModel


def calculate_max_risk_reward(session, group_id: str, strategy_type: str) -> tuple:
    """
    Calculate max risk and max reward for a group based on its opening lots.
    Returns (max_risk, max_reward) as positive numbers, or (None, None) if cannot calculate.
    """
    lot_rows = (
        session.query(PositionLotModel)
        .join(PositionGroupLot,
              PositionLotModel.transaction_id == PositionGroupLot.transaction_id)
        .filter(PositionGroupLot.group_id == group_id)
        .all()
    )

    if not lot_rows:
        return None, None

    # Separate by instrument type
    options = []
    stocks = []
    for lot in lot_rows:
        inst = (lot.instrument_type or '').upper()
        if inst in ('EQUITY', 'STOCK'):
            stocks.append(lot)
        elif lot.option_type:
            options.append(lot)

    if not options and not stocks:
        return None, None

    strategy = (strategy_type or '').lower()

    try:
        if 'bull put spread' in strategy or 'bear call spread' in strategy:
            if len(options) >= 2:
                strikes = sorted(set(lot.strike for lot in options if lot.strike))
                if len(strikes) >= 2:
                    width = (strikes[-1] - strikes[0]) * 100
                    qty = abs(options[0].quantity)
                    premium = sum(
                        abs(lot.entry_price or 0) * abs(lot.quantity) * 100 *
                        (-1 if lot.quantity < 0 else 1)
                        for lot in options
                    )
                    # For credit spreads: premium received is positive (short legs)
                    net_premium = abs(premium)
                    max_risk = abs(width * qty - net_premium)
                    max_reward = net_premium
                    return max_risk, max_reward

        elif 'bull call spread' in strategy or 'bear put spread' in strategy:
            if len(options) >= 2:
                strikes = sorted(set(lot.strike for lot in options if lot.strike))
                if len(strikes) >= 2:
                    width = (strikes[-1] - strikes[0]) * 100
                    qty = abs(options[0].quantity)
                    premium = sum(
                        abs(lot.entry_price or 0) * abs(lot.quantity) * 100 *
                        (1 if lot.quantity < 0 else -1)
                        for lot in options
                    )
                    net_premium = abs(premium)
                    max_risk = net_premium
                    max_reward = abs(width * qty - net_premium)
                    return max_risk, max_reward

        elif 'iron condor' in strategy:
            if len(options) >= 4:
                calls = [l for l in options if (l.option_type or '').upper().startswith('C')]
                puts = [l for l in options if (l.option_type or '').upper().startswith('P')]
                if len(calls) >= 2 and len(puts) >= 2:
                    call_strikes = sorted(set(l.strike for l in calls if l.strike))
                    put_strikes = sorted(set(l.strike for l in puts if l.strike))
                    if len(call_strikes) >= 2 and len(put_strikes) >= 2:
                        call_width = (call_strikes[-1] - call_strikes[0]) * 100
                        put_width = (put_strikes[-1] - put_strikes[0]) * 100
                        wider_width = max(call_width, put_width)
                        premium = sum(
                            abs(lot.entry_price or 0) * abs(lot.quantity) * 100 *
                            (-1 if lot.quantity < 0 else 1)
                            for lot in options
                        )
                        qty = abs(options[0].quantity)
                        net_premium = abs(premium)
                        max_risk = abs(wider_width * qty - net_premium)
                        max_reward = net_premium
                        return max_risk, max_reward

        elif 'covered call' in strategy:
            if stocks and options:
                stock_cost = sum(abs(l.entry_price or 0) * abs(l.quantity) for l in stocks)
                call_premium = sum(
                    abs(l.entry_price or 0) * abs(l.quantity) * 100
                    for l in options if (l.option_type or '').upper().startswith('C')
                )
                call_strike = next(
                    (l.strike for l in options if (l.option_type or '').upper().startswith('C')),
                    0,
                )
                stock_qty = abs(stocks[0].quantity) if stocks else 0
                max_risk = stock_cost - call_premium
                max_reward = (call_strike * stock_qty) - stock_cost + call_premium
                return abs(max_risk), abs(max_reward) if max_reward > 0 else 0

        elif 'cash secured put' in strategy or 'short put' in strategy or 'naked put' in strategy:
            if options:
                put = next(
                    (l for l in options if (l.option_type or '').upper().startswith('P')),
                    options[0],
                )
                premium = abs(put.entry_price or 0) * abs(put.quantity) * 100
                max_risk = (put.strike * 100 * abs(put.quantity)) - premium
                max_reward = premium
                return abs(max_risk), abs(max_reward)

        elif 'long call' in strategy or 'long put' in strategy:
            if options:
                premium = sum(abs(l.entry_price or 0) * abs(l.quantity) * 100 for l in options)
                return premium, None

        elif 'short call' in strategy or 'naked call' in strategy:
            if options:
                premium = sum(abs(l.entry_price or 0) * abs(l.quantity) * 100 for l in options)
                return None, premium

    except Exception as e:
        logger.warning(f"Error calculating risk/reward for group {group_id}: {e}")
        return None, None

    return None, None
