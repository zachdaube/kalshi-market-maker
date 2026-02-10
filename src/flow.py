"""
Flow Detection & Toxic Flow Protection for Kalshi Market Making

Detects adverse selection (toxic flow) by analyzing trade patterns:
- Runs: Consecutive trades in the same direction
- Trade imbalance: Heavy buying or selling pressure
- Price momentum: Rapid price changes
- Volume spikes: Unusual trading activity

When toxic flow is detected, the market maker should:
- Pull quotes (stop quoting temporarily)
- Widen spreads (increase quotes to reduce risk)
- Reduce size (quote smaller quantities)
"""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from collections import deque


@dataclass
class Trade:
    """A single trade from the market."""
    ticker: str
    price: int  # Price in cents
    quantity: int  # Number of contracts
    side: str  # "yes" or "no"
    timestamp: datetime  # When the trade occurred

    @property
    def yes_price(self) -> int:
        """Get the YES price regardless of side."""
        if self.side == "yes":
            return self.price
        else:
            return 100 - self.price

    @property
    def direction(self) -> int:
        """
        Trade direction: +1 for aggressive buy, -1 for aggressive sell.

        In Kalshi, aggressive buys lift the offer (take liquidity).
        Assuming trades at higher prices = buys, lower prices = sells.
        """
        # Simplified: YES buy or NO sell = bullish (+1)
        #            YES sell or NO buy = bearish (-1)
        if self.side == "yes":
            return 1  # Buying YES = bullish
        else:
            return -1  # Buying NO = bearish


@dataclass
class FlowMetrics:
    """Metrics about recent trade flow."""
    ticker: str

    # Run detection
    run_length: int  # Consecutive trades in same direction
    run_direction: int  # Direction of current run (+1 buy, -1 sell, 0 none)
    max_run_length: int  # Longest run in recent history

    # Imbalance
    trade_imbalance: float  # Buy volume - sell volume (as % of total)
    volume_imbalance_ratio: float  # Buy volume / sell volume

    # Momentum
    price_change: int  # Change in cents from first to last trade
    price_velocity: float  # Change per trade

    # Volume
    total_volume: int  # Total contracts traded
    avg_trade_size: float  # Average contracts per trade

    # Time
    trades_count: int  # Number of trades analyzed
    time_window_seconds: float  # Time span of trades

    # Toxicity score
    toxicity_score: float  # 0-100, higher = more toxic
    is_toxic: bool  # Whether flow is considered toxic


@dataclass
class FlowConfig:
    """Configuration for flow detection."""

    # Window configuration
    max_trades: int = 20  # Look at last N trades
    max_time_seconds: float = 300.0  # Or trades in last N seconds

    # Run thresholds
    toxic_run_length: int = 5  # Consider toxic if 5+ trades in same direction
    warning_run_length: int = 3  # Warning level

    # Imbalance thresholds
    toxic_imbalance: float = 0.7  # 70% or more in one direction
    warning_imbalance: float = 0.6  # 60% or more

    # Momentum thresholds
    toxic_price_change: int = 5  # 5¢ or more movement
    warning_price_change: int = 3  # 3¢ or more

    # Volume thresholds
    spike_multiplier: float = 3.0  # 3x average volume = spike

    # Toxicity scoring weights
    run_weight: float = 0.35
    imbalance_weight: float = 0.30
    momentum_weight: float = 0.25
    volume_weight: float = 0.10


@dataclass
class QuoteAdjustment:
    """Recommended quote adjustments based on flow."""

    action: str  # "pull", "widen", "reduce", "normal"

    # Adjustments (multiplicative)
    spread_multiplier: float = 1.0  # Multiply target spread by this
    size_multiplier: float = 1.0  # Multiply quote size by this

    # Timing
    cooldown_seconds: float = 0.0  # Wait this long before requoting

    # Reason
    reason: str = ""  # Why this adjustment was made
    toxicity_score: float = 0.0  # Flow toxicity score


