"""
Market Scanner for Kalshi Market Making

Scans all open Kalshi markets and scores them for profitability
using the Avellaneda-Stoikov market making strategy.

Scoring criteria:
- Spread width: wider natural spreads = more room to capture
- Volume: moderate volume = enough fills without HFT competition
- Fee efficiency: markets away from 50c have lower fees
- Time to expiry: sufficient time to trade, avoid settlement risk
- Liquidity: active markets with real participants
- Price level: avoid near-settled markets (<5c or >95c)
"""

import math
import time
from datetime import datetime, timezone
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, field

from src.fees import MAKER_FEE_RATE


@dataclass
class MarketScore:
    """Scored market with profitability metrics."""
    ticker: str
    event_ticker: str
    title: str

    # Raw market data
    yes_bid: int  # cents
    yes_ask: int  # cents
    spread: int   # cents
    mid_price: float
    volume_24h: int
    open_interest: int
    liquidity_dollars: float
    close_time: Optional[datetime] = None
    days_to_expiry: Optional[float] = None

    # Component scores (0-100)
    spread_score: float = 0.0
    volume_score: float = 0.0
    fee_score: float = 0.0
    expiry_score: float = 0.0
    liquidity_score: float = 0.0
    price_score: float = 0.0

    # Composite
    total_score: float = 0.0

    # Suggested AS parameters
    suggested_gamma: float = 0.1
    suggested_sigma: float = 2.0
    suggested_k: float = 1.5
    suggested_base_size: int = 5
    suggested_max_position: int = 25


@dataclass
class ScanConfig:
    """Configuration for market scanning."""
    # Minimum filters (markets below these are excluded)
    min_spread: int = 2           # cents
    min_volume_24h: int = 10      # contracts
    min_open_interest: int = 0    # contracts
    min_days_to_expiry: float = 1.0
    max_days_to_expiry: float = 365.0
    min_price: int = 5            # cents (exclude near-settled)
    max_price: int = 95           # cents

    # Scoring weights (must sum to 1.0)
    weight_spread: float = 0.30
    weight_volume: float = 0.20
    weight_fee: float = 0.15
    weight_expiry: float = 0.15
    weight_liquidity: float = 0.10
    weight_price: float = 0.10

    # Output
    top_n: int = 20               # Number of top markets to return


# --- Scoring functions ---

def score_spread(spread_cents: int) -> float:
    """
    Score market spread for MM profitability.

    Sweet spot: 4-8c spread provides room to capture while still getting fills.
    Too tight (<2c): can't compete after fees.
    Too wide (>15c): illiquid, fills are rare.
    """
    if spread_cents <= 0:
        return 0.0
    if spread_cents <= 1:
        return 10.0
    if spread_cents <= 2:
        return 30.0
    if spread_cents <= 3:
        return 60.0
    if spread_cents <= 8:
        return 100.0
    if spread_cents <= 12:
        return 75.0
    if spread_cents <= 20:
        return 50.0
    return 25.0


def score_volume(volume_24h: int) -> float:
    """
    Score daily volume for MM profitability.

    Sweet spot: 100-10k daily contracts. Enough activity for fills,
    not so much that sophisticated participants dominate.
    """
    if volume_24h <= 0:
        return 0.0
    if volume_24h < 10:
        return 5.0
    if volume_24h < 50:
        return 20.0
    if volume_24h < 100:
        return 40.0
    if volume_24h < 500:
        return 70.0
    if volume_24h < 2000:
        return 90.0
    if volume_24h < 10000:
        return 100.0
    if volume_24h < 50000:
        return 60.0
    return 35.0  # Very high volume = highly competitive


