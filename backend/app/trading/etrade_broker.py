"""E*TRADE broker integration: OAuth1 3-legged auth + equity order placement.

READ BEFORE USING WITH REAL MONEY:
  - This was implemented against E*TRADE's publicly documented API but could
    NOT be tested end-to-end -- the sandboxed environment this was built in
    has no outbound network access to etrade.com at all, sandbox or prod.
    Every response shape below is best-effort from documentation, not a
    verified integration. Test extensively against E*TRADE's SANDBOX
    (ETRADE_SANDBOX=true, the default) with tiny orders before ever setting
    ETRADE_SANDBOX=false or LIVE_TRADING_ENABLED=true.
  - Only single-leg EQUITY orders are implemented (market/limit/stop/
    stop-limit/trailing-stop, buy/sell, day or GTC). Options order placement
    is NOT implemented: E*TRADE's options order schema (OCC symbology,
    multi-leg spreads) is materially more complex, and higher-risk to get
    wrong with real money -- out of scope for this pass. Placing an option
    OrderRequest raises BrokerError.
  - The stop/stop-limit/trailing-stop field names below (priceType values,
    stopPrice carrying the trail amount/percent for a trailing stop) are
    this build's best-effort reading of E*TRADE's documented order schema,
    with the same "never tested end-to-end" caveat as everything else in
    this file -- verify against E*TRADE's sandbox before trusting it with
    real money. A stop-type order is recorded "pending" (not "filled") once
    placed, since E*TRADE itself hasn't filled it yet either; this app does
    not currently poll E*TRADE for a later fill, so its status here can go
    stale until the next full order sync (not yet implemented).
  - Every E*TRADE response is parsed defensively: an unexpected shape
    raises BrokerError with the raw response body rather than guessing,
    so failures are debuggable instead of silently wrong.
  - Access tokens expire at midnight US Eastern and go inactive after 2
    hours idle; there is no automatic renewal here. If calls start failing
    with an auth error, re-run the authorization flow via
    /api/broker/etrade/auth-url.
"""
from __future__ import annotations

import time

from requests_oauthlib import OAuth1Session

from .. import db
from ..config import get_settings
from .base import Broker, BrokerError
from .models import AccountSummary, OrderRequest, OrderResult, Position
from .serializers import row_to_order_result

_OAUTH_BASE = "https://api.etrade.com"  # OAuth token endpoints live here regardless of sandbox/prod
_AUTHORIZE_BASE = "https://us.etrade.com/e/t/etws/authorize"


def _raise_for_status(resp) -> None:
    if resp.status_code >= 400:
        raise BrokerError(f"E*TRADE API error {resp.status_code}: {resp.text[:1000]}")


def _map_order_pricing(request: OrderRequest) -> tuple:
    """Translate our OrderRequest fields into E*TRADE's priceType/orderTerm/
    price fields. Pulled out as a pure function so the mapping can be unit
    tested without a live session -- see the module docstring's caveat that
    this mapping itself is unverified against real E*TRADE data."""
    price_type = {
        "market": "MARKET",
        "limit": "LIMIT",
        "stop": "STOP",
        "stop_limit": "STOP_LIMIT",
        "trailing_stop": "TRAILING_STOP_CNST" if request.trail_amount else "TRAILING_STOP_PRCT",
    }[request.order_type]
    order_term = {"day": "GOOD_FOR_DAY", "gtc": "GOOD_TILL_CANCEL"}[request.time_in_force]

    price_fields: dict = {}
    if request.order_type in ("limit", "stop_limit"):
        price_fields["limitPrice"] = request.limit_price
    if request.order_type in ("stop", "stop_limit"):
        price_fields["stopPrice"] = request.stop_price
    if request.order_type == "trailing_stop":
        # See the module docstring: this field carries the trail
        # amount/percent itself for a TRAILING_STOP_CNST/PRCT order, per
        # this build's (unverified) reading of E*TRADE's schema.
        price_fields["stopPrice"] = request.trail_amount or request.trail_percent

    return price_type, order_term, price_fields


