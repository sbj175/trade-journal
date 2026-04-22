"""Unit tests for src/services/roll_timeline.py — walk-and-balance roll detection."""

from src.services.roll_timeline import compute_roll_timeline


def _lot(lot_id, opt_type, strike, qty, entry_date, entry_price,
         closings=None, leg_index=0, expiration='2025-07-17',
         opening_fees=0.16, remaining=None, status=None):
    closings = closings or []
    if remaining is None:
        # Infer from closings: sum(quantity_closed) reduces |remaining|
        closed_abs = sum(c.get('quantity_closed', 0) for c in closings)
        orig_abs = abs(qty)
        rem_abs = max(orig_abs - closed_abs, 0)
        remaining = (rem_abs if qty > 0 else -rem_abs)
    status = status or ('OPEN' if remaining != 0 else 'CLOSED')
    return {
        'lot_id': lot_id,
        'option_type': opt_type,
        'strike': strike,
        'expiration': expiration,
        'original_quantity': qty,
        'quantity': qty,
        'remaining_quantity': remaining,
        'status': status,
        'entry_date': entry_date,
        'entry_price': entry_price,
        'opening_fees': opening_fees,
        'leg_index': leg_index,
        'closings': closings,
    }


def _close(closing_id, date, price, qty, closing_type='MANUAL', fees=0.16):
    return {
        'closing_id': closing_id,
        'closing_date': date,
        'closing_price': price,
        'quantity_closed': qty,
        'closing_type': closing_type,
        'fees': fees,
        'realized_pnl': 0,
    }


class TestEmptyOrEquityOnly:
    def test_empty_lots(self):
        tl = compute_roll_timeline([])
        assert tl['opening'] is None
        assert tl['roll_events'] == []
        assert tl['closing'] is None
        assert tl['roll_count'] == 0
        assert tl['current_strike_label'] is None

    def test_equity_only_lots_ignored(self):
        equity_lot = {
            'lot_id': 1,
            'option_type': None,
            'instrument_type': 'EQUITY',
            'strike': None,
            'expiration': None,
            'original_quantity': 100,
            'quantity': 100,
            'remaining_quantity': 100,
            'status': 'OPEN',
            'entry_date': '2025-05-22',
            'entry_price': 580.0,
            'opening_fees': 0,
            'leg_index': 0,
            'closings': [],
        }
        tl = compute_roll_timeline([equity_lot])
        assert tl['roll_count'] == 0
        assert tl['opening'] is None


class TestOpeningOnly:
    def test_iron_condor_no_rolls_open(self):
        lots = [
            _lot(1, 'P', 530, -1, '2025-05-22', 0.42),
            _lot(2, 'P', 545, -1, '2025-05-22', 0.78),
            _lot(3, 'C', 615, -1, '2025-05-22', 0.32),
            _lot(4, 'C', 630, -1, '2025-05-22', 0.18),
        ]
        tl = compute_roll_timeline(lots)
        assert tl['roll_count'] == 0
        assert tl['closing'] is None
        assert tl['opening']['kind'] == 'OPENING'
        assert tl['opening']['date'] == '2025-05-22'
        assert len(tl['opening']['legs']) == 4
        assert tl['current_strike_label'] == '530/545/615/630'


class TestSingleRoll:
    def test_puts_rolled_up(self):
        # Initial: short 530P + 545P
        # Roll:    close 530P/545P + open 585P/600P
        lots = [
            _lot(1, 'P', 530, -1, '2025-05-22', 0.42,
                 closings=[_close(101, '2025-06-27', 0.15, 1)]),
            _lot(2, 'P', 545, -1, '2025-05-22', 0.78,
                 closings=[_close(102, '2025-06-27', 0.25, 1)]),
            _lot(3, 'P', 585, -1, '2025-06-27', 0.55),
            _lot(4, 'P', 600, -1, '2025-06-27', 0.95),
        ]
        tl = compute_roll_timeline(lots)
        assert tl['roll_count'] == 1
        roll = tl['roll_events'][0]
        assert roll['kind'] == 'ROLL'
        assert roll['date'] == '2025-06-27'
        assert roll['closed_strikes_label'] == '530/545'
        assert roll['opened_strikes_label'] == '585/600'
        assert roll['mixed_type'] is False
        assert len(roll['pairs']) == 2
        # Sorted-ascending pairing: 530→585, 545→600
        assert roll['pairs'][0]['closed']['strike'] == 530
        assert roll['pairs'][0]['opened']['strike'] == 585
        assert roll['pairs'][1]['closed']['strike'] == 545
        assert roll['pairs'][1]['opened']['strike'] == 600
        assert tl['current_strike_label'] == '585/600'

    def test_net_credit_debit_is_positive_for_credit_roll(self):
        # Close short puts cheap + open new short puts expensive → net credit
        lots = [
            _lot(1, 'P', 530, -1, '2025-05-22', 0.42,
                 closings=[_close(101, '2025-06-27', 0.10, 1, fees=0)],
                 opening_fees=0),
            _lot(2, 'P', 585, -1, '2025-06-27', 1.00, opening_fees=0),
        ]
        tl = compute_roll_timeline(lots)
        roll = tl['roll_events'][0]
        # close BTC: -0.10 * 100 = -$10 (debit)
        # open STO: +1.00 * 100 = +$100 (credit)
        # net = +$90
        assert roll['net_credit_debit'] == 90.0


