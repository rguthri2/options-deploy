# Deploying to a CyberPanel VPS

CyberPanel runs on OpenLiteSpeed (OLS), which doesn't have a first-class
"Python app" type the way it does PHP. The reliable pattern is: run the app
as its own systemd service on localhost, then have OLS reverse-proxy to it.
This also means the app's outbound calls to Yahoo Finance happen from the
VPS's own network path, which is a genuinely different egress route than any
Claude Code Remote sandbox -- worth testing here specifically because those
sandboxes block Yahoo Finance by policy and a plain VPS very likely does not.

Replace `YOUR_DOMAIN_OR_IP` below with your actual domain (or the bare IP,
`70.36.114.244`, if you're testing without a domain/website entry yet).

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
(paths already match the `optionsapp` user/home from step 1 -- edit them if
you used a different user or clone path).

```bash
sudo cp /home/optionsapp/options-app/backend/deploy/options-app.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now options-app
sudo systemctl status options-app --no-pager
```

Sanity-check it's actually up before touching OLS:

```bash
curl -s http://127.0.0.1:8000/api/health
# {"status":"ok","data_provider":"yfinance"}
```

If that fails, check logs with `sudo journalctl -u options-app -n 100 --no-pager`.

## 3. Point OpenLiteSpeed at it

If you already created a website for this in CyberPanel (Websites -> Create
Website), use its domain below. Otherwise you can proxy from the default
listener using the WebAdmin console directly against the IP.

**Via CyberPanel UI** (Websites -> List Websites -> Manage -> your domain):

1. Go to the **Rewrite Rules** tab (some CyberPanel versions surface this
   proxy setup under **Configurations** instead) and enable the built-in
   reverse-proxy option, pointing it at `127.0.0.1:8000`. If your version's
   UI doesn't expose this directly, use the OLS WebAdmin console fallback
   below -- it always works regardless of CyberPanel UI version.

**Via OpenLiteSpeed WebAdmin console** (always available at
`https://YOUR_DOMAIN_OR_IP:7080`, default user `admin`, password set during
CyberPanel install):

1. **Server Configuration -> External App -> Add**: type `Web Server`,
   name it `optionsapp`, address `127.0.0.1:8000`, max connections `35`.
2. **Virtual Hosts -> (your site) -> Context -> Add**: type `Proxy`,
   URI `/`, Web Server = `optionsapp`.
3. Graceful restart OLS: **Actions -> Graceful Restart** (top right), or
   `sudo systemctl reload lsws` from the shell.

## 4. SSL

Handled entirely by CyberPanel as usual (Websites -> your domain -> SSL ->
Issue SSL / Let's Encrypt). No app-side changes needed -- OLS terminates TLS
and proxies plain HTTP to `127.0.0.1:8000`.

## 5. Firewall

Only 80/443 (and CyberPanel's own admin ports) need to be open publicly.
Port 8000 should stay bound to `127.0.0.1` (the systemd unit already does
this) so it's never reachable from outside the box.

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
is reachable at `https://YOUR_DOMAIN_OR_IP/api/scan?tickers=AAPL&strategy=covered_call`
and can be checked from any machine with a browser or curl, Claude included.

## Updating the deployed code later

```bash
sudo -iu optionsapp
cd options-app && git pull
cd backend && source .venv/bin/activate && pip install -r requirements.txt && deactivate
exit
sudo systemctl restart options-app
```
