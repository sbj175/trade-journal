"""
Position Enricher - Links live positions to order chains for intelligent grouping
Enriches positions with chain metadata (chain_id, strategy_type) by matching them to OPEN order chains
"""

from typing import List, Tuple, Dict, Any, Optional
from loguru import logger


class PositionEnricher:
    """Enriches live positions with chain metadata for intelligent grouping"""

    def enrich_positions(
        self,
        live_positions: List[Dict[str, Any]],
        open_chains: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """
        Enrich positions with chain metadata.

        Args:
            live_positions: Live positions from Tastytrade API
            open_chains: Open order chains from database

        Returns:
            Tuple of:
            - Enriched positions list (with chain_id and strategy_type if matched)
            - List of unmatched position keys for sync triggering
        """
        unmatched = []

        # Convert chains to a lookup structure for faster matching
        chain_lookup = self._build_chain_lookup(open_chains)

        # Enrich each position
        for position in live_positions:
            chain = self._find_matching_chain(position, chain_lookup)

            if chain:
                position['chain_id'] = chain['chain_id']
                position['strategy_type'] = chain['strategy_type']
                logger.debug(
                    f"Enriched position: {position['symbol']} -> chain {chain['chain_id']} "
                    f"({chain['strategy_type']})"
                )
            else:
                # Position has no matching chain - flag for sync
                unmatched.append(self._position_key(position))
                logger.debug(
                    f"Unmatched position: {position['symbol']} in account "
                    f"{position['account_number']}"
                )

        return live_positions, unmatched

    def _build_chain_lookup(
        self,
        open_chains: List[Dict[str, Any]]
    ) -> Dict[Tuple[str, str], Dict[str, Any]]:
        """
        Build lookup structure: (underlying, account_number) -> chain_info

        This is simplified since each account/underlying/strategy combo should have
        only one OPEN chain (or be a multi-leg strategy where all legs are in same chain)

        For more complex scenarios, we may need to group by strategy_type as well.
        """
        lookup = {}

        for chain in open_chains:
            underlying = chain.get('underlying', '')
            account = chain.get('account_number', '')
            strategy = chain.get('strategy_type', 'Unknown')

            key = (underlying, account)

            # Log if we're overwriting (shouldn't happen in normal case)
            if key in lookup:
                existing_strategy = lookup[key].get('strategy_type', '')
                logger.warning(
                    f"Multiple OPEN chains for {underlying} in account {account}: "
                    f"{existing_strategy} and {strategy}. Using most recent."
                )

            lookup[key] = {
                'chain_id': chain.get('chain_id', ''),
                'strategy_type': strategy,
                'chain': chain
            }

        return lookup

    def _find_matching_chain(
        self,
        position: Dict[str, Any],
        chain_lookup: Dict[Tuple[str, str], Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Find matching chain for a position.

        Matching criteria:
        1. Underlying symbol matches
        2. Account number matches
        3. Instrument type is consistent (both options or both stock)
        """
        underlying = position.get('underlying', '')
        account = position.get('account_number', '')
        instrument_type = position.get('instrument_type', '')

        key = (underlying, account)

        if key not in chain_lookup:
            return None

        chain_info = chain_lookup[key]

        # Additional validation: check instrument type consistency
        if not self._instrument_types_compatible(position, chain_info['chain']):
            logger.warning(
                f"Position {position['symbol']} has incompatible instrument type "
                f"with chain {chain_info['chain_id']}"
            )
            return None

        return chain_info

    def _instrument_types_compatible(
        self,
        position: Dict[str, Any],
        chain: Dict[str, Any]
    ) -> bool:
        """
        Check if position's instrument type is compatible with chain's positions.

        For now, accept any match by underlying/account (chains can have mixed positions).
        This may need refinement if we encounter edge cases.
        """
        # Basic check: position should match the chain's instruments
        position_is_option = 'OPTION' in position.get('instrument_type', '')

        # Check chain's positions for instrument type
        orders = chain.get('orders', [])
        for order in orders:
            positions = order.get('positions', [])
            for pos in positions:
                chain_pos_is_option = 'OPTION' in pos.get('instrument_type', '')
                if position_is_option == chain_pos_is_option:
                    return True

        # If chain has no positions yet (shouldn't happen), accept it
        if not orders:
            return True

        return False

    @staticmethod
    def _position_key(position: Dict[str, Any]) -> str:
        """Generate a unique key for an unmatched position"""
        symbol = position.get('symbol', 'UNKNOWN')
        account = position.get('account_number', 'UNKNOWN')
        strike = position.get('strike', '')
        expiration = position.get('expiration', '')

        if strike and expiration:
            return f"{symbol} {strike}C/P {expiration} (account {account})"
        else:
            return f"{symbol} (account {account})"