class TestMixedTypeRoll:
    def test_full_ic_roll_uses_cp_suffix(self):
        # Roll all 4 legs: close 585P/600P/615C/630C, open 590P/605P/610C/625C
        lots = [
            _lot(1, 'P', 585, -1, '2025-05-22', 0.42,
                 closings=[_close(101, '2025-08-12', 0.20, 1)]),
            _lot(2, 'P', 600, -1, '2025-05-22', 0.78,
                 closings=[_close(102, '2025-08-12', 0.30, 1)]),
            _lot(3, 'C', 615, -1, '2025-05-22', 0.32,
                 closings=[_close(103, '2025-08-12', 0.15, 1)]),
            _lot(4, 'C', 630, -1, '2025-05-22', 0.18,
                 closings=[_close(104, '2025-08-12', 0.05, 1)]),
            _lot(5, 'P', 590, -1, '2025-08-12', 0.50),
            _lot(6, 'P', 605, -1, '2025-08-12', 0.85),
            _lot(7, 'C', 610, -1, '2025-08-12', 0.45),
            _lot(8, 'C', 625, -1, '2025-08-12', 0.22),
        ]
        tl = compute_roll_timeline(lots)
        assert tl['roll_count'] == 1
        roll = tl['roll_events'][0]
        assert roll['mixed_type'] is True
        assert roll['closed_strikes_label'] == '585P/600P/615C/630C'
        assert roll['opened_strikes_label'] == '590P/605P/610C/625C'


class TestFullyClosedGroup:
    def test_opening_roll_closing_all_present(self):
        lots = [
            # Original puts, closed in roll
            _lot(1, 'P', 530, -1, '2025-05-22', 0.42,
                 closings=[_close(101, '2025-06-27', 0.15, 1)]),
            _lot(2, 'P', 545, -1, '2025-05-22', 0.78,
                 closings=[_close(102, '2025-06-27', 0.25, 1)]),
            # Original calls, closed at final close
            _lot(3, 'C', 615, -1, '2025-05-22', 0.32,
                 closings=[_close(103, '2025-07-15', 0.05, 1, 'EXPIRATION')]),
            _lot(4, 'C', 630, -1, '2025-05-22', 0.18,
                 closings=[_close(104, '2025-07-15', 0.00, 1, 'EXPIRATION')]),
            # New puts from roll, closed at final close
            _lot(5, 'P', 585, -1, '2025-06-27', 0.55,
                 closings=[_close(105, '2025-07-15', 0.05, 1)]),
            _lot(6, 'P', 600, -1, '2025-06-27', 0.95,
                 closings=[_close(106, '2025-07-15', 0.10, 1)]),
        ]
        tl = compute_roll_timeline(lots)
        assert tl['roll_count'] == 1
        # Opening: 4 legs at May 22
        assert tl['opening']['date'] == '2025-05-22'
        assert len(tl['opening']['legs']) == 4
        # Roll on 2025-06-27
        assert tl['roll_events'][0]['date'] == '2025-06-27'
        # Closing: remaining 4 legs closed Jul 15
        assert tl['closing'] is not None
        assert tl['closing']['kind'] == 'CLOSING'
        assert tl['closing']['date'] == '2025-07-15'
        assert len(tl['closing']['legs']) == 4
        # current_strike_label = final open cohort = the 4 legs closed Jul 15
        assert tl['current_strike_label'] == '585/600/615/630'


class TestOrphans:
    def test_orphan_closes_become_closing(self):
        # 2 legs open, 1 close that never gets paired
        lots = [
            _lot(1, 'P', 530, -1, '2025-05-22', 0.42,
                 closings=[_close(101, '2025-06-01', 0.10, 1)]),
            _lot(2, 'P', 545, -1, '2025-05-22', 0.78),
        ]
        tl = compute_roll_timeline(lots)
        assert tl['roll_count'] == 0
        assert tl['closing'] is not None
        assert len(tl['closing']['legs']) == 1
        assert tl['closing']['legs'][0]['strike'] == 530

    def test_orphan_opens_extend_opening(self):
        # Close on existing 530P then open a call at different time — signatures don't match
        lots = [
            _lot(1, 'P', 530, -1, '2025-05-22', 0.42,
                 closings=[_close(101, '2025-06-01', 0.10, 1)]),
            _lot(2, 'C', 600, 1, '2025-06-02', 0.30),
        ]
        tl = compute_roll_timeline(lots)
        # No roll (signatures differ: short put vs long call)
        assert tl['roll_count'] == 0
        # Orphan close → closing; orphan open → extends opening
        assert tl['closing'] is not None
        assert tl['opening'] is not None
        # opening has original 530P open + 600C (from orphan-opens branch)
        open_strikes = {l['strike'] for l in tl['opening']['legs']}
        assert 600 in open_strikes


