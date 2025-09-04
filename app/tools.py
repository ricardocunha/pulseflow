from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal

import requests

Decision = Literal["BUY", "SELL", "HOLD"]


@dataclass(frozen=True)
class TokenSpec:
    symbol: str
    mint: str
    decimals: int


TOKENS: Dict[str, TokenSpec] = {
    "SOL": TokenSpec("SOL", "So11111111111111111111111111111111111111112", 9),
    "WBTC": TokenSpec("WBTC", "3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh", 8),
}

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDC_DECIMALS = 6


class MarketGateway:
    def __init__(self, api_key: str, base_url: str = "https://public-api.birdeye.so") -> None:
        if not api_key:
            raise ValueError("Missing BIRDEYE_API_KEY")
        self.api_key = api_key
        self.base_url = base_url

    def fetch_prices(self, symbol: str, hours: int = 72) -> List[Dict[str, float]]:
        token = TOKENS.get(symbol)
        if token is None:
            raise ValueError(f"Unsupported symbol: {symbol}")

        now = datetime.now()
        start = now - timedelta(hours=hours)

        response = requests.get(
            f"{self.base_url}/defi/history_price",
            headers={"X-API-KEY": self.api_key, "Accept": "application/json"},
            params={
                "address": token.mint,
                "address_type": "token",
                "type": "1H",
                "time_from": int(start.timestamp()),
                "time_to": int(now.timestamp()),
            },
            timeout=15,
        )
        response.raise_for_status()

        payload = response.json()
        items = payload.get("data", {}).get("items", [])
        if not items:
            raise RuntimeError("No market data returned")

        prices: List[Dict[str, float]] = []
        for item in items:
            value = item.get("value")
            ts = item.get("unixTime")
            if value is None or ts is None:
                continue
            prices.append({"timestamp": float(ts), "price": float(value)})

        if len(prices) < 30:
            raise RuntimeError(f"Not enough data points: {len(prices)}")

        return prices[-60:]


class SwapGateway:
    def __init__(self) -> None:
        self.quote_url = "https://lite-api.jup.ag/swap/v1/quote"
        self.swap_url = "https://lite-api.jup.ag/swap/v1/swap"

    def quote(self, input_mint: str, output_mint: str, amount: int, slippage_bps: int = 50) -> Dict[str, Any]:
        response = requests.get(
            self.quote_url,
            params={
                "inputMint": input_mint,
                "outputMint": output_mint,
                "amount": amount,
                "slippageBps": slippage_bps,
            },
            timeout=15,
        )
        response.raise_for_status()
        return response.json()

    def build_swap(self, user_public_key: str, quote_response: Dict[str, Any]) -> Dict[str, Any]:
        response = requests.post(
            self.swap_url,
            json={
                "quoteResponse": quote_response,
                "userPublicKey": user_public_key,
                "wrapAndUnwrapSol": True,
                "dynamicComputeUnitLimit": True,
                "prioritizationFeeLamports": "auto",
            },
            timeout=20,
        )
        response.raise_for_status()
        return response.json()


def build_signal(prices: List[Dict[str, float]]) -> Dict[str, Any]:
    values = [point["price"] for point in prices]
    if len(values) < 30:
        return {
            "decision": "HOLD",
            "reason": "Not enough data for signal",
        }

    fast_window = values[-6:]
    slow_window = values[-24:]

    fast_avg = sum(fast_window) / len(fast_window)
    slow_avg = sum(slow_window) / len(slow_window)
    latest = values[-1]

    returns: List[float] = []
    for left, right in zip(values[-21:-1], values[-20:]):
        if left == 0:
            continue
        returns.append((right - left) / left)

    volatility = sum(abs(x) for x in returns) / len(returns) if returns else 0.0
    trend_strength = (fast_avg - slow_avg) / slow_avg if slow_avg else 0.0

    decision: Decision = "HOLD"
    reason = "No clear edge"

    if trend_strength > 0.006 and latest > slow_avg and volatility < 0.03:
        decision = "BUY"
        reason = "Short trend is above long trend with stable movement"
    elif trend_strength < -0.006 and latest < slow_avg:
        decision = "SELL"
        reason = "Short trend is below long trend and price is weak"

    return {
        "decision": decision,
        "reason": reason,
        "latest_price": latest,
        "fast_avg": fast_avg,
        "slow_avg": slow_avg,
        "volatility": volatility,
        "trend_strength": trend_strength,
    }


def trade_plan(symbol: str, decision: Decision) -> Dict[str, Any]:
    token = TOKENS[symbol]
    if decision == "BUY":
        amount = 100 * (10 ** USDC_DECIMALS)
        return {
            "input_mint": USDC_MINT,
            "output_mint": token.mint,
            "amount": amount,
            "label": f"Buy {symbol} with 100 USDC",
        }

    amount_map = {"SOL": int(0.4 * (10 ** token.decimals)), "WBTC": int(0.003 * (10 ** token.decimals))}
    return {
        "input_mint": token.mint,
        "output_mint": USDC_MINT,
        "amount": amount_map[symbol],
        "label": f"Sell {symbol} to USDC",
    }


def format_amount(raw: str | int | float, decimals: int) -> float:
    value = int(raw)
    return value / (10 ** decimals)
