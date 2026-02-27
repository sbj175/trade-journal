"""Quote and WebSocket routes."""

import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from loguru import logger

from src.database.db_manager import DatabaseManager
from src.utils.auth_manager import ConnectionManager
from src.dependencies import get_db, get_connection_manager, get_current_user_id, AUTH_ENABLED

router = APIRouter()


@router.get("/api/quotes")
async def get_market_quotes(symbols: str, refresh: bool = False, request: Request = None, db: DatabaseManager = Depends(get_db), connection_manager: ConnectionManager = Depends(get_connection_manager), user_id: str = Depends(get_current_user_id)):
    """Get current market quotes for symbols (cached or fresh)"""
    try:
        symbol_list = [s.strip().upper() for s in symbols.split(',') if s.strip()]
        logger.info(f"GET /api/quotes requested for symbols: {symbol_list}")

        if not symbol_list:
            raise HTTPException(status_code=400, detail="No symbols provided")

        # If not forcing refresh, try cached quotes first (no auth needed)
        if not refresh:
            logger.info(f"Attempting to get cached quotes for: {symbol_list}")
            cached_quotes = db.get_cached_quotes(symbol_list)
            logger.info(f"Cache lookup returned {len(cached_quotes) if cached_quotes else 0} quotes")
            if cached_quotes:
                logger.info(f"Returning {len(cached_quotes)} cached quotes for: {list(cached_quotes.keys())}")
                for symbol, quote_data in cached_quotes.items():
                    if 'mark' in quote_data and quote_data['mark'] is not None:
                        quote_data['price'] = quote_data['mark']
                    if 'change_percent' in quote_data:
                        quote_data['changePercent'] = quote_data['change_percent']
                    if 'iv_percentile' in quote_data:
                        quote_data['ivPercentile'] = quote_data['iv_percentile']
                logger.info(f"Returning {len(cached_quotes)} quotes with camelCase conversion")
                return cached_quotes
            logger.info(f"Cache miss for symbols: {symbol_list}, attempting fresh quotes")

        # Resolve client manually (not via Depends) to allow cache fallback
        if AUTH_ENABLED:
            client = await connection_manager.get_user_client(user_id)
        else:
            client = connection_manager.get_client()
        if not client:
            cached_quotes = db.get_cached_quotes(symbol_list)
            if cached_quotes:
                logger.info(f"Not connected, returning fallback cached quotes: {list(cached_quotes.keys())}")
                for symbol, quote_data in cached_quotes.items():
                    if 'mark' in quote_data and quote_data['mark'] is not None:
                        quote_data['price'] = quote_data['mark']
                    if 'change_percent' in quote_data:
                        quote_data['changePercent'] = quote_data['change_percent']
                    if 'iv_percentile' in quote_data:
                        quote_data['ivPercentile'] = quote_data['iv_percentile']
                return cached_quotes
            raise HTTPException(status_code=503, detail="Not connected to Tastytrade")

        if refresh:
            client.clear_quote_cache()
            logger.info("Cache cleared due to refresh parameter")

        quotes = await client.get_quotes(symbol_list)

        logger.info(f"API endpoint returning quotes for {len(quotes)} symbols")

        if len(quotes) < len(symbol_list):
            missing = [s for s in symbol_list if s not in quotes]
            logger.warning(f"Could not retrieve quotes for: {missing}")

        if not quotes:
            logger.warning("No quotes available - streaming data unavailable")

        return quotes

    except Exception as e:
        logger.error(f"Error fetching quotes from Tastytrade: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch quotes: {str(e)}")


@router.websocket("/ws/quotes")
async def websocket_quotes(websocket: WebSocket, token: str = Query(default=None), db: DatabaseManager = Depends(get_db), connection_manager: ConnectionManager = Depends(get_connection_manager)):
    """WebSocket endpoint for streaming live quotes"""
    # Validate JWT for WebSocket if auth is enabled
    payload = None
    if AUTH_ENABLED:
        if not token:
            await websocket.close(code=4001, reason="Authentication required")
            return
        try:
            from src.auth.jwt_validator import validate_token as _validate_token
            from src.database.tenant import set_current_user_id
            payload = _validate_token(token)
            set_current_user_id(payload["sub"])
        except Exception:
            await websocket.close(code=4001, reason="Invalid token")
            return

    await websocket.accept()
    logger.info("WebSocket connection accepted")

    subscribed_symbols = []

    try:
        await websocket.send_json({"type": "connected", "message": "WebSocket connected"})

        # Resolve client: per-user when auth enabled, global otherwise
        if AUTH_ENABLED and payload:
            ws_user_id = payload["sub"]
            client = await connection_manager.get_user_client(ws_user_id)
        else:
            client = connection_manager.get_client()
        if not client:
            logger.error("WebSocket connection rejected: Not connected to Tastytrade")
            await websocket.send_json({"error": "Not connected to Tastytrade - check settings"})
            await websocket.close()
            return

        logger.info("WebSocket client connected using shared Tastytrade session")

        async def receive_messages():
            nonlocal subscribed_symbols
            try:
                while True:
                    data = await websocket.receive_json()

                    if "subscribe" in data:
                        symbols = data["subscribe"]
                        if isinstance(symbols, list):
                            subscribed_symbols = symbols
                            logger.info(f"WebSocket subscribing to quotes for: {symbols}")

                            if subscribed_symbols:
                                client.clear_quote_cache()
                                quotes = await client.get_quotes(subscribed_symbols)
                                await websocket.send_json({
                                    "type": "quotes",
                                    "data": quotes
                                })

                    elif "unsubscribe" in data:
                        subscribed_symbols = []
                        logger.info("WebSocket unsubscribed from all quotes")

                    elif "ping" in data:
                        await websocket.send_json({"pong": True})

            except WebSocketDisconnect:
                logger.info("WebSocket client disconnected")
                raise

        async def send_updates():
            try:
                while True:
                    await asyncio.sleep(5)

                    if websocket.client_state.value != 1:  # 1 = OPEN
                        logger.info("WebSocket closed, stopping quote updates")
                        break

                    if subscribed_symbols:
                        quotes = await client.get_quotes(subscribed_symbols)

                        for symbol, quote_data in quotes.items():
                            if quote_data:
                                db.cache_quote(symbol, quote_data)

                        try:
                            await websocket.send_json({
                                "type": "quotes",
                                "data": quotes,
                                "timestamp": datetime.now().isoformat()
                            })
                            logger.debug(f"Sent quote update for {len(quotes)} symbols, cached to database")
                        except Exception as send_error:
                            logger.info(f"WebSocket send failed (connection likely closed): {send_error}")
                            break

            except asyncio.CancelledError:
                logger.info("Quote update task cancelled")
                raise
            except Exception as e:
                logger.error(f"Error in send_updates: {str(e)}")
                raise

        try:
            await asyncio.gather(
                receive_messages(),
                send_updates(),
                return_exceptions=True
            )
        except Exception as e:
            logger.info(f"WebSocket tasks completed with: {e}")

    except (WebSocketDisconnect, asyncio.CancelledError):
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
        try:
            await websocket.send_json({"error": str(e)})
        except:
            pass
    finally:
        logger.info("WebSocket connection closed")