def score_fee_efficiency(mid_price: float, spread_cents: int) -> float:
    """
    Score how much of the spread survives after round-trip maker fees.

    Fee per side = 0.0175 * P * (1-P) (in dollar terms per contract).
    Round-trip fee in cents = 2 * 0.0175 * P * (1-P) * 100.

    Higher score = more of the spread is profit vs fees.
    """
    if spread_cents <= 0 or mid_price <= 0 or mid_price >= 100:
        return 0.0
    p = mid_price / 100.0
    round_trip_fee_cents = 2 * MAKER_FEE_RATE * p * (1 - p) * 100
    profit_ratio = 1.0 - (round_trip_fee_cents / spread_cents)
    if profit_ratio <= 0:
        return 0.0
    return min(100.0, profit_ratio * 100.0)


def score_expiry(days_to_expiry: Optional[float]) -> float:
    """
    Score time to expiry for MM suitability.

    < 1 day: too close to settlement, prices converge, adverse selection spikes.
    1-3 days: risky but can work with tight parameters.
    7-30 days: sweet spot for consistent MM activity.
    > 90 days: less activity, longer capital lock.
    """
    if days_to_expiry is None:
        return 50.0  # Unknown, neutral score
    if days_to_expiry < 0.5:
        return 0.0
    if days_to_expiry < 1:
        return 15.0
    if days_to_expiry < 3:
        return 40.0
    if days_to_expiry < 7:
        return 70.0
    if days_to_expiry < 30:
        return 100.0
    if days_to_expiry < 90:
        return 80.0
    if days_to_expiry < 180:
        return 60.0
    return 45.0


def score_liquidity(open_interest: int, liquidity_dollars: float) -> float:
    """
    Score market liquidity (open interest + dollar liquidity).

    Higher open interest = more participants = more likely to get fills.
    Higher liquidity_dollars = deeper book.
    """
    oi_score = 0.0
    if open_interest >= 1000:
        oi_score = 100.0
    elif open_interest >= 500:
        oi_score = 80.0
    elif open_interest >= 100:
        oi_score = 60.0
    elif open_interest >= 20:
        oi_score = 40.0
    elif open_interest > 0:
        oi_score = 20.0

    liq_score = 0.0
    if liquidity_dollars >= 10000:
        liq_score = 100.0
    elif liquidity_dollars >= 5000:
        liq_score = 80.0
    elif liquidity_dollars >= 1000:
        liq_score = 60.0
    elif liquidity_dollars >= 100:
        liq_score = 40.0
    elif liquidity_dollars > 0:
        liq_score = 20.0

    return (oi_score + liq_score) / 2.0


def score_price_level(mid_price: float) -> float:
    """
    Score the price level for MM activity.

    Near 50c: most active but highest fees.
    15-85c: good range for activity.
    5-15c or 85-95c: lower fees but fewer counterparties.
    <5c or >95c: near-settled, avoid.
    """
    if mid_price < 5 or mid_price > 95:
        return 5.0
    if mid_price < 10 or mid_price > 90:
        return 30.0
    if mid_price < 15 or mid_price > 85:
        return 50.0
    if mid_price < 25 or mid_price > 75:
        return 70.0
    if mid_price < 35 or mid_price > 65:
        return 85.0
    return 100.0  # 35-65c: most active


# --- Parameter suggestion ---

