"""Roll timeline computation — walk-and-balance for same-expiration rolls.

Groups a position group's lots + closings into three staged sections:
  1. Opening event (initial opens before any close)
  2. Roll events (signature-matched close/open pairs)
  3. Closing event (trailing closes after the final pairing)

See OPT-263 for design rationale. Does not use order_id for roll detection
(per feedback_no_order_id_for_rolls.md): paired buckets balance by
(option_type, sign, quantity) multiset, not by broker-supplied order linkage.
"""

from collections import Counter, defaultdict
from typing import List


def compute_roll_timeline(lots: List[dict]) -> dict:
    """Walk a position group's option lots in execution order; emit staged timeline.

    Args:
        lots: Serialized lot dicts from the ledger endpoint. Required fields:
            option_type, strike, expiration, original_quantity, quantity,
            remaining_quantity, status, entry_date, entry_price, opening_fees,
            leg_index, lot_id, closings (each with closing_date, closing_price,
            quantity_closed, closing_type, fees, closing_id).

    Returns:
        Dict with opening / roll_events / closing / roll_count / current_strike_label.
    """
    option_lots = [l for l in lots if l.get('option_type')]

    if not option_lots:
        return {
            'opening': None,
            'roll_events': [],
            'closing': None,
            'roll_count': 0,
            'current_strike_label': None,
        }

    transactions = _build_transaction_stream(option_lots)
    opening_txs, roll_events, closing_txs = _walk_and_balance(transactions)

    return {
        'opening': _make_open_close_event('OPENING', opening_txs),
        'roll_events': roll_events,
        'closing': _make_open_close_event('CLOSING', closing_txs) if closing_txs else None,
        'roll_count': len(roll_events),
        'current_strike_label': _current_strike_label(option_lots),
    }


# ---------- transaction stream ----------

def _build_transaction_stream(option_lots):
    txs = []
    for lot in option_lots:
        # `quantity` is the signed field (+ long, - short).
        # `original_quantity` is the absolute magnitude at lot creation.
        signed_qty = lot.get('quantity') or 0
        sign = 1 if signed_qty > 0 else -1
        mag = lot.get('original_quantity') or abs(signed_qty) or 0
        opt_type = (lot.get('option_type') or '').upper()
        opt_initial = opt_type[0] if opt_type else ''

        txs.append({
            'kind': 'OPEN',
            'timestamp': lot.get('entry_date') or '',
            'leg_index': lot.get('leg_index') or 0,
            'lot_id': lot.get('lot_id') or 0,
            'sign': sign,
            'option_type': opt_initial,
            'strike': lot.get('strike'),
            'expiration': lot.get('expiration'),
            'quantity_abs': abs(mag),
            'price': lot.get('entry_price') or 0,
            'fees': lot.get('opening_fees') or 0,
        })

        for c in lot.get('closings') or []:
            txs.append({
                'kind': 'CLOSE',
                'timestamp': c.get('closing_date') or '',
                'leg_index': lot.get('leg_index') or 0,
                'lot_id': lot.get('lot_id') or 0,
                'closing_id': c.get('closing_id'),
                'sign': sign,
                'option_type': opt_initial,
                'strike': lot.get('strike'),
                'expiration': lot.get('expiration'),
                'quantity_abs': c.get('quantity_closed') or 0,
                'price': c.get('closing_price') or 0,
                'fees': c.get('fees') or 0,
                'closing_type': c.get('closing_type') or 'MANUAL',
            })

    # Deterministic ordering: timestamp ASC, CLOSE before OPEN on ties
    # (so a roll executed as one order forms a pair), then leg_index, lot_id.
    txs.sort(key=lambda t: (
        str(t['timestamp']),
        0 if t['kind'] == 'CLOSE' else 1,
        t['leg_index'],
        t['lot_id'],
    ))
    return txs


# ---------- walk-and-balance ----------

