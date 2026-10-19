# MPV PRO V5

MPV PRO V5 is a forex and cryptocurrency trading-research API. It supports candle retrieval through Twelve Data, indicator-based baseline signals, on-demand multi-timeframe signal evaluation, heuristic market-structure analysis, risk planning, historical candle backtests, Finnhub news sentiment, authenticated TradingView signal intake, a persistent simulated paper-order ledger, and paper-mode loss limits.

**Current mode: research / paper-only. Live broker or exchange order execution is not implemented or enabled.** No strategy is guaranteed to be profitable.

## API endpoints

- `GET /` and `GET /health`: service status and version.
- `GET /timeframes/{style}`: profiles for `scalping`, `day_trading`, and `swing_trading`.
- `GET /market-data/candles?ticker=EURUSD&market=forex&timeframe=1h&limit=220`: fetch completed OHLC candles from Twelve Data.
- `GET /binance/rotation-scan`: read-only Binance Spot market scanner for BTC, ETH, FET, RENDER, NEAR, SUI, and AKT using completed 1h/4h candles; ranks relative strength and only emits BUY/SELL when the existing baseline agrees across both timeframes.
- `GET /binance/futures-context`: read-only public USDⓈ-M Futures context for funding rate, mark/index basis, open interest, and 24-hour change/quote volume; no account access and no orders.
- `GET /strategy/auto-evaluate?ticker=EURUSD&market=forex&style=day_trading`: fetch entry, confirmation, and context candles, evaluate all three, and return BUY/SELL only when the baseline signals agree; otherwise HOLD. When risk controls permit, it includes entry, stop-loss, take-profit, and estimated position size.
- `GET /news/sentiment?ticker=BTCUSDT&market=crypto`: retrieve Finnhub category headlines and score them with a transparent keyword heuristic.
- `GET /risk/status?equity=10000`: view emergency halt, daily realized P&L estimate, and consecutive-loss status.
- `POST /risk/calculate`: stop-loss / take-profit planning with fixed 1:3 risk-to-reward.
- `POST /strategy/evaluate`: EMA 9/21/50/200, RSI, MACD, ADX, Bollinger Bands, and ATR; returns a transparent baseline BUY/SELL/HOLD.
- `POST /strategy/multi-timeframe`: evaluate separately supplied entry, confirmation, and context candle sets.
- `POST /market-structure/analyze`: heuristic swing highs/lows, BOS/CHoCH events, fair-value gaps, simple order-block candidates, and liquidity sweeps.
- `POST /backtest/run`: historical candle simulation with configurable proportional fee and slippage assumptions.
- `POST /paper/orders`: create a persistent simulated order with a 1:3 target and estimated position size, subject to paper risk limits.
- `GET /paper/orders`: list simulated orders.
- `POST /paper/orders/{order_id}/close`: manually close a simulated order at a supplied price and estimate gross P&L.
- `POST /webhook/tradingview`: authenticated signal intake with duplicate `signal_id` protection.
- `GET /signals`: recent stored TradingView signals.
- SQLite persistence and GitHub Actions tests.

## Run locally

Requires Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set a unique `TRADINGVIEW_WEBHOOK_SECRET` in `.env`. Set `TWELVE_DATA_API_KEY` to enable market-data candles and `FINNHUB_API_KEY` to enable news sentiment. Keep all secrets out of source control. Then run:

```bash
uvicorn app.main:app --reload
```

Open `/docs` on the local server to explore and call the API. Run tests with:

```bash
python -m pytest -q
```

## Binance rotation scanner

`GET /binance/rotation-scan` reads public Binance Spot candles without API keys, scores the default watchlist (`BTCUSDT`, `ETHUSDT`, `FETUSDT`, `RENDERUSDT`, `NEARUSDT`, `SUIUSDT`, `AKTUSDT`), and returns price, 24-hour momentum, RSI, ADX, 1h/4h baseline signals, and a transparent rotation score. Pass a custom list with `?symbols=BTCUSDT,FETUSDT`. This is read-only public market data—not an authenticated Binance Spot/Futures demo account. It never reads balances or places orders. Unsupported or unavailable pairs are reported under `errors` so one bad symbol does not stop the entire scan.

