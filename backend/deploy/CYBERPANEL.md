# Deploying to a CyberPanel VPS

CyberPanel runs on OpenLiteSpeed (OLS), which doesn't have a first-class
"Python app" type the way it does PHP. The reliable pattern is: run the app
as its own systemd service on localhost, then have OLS reverse-proxy to it.
This also means the app's outbound calls to Yahoo Finance happen from the
VPS's own network path, which is a genuinely different egress route than any
Claude Code Remote sandbox -- worth testing here specifically because those
sandboxes block Yahoo Finance by policy and a plain VPS very likely does not.

This box already hosts other sites on port 8000, so this app uses **port
8005** instead (the systemd unit and steps below already reflect that). Site:
**`options.rginvestor67.com`**.

The frontend is two separate pages served by the same backend: `/` is the
public research site (news, watchlist, portfolio preview, research, scanner,
Level 2 -- no login), and `/trading.html` is the password-gated Trading
module (account, orders, E*TRADE connection). No extra proxy config is
needed for this split -- both are static files served from `frontend/` by
the one FastAPI app.

## 1. Create a dedicated system user and pull the code

```bash
sudo adduser --system --group --home /home/optionsapp optionsapp
sudo -iu optionsapp
git clone -b claude/options-trading-app-qgb85d https://github.com/rguthri2/Options.git options-app
cd options-app/backend
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt   # fastapi, uvicorn, yfinance
deactivate
exit   # back to your sudo-capable user
```

## 2. Install and start the systemd service

The unit file is checked into the repo at `backend/deploy/options-app.service`
(paths already match the `optionsapp` user/home from step 1, and it's set to
listen on `127.0.0.1:8005` -- edit if you used a different user, clone path,
or port).

```bash
sudo cp /home/optionsapp/options-app/backend/deploy/options-app.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now options-app
sudo systemctl status options-app --no-pager
```

Sanity-check it's actually up before touching OLS:

```bash
curl -s http://127.0.0.1:8005/api/health
# {"status":"ok","data_provider":"yfinance"}
```

If that fails, check logs with `sudo journalctl -u options-app -n 100 --no-pager`.

## 3. Point OpenLiteSpeed at it

In CyberPanel, create the website first if you haven't (Websites -> Create
Website -> domain `options.rginvestor67.com`), then wire up the proxy.

**Via CyberPanel UI** (Websites -> List Websites -> Manage ->
`options.rginvestor67.com`):

1. Go to the **Rewrite Rules** tab (some CyberPanel versions surface this
   proxy setup under **Configurations** instead) and enable the built-in
   reverse-proxy option, pointing it at `127.0.0.1:8005`. If your version's
   UI doesn't expose this directly, use the OLS WebAdmin console fallback
   below -- it always works regardless of CyberPanel UI version.

**Via OpenLiteSpeed WebAdmin console** (always available at
`https://options.rginvestor67.com:7080`, or `https://70.36.114.244:7080`;
default user `admin`, password set during CyberPanel install):

1. **Server Configuration -> External App -> Add**: type `Web Server`,
   name it `optionsapp`, address `127.0.0.1:8005`, max connections `35`.
2. **Virtual Hosts -> options.rginvestor67.com -> Context -> Add**: type
   `Proxy`, URI `/`, Web Server = `optionsapp`.
3. Graceful restart OLS: **Actions -> Graceful Restart** (top right), or
   `sudo systemctl reload lsws` from the shell.

## 4. SSL