class FlowAnalyzer:
    """
    Analyzes trade flow to detect toxic flow and adverse selection.

    Key concept: Market makers lose money to informed traders (toxic flow).
    Detect when someone knows something we don't and protect ourselves.
    """

    def __init__(self, config: Optional[FlowConfig] = None):
        """
        Initialize flow analyzer.

        Args:
            config: Flow detection configuration
        """
        self.config = config or FlowConfig()
        self.trade_history: Dict[str, deque] = {}  # ticker -> deque of trades

    def add_trade(self, trade: Trade):
        """
        Add a trade to the history.

        Args:
            trade: Trade to add
        """
        if trade.ticker not in self.trade_history:
            self.trade_history[trade.ticker] = deque(maxlen=self.config.max_trades)

        self.trade_history[trade.ticker].append(trade)

    def add_trades(self, trades: List[Trade]):
        """
        Add multiple trades to the history.

        Args:
            trades: List of trades to add (oldest first)
        """
        for trade in trades:
            self.add_trade(trade)

    def analyze_flow(self, ticker: str) -> Optional[FlowMetrics]:
        """
        Analyze recent trade flow for a ticker.

        Args:
            ticker: Market ticker to analyze

        Returns:
            FlowMetrics or None if insufficient data
        """
        if ticker not in self.trade_history or len(self.trade_history[ticker]) < 2:
            return None

        trades = list(self.trade_history[ticker])

        # Filter by time window
        if self.config.max_time_seconds:
            # Use timezone-aware now if trades have timezone info, naive otherwise
            if trades and trades[0].timestamp.tzinfo is not None:
                now = datetime.now(timezone.utc)
            else:
                now = datetime.now()
            cutoff = now - timedelta(seconds=self.config.max_time_seconds)
            trades = [t for t in trades if t.timestamp >= cutoff]

        if len(trades) < 2:
            return None

        # Calculate metrics
        run_length, run_direction, max_run = self._calculate_runs(trades)
        trade_imbalance, volume_ratio = self._calculate_imbalance(trades)
        price_change, price_velocity = self._calculate_momentum(trades)
        total_volume, avg_size = self._calculate_volume(trades)

        # Calculate time span
        time_span = (trades[-1].timestamp - trades[0].timestamp).total_seconds()

        # Calculate toxicity score
        toxicity = self._calculate_toxicity(
            run_length, trade_imbalance, price_change, total_volume, avg_size
        )

        return FlowMetrics(
            ticker=ticker,
            run_length=run_length,
            run_direction=run_direction,
            max_run_length=max_run,
            trade_imbalance=trade_imbalance,
            volume_imbalance_ratio=volume_ratio,
            price_change=price_change,
            price_velocity=price_velocity,
            total_volume=total_volume,
            avg_trade_size=avg_size,
            trades_count=len(trades),
            time_window_seconds=time_span,
            toxicity_score=toxicity,
            is_toxic=toxicity >= 60.0  # Threshold: 60+ is toxic
        )

    def _calculate_runs(self, trades: List[Trade]) -> Tuple[int, int, int]:
        """
        Calculate run statistics.

        Returns:
            (current_run_length, run_direction, max_run_length)
        """
        if not trades:
            return 0, 0, 0

        current_run = 1
        max_run = 1
        current_direction = trades[-1].direction

        # Calculate current run (from end backwards)
        for i in range(len(trades) - 2, -1, -1):
            if trades[i].direction == current_direction:
                current_run += 1
            else:
                break

        # Find max run in entire history
        temp_run = 1
        for i in range(1, len(trades)):
            if trades[i].direction == trades[i-1].direction:
                temp_run += 1
                max_run = max(max_run, temp_run)
            else:
                temp_run = 1

        return current_run, current_direction, max_run

    def _calculate_imbalance(self, trades: List[Trade]) -> Tuple[float, float]:
        """
        Calculate trade imbalance.

        Returns:
            (trade_imbalance_pct, volume_ratio)
        """
        buy_volume = sum(t.quantity for t in trades if t.direction > 0)
        sell_volume = sum(t.quantity for t in trades if t.direction < 0)
        total_volume = buy_volume + sell_volume

        if total_volume == 0:
            return 0.0, 1.0

        # Imbalance as % (-1 to +1, where +1 = all buys)
        imbalance = (buy_volume - sell_volume) / total_volume

        # Volume ratio (buy / sell)
        if sell_volume == 0:
            ratio = float('inf') if buy_volume > 0 else 1.0
        else:
            ratio = buy_volume / sell_volume

        return imbalance, ratio

    def _calculate_momentum(self, trades: List[Trade]) -> Tuple[int, float]:
        """
        Calculate price momentum.

        Returns:
            (total_price_change, price_velocity)
        """
        if len(trades) < 2:
            return 0, 0.0

        first_price = trades[0].yes_price
        last_price = trades[-1].yes_price

        change = last_price - first_price
        velocity = change / len(trades)

        return change, velocity

    def _calculate_volume(self, trades: List[Trade]) -> Tuple[int, float]:
        """
        Calculate volume statistics.

        Returns:
            (total_volume, avg_trade_size)
        """
        if not trades:
            return 0, 0.0

        total = sum(t.quantity for t in trades)
        avg = total / len(trades)

        return total, avg

    def _calculate_toxicity(
        self,
        run_length: int,
        imbalance: float,
        price_change: int,
        total_volume: int,
        avg_size: float
    ) -> float:
        """
        Calculate toxicity score (0-100).

        Higher score = more toxic flow = more likely to lose money.
        """
        config = self.config

        # 1. Run score (0-100)
        if run_length >= config.toxic_run_length:
            run_score = 100.0
        elif run_length >= config.warning_run_length:
            run_score = 50.0 + (run_length - config.warning_run_length) * 25.0
        else:
            run_score = (run_length / config.warning_run_length) * 50.0

        # 2. Imbalance score (0-100)
        abs_imbalance = abs(imbalance)
        if abs_imbalance >= config.toxic_imbalance:
            imbalance_score = 100.0
        elif abs_imbalance >= config.warning_imbalance:
            imbalance_score = 50.0 + (abs_imbalance - config.warning_imbalance) * 250.0
        else:
            imbalance_score = (abs_imbalance / config.warning_imbalance) * 50.0

        # 3. Momentum score (0-100)
        abs_change = abs(price_change)
        if abs_change >= config.toxic_price_change:
            momentum_score = 100.0
        elif abs_change >= config.warning_price_change:
            momentum_score = 50.0 + (abs_change - config.warning_price_change) * 25.0
        else:
            momentum_score = (abs_change / config.warning_price_change) * 50.0

        # 4. Volume score (0-100) - not implemented yet, needs baseline
        volume_score = 0.0

        # Weighted average
        toxicity = (
            run_score * config.run_weight +
            imbalance_score * config.imbalance_weight +
            momentum_score * config.momentum_weight +
            volume_score * config.volume_weight
        )

        return min(100.0, max(0.0, toxicity))

    def recommend_adjustment(self, ticker: str) -> QuoteAdjustment:
        """
        Recommend quote adjustments based on flow analysis.

        Args:
            ticker: Market ticker

        Returns:
            QuoteAdjustment with recommended actions
        """
        metrics = self.analyze_flow(ticker)

        if metrics is None:
            # Insufficient data, quote normally
            return QuoteAdjustment(
                action="normal",
                spread_multiplier=1.0,
                size_multiplier=1.0,
                reason="Insufficient trade data"
            )

        toxicity = metrics.toxicity_score

        # Critical: Pull quotes entirely
        if toxicity >= 80.0:
            return QuoteAdjustment(
                action="pull",
                spread_multiplier=0.0,
                size_multiplier=0.0,
                cooldown_seconds=30.0,
                reason=f"Critical toxic flow detected (score: {toxicity:.0f})",
                toxicity_score=toxicity
            )

        # High: Widen spreads significantly and reduce size
        elif toxicity >= 60.0:
            return QuoteAdjustment(
                action="widen",
                spread_multiplier=2.0,  # Double the spread
                size_multiplier=0.5,  # Half the size
                cooldown_seconds=10.0,
                reason=f"High toxic flow (score: {toxicity:.0f})",
                toxicity_score=toxicity
            )

        # Moderate: Widen spreads slightly and reduce size
        elif toxicity >= 40.0:
            return QuoteAdjustment(
                action="reduce",
                spread_multiplier=1.5,  # 50% wider spread
                size_multiplier=0.75,  # 25% smaller size
                cooldown_seconds=5.0,
                reason=f"Moderate flow pressure (score: {toxicity:.0f})",
                toxicity_score=toxicity
            )

        # Low: Quote normally
        else:
            return QuoteAdjustment(
                action="normal",
                spread_multiplier=1.0,
                size_multiplier=1.0,
                reason=f"Normal flow (score: {toxicity:.0f})",
                toxicity_score=toxicity
            )

    def get_trade_count(self, ticker: str) -> int:
        """Get number of trades tracked for a ticker."""
        if ticker not in self.trade_history:
            return 0
        return len(self.trade_history[ticker])

    def clear_history(self, ticker: Optional[str] = None):
        """
        Clear trade history.

        Args:
            ticker: Clear specific ticker, or all if None
        """
        if ticker:
            if ticker in self.trade_history:
                self.trade_history[ticker].clear()
        else:
            self.trade_history.clear()


