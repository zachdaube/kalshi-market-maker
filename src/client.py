"""
Kalshi API client wrapper for market data and order management.
"""

from typing import Optional, Dict, List, Any
from kalshi_python_sync import Configuration, KalshiClient as KalshiAPIClient
import json

class KalshiClient:
    """
    Wrapper around the Kalshi API for market making operations.

    This handles authentication via RSA private keys and provides
    convenient methods for fetching market data and managing orders.
    """

    def __init__(self, key_id: str, private_key: str, host: str = "https://demo-api.kalshi.co/trade-api/v2"):
        """
        Initialize the Kalshi client.

        Args:
            key_id: Your Kalshi API key ID
            private_key: Your RSA private key as a string (PEM format)
            host: API host URL (demo or production)
        """
        self.host = host
        self.key_id = key_id

        # Configure the API client using kalshi_python_sync
        config = Configuration(host=host)
        config.api_key_id = key_id
        config.private_key_pem = private_key

        self.client = KalshiAPIClient(config)

    # ==================== Market Data Methods ====================

    def get_markets(self,
                    limit: int = 100,
                    status: Optional[str] = None,
                    series_ticker: Optional[str] = None,
                    event_ticker: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Fetch available markets with optional filters.

        Args:
            limit: Maximum number of markets to return
            status: Filter by status (e.g., "open", "closed")
            series_ticker: Filter by series ticker
            event_ticker: Filter by event ticker

        Returns:
            List of market dictionaries
        """
        try:
            params = {"limit": limit}
            if status:
                params["status"] = status
            if series_ticker:
                params["series_ticker"] = series_ticker
            if event_ticker:
                params["event_ticker"] = event_ticker

            response = self.client.get_markets(**params)

            # Convert Pydantic models to dictionaries
            if hasattr(response, 'markets'):
                markets = []
                for market in response.markets:
                    if hasattr(market, 'model_dump'):
                        markets.append(market.model_dump())
                    elif hasattr(market, 'dict'):
                        markets.append(market.dict())
                    else:
                        markets.append(market)
                return markets
            return []
        except Exception as e:
            print(f"Error fetching markets: {e}")
            return []

    def get_market(self, ticker: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information for a specific market.

        Args:
            ticker: Market ticker symbol

        Returns:
            Market details dictionary or None if not found
        """
        try:
            response = self.client.get_market(ticker=ticker)
            if hasattr(response, 'market'):
                market = response.market
                if hasattr(market, 'model_dump'):
                    return market.model_dump()
                elif hasattr(market, 'dict'):
                    return market.dict()
                return market
            return None
        except Exception as e:
            print(f"Error fetching market {ticker}: {e}")
            return None

    def get_orderbook(self, ticker: str, depth: int = 10) -> Optional[Dict[str, Any]]:
        """
        Get the current order book for a market.

        Kalshi's order book format returns YES and NO bids only.
        Remember: A NO bid at price X is equivalent to a YES ask at (100 - X).

        Args:
            ticker: Market ticker symbol
            depth: Number of price levels to return

        Returns:
            Order book dictionary with format:
            {
                "yes": [[price, quantity], ...],  # YES bids, ascending by price
                "no": [[price, quantity], ...]    # NO bids, ascending by price
            }
            Or None if the orderbook is empty or an error occurs.
        """
        try:
            # The kalshi_python_sync SDK has a validation bug where it expects
            # strings for quantities in yes_dollars/no_dollars but the API returns ints.
            # We bypass the SDK and make a raw HTTP request to get the orderbook.


            # Use the client's rest client and auth
            url = f"{self.host}/markets/{ticker}/orderbook?depth={depth}"

            # Make authenticated request using the client's call_api method
            response = self.client.call_api(
                method="GET",
                url=url,
            )

            # Parse the JSON response (must use .read() not .data)
            if response and response.status == 200:
                raw_data = response.read()
                data = json.loads(raw_data) if isinstance(raw_data, bytes) else raw_data

                if 'orderbook' in data:
                    orderbook = data['orderbook']
                    # Return the yes/no arrays (prices in cents)
                    # Format: [[price_cents, quantity], ...]
                    return {
                        "yes": orderbook.get('yes', []),
                        "no": orderbook.get('no', [])
                    }

            return {"yes": [], "no": []}

        except Exception as e:
            # Fallback: try to get best bid/ask from market endpoint
            # This gives us top-of-book even if full orderbook fails
            try:
                market = self.get_market(ticker)
                if market:
                    yes_bid = market.get('yes_bid', 0)
                    no_bid = market.get('no_bid', 0)

                    # Construct a minimal orderbook from top-of-book data
                    orderbook = {"yes": [], "no": []}
                    if yes_bid > 0:
                        orderbook["yes"].append([yes_bid, 1])  # We don't know quantity, use 1
                    if no_bid > 0:
                        orderbook["no"].append([no_bid, 1])

                    return orderbook
            except:
                pass

            print(f"Error fetching orderbook for {ticker}: {e}")
            return {"yes": [], "no": []}

    def get_trades(self, ticker: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get recent trades for a market.

        Useful for analyzing order flow and detecting toxic flow.

        Args:
            ticker: Market ticker symbol
            limit: Maximum number of trades to return

        Returns:
            List of trade dictionaries
        """
        try:
            response = self.client.get_trades(ticker=ticker, limit=limit)
            if hasattr(response, 'trades'):
                trades = []
                for trade in response.trades:
                    if hasattr(trade, 'model_dump'):
                        trades.append(trade.model_dump())
                    elif hasattr(trade, 'dict'):
                        trades.append(trade.dict())
                    else:
                        trades.append(trade)
                return trades
            return []
        except Exception as e:
            print(f"Error fetching trades for {ticker}: {e}")
            return []

    # ==================== Order Management Methods ====================

    def place_order(self,
                    ticker: str,
                    side: str,  # "yes" or "no"
                    action: str,  # "buy" or "sell"
                    quantity: int,
                    price: int,  # Price in cents (1-99)
                    order_type: str = "limit",
                    client_order_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Place a new order.

        Args:
            ticker: Market ticker symbol
            side: "yes" or "no"
            action: "buy" or "sell"
            quantity: Number of contracts
            price: Price in cents (1-99)
            order_type: "limit" or "market"
            client_order_id: Optional client order ID for idempotency

        Returns:
            Order confirmation dictionary or None if failed
        """
        try:
            params = {
                "ticker": ticker,
                "client_order_id": client_order_id or f"{ticker}_{side}_{action}_{price}",
                "side": side,
                "action": action,
                "count": quantity,
                "type": order_type,
            }

            if order_type == "limit":
                params["yes_price"] = price if side == "yes" else None
                params["no_price"] = price if side == "no" else None

            response = self.client.create_order(**params)
            if hasattr(response, 'order'):
                order = response.order
                if hasattr(order, 'model_dump'):
                    return order.model_dump()
                elif hasattr(order, 'dict'):
                    return order.dict()
                return order
            return None
        except Exception as e:
            print(f"Error placing order: {e}")
            return None

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel a specific order.

        Args:
            order_id: The order ID to cancel

        Returns:
            True if successful, False otherwise
        """
        try:
            self.client.cancel_order(order_id=order_id)
            return True
        except Exception as e:
            print(f"Error canceling order {order_id}: {e}")
            return False

    def cancel_all_orders(self, ticker: Optional[str] = None) -> bool:
        """
        Cancel all orders, optionally filtered by ticker.

        Args:
            ticker: Optional market ticker to filter cancellations

        Returns:
            True if successful, False otherwise
        """
        try:
            # Get all open orders and cancel them
            orders = self.get_open_orders(ticker=ticker)
            for order in orders:
                order_id = order.get('order_id') if isinstance(order, dict) else order.order_id
                self.cancel_order(order_id)
            return True
        except Exception as e:
            print(f"Error canceling orders: {e}")
            return False

    def get_open_orders(self, ticker: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get all open orders.

        Args:
            ticker: Optional market ticker to filter orders

        Returns:
            List of open order dictionaries
        """
        try:
            params = {}
            if ticker:
                params["ticker"] = ticker

            response = self.client.get_orders(**params)
            if hasattr(response, 'orders'):
                orders = []
                for order in response.orders:
                    if hasattr(order, 'model_dump'):
                        orders.append(order.model_dump())
                    elif hasattr(order, 'dict'):
                        orders.append(order.dict())
                    else:
                        orders.append(order)
                return orders
            return []
        except Exception as e:
            print(f"Error fetching open orders: {e}")
            return []

    def get_positions(self) -> List[Dict[str, Any]]:
        """
        Get current positions across all markets.

        Returns:
            List of position dictionaries
        """
        try:
            response = self.client.get_portfolio()

            # The portfolio response contains market positions
            if hasattr(response, 'market_positions'):
                positions = []
                for pos in response.market_positions:
                    if hasattr(pos, 'model_dump'):
                        positions.append(pos.model_dump())
                    elif hasattr(pos, 'dict'):
                        positions.append(pos.dict())
                    else:
                        positions.append(pos)
                return positions
            return []
        except Exception as e:
            print(f"Error fetching positions: {e}")
            return []

    def get_balance(self) -> Optional[Dict[str, Any]]:
        """
        Get account balance information.

        Returns:
            Balance dictionary with available balance, etc.
        """
        try:
            response = self.client.get_balance()
            return {
                "balance": response.balance if hasattr(response, 'balance') else 0,
                "portfolio_value": response.portfolio_value if hasattr(response, 'portfolio_value') else 0,
            }
        except Exception as e:
            print(f"Error fetching balance: {e}")
            return None
