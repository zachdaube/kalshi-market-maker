"""
Execution Engine for Avellaneda-Stoikov Market Making

Main loop that:
- Monitors markets and fetches orderbooks
- Generates quotes using AS model
- Manages order placement (cancel/replace)
- Tracks positions and enforces risk limits
"""

from typing import Dict, List, Optional
from dataclasses import dataclass, field
import time
import logging

from src.client import KalshiClient
from src.orderbook import OrderBook
from src.quotes import ASParams, Position, PositionTracker, TwoSidedQuote, generate_quote
from src.flow import FlowAnalyzer, FlowConfig, parse_kalshi_trades

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class MarketConfig:
    """Configuration for a single market."""
    ticker: str
    enabled: bool = True
    # AS model parameters
    gamma: float = 0.1
    sigma: float = 2.0
    k: float = 1.5
    base_size: int = 10
    max_position: int = 100
    max_loss_cents: float = 500.0


@dataclass
class ExecutionConfig:
    """Configuration for the execution engine."""
    quote_interval: float = 1.0
    position_sync_interval: float = 5.0
    total_max_position: int = 500
    cancel_threshold: int = 1  # Cents moved before requote
    markets: Dict[str, MarketConfig] = field(default_factory=dict)
    dry_run: bool = True


@dataclass
class OrderState:
    """Active orders for a market."""
    ticker: str
    yes_order_id: Optional[str] = None
    no_order_id: Optional[str] = None
    last_quote: Optional[TwoSidedQuote] = None
    last_update: float = 0.0
    flow_cooldown_until: float = 0.0


