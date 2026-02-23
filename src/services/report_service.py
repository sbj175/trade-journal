"""Report service — risk/reward calculations for performance reports."""

from loguru import logger

from src.database.models import OrderChainMember as OCM, Order as OrderModel, OrderPosition as OP


def calculate_max_risk_reward(session, chain_id: str, strategy_type: str) -> tuple:
    """
    Calculate max risk and max reward for a chain based on its opening positions.
    Returns (max_risk, max_reward) as positive numbers, or (None, None) if cannot calculate.
    """
    # Get the opening order for this chain (first order)
    row = (
        session.query(OCM.order_id)
        .join(OrderModel, OrderModel.order_id == OCM.order_id)
        .filter(OCM.chain_id == chain_id)
        .order_by(OrderModel.order_date.asc())
        .first()
    )
    if not row:
        return None, None

    opening_order_id = row[0]

    # Get positions for the opening order
    pos_rows = (
        session.query(
            OP.symbol, OP.instrument_type, OP.option_type, OP.strike,
            OP.quantity, OP.opening_price, OP.opening_action,
        )
        .filter(OP.order_id == opening_order_id)
        .all()
    )

    if not pos_rows:
        return None, None

    # Convert to dicts for compatibility with calculation logic
    positions = []
    for r in pos_rows:
        positions.append({
            'symbol': r[0], 'instrument_type': r[1], 'option_type': r[2],
            'strike': r[3], 'quantity': r[4], 'opening_price': r[5],
            'opening_action': r[6],
        })

    # Separate by instrument type
    options = [p for p in positions if 'OPTION' in (p['instrument_type'] or '').upper()]
    stocks = [p for p in positions if 'EQUITY' in (p['instrument_type'] or '').upper() and 'OPTION' not in (p['instrument_type'] or '').upper()]

    if not options and not stocks:
        return None, None

    # Calculate based on strategy type
    strategy = (strategy_type or '').lower()

    try:
        if 'bull put spread' in strategy or 'bear call spread' in strategy:
            # Credit spread: max risk = width - premium, max reward = premium
            if len(options) >= 2:
                strikes = sorted([p['strike'] for p in options])
                width = (strikes[-1] - strikes[0]) * 100
                premium = sum(
                    abs(p['opening_price'] or 0) * abs(p['quantity']) * 100 *
                    (1 if 'SELL' in (p['opening_action'] or '').upper() else -1)
                    for p in options
                )
                max_risk = abs(width * abs(options[0]['quantity']) - premium)
                max_reward = abs(premium)
                return max_risk, max_reward

        elif 'bull call spread' in strategy or 'bear put spread' in strategy:
            # Debit spread: max risk = premium paid, max reward = width - premium
            if len(options) >= 2:
                strikes = sorted([p['strike'] for p in options])
                width = (strikes[-1] - strikes[0]) * 100
                premium = sum(
                    abs(p['opening_price'] or 0) * abs(p['quantity']) * 100 *
                    (-1 if 'BUY' in (p['opening_action'] or '').upper() else 1)
                    for p in options
                )
                max_risk = abs(premium)
                max_reward = abs(width * abs(options[0]['quantity']) + premium)
                return max_risk, max_reward

        elif 'iron condor' in strategy:
            if len(options) >= 4:
                calls = [p for p in options if p['option_type'] == 'Call']
                puts = [p for p in options if p['option_type'] == 'Put']
                if len(calls) >= 2 and len(puts) >= 2:
                    call_strikes = sorted([p['strike'] for p in calls])
                    put_strikes = sorted([p['strike'] for p in puts])
                    call_width = (call_strikes[-1] - call_strikes[0]) * 100
                    put_width = (put_strikes[-1] - put_strikes[0]) * 100
                    wider_width = max(call_width, put_width)
                    premium = sum(
                        abs(p['opening_price'] or 0) * abs(p['quantity']) * 100 *
                        (1 if 'SELL' in (p['opening_action'] or '').upper() else -1)
                        for p in options
                    )
                    qty = abs(options[0]['quantity'])
                    max_risk = abs(wider_width * qty - premium)
                    max_reward = abs(premium)
                    return max_risk, max_reward

        elif 'covered call' in strategy:
            if stocks and options:
                stock_cost = sum(abs(p['opening_price'] or 0) * abs(p['quantity']) for p in stocks)
                call_premium = sum(
                    abs(p['opening_price'] or 0) * abs(p['quantity']) * 100
                    for p in options if p['option_type'] == 'Call'
                )
                call_strike = options[0]['strike'] if options else 0
                stock_qty = abs(stocks[0]['quantity']) if stocks else 0
                max_risk = stock_cost - call_premium
                max_reward = (call_strike * stock_qty) - stock_cost + call_premium
                return abs(max_risk), abs(max_reward) if max_reward > 0 else 0

        elif 'cash secured put' in strategy or 'short put' in strategy or 'naked put' in strategy:
            if options:
                put = next((p for p in options if p['option_type'] == 'Put'), options[0])
                premium = abs(put['opening_price'] or 0) * abs(put['quantity']) * 100
                max_risk = (put['strike'] * 100 * abs(put['quantity'])) - premium
                max_reward = premium
                return abs(max_risk), abs(max_reward)

        elif 'long call' in strategy or 'long put' in strategy:
            if options:
                premium = sum(abs(p['opening_price'] or 0) * abs(p['quantity']) * 100 for p in options)
                max_risk = premium
                max_reward = None
                return max_risk, max_reward

        elif 'short call' in strategy or 'naked call' in strategy:
            if options:
                premium = sum(abs(p['opening_price'] or 0) * abs(p['quantity']) * 100 for p in options)
                max_risk = None
                max_reward = premium
                return max_risk, max_reward

    except Exception as e:
        logger.warning(f"Error calculating risk/reward for chain {chain_id}: {e}")
        return None, None

    return None, None