def parse_kalshi_trades(raw_trades: List[Dict[str, Any]]) -> List[Trade]:
    """
    Parse raw Kalshi trade data into Trade objects.

    Args:
        raw_trades: List of trade dicts from Kalshi API

    Returns:
        List of Trade objects
    """
    trades = []

    for raw in raw_trades:
        try:
            # Parse timestamp
            timestamp_str = raw.get('created_time') or raw.get('trade_time')
            if timestamp_str:
                timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            else:
                timestamp = datetime.now(timezone.utc)

            trade = Trade(
                ticker=raw.get('ticker', ''),
                price=raw.get('yes_price') or raw.get('price', 0),
                quantity=raw.get('count') or raw.get('quantity', 0),
                side=raw.get('side', 'yes'),
                timestamp=timestamp
            )

            trades.append(trade)
        except Exception as e:
            # Skip malformed trades
            continue

    return trades


def format_flow_metrics(metrics: FlowMetrics) -> str:
    """Pretty-print flow metrics."""
    lines = []
    lines.append(f"\n{'='*60}")
    lines.append(f"Flow Analysis: {metrics.ticker}")
    lines.append(f"{'='*60}")

    lines.append(f"\n📊 Trade Statistics:")
    lines.append(f"   Trades:      {metrics.trades_count}")
    lines.append(f"   Time Window: {metrics.time_window_seconds:.1f}s")
    lines.append(f"   Total Volume: {metrics.total_volume} contracts")
    lines.append(f"   Avg Size:    {metrics.avg_trade_size:.1f} contracts/trade")

    lines.append(f"\n🏃 Run Detection:")
    direction_str = "BUY" if metrics.run_direction > 0 else "SELL" if metrics.run_direction < 0 else "NONE"
    lines.append(f"   Current Run:  {metrics.run_length} {direction_str}s")
    lines.append(f"   Max Run:      {metrics.max_run_length}")

    lines.append(f"\n⚖️  Trade Imbalance:")
    lines.append(f"   Imbalance:    {metrics.trade_imbalance:+.1%}")
    if abs(metrics.trade_imbalance) > 0.5:
        bias = "BULLISH" if metrics.trade_imbalance > 0 else "BEARISH"
        lines.append(f"   Bias:         {bias}")

    lines.append(f"\n📈 Price Momentum:")
    lines.append(f"   Price Change: {metrics.price_change:+d}¢")
    lines.append(f"   Velocity:     {metrics.price_velocity:+.2f}¢/trade")

    lines.append(f"\n⚠️  Toxicity Assessment:")
    lines.append(f"   Score:        {metrics.toxicity_score:.0f}/100")

    if metrics.is_toxic:
        lines.append(f"   Status:       🚨 TOXIC FLOW DETECTED")
    elif metrics.toxicity_score >= 40:
        lines.append(f"   Status:       ⚠️  ELEVATED RISK")
    else:
        lines.append(f"   Status:       ✅ NORMAL FLOW")

    lines.append(f"{'='*60}")

    return "\n".join(lines)


def format_adjustment(adj: QuoteAdjustment) -> str:
    """Pretty-print quote adjustment recommendation."""
    lines = []
    lines.append(f"\n{'='*60}")
    lines.append(f"Quote Adjustment Recommendation")
    lines.append(f"{'='*60}")

    # Action with emoji
    action_emoji = {
        "pull": "🛑",
        "widen": "⚠️",
        "reduce": "⚡",
        "normal": "✅"
    }
    emoji = action_emoji.get(adj.action, "")
    lines.append(f"\n{emoji} Action: {adj.action.upper()}")

    lines.append(f"\nAdjustments:")
    if adj.action != "pull":
        lines.append(f"   Spread:  {adj.spread_multiplier:.1f}x")
        lines.append(f"   Size:    {adj.size_multiplier:.1f}x")
    else:
        lines.append(f"   PULL ALL QUOTES")

    if adj.cooldown_seconds > 0:
        lines.append(f"\nCooldown: {adj.cooldown_seconds:.0f}s before requoting")

    lines.append(f"\nReason: {adj.reason}")
    lines.append(f"Toxicity Score: {adj.toxicity_score:.0f}/100")

    lines.append(f"{'='*60}")

    return "\n".join(lines)
