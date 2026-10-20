# OrderFlow V1 — cTrader Indicator

Status: specification / implementation in progress. This is a separate C# cTrader Automate indicator and does not alter the MPV PRO V5 Python service.

## Confirmed core rule
- Primary signal timeframe: H4.
- Evaluate only completed H4 candles; do not repaint a signal intrabar.
- BUY requires a valid bullish order block AND a completed bullish reversal candle at/inside that block.
- SELL requires a valid bearish order block AND a completed bearish reversal candle at/inside that block.
- A candlestick pattern by itself is never a trade signal.
- Bearish rejection candidate: prominent upper wick; bullish inverse: prominent lower wick. Wick/body thresholds must be explicit configurable parameters.
- SL belongs beyond the setup invalidation level; never widen it after entry.
- Display the reversal pattern name on the dashboard and highlight qualifying pattern candles yellow.
- Configurable H4 / H1 / M15 analysis and Volume Profile / market-structure context are desired, but the strict H4 entry rule remains authoritative.
- Discord alerts are required for the two previously agreed alert types; alert delivery must fail safely if credentials are absent.

## Build sequence
1. Implement and compile the cTrader indicator shell and strict H4 guard.
2. Define and implement objective order-block formation, mitigation, and invalidation.
3. Add completed-candle reversal detection with explicit wick/body rules.
4. Require both conditions for signal generation; add chart annotations and dashboard.
5. Add SL/TP display (TP1 1:2, TP2 1:3 if this remains the chosen target scheme), Volume Profile / market-structure context, and Discord alerts.
6. Test compile, no-repaint behavior, historical examples, and edge cases before calling the indicator complete.

## Important status note
This file records the implementation contract; it is not proof that the indicator is implemented or tested. No live trading or order execution is part of this indicator.
