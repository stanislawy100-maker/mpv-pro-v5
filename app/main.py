from __future__ import annotations

import asyncio
import hmac
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal
from uuid import uuid4

import httpx
from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from app.config import settings
from app.backtest import run_backtest
from app.timeframes import get_timeframe_profile
from app.indicators import calculate_indicators
from app.market_structure import analyze_market_structure
from app.market_data import fetch_candles
from app.binance_scanner import DEFAULT_SYMBOLS, scan_binance_demo
from app.binance_futures import DEFAULT_FUTURES_SYMBOLS, scan_binance_futures_context
from app.news import fetch_news_sentiment
from app.storage import close_paper_order, get_paper_order, initialize_database, paper_risk_state, recent_paper_orders, recent_signals, save_paper_order, save_signal
from app.strategy import evaluate_trend


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="MPV PRO V5",
    version="0.9.1",
    description="Forex and crypto signal research API. Live orders are disabled.",
    lifespan=lifespan,
)


class RiskRequest(BaseModel):
    side: Literal["BUY", "SELL"]
    entry: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    equity: float = Field(gt=0)
    risk_percent: float = Field(default=1.0, gt=0, le=5)

    @model_validator(mode="after")
    def validate_stop_side(self):
        if self.side == "BUY" and self.stop_loss >= self.entry:
            raise ValueError("For BUY, stop_loss must be below entry.")
        if self.side == "SELL" and self.stop_loss <= self.entry:
            raise ValueError("For SELL, stop_loss must be above entry.")
        return self


class PaperOrderRequest(RiskRequest):
    ticker: str = Field(min_length=1, max_length=40)
    market: Literal["forex", "crypto"]
    client_order_id: str | None = Field(default=None, min_length=1, max_length=120)


class ClosePaperOrderRequest(BaseModel):
    close_price: float = Field(gt=0)


class TradingViewSignal(BaseModel):
    ticker: str = Field(min_length=1, max_length=40)
    market: Literal["forex", "crypto"]
    action: Literal["BUY", "SELL"]
    timeframe: str = Field(default="unknown", max_length=20)
    entry: float | None = Field(default=None, gt=0)
    stop_loss: float | None = Field(default=None, gt=0)
    signal_id: str = Field(min_length=1, max_length=120)
    secret: str | None = Field(default=None, max_length=200)


class Candle(BaseModel):
    timestamp: datetime | None = None
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)

    @model_validator(mode="after")
    def valid_ohlc(self):
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close) or self.low > self.high:
            raise ValueError("Invalid OHLC candle: require low <= open/close <= high.")
        return self


class BacktestRequest(BaseModel):
    market: Literal["forex", "crypto"]
    ticker: str = Field(min_length=1, max_length=40)
    timeframe: str = Field(min_length=1, max_length=20)
    candles: list[Candle] = Field(min_length=222, max_length=2000)
    fee_rate: float = Field(default=0.0005, ge=0, le=0.02)
    slippage_rate: float = Field(default=0.0002, ge=0, le=0.02)


class StrategyRequest(BaseModel):
    market: Literal["forex", "crypto"]
    ticker: str = Field(min_length=1, max_length=40)
    timeframe: str = Field(min_length=1, max_length=20)
    candles: list[Candle] = Field(min_length=220, max_length=5000)


class MarketStructureRequest(BaseModel):
    market: Literal["forex", "crypto"]
    ticker: str = Field(min_length=1, max_length=40)
    timeframe: str = Field(min_length=1, max_length=20)
    candles: list[Candle] = Field(min_length=15, max_length=5000)
    swing_window: int = Field(default=3, ge=1, le=10)
    max_patterns: int = Field(default=10, ge=1, le=50)


class MultiTimeframeRequest(BaseModel):
    market: Literal["forex", "crypto"]
    ticker: str = Field(min_length=1, max_length=40)
    entry_timeframe: str = Field(min_length=1, max_length=20)
    confirmation_timeframe: str = Field(min_length=1, max_length=20)
    context_timeframe: str = Field(min_length=1, max_length=20)
    entry_candles: list[Candle] = Field(min_length=220, max_length=5000)
    confirmation_candles: list[Candle] = Field(min_length=220, max_length=5000)
    context_candles: list[Candle] = Field(min_length=220, max_length=5000)


def current_paper_risk_state(equity: float) -> dict:
    return paper_risk_state(
        equity=equity,
        max_daily_loss_percent=settings.max_daily_loss_percent,
        max_consecutive_losses=settings.max_consecutive_losses,
    )


