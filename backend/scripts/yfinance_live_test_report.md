# yfinance Live Connectivity Test Report

- **Date/time:** 2026-09-06 11:33 UTC
- **Session:** independent diagnostic session on branch `yfinance-live-test-results` (base: `claude/options-trading-app-qgb85d`)
- **Purpose:** determine whether *this* Claude Code Remote environment has real outbound internet access to Yahoo Finance, since a prior session's egress policy blocked it outright.

## TL;DR

**Yahoo Finance is NOT reachable from this environment either.** The outbound proxy explicitly rejects CONNECT tunnels to Yahoo Finance hosts with HTTP 403 ("policy denial or upstream failure"). This is a proxy/organization-policy block, not a transient network issue, a DNS failure, or an application bug — behavior is consistent with the prior session's findings.

## Proxy-level evidence

Querying the agent proxy's own status endpoint (`$HTTPS_PROXY/__agentproxy/status`) after running the test showed repeated `connect_rejected` entries in `recentRelayFailures`, all with `"detail": "gateway answered 403 to CONNECT (policy denial or upstream failure)"`, for:

- `guce.yahoo.com:443`
- `query2.finance.yahoo.com:443`

This confirms the block happens at the outbound gateway/proxy layer before any TLS handshake with Yahoo completes — i.e., it is an infrastructure/policy decision, not something the app or `yfinance` library can work around.

## Step 1-2: `python3 scripts/test_yfinance_live.py AAPL MSFT NVDA TSLA SPY`

Environment: fresh venv (`backend/.venv-livetest`), `pip install -r requirements.txt` completed cleanly (fastapi, uvicorn, yfinance and deps installed with no errors).

**Exit code: `1`**

Full stdout/stderr:

```
Testing yfinance provider with: AAPL, MSFT, NVDA, TSLA, SPY

--- AAPL ---
Cookie fetch from fc.yahoo.com failed (ConnectionError), continuing without it
Cookie/crumb fetch failed (ConnectionError), continuing without crumb
Failed to get ticker 'AAPL' reason: Failed to perform, curl: (7) CONNECT tunnel failed, response 403. See https://curl.se/libcurl/c/libcurl-errors.html first for more details.
Cookie/crumb fetch failed (ConnectionError), continuing without crumb
  FAILED to fetch quote: Could not fetch a quote for 'AAPL': Failed to perform, curl: (7) CONNECT tunnel failed, response 403. See https://curl.se/libcurl/c/libcurl-errors.html first for more details.
--- MSFT ---
Cookie/crumb fetch failed (ConnectionError), continuing without crumb
Failed to get ticker 'MSFT' reason: Failed to perform, curl: (7) CONNECT tunnel failed, response 403. See https://curl.se/libcurl/c/libcurl-errors.html first for more details.
Cookie/crumb fetch failed (ConnectionError), continuing without crumb
  FAILED to fetch quote: Could not fetch a quote for 'MSFT': Failed to perform, curl: (7) CONNECT tunnel failed, response 403. See https://curl.se/libcurl/c/libcurl-errors.html first for more details.
--- NVDA ---
Cookie/crumb fetch failed (ConnectionError), continuing without crumb
Failed to get ticker 'NVDA' reason: Failed to perform, curl: (7) CONNECT tunnel failed, response 403. See https://curl.se/libcurl/c/libcurl-errors.html first for more details.
Cookie/crumb fetch failed (ConnectionError), continuing without crumb
$NVDA: possibly delisted; no price data found  (period=1y)
  FAILED to fetch quote: Could not fetch a quote for 'NVDA': 'currentTradingPeriod'
--- TSLA ---
Cookie/crumb fetch failed (ConnectionError), continuing without crumb
Failed to get ticker 'TSLA' reason: Failed to perform, curl: (7) CONNECT tunnel failed, response 403. See https://curl.se/libcurl/c/libcurl-errors.html first for more details.
Cookie/crumb fetch failed (ConnectionError), continuing without crumb
$TSLA: possibly delisted; no price data found  (period=1y)
  FAILED to fetch quote: Could not fetch a quote for 'TSLA': 'currentTradingPeriod'
--- SPY ---
Cookie/crumb fetch failed (ConnectionError), continuing without crumb
Failed to get ticker 'SPY' reason: Failed to perform, curl: (7) CONNECT tunnel failed, response 403. See https://curl.se/libcurl/c/libcurl-errors.html first for more details.
Cookie/crumb fetch failed (ConnectionError), continuing without crumb
$SPY: possibly delisted; no price data found  (period=1y)
  FAILED to fetch quote: Could not fetch a quote for 'SPY': 'currentTradingPeriod'
--- Full API path (FastAPI TestClient, DATA_PROVIDER=yfinance) ---
  FAILED: The starlette.testclient module requires the httpx2 package to be installed.
You can install this with:
    $ pip install httpx2


DONE with 6 failure(s). See output above.
If you saw connection/certificate errors: this machine needs outbound HTTPS access to query1.finance.yahoo.com and query2.finance.yahoo.com.
If quotes/chains fetched fine but nothing ever screens in: markets may be closed with a thin chain, or try a more liquid ticker/lower --min-delta via the API's min_delta param.
```

Note: the "Full API path" sub-check failure (`httpx2` package missing) is a separate, pre-existing script/dependency issue unrelated to network access — `requirements.txt` does not pin an httpx test-client dependency. All 5 ticker fetches failed purely due to the network-level 403, not this.

## Step 3: Live server smoke test (`DATA_PROVIDER=yfinance uvicorn app.main:app --port 8010`)

Server started cleanly and stayed up for the duration of the test.

### `GET /api/health`
```
HTTP 200
{"status":"ok","data_provider":"yfinance"}
```

### `GET /api/screen?ticker=AAPL`
```
HTTP 400
{"detail":"Could not fetch a quote for 'AAPL': Failed to perform, curl: (7) CONNECT tunnel failed, response 403. See https://curl.se/libcurl/c/libcurl-errors.html first for more details."}
```

### `GET /api/scan?tickers=AAPL,MSFT&strategy=all`
```
HTTP 200
{
  "criteria": {"min_open_interest": 100, "min_abs_delta": 0.4, "min_days_to_expiration": 14},
  "results": [
    {
      "symbol": "AAPL",
      "error": "Could not fetch a quote for 'AAPL': Failed to perform, curl: (7) CONNECT tunnel failed, response 403. See https://curl.se/libcurl/c/libcurl-errors.html first for more details.",
      "ideas": []
    },
    {
      "symbol": "MSFT",
      "error": "Could not fetch a quote for 'MSFT': 'currentTradingPeriod'",
      "ideas": []
    }
  ]
}
```

The app itself behaves correctly under this failure: it degrades gracefully (200 with per-symbol `error` fields on `/scan`, 400 with a clear `detail` message on `/screen`) rather than crashing. No live strategy "idea" objects could be produced end-to-end because no underlying quote/chain data could ever be fetched — this is a pure network-access blocker, not an app defect.

## Conclusion

This environment's outbound proxy blocks Yahoo Finance (`guce.yahoo.com`, `query1/query2.finance.yahoo.com`, `fc.yahoo.com`) with 403 policy denials at the CONNECT-tunnel level, identical in nature to the original session's finding. A true live/E2E test of `YFinanceProvider` against real Yahoo Finance data is **not possible from any Claude Code Remote environment tested so far**. Validating `YFinanceProvider` will require either running it outside this sandboxed proxy environment (e.g., a developer's own machine or a CI runner with unrestricted egress) or recording/replaying fixture responses for offline testing.