## Binance Futures context

`GET /binance/futures-context` retrieves public USDⓈ-M Futures mark/index prices, latest funding rate, open interest, and 24-hour price change/quote volume for the default watchlist. These are market-context measurements only, not trade signals. The endpoint does not connect an authenticated demo account, read balances, or place orders. A pair may be unavailable on Futures even if it exists on Spot; those failures are returned under `errors`.

## Market-data notes

Twelve Data is used for both forex and crypto candles. The API converts common tickers such as `EURUSD` to `EUR/USD` and `BTCUSDT` to `BTC/USDT`, requests UTC timestamps, validates OHLC values, sorts candles chronologically, and excludes candles whose interval has not finished. Some symbols or history depths may not be available on every plan.

Twelve Data's Basic plan is listed as free with 8 API credits per minute and 800 per day, and includes real-time forex and crypto data for supported symbols. Verify current provider limits and licensing before use; the free plan is for internal/non-display use, not public redistribution. See the official [Twelve Data pricing page](https://twelvedata.com/pricing) and [API documentation](https://twelvedata.com/docs).

## Automatic signal evaluation

`/strategy/auto-evaluate` makes three candle requests using the selected style's entry, confirmation, and context profiles, evaluates the baseline on each timeframe, and returns a directional signal only if all three agree. It also includes heuristic market-structure output for the entry timeframe. When aligned and risk controls are clear, it returns an estimated trade plan with a 1:3 target and position-size estimate. It is on-demand, not a continuously running scanner, and it does not send orders. Provider limits apply; the default request uses three market-data API credits.

## Paper risk controls

Set these environment variables:

- `MAX_DAILY_LOSS_PERCENT=3`: block new paper orders after estimated realized losses reach this percentage of the equity supplied with the request.
- `MAX_CONSECUTIVE_LOSSES=3`: block new paper orders after this many consecutive losing closed paper orders.
- `EMERGENCY_HALT=true`: immediately block new paper orders and suppress trade plans from automatic signal evaluation.

These controls only govern the paper ledger and estimated gross P&L. They are not a substitute for broker-side protections and do not govern any live trading, which is not implemented. The daily limit uses UTC calendar days; estimated P&L excludes costs.

## Trading styles

- **Scalping:** entry 1m/5m; confirmation 5m/15m; context 15m/1h.
- **Day trading:** entry 5m/15m; confirmation 15m/1h; context 1h/4h.
- **Swing trading:** entry 1h/4h; confirmation 4h/1d; context 1d/1w.

These are configuration profiles, not evidence of strategy performance. Scalping is especially sensitive to spread, fees, latency, and slippage.

## Strategy notes

The baseline requires aligned EMAs, MACD direction, an RSI range, and ADX trend strength. It returns BUY, SELL, or HOLD and an ATR-based stop/target distance at 1:3. Bollinger Bands are calculated as context but are not currently a signal condition.

The multi-timeframe endpoint expects three separately supplied, chronological candle arrays for the same instrument. It does **not** resample candles or verify timestamps/freshness. Supply correctly aligned datasets. All three signal directions must agree before it returns BUY or SELL.

## News sentiment notes

The news endpoint uses Finnhub's `/news` endpoint with `crypto` or `forex` categories. It filters for common asset/currency keywords when possible and falls back to category-level headlines if none match. Sentiment is a small, transparent positive/negative keyword count, **not** a trained language model. It can miss context, sarcasm, negation, and event-specific meaning; do not use it alone to trade. A Finnhub API key is required and the provider's rate limits, plan, and licensing terms apply.

## Market structure notes

The structure endpoint uses transparent heuristics: swing pivots need bars on both sides, FVGs are three-candle gaps, and order-block candidates are the nearest opposite-colour candle before a close-based break of structure. BOS, CHoCH, FVGs, order blocks, and liquidity sweeps are interpreted differently by different traders; these labels are not validated entry signals and may require tuning.

## Paper-order ledger