Handled entirely by CyberPanel as usual (Websites -> `options.rginvestor67.com`
-> SSL -> Issue SSL / Let's Encrypt). No app-side changes needed -- OLS
terminates TLS and proxies plain HTTP to `127.0.0.1:8005`.

## 5. Firewall

Only 80/443 (and CyberPanel's own admin ports) need to be open publicly.
Port 8005 should stay bound to `127.0.0.1` (the systemd unit already does
this) so it's never reachable from outside the box directly.

## 6. Verify

From the VPS itself:

```bash
sudo -iu optionsapp
cd options-app/backend && source .venv/bin/activate
python3 scripts/test_yfinance_live.py AAPL MSFT NVDA TSLA SPY
```

This is the definitive test of whether the VPS's own network can reach
Yahoo Finance -- completely independent of any Claude Code Remote sandbox
restriction.

From outside (once the domain/proxy is live), the same `/api/scan` endpoint
is reachable at:

```
https://options.rginvestor67.com/api/scan?tickers=AAPL,MSFT&strategy=all
```

and can be checked from any machine with a browser or curl -- including
Claude, from a different session, once DNS/SSL are live.

## 7. Auth & trading setup

As of the auth/trading update, the app returns `503` on every request until
login is configured. Generate real credentials and wire them into the
systemd unit (the checked-in unit file has placeholder values):

```bash
sudo -iu optionsapp
cd options-app/backend && source .venv/bin/activate
python3 scripts/create_admin.py
# prints ADMIN_USERNAME=..., ADMIN_PASSWORD_HASH=..., SECRET_KEY=... -- copy these
deactivate
exit

sudo nano /etc/systemd/system/options-app.service
# replace the three REPLACE_ME placeholders under [Service] with the printed values
sudo systemctl daemon-reload
sudo systemctl restart options-app
curl -s http://127.0.0.1:8005/api/auth/me   # should now say {"detail":"Not authenticated"}, not 503
```

The app defaults to **paper trading** (`ACTIVE_BROKER=paper`,
`LIVE_TRADING_ENABLED=false`) regardless of anything else -- this is
intentional and safe to leave as-is indefinitely; the screener and paper
trading UI work fully without ever touching E*TRADE.

### Enabling real E*TRADE order placement (optional, real money)

Read `backend/app/trading/etrade_broker.py`'s module docstring first --
this integration was built against E*TRADE's documented API but could not
be tested end-to-end from the sandboxed session that built it (no network
path to etrade.com from there at all). Test extensively in E*TRADE's
sandbox before ever going live.

1. Register a developer app at https://developer.etrade.com -- this gives
   you a **sandbox** consumer key/secret immediately; production keys
   require an additional approval step from E*TRADE.
2. Add to the systemd unit and restart:
   ```
   Environment=ETRADE_CONSUMER_KEY=your_sandbox_key
   Environment=ETRADE_CONSUMER_SECRET=your_sandbox_secret
   Environment=ETRADE_SANDBOX=true
   Environment=ACTIVE_BROKER=etrade
   ```
   Leave `LIVE_TRADING_ENABLED=false` for now -- with `ETRADE_SANDBOX=true`
   this exercises the real OAuth + order flow against E*TRADE's sandbox
   (fake fills, no real money) without needing the live-trading gate open.
3. While logged into the app, complete the OAuth handshake:
   - `GET /api/broker/etrade/auth-url` (send the session cookie, e.g. via
     the browser's devtools network tab, or `curl -b cookies.txt`) returns
     an `authorize_url` plus a `request_token`/`request_token_secret` pair.
   - Open `authorize_url` in a browser, log into E*TRADE, and copy the
     verifier code it displays.
   - `POST /api/broker/etrade/complete-auth` with
     `{"request_token": "...", "request_token_secret": "...", "verifier": "..."}`
     (the two token values from the previous step, not values you invent).
4. Place small sandbox orders through the UI and confirm they behave as
   expected -- preview/place succeed, `/api/account` and `/api/orders`
   reflect them correctly, cancel works.
5. Only after that: switch `ETRADE_SANDBOX=false` (using your approved
   production consumer key/secret) and, when you are ready for the safety
   gate itself, `LIVE_TRADING_ENABLED=true`. Every order still requires
   `confirm_live: true` in the request even then -- the UI's confirm modal
   handles this, but note it if you ever call the API directly.
6. Access tokens expire at midnight US Eastern and go inactive after 2
   hours idle. If orders start failing with an auth-shaped error, redo step
   3.

`options_app.db` (path set by `DB_PATH` in the unit file) holds order
history, the paper account balance, and E*TRADE tokens -- back it up like
any other stateful data, and don't commit it to git (it isn't tracked).

## 8. Adding rginvestor67.com as the main site

Since `rginvestor67.com` is unused, point it at the same backend service
(no second deployment needed -- one systemd service, two domains):

1. **Websites -> Create Website** for `rginvestor67.com` in CyberPanel.
2. Repeat step 3 above (External App + Proxy Context, or the Rewrite
   Rules UI) for this new virtual host, pointing at the same
   `127.0.0.1:8005`.
3. Issue SSL for `rginvestor67.com` the same way (step 4).
4. Both `https://rginvestor67.com` and `https://options.rginvestor67.com`
   now serve the identical app/session store -- logging in on one does not
   log you into the other (cookies are per-domain), but the data
   (orders, positions, paper account) is shared since it's the same
   backend and database.

## Updating the deployed code later

```bash
sudo -iu optionsapp
cd options-app && git pull
cd backend && source .venv/bin/activate && pip install -r requirements.txt && deactivate
exit
sudo systemctl restart options-app
```