@app.get("/")
def root():
    return {"name": "MPV PRO V5", "status": "running", "version": app.version,
            "supported_markets": ["forex", "crypto"], "mode": "paper_only",
            "live_execution_enabled": False}


@app.get("/health")
def health():
    return {"ok": True, "version": app.version}


@app.get("/risk/status")
def risk_status(equity: float = Query(default=10000, gt=0)):
    try:
        state = current_paper_risk_state(equity)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    halted = settings.emergency_halt or state["daily_loss_limit_reached"] or state["consecutive_loss_limit_reached"]
    return {
        "mode": "paper_only",
        "emergency_halt": settings.emergency_halt,
        "new_paper_orders_blocked": halted,
        "block_reason": "emergency_halt" if settings.emergency_halt else
            "daily_loss_limit" if state["daily_loss_limit_reached"] else
            "consecutive_loss_limit" if state["consecutive_loss_limit_reached"] else None,
        "risk_state": state,
        "live_execution_enabled": False,
    }


@app.get("/market-data/candles")
async def market_data_candles(
    ticker: str = Query(min_length=1, max_length=40),
    market: Literal["forex", "crypto"] = Query(),
    timeframe: Literal["1m", "5m", "15m", "30m", "1h", "2h", "4h", "1d", "1w"] = Query(default="1h"),
    limit: int = Query(default=220, ge=15, le=1000),
):
    try:
        return await fetch_candles(ticker=ticker, market=market, timeframe=timeframe, limit=limit)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Market-data provider request timed out.") from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Market-data provider returned HTTP {exc.response.status_code}.") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="Could not reach the market-data provider.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/strategy/auto-evaluate")
async def strategy_auto_evaluate(
    ticker: str = Query(min_length=1, max_length=40),
    market: Literal["forex", "crypto"] = Query(),
    style: Literal["scalping", "day_trading", "swing_trading"] = Query(default="day_trading"),
    equity: float = Query(default=10000, gt=0),
    risk_percent: float = Query(default=1.0, gt=0, le=5),
):
    profile = get_timeframe_profile(style)
    timeframes = {
        "entry": profile["entry_timeframes"][0],
        "confirmation": profile["confirmation_timeframes"][0],
        "context": profile["context_timeframes"][0],
    }
    try:
        fetched = await asyncio.gather(*[
            fetch_candles(ticker=ticker, market=market, timeframe=timeframe, limit=220)
            for timeframe in timeframes.values()
        ])
        evaluations = {}
        for role, timeframe, data in zip(timeframes.keys(), timeframes.values(), fetched):
            snapshot = calculate_indicators(data["candles"])
            evaluations[role] = {
                "timeframe": timeframe,
                "last_candle_at": data["candles"][-1]["timestamp"],
                "close": snapshot.close,
                "signal": evaluate_trend(snapshot),
                "candle_count": data["count"],
            }
        structure = analyze_market_structure(fetched[0]["candles"])
        risk_state = current_paper_risk_state(equity)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Market-data provider request timed out.") from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Market-data provider returned HTTP {exc.response.status_code}.") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="Could not reach the market-data provider.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    actions = [evaluations[role]["signal"]["action"] for role in ("entry", "confirmation", "context")]
    aligned = actions[0] in ("BUY", "SELL") and actions.count(actions[0]) == 3
    halted = settings.emergency_halt or risk_state["daily_loss_limit_reached"] or risk_state["consecutive_loss_limit_reached"]
    trade_plan = None
    if aligned and not halted:
        entry = evaluations["entry"]["close"]
        stop_distance = evaluations["entry"]["signal"]["stop_loss_distance"]
        target_distance = evaluations["entry"]["signal"]["take_profit_distance"]
        side = actions[0]
        stop_loss = entry - stop_distance if side == "BUY" else entry + stop_distance
        take_profit = entry + target_distance if side == "BUY" else entry - target_distance
        risk_amount = equity * risk_percent / 100.0
        trade_plan = {
            "side": side,
            "entry": entry,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_reward_ratio": "1:3",
            "equity_assumption": equity,
            "risk_percent": risk_percent,
            "risk_amount_estimate": risk_amount,
            "quantity_estimate": risk_amount / stop_distance if stop_distance > 0 else None,
            "note": "Sizing estimate only; contract multipliers, pip/tick value, account currency, fees and slippage are not modelled.",
        }
    return {
        "ticker": ticker.upper(),
        "market": market,
        "style": style,
        "evaluations": evaluations,
        "alignment": "aligned" if aligned else "mixed_or_no_signal",
        "signal": actions[0] if aligned else "HOLD",
        "trade_plan": trade_plan,
        "risk_controls": {
            "trading_halted": halted,
            "emergency_halt": settings.emergency_halt,
            "risk_state": risk_state,
        },
        "risk_reward_ratio": "1:3",
        "market_structure": structure,
        "live_execution_enabled": False,
        "warning": "On-demand research signal only. Verify candle timestamps and provider coverage; no broker orders are placed and no profitability is implied.",
    }