class TestDeterminism:
    def test_identical_timestamps_stable(self):
        # Two legs open at exact same timestamp — order by leg_index, lot_id
        lots = [
            _lot(1, 'P', 545, -1, '2025-05-22', 0.78, leg_index=1),
            _lot(2, 'P', 530, -1, '2025-05-22', 0.42, leg_index=0),
        ]
        tl1 = compute_roll_timeline(lots)
        tl2 = compute_roll_timeline(list(reversed(lots)))
        # Legs in opening are sorted by option_type/strike in output,
        # so both inputs produce identical label
        assert tl1['current_strike_label'] == tl2['current_strike_label']
        assert tl1['opening']['net_credit_debit'] == tl2['opening']['net_credit_debit']

    def test_roll_with_simultaneous_close_open(self):
        # Close and open at same timestamp — closes should sort before opens
        lots = [
            _lot(1, 'P', 530, -1, '2025-05-22', 0.42,
                 closings=[_close(101, '2025-06-27', 0.15, 1)]),
            _lot(2, 'P', 585, -1, '2025-06-27', 0.55),
        ]
        tl = compute_roll_timeline(lots)
        assert tl['roll_count'] == 1


class TestLeggedInRoll:
    def test_two_step_roll_over_counts_per_spec(self):
        # Close 530P, open 585P, then close 545P, open 600P — counts as 2 rolls.
        # Per OPT-263: "accept over-count; visual staging makes the reality clear."
        lots = [
            _lot(1, 'P', 530, -1, '2025-05-22', 0.42,
                 closings=[_close(101, '2025-06-27T10:00:00', 0.15, 1)]),
            _lot(2, 'P', 585, -1, '2025-06-27T10:02:00', 0.55),
            _lot(3, 'P', 545, -1, '2025-05-22', 0.78,
                 closings=[_close(102, '2025-06-27T10:04:00', 0.25, 1)]),
            _lot(4, 'P', 600, -1, '2025-06-27T10:06:00', 0.95),
        ]
        tl = compute_roll_timeline(lots)
        assert tl['roll_count'] == 2


class TestSignDerivation:
    def test_sign_comes_from_quantity_not_original_quantity(self):
        """DB stores `quantity` signed (+ long, - short) but `original_quantity`
        as absolute magnitude. Walk-and-balance must use `quantity` for sign."""
        # Short put: quantity=-1 but original_quantity=+1 (as real DB stores it)
        short_put = {
            'lot_id': 1, 'option_type': 'P', 'strike': 545,
            'expiration': '2025-07-17',
            'quantity': -1, 'original_quantity': 1,
            'remaining_quantity': -1, 'status': 'OPEN',
            'entry_date': '2025-05-22', 'entry_price': 0.78,
            'opening_fees': 0.16, 'leg_index': 0, 'closings': [],
        }
        # Long put: quantity=+1, original_quantity=+1
        long_put = {
            'lot_id': 2, 'option_type': 'P', 'strike': 530,
            'expiration': '2025-07-17',
            'quantity': 1, 'original_quantity': 1,
            'remaining_quantity': 1, 'status': 'OPEN',
            'entry_date': '2025-05-22', 'entry_price': 0.42,
            'opening_fees': 0.16, 'leg_index': 1, 'closings': [],
        }
        tl = compute_roll_timeline([short_put, long_put])
        legs = tl['opening']['legs']
        by_strike = {l['strike']: l for l in legs}
        assert by_strike[545]['sign'] == -1  # short
        assert by_strike[530]['sign'] == 1   # long


class TestCurrentStrikeLabel:
    def test_open_group_uses_open_lots(self):
        lots = [
            _lot(1, 'P', 530, -1, '2025-05-22', 0.42,
                 closings=[_close(101, '2025-06-27', 0.15, 1)],
                 remaining=0, status='CLOSED'),
            _lot(2, 'P', 585, -1, '2025-06-27', 0.55),
        ]
        tl = compute_roll_timeline(lots)
        assert tl['current_strike_label'] == '585'

    def test_closed_group_uses_final_cohort(self):
        lots = [
            _lot(1, 'P', 530, -1, '2025-05-22', 0.42,
                 closings=[_close(101, '2025-06-27', 0.15, 1)],
                 remaining=0, status='CLOSED'),
            _lot(2, 'P', 585, -1, '2025-06-27', 0.55,
                 closings=[_close(102, '2025-07-15', 0.05, 1)],
                 remaining=0, status='CLOSED'),
        ]
        tl = compute_roll_timeline(lots)
        # Final cohort = lot 2 (closed at latest date 2025-07-15)
        assert tl['current_strike_label'] == '585'
