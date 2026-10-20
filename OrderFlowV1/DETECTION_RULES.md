# OrderFlow V1 — Objective Detection Rules (Draft for Review)

This document defines the next implementation stage. No BUY/SELL signal is valid until both the order block and a completed reversal candle qualify.

## Candle measurements
For candle i:
- range = high - low
- body = absolute(close - open)
- upper wick = high - max(open, close)
- lower wick = min(open, close) - low
- use a small epsilon when body is near zero to avoid division by zero.

## Reversal candidates
- Bearish rejection: upper wick >= configured wick/body ratio times body, lower wick <= configured maximum opposite-wick ratio times body, and candle closes below its open.
- Bullish rejection: lower wick >= configured wick/body ratio times body, upper wick <= configured maximum opposite-wick ratio times body, and candle closes above its open.
- Candle range must meet the configured minimum.
- Patterns are evaluated only after candle close and marked yellow; their names appear in the dashboard.
- Doji / zero-body candles are excluded from pin-bar classification unless a separate, explicit rule is added.

## Order block requirements (next coding stage)
A candidate block must be formed by the last opposite-colour candle before a measurable displacement move. Displacement must close beyond a confirmed recent swing level; the swing definition and lookback must be configurable and confirmed before implementation. A block is not valid indefinitely: invalidation occurs when price closes beyond the far edge of the block. Wick touches alone count as mitigation only if that rule is explicitly enabled.

## Signal gate
- BUY = valid bullish block + bullish rejection pattern overlapping the block + all required H4 close conditions.
- SELL = valid bearish block + bearish rejection pattern overlapping the block + all required H4 close conditions.
- Pattern-only signals are forbidden.
- Signal IDs should be keyed by symbol, timeframe, direction, and closed-candle timestamp to prevent duplicate alerts.

## Validation cases
1. Pattern outside a valid block -> no signal.
2. Pattern inside a valid block, but candle is still forming -> no signal.
3. Bullish pattern in bearish block -> no BUY.
4. Close through the block invalidation edge -> block becomes invalid.
5. Repeated calculation of the same closed candle -> no duplicate alert.
6. Non-H4 chart with strict H4 mode enabled -> no signals.
7. Zero-body candle -> no divide-by-zero and no accidental pin-bar signal.

Status: design notes only. These rules still require implementation and cTrader compilation/testing.