@app.get("/binance/rotation-scan")
async def binance_rotation_scan(
    symbols: str = Query(default=",".join(DEFAULT_SYMBOLS), min_length=5, max_length=500),
):
    """Read-only Binance Spot scanner using public 1h/4h candles; never places orders."""
    requested = [part.strip().upper() for part in symbols.split(",") if part.strip()]
    try:
        return await scan_binance_demo(requested)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Binance market-data request timed out.") from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Binance returned HTTP {exc.response.status_code}.") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="Could not reach Binance public market data.") from exc


@app.get("/binance/futures-context")
async def binance_futures_context(
    symbols: str = Query(default=",".join(DEFAULT_FUTURES_SYMBOLS), min_length=5, max_length=500),
):
    """Read-only public Binance USDⓈ-M Futures context; never places orders."""
    requested = [part.strip().upper() for part in symbols.split(",") if part.strip()]
    try:
        return await scan_binance_futures_context(requested)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Binance Futures market-data request timed out.") from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Binance Futures returned HTTP {exc.response.status_code}.") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="Could not reach Binance Futures public market data.") from exc


@app.get("/news/sentiment")
async def news_sentiment(
    ticker: str = Query(min_length=1, max_length=40),
    market: Literal["forex", "crypto"] = Query(),
    limit: int = Query(default=20, ge=1, le=50),
):
    try:
        return await fetch_news_sentiment(ticker=ticker, market=market, limit=limit)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="News provider request timed out.") from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"News provider returned HTTP {exc.response.status_code}.") from exc
    except (httpx.RequestError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Could not retrieve or parse news from the provider.") from exc


@app.post("/risk/calculate")
def calculate_risk(request: RiskRequest):
    risk_distance = abs(request.entry - request.stop_loss)
    take_profit_distance = risk_distance * 3.0
    take_profit = request.entry + take_profit_distance if request.side == "BUY" else request.entry - take_profit_distance
    risk_amount = request.equity * request.risk_percent / 100.0
    quantity_estimate = risk_amount / risk_distance
    return {"side": request.side, "entry": request.entry, "stop_loss": request.stop_loss,
            "take_profit": take_profit, "risk_reward_ratio": "1:3",
            "risk_amount": round(risk_amount, 8), "risk_percent": request.risk_percent,
            "quantity_estimate": round(quantity_estimate, 8),
            "note": "Estimate only; adapt quantity for the instrument's contract specifications, account currency, and trading costs."}


@app.post("/paper/orders")
def create_paper_order(request: PaperOrderRequest):
    risk_distance = abs(request.entry - request.stop_loss)
    risk_amount = request.equity * request.risk_percent / 100.0
    quantity_estimate = risk_amount / risk_distance
    target_distance = risk_distance * 3.0
    take_profit = request.entry + target_distance if request.side == "BUY" else request.entry - target_distance
    order_id = request.client_order_id or uuid4().hex
    try:
        if request.client_order_id:
            existing = get_paper_order(order_id)
            if existing:
                return {"created": False, "duplicate": True, "order": existing, "mode": "paper_only",
                        "live_execution_enabled": False}
        if settings.emergency_halt:
            raise HTTPException(status_code=423, detail="Emergency halt is active; new paper orders are blocked.")
        state = current_paper_risk_state(request.equity)
        if state["daily_loss_limit_reached"] or state["consecutive_loss_limit_reached"]:
            raise HTTPException(status_code=409, detail={
                "message": "Paper risk limit reached; new orders are blocked.",
                "risk_state": state,
            })
        order = {"order_id": order_id, "ticker": request.ticker.upper(), "market": request.market,
                 "side": request.side, "entry": request.entry, "stop_loss": request.stop_loss,
                 "take_profit": take_profit, "equity": request.equity, "risk_percent": request.risk_percent,
                 "risk_amount": risk_amount, "quantity_estimate": quantity_estimate}
        inserted = save_paper_order(order)
        stored = get_paper_order(order_id)
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"created": inserted, "duplicate": not inserted, "order": stored, "mode": "paper_only",
            "live_execution_enabled": False,
            "warning": "Simulated ledger only: it does not monitor live prices, trigger stops/targets, or send broker orders. Quantity is an estimate and excludes contract multipliers and trading costs."}


