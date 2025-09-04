from __future__ import annotations

import os
from typing import Any, Dict, List, Literal, TypedDict

from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.tools import (
    TOKENS,
    MarketGateway,
    SwapGateway,
    build_signal,
    trade_plan,
)

load_dotenv()


class TradeState(TypedDict):
    symbol: str
    prices: List[Dict[str, float]]
    signal: Dict[str, Any]
    plan: Dict[str, Any]
    quote: Dict[str, Any]
    swap_tx: Dict[str, Any]
    error: str


market_gateway = MarketGateway(api_key=os.getenv("BIRDEYE_API_KEY", ""))
swap_gateway = SwapGateway()


def load_prices(state: TradeState) -> TradeState:
    try:
        prices = market_gateway.fetch_prices(state["symbol"])
        return {**state, "prices": prices, "error": ""}
    except Exception as exc:
        return {**state, "error": str(exc)}


def analyze_prices(state: TradeState) -> TradeState:
    if state.get("error"):
        return state

    signal = build_signal(state["prices"])
    return {**state, "signal": signal}


def need_quote(state: TradeState) -> Literal["prepare_quote", "done"]:
    if state.get("error"):
        return "done"
    if state.get("signal", {}).get("decision") in {"BUY", "SELL"}:
        return "prepare_quote"
    return "done"


def prepare_quote(state: TradeState) -> TradeState:
    if state.get("error"):
        return state

    try:
        plan = trade_plan(state["symbol"], state["signal"]["decision"])
        quote = swap_gateway.quote(
            input_mint=plan["input_mint"],
            output_mint=plan["output_mint"],
            amount=plan["amount"],
        )
        return {**state, "plan": plan, "quote": quote}
    except Exception as exc:
        return {**state, "error": str(exc)}


def build_transaction(state: TradeState) -> TradeState:
    if state.get("error"):
        return state

    try:
        swap_tx = swap_gateway.build_swap(
            user_public_key="11111111111111111111111111111111",
            quote_response=state["quote"],
        )
        return {**state, "swap_tx": swap_tx}
    except Exception as exc:
        return {**state, "error": str(exc)}


def create_app():
    graph = StateGraph(TradeState)

    graph.add_node("load_prices", load_prices)
    graph.add_node("analyze_prices", analyze_prices)
    graph.add_node("prepare_quote", prepare_quote)
    graph.add_node("build_transaction", build_transaction)

    graph.set_entry_point("load_prices")
    graph.add_edge("load_prices", "analyze_prices")
    graph.add_conditional_edges("analyze_prices", need_quote, {"prepare_quote": "prepare_quote", "done": END})
    graph.add_edge("prepare_quote", "build_transaction")
    graph.add_edge("build_transaction", END)

    return graph.compile(checkpointer=MemorySaver(), interrupt_before=["build_transaction"])


trade_app = create_app()
AVAILABLE_SYMBOLS = sorted(TOKENS.keys())