Paper orders are stored in SQLite, support client-provided idempotency keys, calculate a 1:3 target, and can be manually closed to estimate gross P&L. This ledger does **not** connect to a live price feed, automatically trigger stops/targets, deduct costs, or send orders to a broker. Position sizing is an estimate and does not account for instrument contract multipliers, pip/tick values, or account-currency conversion.

## Backtest limitations

Send 222–2000 chronological OHLC candles to `POST /backtest/run`. Optional `fee_rate` and `slippage_rate` are proportional assumptions per side.

This is a research prototype, not an exchange-grade backtester. It uses unit-notional trades and a simplified cost model. If stop and target are both touched in one candle, it assumes the stop is hit first. It does not model actual instrument contract sizes, funding, changing spreads, gaps, order-book execution, or account-currency conversion. Profit factor is reported as undefined when there are no gross losses rather than returning a non-JSON infinity.

## TradingView webhook

Send JSON with `ticker`, `market` (`forex` or `crypto`), `action` (`BUY` or `SELL`), `timeframe`, `signal_id`, and optional `entry` / `stop_loss`. Put the configured secret in the `x-mpv-webhook-secret` header. Never commit real secrets.

Webhook signals are stored, deduplicated, and returned for review. They do not create orders.

## Deployment preparation (Railway / Docker)

A Railway-compatible Docker configuration is included. The container listens on the platform-provided `PORT` and exposes `/health` for health checks.

Before deploying:
1. Set `TRADINGVIEW_WEBHOOK_SECRET` to a long, random secret in the hosting provider's environment variables.
2. Set `TWELVE_DATA_API_KEY` for candles and `FINNHUB_API_KEY` for news sentiment.
3. Set risk controls deliberately, and keep `EMERGENCY_HALT=false` only when you want paper orders enabled.
4. Mount a persistent volume at `/data` and set `DATABASE_URL=sqlite:////data/mpv_pro_v5.db`. Without persistent storage, SQLite history may be lost when the service is replaced or redeployed.
5. Keep live execution disabled.
6. After deployment, verify `/health`, `/docs`, market-data availability, news-provider error handling, webhook authentication, duplicate-signal handling, paper-order persistence, and risk-limit blocking.

Do not put secrets in the repository or Docker image. The `.dockerignore` excludes local environment files and database files from the image build context.

## Remaining before a production-ready system

- Verify the latest CI run, including tests and Docker image build.
- Validate timestamp alignment and data freshness across multi-timeframe signals.
- Add broker-specific adapters, broker-side protective-order verification, and operational monitoring.
- Run realistic out-of-sample backtests and paper-trade for an extended period.
- Configure hosting, persistent storage, secrets, and uptime monitoring.

A broker/exchange has not been selected. Real-money execution should not be enabled until a specific platform is chosen, its test environment is validated, and order sizing/stop behaviour is verified. No API key or secret should ever be committed to this repository.

**Deployment status:** configuration only; this repository is not yet a deployed public service.

## CoinMarketCap market screener (read-only)

`GET /coinmarketcap/market-screener` ranks CoinMarketCap-listed assets by a transparent heuristic using 24-hour and 7-day percentage change plus 24-hour volume-to-market-cap ratio. It defaults to the top 100 listings, minimum market cap of USD 50 million, minimum 24-hour volume of USD 5 million, and excludes common stablecoin symbols. Filters can be adjusted with `limit`, `min_market_cap_usd`, `min_volume_24h_usd`, and `exclude_stablecoins`.

By default the adapter uses CoinMarketCap's keyless public API. For authenticated API access, set `COINMARKETCAP_API_KEY` in the deployment environment; never commit the key. Responses are cached in-process for 60 seconds and include the source timestamp where supplied. CoinMarketCap's available endpoints and quotas depend on the current provider plan; review the [official API documentation](https://coinmarketcap.com/api/documentation/pro-api-reference/keyless-public-api/) before relying on specific data or rate limits.

This is a **market-discovery and research feed**, not an exchange execution API. CoinMarketCap's aggregated prices/volumes do not establish whether a specific Kraken pair is tradable or what its executable order-book price is. Treat the score as a heuristic ranking, not a buy/sell signal. The endpoint is read-only and never places orders.
