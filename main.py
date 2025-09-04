from __future__ import annotations

import os
from typing import Any, Dict

from dotenv import load_dotenv

from app.graph import AVAILABLE_SYMBOLS, trade_app
from app.tools import TOKENS, USDC_DECIMALS, format_amount


def pick_symbol() -> str:
    print("\nPick a market:")
    for idx, symbol in enumerate(AVAILABLE_SYMBOLS, start=1):
        print(f"{idx}. {symbol}")

    while True:
        raw = input("Select number: ").strip()
        if not raw.isdigit():
            print("Please enter a number")
            continue

        option = int(raw)
        if 1 <= option <= len(AVAILABLE_SYMBOLS):
            return AVAILABLE_SYMBOLS[option - 1]

        print("Choice out of range")


def stream_until_pause(initial_state: Dict[str, Any], thread_id: str) -> Dict[str, Any]:
    config = {"configurable": {"thread_id": thread_id}}
    snapshot: Dict[str, Any] = {}

    for event in trade_app.stream(initial_state, config):
        if not event or "__interrupt__" in event:
            continue
        state = list(event.values())[0]
        if isinstance(state, dict):
            snapshot = state

    return snapshot


def continue_after_approval(thread_id: str) -> Dict[str, Any]:
    config = {"configurable": {"thread_id": thread_id}}
    snapshot: Dict[str, Any] = {}

    for event in trade_app.stream(None, config):
        if not event:
            continue
        state = list(event.values())[0]
        if isinstance(state, dict):
            snapshot = state

    return snapshot


def print_signal(state: Dict[str, Any]) -> None:
    signal = state.get("signal", {})
    print("\nSignal report")
    print(f"Decision: {signal.get('decision', 'N/A')}")
    print(f"Reason: {signal.get('reason', 'N/A')}")

    latest = signal.get("latest_price")
    fast = signal.get("fast_avg")
    slow = signal.get("slow_avg")
    vol = signal.get("volatility")
    if all(value is not None for value in [latest, fast, slow, vol]):
        print(f"Latest price: {latest:.4f}")
        print(f"Fast average: {fast:.4f}")
        print(f"Slow average: {slow:.4f}")
        print(f"Volatility score: {vol:.4f}")


def print_quote(state: Dict[str, Any]) -> None:
    quote = state.get("quote", {})
    plan = state.get("plan", {})
    symbol = state["symbol"]

    print("\nQuote")
    print(plan.get("label", "Trade"))

    in_decimals = USDC_DECIMALS if plan.get("input_mint") != TOKENS[symbol].mint else TOKENS[symbol].decimals
    out_decimals = USDC_DECIMALS if plan.get("output_mint") != TOKENS[symbol].mint else TOKENS[symbol].decimals

    in_amount = format_amount(quote.get("inAmount", 0), in_decimals)
    out_amount = format_amount(quote.get("outAmount", 0), out_decimals)

    print(f"Input amount: {in_amount:.6f}")
    print(f"Output amount: {out_amount:.6f}")
    print(f"Price impact: {float(quote.get('priceImpactPct', 0)):.4f}%")


def ask_approval() -> bool:
    while True:
        raw = input("\nApprove transaction build? (yes/no): ").strip().lower()
        if raw in {"yes", "y"}:
            return True
        if raw in {"no", "n"}:
            return False
        print("Type yes or no")


def main() -> None:
    load_dotenv()

    if not os.getenv("BIRDEYE_API_KEY"):
        print("Missing BIRDEYE_API_KEY in your environment")
        return

    print("\nPulseFlow Trader")
    print("Simple signal and human-approved swap flow")

    symbol = pick_symbol()
    thread_id = f"session-{symbol.lower()}"

    state = stream_until_pause(
        {
            "symbol": symbol,
            "prices": [],
            "signal": {},
            "plan": {},
            "quote": {},
            "swap_tx": {},
            "error": "",
        },
        thread_id,
    )

    if state.get("error"):
        print(f"\nError: {state['error']}")
        return

    print_signal(state)

    if state.get("signal", {}).get("decision") == "HOLD":
        print("\nNo trade for now")
        return

    print_quote(state)

    if not ask_approval():
        print("\nStopped by user")
        return

    final_state = continue_after_approval(thread_id)

    if final_state.get("error"):
        print(f"\nError: {final_state['error']}")
        return

    swap_tx = final_state.get("swap_tx", {})
    payload = swap_tx.get("swapTransaction", "")
    print("\nTransaction built")
    print(f"Serialized length: {len(payload)}")


if __name__ == "__main__":
    main()