def _walk_and_balance(transactions):
    opening_txs = []
    pending_closes = []
    pending_opens = []
    roll_events = []
    closing_txs = []

    state = 'OPENING'

    for tx in transactions:
        if state == 'OPENING':
            if tx['kind'] == 'OPEN':
                opening_txs.append(tx)
                continue
            # First close flips us into rolling mode
            pending_closes.append(tx)
            state = 'ROLLING'
            continue

        # ROLLING
        if tx['kind'] == 'CLOSE':
            pending_closes.append(tx)
        else:
            pending_opens.append(tx)

        if pending_closes and pending_opens:
            if _position_signature(pending_closes) == _position_signature(pending_opens):
                roll_events.append(_make_roll_event(pending_closes, pending_opens))
                pending_closes = []
                pending_opens = []

    # Trailing state:
    #   orphan closes → closing event
    #   orphan opens → extend opening event (partial roll never completed its open side)
    if pending_closes:
        closing_txs = pending_closes
    if pending_opens:
        opening_txs.extend(pending_opens)

    return opening_txs, roll_events, closing_txs


def _position_signature(txs):
    return tuple(sorted(
        Counter((t['option_type'], t['sign'], t['quantity_abs']) for t in txs).items()
    ))


# ---------- event builders ----------

def _make_open_close_event(kind, txs):
    if not txs:
        return None

    mixed_type = _is_mixed_type(txs)
    date = _normalize_date(max((str(t['timestamp']) for t in txs), default=''))
    net = sum(_cash_flow(t, is_open=(t['kind'] == 'OPEN')) for t in txs)

    # Sort by strike ascending for a natural price-ladder read
    # (e.g., an Iron Condor shows P low → P high → C low → C high).
    legs = [_leg_detail(t) for t in sorted(
        txs,
        key=lambda x: (x['strike'] or 0, x['option_type'] or '', str(x['timestamp'] or '')),
    )]

    return {
        'kind': kind,
        'date': date,
        'net_credit_debit': round(net, 2),
        'mixed_type': mixed_type,
        'legs': legs,
    }


def _make_roll_event(closes, opens):
    mixed_type = _is_mixed_type(closes + opens)
    date = _normalize_date(max(
        (str(t['timestamp']) for t in closes + opens),
        default='',
    ))
    net = sum(_cash_flow(t, is_open=False) for t in closes) \
        + sum(_cash_flow(t, is_open=True) for t in opens)

    return {
        'kind': 'ROLL',
        'date': date,
        'net_credit_debit': round(net, 2),
        'closed_strikes_label': _side_label(closes, mixed_type),
        'opened_strikes_label': _side_label(opens, mixed_type),
        'mixed_type': mixed_type,
        'pairs': _pair_legs(closes, opens),
    }


def _leg_detail(t):
    leg = {
        'kind': t['kind'],
        'option_type': t['option_type'],
        'sign': t['sign'],
        'quantity': t['quantity_abs'],
        'expiration': str(t['expiration']) if t.get('expiration') else None,
        'strike': t.get('strike'),
        'price': round(t.get('price') or 0, 4),
        'fees': round(t.get('fees') or 0, 4),
        'lot_id': t.get('lot_id'),
    }
    if t['kind'] == 'CLOSE':
        leg['closing_type'] = t.get('closing_type', 'MANUAL')
    return leg


