"""
Position Enricher - Links live positions to order chains for intelligent grouping
Enriches positions with chain metadata (chain_id, strategy_type) by matching them to OPEN order chains
"""

from typing import List, Tuple, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class PositionEnricher:
    """Enriches live positions with chain metadata for intelligent grouping"""

    def __init__(self, db_connection=None):
        """Initialize enricher with optional database connection for precise matching"""
        self.db = db_connection

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

        # Build lookup of positions by symbol for database-based matching
        position_symbol_lookup = self._build_position_symbol_lookup(open_chains)

        logger.info(
            f"Enriching {len(live_positions)} positions against {len(open_chains)} open chains. "
            f"Position symbol lookup has {len(position_symbol_lookup)} symbols mapped to chains"
        )

        # Enrich each position
        enriched_count = 0
        for position in live_positions:
            chain = self._find_matching_chain_by_symbol(position, position_symbol_lookup)

            if chain:
                position['chain_id'] = chain['chain_id']
                position['strategy_type'] = chain['strategy_type']
                enriched_count += 1
                logger.debug(
                    f"Enriched position: {position['symbol']} -> chain {chain['chain_id']} "
                    f"({chain['strategy_type']})"
                )
            else:
                # Position has no matching chain - flag for sync
                unmatched.append(self._position_key(position))
                underlying = position.get('underlying', 'UNKNOWN')
                account = position.get('account_number', 'UNKNOWN')
                logger.debug(
                    f"Unmatched position: {position['symbol']} (underlying='{underlying}', "
                    f"account='{account}')"
                )

        logger.info(
            f"Enrichment complete: {enriched_count} positions enriched, "
            f"{len(unmatched)} positions unmatched"
        )

        return live_positions, unmatched

    def _build_position_symbol_lookup(
        self,
        open_chains: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Build lookup structure: position_symbol -> chain_info

        Maps each position symbol in a chain to that chain's metadata.
        This requires querying order_positions table to get the actual positions in each chain.
        Falls back to underlying-based matching if database connection not available.
        """
        lookup = {}

        # If we don't have database connection, fall back to underlying matching
        if not self.db:
            logger.warning("No database connection for position symbol lookup. Using underlying-based matching only.")
            return self._build_underlying_lookup(open_chains)

        # Query database to find which symbols belong to each chain
        try:
            # Get all position symbols in each open chain
            cursor = self.db.cursor()
            cursor.execute("""
                SELECT DISTINCT op.symbol, ocm.chain_id
                FROM order_positions op
                JOIN order_chain_members ocm ON op.order_id = ocm.order_id
                WHERE ocm.chain_id IN ({})
            """.format(','.join('?' * len(open_chains))),
                [chain.get('chain_id') for chain in open_chains]
            )

            # Build lookup of symbol -> chain_info
            chain_map = {chain.get('chain_id'): chain for chain in open_chains}

            for row in cursor.fetchall():
                symbol = row[0]
                chain_id = row[1]
                chain_info = chain_map.get(chain_id)

                if chain_info:
                    lookup[symbol] = {
                        'chain_id': chain_id,
                        'strategy_type': chain_info.get('strategy_type', 'Unknown')
                    }

            logger.debug(f"Built symbol lookup with {len(lookup)} position symbols mapped to chains")

        except Exception as e:
            logger.warning(f"Error building position symbol lookup: {e}. Falling back to underlying matching.")
            lookup = self._build_underlying_lookup(open_chains)

        return lookup

    def _build_underlying_lookup(
        self,
        open_chains: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Fallback: Build lookup by underlying symbol only.
        Note: This will match all positions of the same underlying to one chain!
        """
        lookup = {}

        for chain in open_chains:
            underlying = chain.get('underlying', '').strip()
            if underlying:
                # Store chain by underlying - note: if multiple chains have same underlying,
                # only the last one is kept (this is the old problematic behavior)
                lookup[underlying] = {
                    'chain_id': chain.get('chain_id', ''),
                    'strategy_type': chain.get('strategy_type', 'Unknown')
                }

        return lookup

    def _find_matching_chain_by_symbol(
        self,
        position: Dict[str, Any],
        symbol_lookup: Dict[str, Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Find matching chain for a position by exact symbol match.
        Falls back to underlying match if symbol not found.
        """
        symbol = position.get('symbol', '').strip()
        underlying = position.get('underlying', '').strip()

        # Try exact symbol match first (most precise)
        if symbol in symbol_lookup:
            return symbol_lookup[symbol]

        # Fall back to underlying match
        if underlying in symbol_lookup:
            return symbol_lookup[underlying]

        return None

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