class ExecutionEngine:
    """Main execution engine using Avellaneda-Stoikov model."""

    def __init__(self, client: KalshiClient, config: ExecutionConfig):
        self.client = client
        self.config = config
        self.positions = PositionTracker()
        self.orders: Dict[str, OrderState] = {}
        self.running = False
        self.last_sync = 0.0
        self.stats = {'quotes': 0, 'cancels': 0, 'fills': 0}
        self.flow_analyzer = FlowAnalyzer(FlowConfig())
        logger.info(f"Engine initialized (dry_run={config.dry_run})")

    def start(self):
        """Run the main loop."""
        self.running = True
        logger.info("Engine started")
        try:
            while self.running:
                self._tick()
                time.sleep(self.config.quote_interval)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self):
        """Stop and cancel all orders."""
        logger.info("Stopping...")
        self.running = False
        for ticker in self.orders:
            self._cancel_orders(ticker)
        self._print_stats()

    def _tick(self):
        """Single iteration of the main loop."""
        # Sync positions periodically
        if time.time() - self.last_sync > self.config.position_sync_interval:
            self._sync_positions()
            self.last_sync = time.time()

        # Check risk limits
        if self.positions.get_total_exposure() > self.config.total_max_position:
            logger.warning("Position limit exceeded, pulling quotes")
            for ticker in self.orders:
                self._cancel_orders(ticker)
            return

        # Update each market
        for ticker, mc in self.config.markets.items():
            if mc.enabled:
                self._update_market(ticker, mc)

    def _sync_positions(self):
        """Sync positions from API."""
        try:
            api_positions = self.client.get_positions()
            for p in api_positions:
                ticker = p.get('ticker')
                qty = p.get('position', 0)
                avg_price = p.get('average_price_paid') or p.get('avg_price')
                current = self.positions.get_position(ticker)
                if current.quantity != qty:
                    delta = abs(qty - current.quantity)
                    self.stats['fills'] += delta
                    logger.info(f"Position {ticker}: {current.quantity} -> {qty}")
                self.positions.positions[ticker] = Position(
                    ticker, qty, avg_price if avg_price else current.avg_entry_price
                )
        except Exception as e:
            logger.error(f"Position sync error: {e}")

    def _update_market(self, ticker: str, mc: MarketConfig):
        """Update quotes for a single market."""
        if ticker not in self.orders:
            self.orders[ticker] = OrderState(ticker=ticker)
        state = self.orders[ticker]

        # Get orderbook
        try:
            raw_ob = self.client.get_orderbook(ticker, depth=5)
            if not raw_ob:
                return
            ob = OrderBook(ticker, raw_ob)
        except Exception as e:
            logger.error(f"Orderbook error {ticker}: {e}")
            return

        if ob.mid_price is None:
            self._cancel_orders(ticker)
            return

        # Get position and check stop loss
        pos = self.positions.get_position(ticker)
        if pos.quantity != 0 and pos.avg_entry_price:
            pnl = (ob.mid_price - pos.avg_entry_price) * pos.quantity
            if pnl < -mc.max_loss_cents:
                logger.warning(f"Stop loss {ticker}: PnL={pnl:.0f}c")
                self._cancel_orders(ticker)
                return

        # Flow detection: fetch trades and analyze
        flow_adjustment = self.flow_analyzer.recommend_adjustment(ticker)
        try:
            raw_trades = self.client.get_trades(ticker, limit=20)
            if raw_trades:
                trades = parse_kalshi_trades(raw_trades)
                self.flow_analyzer.add_trades(trades)
                flow_adjustment = self.flow_analyzer.recommend_adjustment(ticker)
        except Exception as e:
            logger.error(f"Flow analysis error {ticker}: {e}")

        # Respect flow cooldown
        if flow_adjustment.action == "pull":
            logger.warning(f"Flow PULL {ticker}: {flow_adjustment.reason}")
            self._cancel_orders(ticker)
            state.flow_cooldown_until = time.time() + flow_adjustment.cooldown_seconds
            return

        if time.time() < state.flow_cooldown_until:
            return

        # Generate quote using AS model
        params = ASParams(
            gamma=mc.gamma,
            sigma=mc.sigma,
            k=mc.k,
            max_position=mc.max_position,
            base_size=mc.base_size
        )
        quote = generate_quote(ticker, ob.mid_price, pos, params)

        if not quote:
            self._cancel_orders(ticker)
            return

        # Apply flow adjustments to quote (widen spread, reduce size)
        if flow_adjustment.spread_multiplier != 1.0 or flow_adjustment.size_multiplier != 1.0:
            logger.info(f"Flow adjust {ticker}: {flow_adjustment.action} "
                       f"(spread x{flow_adjustment.spread_multiplier}, size x{flow_adjustment.size_multiplier})")
            mid = quote.reservation_price
            half_spread = (quote.ask.price_cents - quote.bid.price_cents) / 2.0
            new_half = half_spread * flow_adjustment.spread_multiplier
            new_bid = max(1, min(98, int(round(mid - new_half))))
            new_ask = max(2, min(99, int(round(mid + new_half))))
            if new_bid >= new_ask:
                new_bid = max(1, int(mid) - 1)
                new_ask = min(99, int(mid) + 1)
            if new_bid >= new_ask:
                self._cancel_orders(ticker)
                return
            quote.bid.price_cents = new_bid
            quote.ask.price_cents = new_ask
            quote.spread_cents = new_ask - new_bid
            quote.bid.quantity = max(1, int(quote.bid.quantity * flow_adjustment.size_multiplier))
            quote.ask.quantity = max(1, int(quote.ask.quantity * flow_adjustment.size_multiplier))

        # Check if we need to update
        if state.last_quote:
            bid_diff = abs(quote.bid.price_cents - state.last_quote.bid.price_cents)
            ask_diff = abs(quote.ask.price_cents - state.last_quote.ask.price_cents)
            if bid_diff < self.config.cancel_threshold and ask_diff < self.config.cancel_threshold:
                return

        # Place orders
        self._place_orders(ticker, quote, state)

    def _place_orders(self, ticker: str, quote: TwoSidedQuote, state: OrderState):
        """Cancel old orders and place new ones."""
        self._cancel_orders(ticker)

        if self.config.dry_run:
            logger.info(
                f"[DRY] {ticker} bid={quote.bid.price_cents}c x{quote.bid.quantity} "
                f"ask={quote.ask.price_cents}c x{quote.ask.quantity} "
                f"(r={quote.reservation_price:.1f})"
            )
            state.last_quote = quote
            return

        yes_bid, no_bid = quote.to_kalshi_orders()

        try:
            # Place YES bid
            resp = self.client.place_order(
                ticker=ticker,
                side=yes_bid['side'],
                action=yes_bid['action'],
                quantity=yes_bid['quantity'],
                price=yes_bid['price'],
                order_type="limit"
            )
            if resp:
                state.yes_order_id = resp.get('order_id')

            # Place NO bid (YES ask)
            resp = self.client.place_order(
                ticker=ticker,
                side=no_bid['side'],
                action=no_bid['action'],
                quantity=no_bid['quantity'],
                price=no_bid['price'],
                order_type="limit"
            )
            if resp:
                state.no_order_id = resp.get('order_id')

            state.last_quote = quote
            state.last_update = time.time()
            self.stats['quotes'] += 1
            logger.info(f"Placed {ticker} {quote.bid.price_cents}/{quote.ask.price_cents}")

        except Exception as e:
            logger.error(f"Order error {ticker}: {e}")

    def _cancel_orders(self, ticker: str):
        """Cancel active orders for a market."""
        if ticker not in self.orders:
            return
        state = self.orders[ticker]

        if self.config.dry_run:
            state.yes_order_id = None
            state.no_order_id = None
            return

        for attr in ['yes_order_id', 'no_order_id']:
            order_id = getattr(state, attr)
            if order_id:
                try:
                    success = self.client.cancel_order(order_id)
                    if success:
                        setattr(state, attr, None)
                        self.stats['cancels'] += 1
                    else:
                        logger.warning(f"Cancel failed for {order_id}, retrying...")
                        # Retry once
                        if self.client.cancel_order(order_id):
                            setattr(state, attr, None)
                            self.stats['cancels'] += 1
                        else:
                            logger.error(f"Cancel retry failed for {order_id}, clearing anyway")
                            setattr(state, attr, None)
                except Exception as e:
                    logger.error(f"Cancel error {order_id}: {e}")
                    setattr(state, attr, None)

    def _print_stats(self):
        """Print final statistics."""
        print("\n" + "=" * 40)
        print("FINAL STATS")
        print("=" * 40)
        print(f"Quotes placed: {self.stats['quotes']}")
        print(f"Orders cancelled: {self.stats['cancels']}")
        print(f"Fills detected: {self.stats['fills']}")
        print("\nPositions:")
        positions = self.positions.get_all_positions()
        if positions:
            for t, p in positions.items():
                print(f"  {t}: {p.quantity:+d}")
        else:
            print("  All flat")
        print("=" * 40)


def create_config(tickers: List[str], dry_run: bool = True, **kwargs) -> ExecutionConfig:
    """Create execution config with defaults."""
    markets = {}
    for ticker in tickers:
        markets[ticker] = MarketConfig(
            ticker=ticker,
            gamma=kwargs.get('gamma', 0.1),
            sigma=kwargs.get('sigma', 2.0),
            k=kwargs.get('k', 1.5),
            base_size=kwargs.get('base_size', 10),
            max_position=kwargs.get('max_position', 100)
        )
    return ExecutionConfig(
        quote_interval=kwargs.get('quote_interval', 1.0),
        position_sync_interval=kwargs.get('position_sync_interval', 5.0),
        total_max_position=kwargs.get('total_max_position', 500),
        markets=markets,
        dry_run=dry_run
    )