@app.get("/paper/orders")
def list_paper_orders(limit: int = Query(default=50, ge=1, le=200)):
    return {"orders": recent_paper_orders(limit=limit), "mode": "paper_only", "live_execution_enabled": False}


@app.post("/paper/orders/{order_id}/close")
def finish_paper_order(order_id: str, request: ClosePaperOrderRequest):
    try:
        status, order = close_paper_order(order_id, request.close_price)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if status == "not_found":
        raise HTTPException(status_code=404, detail="Paper order not found.")
    if status == "already_closed":
        raise HTTPException(status_code=409, detail="Paper order is already closed.")
    return {"order": order, "mode": "paper_only", "live_execution_enabled": False,
            "pnl_note": "Estimated gross P&L only; fees, spread, slippage, funding and contract specifications are not included."}


@app.post("/strategy/evaluate")
def strategy_evaluate(request: StrategyRequest):
    try:
        indicators = calculate_indicators([c.model_dump() for c in request.candles])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = evaluate_trend(indicators)
    return {"market": request.market, "ticker": request.ticker, "timeframe": request.timeframe,
            "close": indicators.close, "indicators": indicators.__dict__, "signal": result,
            "live_execution_enabled": False}


@app.post("/market-structure/analyze")
def market_structure_analyze(request: MarketStructureRequest):
    try:
        result = analyze_market_structure([c.model_dump() for c in request.candles],
                                          swing_window=request.swing_window, max_patterns=request.max_patterns)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"market": request.market, "ticker": request.ticker, "timeframe": request.timeframe,
            "analysis": result, "live_execution_enabled": False}


@app.post("/strategy/multi-timeframe")
def strategy_multi_timeframe(request: MultiTimeframeRequest):
    datasets = {"entry": (request.entry_timeframe, request.entry_candles),
                "confirmation": (request.confirmation_timeframe, request.confirmation_candles),
                "context": (request.context_timeframe, request.context_candles)}
    evaluations = {}
    try:
        for role, (timeframe, candles) in datasets.items():
            snapshot = calculate_indicators([c.model_dump() for c in candles])
            evaluations[role] = {"timeframe": timeframe, "close": snapshot.close,
                                 "indicators": snapshot.__dict__, "signal": evaluate_trend(snapshot)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    actions = [evaluations[role]["signal"]["action"] for role in ("entry", "confirmation", "context")]
    aligned = actions[0] in ("BUY", "SELL") and actions.count(actions[0]) == len(actions)
    return {"market": request.market, "ticker": request.ticker, "evaluations": evaluations,
            "alignment": "aligned" if aligned else "mixed_or_no_signal",
            "signal": actions[0] if aligned else "HOLD", "risk_reward_ratio": "1:3",
            "live_execution_enabled": False,
            "warning": "Supply correctly timestamp-aligned datasets for the same instrument. This endpoint checks direction only; it does not resample candles or verify timestamp freshness."}


@app.get("/timeframes/{style}")
def timeframe_profile(style: Literal["scalping", "day_trading", "swing_trading"]):
    return get_timeframe_profile(style)


@app.post("/backtest/run")
def backtest_run(request: BacktestRequest):
    try:
        result = run_backtest([c.model_dump() for c in request.candles],
                              fee_rate=request.fee_rate, slippage_rate=request.slippage_rate)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result.update({"market": request.market, "ticker": request.ticker, "timeframe": request.timeframe})
    return result


@app.post("/webhook/tradingview")
def tradingview_webhook(signal: TradingViewSignal, x_mpv_webhook_secret: str | None = Header(default=None)):
    expected = settings.tradingview_webhook_secret
    supplied_secret = x_mpv_webhook_secret if x_mpv_webhook_secret is not None else signal.secret
    if not expected:
        raise HTTPException(status_code=503, detail="Webhook secret is not configured.")
    if not supplied_secret or not hmac.compare_digest(supplied_secret, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook secret.")
    try:
        inserted = save_signal(signal)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"accepted": True, "duplicate": not inserted, "signal_id": signal.signal_id,
            "ticker": signal.ticker, "market": signal.market, "action": signal.action,
            "timeframe": signal.timeframe, "execution": "disabled", "mode": "paper_only"}


@app.get("/signals")
def get_signals(limit: int = Query(default=50, ge=1, le=200)):
    return {"signals": recent_signals(limit=limit), "live_execution_enabled": False}

# CoinMarketCap provides market data only; this router never places exchange orders.
from app.coinmarketcap import router as coinmarketcap_router
app.include_router(coinmarketcap_router)