class ETradeBroker(Broker):
    name = "etrade"

    def __init__(self):
        settings = get_settings()
        if not settings.etrade_consumer_key or not settings.etrade_consumer_secret:
            raise BrokerError(
                "E*TRADE is not configured. Set ETRADE_CONSUMER_KEY and ETRADE_CONSUMER_SECRET "
                "(from your E*TRADE developer app) first."
            )
        self._consumer_key = settings.etrade_consumer_key
        self._consumer_secret = settings.etrade_consumer_secret
        self._api_base = "https://apisb.etrade.com" if settings.etrade_sandbox else "https://api.etrade.com"

        tokens = db.get_etrade_tokens()
        if tokens is None or not tokens["oauth_token"]:
            raise BrokerError(
                "No E*TRADE access token on file. Complete authorization first: "
                "GET /api/broker/etrade/auth-url, visit the URL, then POST the verifier code "
                "to /api/broker/etrade/complete-auth."
            )
        self._access_token = tokens["oauth_token"]
        self._access_token_secret = tokens["oauth_token_secret"]
        self._account_id_key = tokens["account_id_key"]

    def _session(self) -> OAuth1Session:
        return OAuth1Session(
            self._consumer_key,
            client_secret=self._consumer_secret,
            resource_owner_key=self._access_token,
            resource_owner_secret=self._access_token_secret,
        )

    # --- OAuth setup: called from API routes, not part of the Broker interface ---

    @staticmethod
    def start_authorization() -> tuple[str, str, str]:
        """Return (authorize_url, request_token, request_token_secret).

        The caller (an API route) must hand the request token pair back to
        the browser (e.g. in the response body) so it can be resubmitted to
        complete_authorization() once the user has the verifier code --
        E*TRADE's request tokens are single-use and not something to
        persist server-side across the redirect.
        """
        settings = get_settings()
        if not settings.etrade_consumer_key or not settings.etrade_consumer_secret:
            raise BrokerError(
                "E*TRADE is not configured. Set ETRADE_CONSUMER_KEY and ETRADE_CONSUMER_SECRET "
                "(from your E*TRADE developer app) first."
            )
        oauth = OAuth1Session(
            settings.etrade_consumer_key, client_secret=settings.etrade_consumer_secret, callback_uri="oob"
        )
        try:
            tokens = oauth.fetch_request_token(f"{_OAUTH_BASE}/oauth/request_token")
        except Exception as exc:  # noqa: BLE001 - surface whatever requests_oauthlib/E*TRADE returned
            raise BrokerError(f"Failed to fetch E*TRADE request token: {exc}") from exc
        request_token = tokens["oauth_token"]
        request_token_secret = tokens["oauth_token_secret"]
        authorize_url = f"{_AUTHORIZE_BASE}?key={settings.etrade_consumer_key}&token={request_token}"
        return authorize_url, request_token, request_token_secret

    @staticmethod
    def complete_authorization(request_token: str, request_token_secret: str, verifier: str) -> None:
        """Exchange the request token + verifier code for a real access token, and persist it."""
        settings = get_settings()
        if not settings.etrade_consumer_key or not settings.etrade_consumer_secret:
            raise BrokerError(
                "E*TRADE is not configured. Set ETRADE_CONSUMER_KEY and ETRADE_CONSUMER_SECRET "
                "(from your E*TRADE developer app) first."
            )
        oauth = OAuth1Session(
            settings.etrade_consumer_key,
            client_secret=settings.etrade_consumer_secret,
            resource_owner_key=request_token,
            resource_owner_secret=request_token_secret,
            verifier=verifier,
        )
        try:
            tokens = oauth.fetch_access_token(f"{_OAUTH_BASE}/oauth/access_token")
        except Exception as exc:  # noqa: BLE001
            raise BrokerError(f"Failed to exchange E*TRADE verifier code: {exc}") from exc
        db.save_etrade_tokens(tokens["oauth_token"], tokens["oauth_token_secret"])

    def _ensure_account(self) -> str:
        if self._account_id_key:
            return self._account_id_key
        resp = self._session().get(f"{self._api_base}/v1/accounts/list.json")
        _raise_for_status(resp)
        try:
            accounts = resp.json()["AccountListResponse"]["Accounts"]["Account"]
            account_id_key = accounts[0]["accountIdKey"]
        except (KeyError, IndexError, TypeError) as exc:
            raise BrokerError(f"Unexpected E*TRADE accounts response: {resp.text[:500]}") from exc
        db.save_etrade_tokens(self._access_token, self._access_token_secret, account_id_key)
        self._account_id_key = account_id_key
        return account_id_key

    def place_order(self, request: OrderRequest) -> OrderResult:
        if request.asset_type != "equity":
            raise BrokerError(
                "Options order placement is not implemented for E*TRADE in this build -- "
                "only single-leg equity orders are supported. See etrade_broker.py docstring."
            )
        error = request.validate()
        if error:
            raise BrokerError(error)

        account_id_key = self._ensure_account()
        order_id = db.insert_order(
            broker=self.name,
            symbol=request.symbol.upper(),
            asset_type=request.asset_type,
            option_type=None,
            strike=None,
            expiration=None,
            side=request.side,
            quantity=request.quantity,
            order_type=request.order_type,
            limit_price=request.limit_price,
            stop_price=request.stop_price,
            trail_amount=request.trail_amount,
            trail_percent=request.trail_percent,
            time_in_force=request.time_in_force,
            status="pending",
            rationale=request.rationale,
        )

        def reject(reason: str) -> OrderResult:
            db.update_order(order_id, status="rejected", rejection_reason=reason)
            return row_to_order_result(db.get_order(order_id))

        price_type, order_term, price_fields = _map_order_pricing(request)

        preview_body = {
            "orderType": "EQ",
            "clientOrderId": f"opt{order_id}{int(time.time())}",
            "Order": [
                {
                    "allOrNone": "false",
                    "priceType": price_type,
                    "orderTerm": order_term,
                    "marketSession": "REGULAR",
                    **price_fields,
                    "Instrument": [
                        {
                            "Product": {"securityType": "EQ", "symbol": request.symbol.upper()},
                            "orderAction": request.side.upper(),
                            "quantityType": "QUANTITY",
                            "quantity": request.quantity,
                        }
                    ],
                }
            ],
        }

        session = self._session()
        try:
            preview_resp = session.post(
                f"{self._api_base}/v1/accounts/{account_id_key}/orders/preview.json",
                json={"PreviewOrderRequest": preview_body},
            )
            _raise_for_status(preview_resp)
            preview_id = preview_resp.json()["PreviewOrderResponse"]["PreviewIds"][0]["previewId"]

            place_body = {**preview_body, "PreviewIds": [{"previewId": preview_id}]}
            place_resp = session.post(
                f"{self._api_base}/v1/accounts/{account_id_key}/orders/place.json",
                json={"PlaceOrderRequest": place_body},
            )
            _raise_for_status(place_resp)
            broker_order_id = str(place_resp.json()["PlaceOrderResponse"]["OrderIds"][0]["orderId"])
        except BrokerError as exc:
            return reject(str(exc))
        except (KeyError, IndexError, TypeError) as exc:
            return reject(f"Unexpected E*TRADE order response shape: {exc}")

        if request.order_type in ("stop", "stop_limit", "trailing_stop"):
            # Accepted by E*TRADE, but not filled -- a stop-type order only
            # fills once the market reaches its trigger, which happens on
            # E*TRADE's own systems, not synchronously in this call. There is
            # no polling here (yet) to learn when that later happens; see the
            # module docstring.
            db.update_order(order_id, status="pending", broker_order_id=broker_order_id)
        else:
            db.update_order(order_id, status="filled", broker_order_id=broker_order_id, filled_at=db.now_iso())
        return row_to_order_result(db.get_order(order_id))

    def get_account(self) -> AccountSummary:
        account_id_key = self._ensure_account()
        resp = self._session().get(
            f"{self._api_base}/v1/accounts/{account_id_key}/balance.json",
            params={"instType": "BROKERAGE", "realTimeNAV": "true"},
        )
        _raise_for_status(resp)
        try:
            computed = resp.json()["BalanceResponse"]["Computed"]
            cash = float(computed.get("cashAvailableForInvestment", 0.0))
            total_value = float(computed["RealTimeValues"]["totalAccountValue"])
        except (KeyError, TypeError) as exc:
            raise BrokerError(f"Unexpected E*TRADE balance response: {resp.text[:500]}") from exc

        positions = self.get_positions()
        return AccountSummary(
            broker=self.name,
            cash_balance=cash,
            positions_value=total_value - cash,
            portfolio_value=total_value,
            positions=positions,
        )

    def get_positions(self) -> list[Position]:
        account_id_key = self._ensure_account()
        resp = self._session().get(f"{self._api_base}/v1/accounts/{account_id_key}/portfolio.json")
        if resp.status_code == 204:
            return []
        _raise_for_status(resp)
        try:
            account_portfolios = resp.json().get("PortfolioResponse", {}).get("AccountPortfolio", [])
        except ValueError as exc:
            raise BrokerError(f"Unexpected E*TRADE portfolio response: {resp.text[:500]}") from exc

        positions: list[Position] = []
        for portfolio in account_portfolios:
            for pos in portfolio.get("Position", []):
                quantity = int(pos.get("quantity", 0))
                positions.append(
                    Position(
                        symbol=pos.get("symbolDescription") or pos.get("Product", {}).get("symbol", ""),
                        asset_type="equity" if pos.get("Product", {}).get("securityType") == "EQ" else "option",
                        quantity=quantity,
                        avg_cost=float(pos.get("pricePaid", 0.0)),
                        current_price=float(pos.get("marketValue", 0.0)) / max(quantity, 1),
                    )
                )
        return positions

    def list_orders(self) -> list[OrderResult]:
        return [row_to_order_result(row) for row in db.list_orders(self.name)]

    def cancel_order(self, order_id: int) -> OrderResult:
        row = db.get_order(order_id)
        if row is None or row["broker"] != self.name:
            raise BrokerError(f"No E*TRADE order with id {order_id}.")
        if row["status"] != "filled" or not row["broker_order_id"]:
            raise BrokerError(f"Order {order_id} has no broker order id to cancel.")
        account_id_key = self._ensure_account()
        resp = self._session().put(
            f"{self._api_base}/v1/accounts/{account_id_key}/orders/cancel.json",
            json={"CancelOrderRequest": {"orderId": row["broker_order_id"]}},
        )
        _raise_for_status(resp)
        db.update_order(order_id, status="canceled")
        return row_to_order_result(db.get_order(order_id))