def suggest_parameters(market: MarketScore) -> Tuple[float, float, float, int, int]:
    """
    Suggest AS model parameters based on market characteristics.

    Returns (gamma, sigma, k, base_size, max_position).
    """
    # Gamma (risk aversion): higher for wider-spread/lower-volume markets
    if market.spread <= 3:
        gamma = 0.05  # Tight spread, be aggressive
    elif market.spread <= 6:
        gamma = 0.1   # Standard
    elif market.spread <= 10:
        gamma = 0.15  # Wider spread, more conservative
    else:
        gamma = 0.2   # Very wide, be cautious

    # Sigma (volatility): estimate from spread width
    # A wider natural spread implies more price uncertainty
    sigma = max(1.0, market.spread * 0.6)

    # K (order arrival): estimate from volume
    # Higher volume = faster order arrival = can quote tighter
    if market.volume_24h > 5000:
        k = 2.5
    elif market.volume_24h > 1000:
        k = 2.0
    elif market.volume_24h > 200:
        k = 1.5
    elif market.volume_24h > 50:
        k = 1.0
    else:
        k = 0.7

    # Base size: smaller for lower-volume markets
    if market.volume_24h > 2000:
        base_size = 10
    elif market.volume_24h > 500:
        base_size = 7
    elif market.volume_24h > 100:
        base_size = 5
    else:
        base_size = 3

    # Max position: proportional to volume, capped
    max_position = min(100, max(10, market.volume_24h // 10))

    return gamma, sigma, k, base_size, max_position


# --- Main scanner ---

def parse_market_data(market: Dict) -> Optional[MarketScore]:
    """
    Parse raw Kalshi market dict into a MarketScore.
    Returns None if market data is insufficient for scoring.
    """
    ticker = market.get('ticker', '')
    if not ticker:
        return None

    yes_bid = market.get('yes_bid', 0) or 0
    yes_ask = market.get('yes_ask', 0) or 0

    # If no ask, try to derive from no_bid
    if yes_ask == 0:
        no_bid = market.get('no_bid', 0) or 0
        if no_bid > 0:
            yes_ask = 100 - no_bid

    # Need both sides for spread calculation
    if yes_bid <= 0 or yes_ask <= 0:
        return None
    if yes_bid >= yes_ask:
        return None

    spread = yes_ask - yes_bid
    mid_price = (yes_bid + yes_ask) / 2.0

    # Volume - use volume_24h if available, fall back to volume
    volume_24h = market.get('volume_24h', 0) or market.get('volume', 0) or 0

    open_interest = market.get('open_interest', 0) or 0

    # Liquidity dollars - may be a string like "123.45"
    liq_raw = market.get('liquidity', 0) or 0
    try:
        liquidity_dollars = float(liq_raw)
    except (ValueError, TypeError):
        liquidity_dollars = 0.0

    # Close time parsing
    close_time = None
    days_to_expiry = None
    close_ts = market.get('close_time') or market.get('expiration_time')
    if close_ts:
        try:
            if isinstance(close_ts, str):
                # Handle ISO format: "2026-03-15T12:00:00Z"
                ct = close_ts.replace('Z', '+00:00')
                close_time = datetime.fromisoformat(ct)
            elif isinstance(close_ts, (int, float)):
                close_time = datetime.fromtimestamp(close_ts, tz=timezone.utc)
            if close_time:
                now = datetime.now(timezone.utc)
                delta = close_time - now
                days_to_expiry = max(0, delta.total_seconds() / 86400.0)
        except (ValueError, OSError):
            pass

    title = market.get('title', '') or market.get('subtitle', '') or ticker
    event_ticker = market.get('event_ticker', '') or ''

    return MarketScore(
        ticker=ticker,
        event_ticker=event_ticker,
        title=title,
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        spread=spread,
        mid_price=mid_price,
        volume_24h=volume_24h,
        open_interest=open_interest,
        liquidity_dollars=liquidity_dollars,
        close_time=close_time,
        days_to_expiry=days_to_expiry,
    )


def score_market(market: MarketScore, config: ScanConfig) -> MarketScore:
    """
    Calculate all component scores and composite score for a market.
    Modifies the MarketScore in place and returns it.
    """
    market.spread_score = score_spread(market.spread)
    market.volume_score = score_volume(market.volume_24h)
    market.fee_score = score_fee_efficiency(market.mid_price, market.spread)
    market.expiry_score = score_expiry(market.days_to_expiry)
    market.liquidity_score = score_liquidity(market.open_interest, market.liquidity_dollars)
    market.price_score = score_price_level(market.mid_price)

    market.total_score = (
        config.weight_spread * market.spread_score +
        config.weight_volume * market.volume_score +
        config.weight_fee * market.fee_score +
        config.weight_expiry * market.expiry_score +
        config.weight_liquidity * market.liquidity_score +
        config.weight_price * market.price_score
    )

    # Suggest parameters
    gamma, sigma, k, base_size, max_pos = suggest_parameters(market)
    market.suggested_gamma = gamma
    market.suggested_sigma = sigma
    market.suggested_k = k
    market.suggested_base_size = base_size
    market.suggested_max_position = max_pos

    return market


def filter_market(market: MarketScore, config: ScanConfig) -> bool:
    """Return True if market passes all minimum filters."""
    if market.spread < config.min_spread:
        return False
    if market.volume_24h < config.min_volume_24h:
        return False
    if market.open_interest < config.min_open_interest:
        return False
    if market.mid_price < config.min_price or market.mid_price > config.max_price:
        return False
    if market.days_to_expiry is not None:
        if market.days_to_expiry < config.min_days_to_expiry:
            return False
        if market.days_to_expiry > config.max_days_to_expiry:
            return False
    return True


def scan_markets(raw_markets: List[Dict], config: Optional[ScanConfig] = None) -> List[MarketScore]:
    """
    Score and rank a list of raw market dicts.

    Args:
        raw_markets: List of market dicts from Kalshi API
        config: Scan configuration (uses defaults if None)

    Returns:
        List of MarketScore objects, sorted by total_score descending
    """
    if config is None:
        config = ScanConfig()

    results = []
    for raw in raw_markets:
        market = parse_market_data(raw)
        if market is None:
            continue
        if not filter_market(market, config):
            continue
        score_market(market, config)
        results.append(market)

    results.sort(key=lambda m: m.total_score, reverse=True)
    return results[:config.top_n]


def format_results(markets: List[MarketScore]) -> str:
    """Format scan results as a readable table."""
    if not markets:
        return "No markets found matching criteria."

    lines = []
    lines.append(f"{'Rank':<5} {'Score':<7} {'Ticker':<30} {'Bid':>4} {'Ask':>4} {'Sprd':>5} "
                 f"{'Vol24h':>8} {'OI':>7} {'Days':>6} {'Title'}")
    lines.append("-" * 120)

    for i, m in enumerate(markets, 1):
        days_str = f"{m.days_to_expiry:.1f}" if m.days_to_expiry is not None else "N/A"
        title = m.title[:40] if m.title else ""
        lines.append(
            f"{i:<5} {m.total_score:<7.1f} {m.ticker:<30} {m.yes_bid:>4} {m.yes_ask:>4} {m.spread:>5} "
            f"{m.volume_24h:>8} {m.open_interest:>7} {days_str:>6} {title}"
        )

    lines.append("")
    lines.append("Suggested Parameters for Top Markets:")
    lines.append(f"{'Ticker':<30} {'gamma':>7} {'sigma':>7} {'k':>7} {'size':>6} {'max_pos':>8}")
    lines.append("-" * 70)

    for m in markets[:10]:
        lines.append(
            f"{m.ticker:<30} {m.suggested_gamma:>7.2f} {m.suggested_sigma:>7.1f} "
            f"{m.suggested_k:>7.1f} {m.suggested_base_size:>6} {m.suggested_max_position:>8}"
        )

    return "\n".join(lines)


def generate_config_yaml(markets: List[MarketScore], top_n: int = 5) -> str:
    """Generate YAML market config entries for the top markets."""
    lines = ["markets:"]
    for m in markets[:top_n]:
        lines.append(f"  - ticker: {m.ticker}")
        lines.append(f"    enabled: true")
        lines.append(f"    gamma: {m.suggested_gamma}")
        lines.append(f"    sigma: {m.suggested_sigma}")
        lines.append(f"    k: {m.suggested_k}")
        lines.append(f"    base_size: {m.suggested_base_size}")
        lines.append(f"    max_position: {m.suggested_max_position}")
        lines.append(f"    max_loss_cents: 100.0")
        lines.append(f"    # {m.title[:60]}")
        lines.append(f"    # Score: {m.total_score:.1f}, Spread: {m.spread}c, Vol24h: {m.volume_24h}")
        lines.append("")
    return "\n".join(lines)