def _pair_legs(closes, opens):
    """Pair each close with an open of matching (option_type, sign, qty), sorted by strike ascending.

    Pairing-by-sorted-strike matches the mental model "lower put rolled to lower put,
    upper put to upper put" and is deterministic.
    """
    close_buckets = defaultdict(list)
    open_buckets = defaultdict(list)
    for t in closes:
        close_buckets[(t['option_type'], t['sign'], t['quantity_abs'])].append(t)
    for t in opens:
        open_buckets[(t['option_type'], t['sign'], t['quantity_abs'])].append(t)

    for bucket in close_buckets.values():
        bucket.sort(key=lambda t: (t['strike'] or 0))
    for bucket in open_buckets.values():
        bucket.sort(key=lambda t: (t['strike'] or 0))

    pairs = []
    for key, closes_in in close_buckets.items():
        opens_in = open_buckets.get(key, [])
        for c, o in zip(closes_in, opens_in):
            pairs.append({
                'option_type': o['option_type'],
                'sign': o['sign'],
                'quantity': o['quantity_abs'],
                'expiration': str(o['expiration']) if o.get('expiration') else None,
                'closed': {
                    'lot_id': c.get('lot_id'),
                    'strike': c.get('strike'),
                    'price': round(c.get('price') or 0, 4),
                    'fees': round(c.get('fees') or 0, 4),
                    'closing_type': c.get('closing_type', 'MANUAL'),
                },
                'opened': {
                    'lot_id': o.get('lot_id'),
                    'strike': o.get('strike'),
                    'price': round(o.get('price') or 0, 4),
                    'fees': round(o.get('fees') or 0, 4),
                },
            })
    return pairs


# ---------- helpers ----------

def _is_mixed_type(txs):
    has_puts = any((t.get('option_type') or '').startswith('P') for t in txs)
    has_calls = any((t.get('option_type') or '').startswith('C') for t in txs)
    return has_puts and has_calls


def _side_label(txs, mixed_type):
    sorted_txs = sorted(txs, key=lambda t: (t['strike'] or 0))
    parts = []
    for t in sorted_txs:
        strike = _fmt_strike(t.get('strike'))
        parts.append(f"{strike}{t['option_type']}" if mixed_type else strike)
    return '/'.join(parts)


def _cash_flow(tx, is_open):
    """Signed cash flow for one transaction. Positive = credit, negative = debit.

    Opening: cash = -sign * price * qty * 100 - fees
      STO (sign=-1): +price*qty*100 - fees  (credit received)
      BTO (sign=+1): -price*qty*100 - fees  (debit paid)
    Closing: cash = sign * price * qty * 100 - fees
      BTC of short (sign=-1): -price*qty*100 - fees  (debit to buy back)
      STC of long  (sign=+1): +price*qty*100 - fees  (credit from sale)
    """
    price = tx.get('price') or 0
    qty = tx.get('quantity_abs') or 0
    fees = tx.get('fees') or 0
    sign = tx.get('sign') or 0
    multiplier = 100
    if is_open:
        return -sign * price * qty * multiplier - fees
    return sign * price * qty * multiplier - fees


def _normalize_date(ts):
    if not ts:
        return None
    s = str(ts)
    for sep in ('T', ' '):
        if sep in s:
            s = s.split(sep)[0]
            break
    return s or None


def _fmt_strike(s):
    if s is None:
        return ''
    try:
        f = float(s)
        if f == int(f):
            return str(int(f))
        return str(s)
    except (ValueError, TypeError):
        return str(s)


def _current_strike_label(option_lots):
    open_lots = [
        l for l in option_lots
        if (l.get('remaining_quantity') or 0) != 0 and l.get('status') != 'CLOSED'
    ]
    if open_lots:
        return _strikes_from_lots(open_lots)

    # Fully closed — use the cohort closed at the latest close date
    max_close = None
    for lot in option_lots:
        for c in lot.get('closings') or []:
            cd = c.get('closing_date')
            if cd and (max_close is None or str(cd) > str(max_close)):
                max_close = cd

    if not max_close:
        return _strikes_from_lots(option_lots)

    final_cohort = []
    for lot in option_lots:
        for c in lot.get('closings') or []:
            if str(c.get('closing_date')) == str(max_close):
                final_cohort.append(lot)
                break
    return _strikes_from_lots(final_cohort or option_lots)


def _strikes_from_lots(lots):
    strikes = sorted({l.get('strike') for l in lots if l.get('strike') is not None})
    if not strikes:
        return None
    return '/'.join(_fmt_strike(s) for s in strikes)
