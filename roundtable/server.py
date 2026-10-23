"""Stock Roundtable server: MCP (streamable HTTP) + REST + web board on one port.

Run:  python -m roundtable.server
MCP:  http://<host>:8787/mcp              with header  Authorization: Bearer <ROUNDTABLE_TOKEN>
      http://<host>:8787/key/<token>/mcp  for clients that cannot send headers
UI:   http://<host>:8787/?token=<token>
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response

from . import config, db, protocol, service, ui
from .service import RoundtableError

# ----------------------------------------------------------------- MCP server

mcp = MCPServer(
    name="stock_roundtable_mcp",
    title="Stock Roundtable",
    instructions=(
        "Shared desk for an options trading roundtable. Call roundtable_protocol once to learn the rules "
        "and roundtable_state at the start of every session to read the room. Authors are claude (strategist), "
        "gpt (executor), critic (local model) and shawn (owner)."
    ),
)

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)


def _run(fn, *args, **kwargs) -> str:
    """Open a session, run a service function, return JSON text or a clear error string."""
    with db.session() as s:
        try:
            return json.dumps(fn(s, *args, **kwargs), indent=2, default=str)
        except RoundtableError as e:
            return f"Error: {e}"


class Leg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    side: str = Field(description="buy or sell")
    option_type: str = Field(description="call or put")
    strike: float = Field(description="Strike price, e.g. 105")
    occ_symbol: str | None = Field(default=None, description="Optional OCC symbol, e.g. UAL261113C00105000")
    rh_instrument_id: str | None = Field(default=None, description="Optional Robinhood option instrument UUID")


@mcp.tool(name="roundtable_protocol", annotations=READ)
def roundtable_protocol() -> str:
    """Return the roundtable rules: seats, ticket lifecycle, pricing and recording rules. Read once per session."""
    return protocol.PROTOCOL


@mcp.tool(name="roundtable_state", annotations=READ)
def roundtable_state(limit_messages: int = Field(default=30, ge=1, le=200)) -> str:
    """Read the room in one call: P&L summary, tickets ready for execution, open positions, recent thread.
    Call this first in every session before posting or acting."""
    return _run(service.state, limit_messages)


@mcp.tool(name="roundtable_read_thread", annotations=READ)
def roundtable_read_thread(
    limit: int = Field(default=50, ge=1, le=500),
    since_id: int | None = Field(default=None, description="Only messages with id greater than this"),
    ticket_id: str | None = Field(default=None, description="Only messages attached to this ticket, e.g. T-001"),
    author: str | None = Field(default=None, description="Only messages from this author"),
) -> str:
    """Read the discussion thread in chronological order. Returns JSON list of {id, created_at, author, kind, ticket_id, text}."""
    return _run(service.read_thread, limit, since_id, ticket_id, author)


@mcp.tool(name="roundtable_post_message", annotations=WRITE)
def roundtable_post_message(
    author: str = Field(description="Who is speaking: claude, gpt, critic or shawn"),
    text: str = Field(description="The message"),
    kind: str = Field(default="note", description="note | proposal | vote | decision | alert | critique | execution"),
    ticket_id: str | None = Field(default=None, description="Attach to a ticket, e.g. T-001"),
) -> str:
    """Post a message to the thread. Use kind=vote for agree/disagree, decision for calls, alert for urgent risks."""
    return _run(service.post_message, author, text, kind, ticket_id)


@mcp.tool(name="roundtable_create_ticket", annotations=WRITE)
def roundtable_create_ticket(
    author: str = Field(description="Who proposes it, normally claude"),
    underlying: str = Field(description="Ticker, e.g. UAL"),
    strategy: str = Field(description="e.g. bear_call_credit_spread, bear_put_debit_spread, long_put, long_call"),
    direction: str = Field(description="bearish | bullish | neutral"),
    entry_type: str = Field(description="credit (you receive the net) or debit (you pay the net)"),
    expiry: str = Field(description="YYYY-MM-DD"),
    legs: list[Leg] = Field(description="Legs in order; a vertical spread has two"),
    contracts: int = Field(ge=1, description="Number of spreads (each leg fills this many contracts)"),
    limit_price: float = Field(gt=0, description="Net limit per share for the whole spread, positive"),
    fallback_price: float | None = Field(default=None, description="Second try if the first limit does not fill"),
    floor_price: float | None = Field(default=None, description="Worst acceptable net; never go past this"),
    breakeven_px: float | None = Field(default=None),
    profit_target_usd: float | None = Field(default=None, description="Close when unrealized P&L reaches this"),
    stop_loss_usd: float | None = Field(default=None, description="Negative number; close when P&L falls to this"),
    max_loss_usd: float | None = Field(default=None, description="Computed for 2-leg verticals if omitted"),
    max_gain_usd: float | None = Field(default=None, description="Computed for 2-leg verticals if omitted"),
    underlying_px: float | None = Field(default=None, description="Stock price when the ticket was written"),
    exit_rules: str = Field(default="", description="Plain-English exit plan"),
    rationale: str = Field(default="", description="Why this trade, with the evidence"),
    thesis_tag: str = Field(default="", description="Groups trades by thesis, e.g. airline_fuel_cost_2026Q4"),
    catalyst: str = Field(default=""),
    status: str = Field(default="proposed", description="proposed (discuss first) or ready (gpt may execute)"),
    notes: str = Field(default=""),
) -> str:
    """Create a trade ticket (one row per strategy-level trade). Returns the ticket as JSON including its id."""
    data = dict(
        underlying=underlying, strategy=strategy, direction=direction, entry_type=entry_type, expiry=expiry,
        legs=[l.model_dump(exclude_none=True) for l in legs], contracts=contracts, limit_price=limit_price,
        fallback_price=fallback_price, floor_price=floor_price, breakeven_px=breakeven_px,
        profit_target_usd=profit_target_usd, stop_loss_usd=stop_loss_usd, max_loss_usd=max_loss_usd,
        max_gain_usd=max_gain_usd, underlying_px=underlying_px, exit_rules=exit_rules, rationale=rationale,
        thesis_tag=thesis_tag, catalyst=catalyst, status=status, notes=notes,
    )
    return _run(service.create_ticket, author, data)


@mcp.tool(name="roundtable_list_tickets", annotations=READ)
def roundtable_list_tickets(
    status: str | None = Field(default=None, description="Comma-separated filter, e.g. ready,close_ready. Omit for all."),
    limit: int = Field(default=50, ge=1, le=500),
) -> str:
    """List tickets newest first, optionally filtered by status."""
    return _run(service.list_tickets, status, limit)


@mcp.tool(name="roundtable_get_ticket", annotations=READ)
def roundtable_get_ticket(ticket_id: str = Field(description="e.g. T-001")) -> str:
    """Get one ticket with its fills."""
    def _get(s, tid):
        return service.ticket_to_dict(service.get_ticket(s, tid), with_fills=True)
    return _run(_get, ticket_id)


@mcp.tool(name="roundtable_set_status", annotations=WRITE)
def roundtable_set_status(
    ticket_id: str = Field(description="e.g. T-001"),
    author: str = Field(description="Who decides"),
    status: str = Field(description="proposed | ready | placed | close_ready | rejected | cancelled | expired"),
    reason: str = Field(default="", description="Why, in one line"),
) -> str:
    """Move a ticket along its lifecycle. open and closed are set by roundtable_record_execution, not here.
    gpt sets placed right after submitting an order to Robinhood."""
    return _run(service.set_status, ticket_id, author, status, reason)


@mcp.tool(name="roundtable_record_execution", annotations=WRITE)
def roundtable_record_execution(
    ticket_id: str = Field(description="e.g. T-001"),
    author: str = Field(description="Who executed, normally gpt"),
    phase: str = Field(description="entry (opening order filled) or exit (closing order filled)"),
    order_id: str = Field(description="Robinhood order UUID"),
    filled_at: str = Field(description="Fill time in ISO 8601 UTC, e.g. 2026-10-23T17:05:12Z"),
    net_price: float = Field(ge=0, description="Net per share for the whole spread, positive (0 if expired worthless)"),
    fees_usd: float = Field(default=0.0, ge=0),
    leg_prices: list[float] | None = Field(default=None, description="Per-leg fill prices in ticket leg order"),
    underlying_px: float | None = Field(default=None, description="Stock price at the fill"),
    close_reason: str = Field(default="", description="exit only: profit_target | stop_loss | expiry | manual"),
) -> str:
    """Record a filled order. phase=entry moves the ticket to open; phase=exit moves it to closed and computes P&L.
    This is the trade dataset: every fill must be recorded here."""
    return _run(service.record_execution, ticket_id, author, phase, order_id, filled_at, net_price, fees_usd,
                leg_prices, underlying_px, close_reason)


@mcp.tool(name="roundtable_update_ticket", annotations=WRITE)
def roundtable_update_ticket(
    ticket_id: str = Field(description="e.g. T-001"),
    author: str = Field(description="Who edits"),
    fields: dict[str, Any] = Field(description="Fields to change, e.g. {\"current_mark_net\": 0.62, \"exit_rules\": \"...\"}"),
) -> str:
    """Edit ticket fields: limit/fallback/floor prices, exit rules, targets, notes, current_mark_net (drives unrealized P&L)."""
    return _run(service.update_fields, ticket_id, author, fields)


@mcp.tool(name="roundtable_record_snapshot", annotations=WRITE)
def roundtable_record_snapshot(
    author: str = Field(description="Who captured it"),
    kind: str = Field(description="quotes | positions | portfolio | pnl | orders | other"),
    payload: dict[str, Any] | list[Any] = Field(description="The data as JSON (quotes, positions, greeks...)"),
    note: str = Field(default="", description="What this is and when it was pulled"),
) -> str:
    """Store a market or account snapshot for the dataset (option quotes with greeks, positions, buying power)."""
    return _run(service.record_snapshot, author, kind, payload, note)


@mcp.tool(name="roundtable_list_snapshots", annotations=READ)
def roundtable_list_snapshots(
    kind: str | None = Field(default=None),
    limit: int = Field(default=20, ge=1, le=200),
    with_payload: bool = Field(default=False, description="Include the stored JSON (can be large)"),
) -> str:
    """List stored snapshots newest first."""
    return _run(service.list_snapshots, kind, limit, with_payload)


@mcp.tool(name="roundtable_pnl_summary", annotations=READ)
def roundtable_pnl_summary() -> str:
    """Closed trades, win rate, realized and unrealized P&L, open risk, tickets by status."""
    return _run(service.pnl_summary)


@mcp.tool(name="roundtable_export", annotations=READ)
def roundtable_export(
    table: str = Field(description="tickets | fills | messages | snapshots"),
    format: str = Field(default="json", description="json or csv"),
    limit: int = Field(default=5000, ge=1, le=100000),
) -> str:
    """Export a table for datasets."""
    with db.session() as s:
        try:
            rows = service.export_rows(s, table, limit)
        except RoundtableError as e:
            return f"Error: {e}"
    return service.rows_to_csv(rows) if format.lower() == "csv" else json.dumps(rows, indent=2, default=str)


# ----------------------------------------------------------------- REST + UI


def _json_error(e: Exception, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": str(e)}, status_code=status)


@mcp.custom_route("/", methods=["GET"], include_in_schema=False)
async def board(_: Request) -> Response:
    return HTMLResponse(ui.page(config.DISPLAY_TZ))


@mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
async def health(_: Request) -> Response:
    return JSONResponse({"ok": True, "service": "stock-roundtable"})


@mcp.custom_route("/api/protocol", methods=["GET"], include_in_schema=False)
async def api_protocol(_: Request) -> Response:
    return PlainTextResponse(protocol.PROTOCOL)


@mcp.custom_route("/api/state", methods=["GET"], include_in_schema=False)
async def api_state(_: Request) -> Response:
    with db.session() as s:
        return JSONResponse(service.state(s))


@mcp.custom_route("/api/messages", methods=["POST"], include_in_schema=False)
async def api_post_message(request: Request) -> Response:
    body = await request.json()
    with db.session() as s:
        try:
            return JSONResponse(service.post_message(s, body.get("author", ""), body.get("text", ""),
                                                     body.get("kind", "note"), body.get("ticket_id")))
        except RoundtableError as e:
            return _json_error(e)


@mcp.custom_route("/api/tickets/{ticket_id}/status", methods=["POST"], include_in_schema=False)
async def api_set_status(request: Request) -> Response:
    body = await request.json()
    with db.session() as s:
        try:
            return JSONResponse(service.set_status(s, request.path_params["ticket_id"], body.get("author", ""),
                                                   body.get("status", ""), body.get("reason", "")))
        except RoundtableError as e:
            return _json_error(e)


@mcp.custom_route("/api/export/{table}.csv", methods=["GET"], include_in_schema=False)
async def api_export(request: Request) -> Response:
    with db.session() as s:
        try:
            rows = service.export_rows(s, request.path_params["table"])
        except RoundtableError as e:
            return _json_error(e)
    return PlainTextResponse(service.rows_to_csv(rows), media_type="text/csv")


# ----------------------------------------------------------------- auth wrapper


class TokenAuth:
    """ASGI wrapper. Accepts `Authorization: Bearer <token>` or a `/key/<token>/...` path prefix.
    Strips an optional base path (ROUNDTABLE_BASE_PATH) left by a reverse proxy.
    The board page itself (/) and /health are public; everything else needs the token."""

    PUBLIC = {"/", "/health"}

    def __init__(self, app, token: str, base_path: str = "", token_segment: str = "key"):
        self.app = app
        self.token = token
        self.base_path = base_path.rstrip("/")
        self.prefix = f"/{token_segment}/{token}"

    def _rewrite(self, scope, new_path: str):
        scope = dict(scope)
        scope["path"] = new_path or "/"
        scope["raw_path"] = (new_path or "/").encode()
        return scope

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if self.base_path and (path == self.base_path or path.startswith(self.base_path + "/")):
            path = path[len(self.base_path):] or "/"
            scope = self._rewrite(scope, path)
        if path == self.prefix or path.startswith(self.prefix + "/"):
            return await self.app(self._rewrite(scope, path[len(self.prefix):]), receive, send)
        if path in self.PUBLIC:
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "")
        if auth.lower().startswith("bearer ") and auth[7:].strip() == self.token:
            return await self.app(scope, receive, send)
        response = JSONResponse({"error": "unauthorized: send Authorization: Bearer <ROUNDTABLE_TOKEN> or use /key/<token>/..."},
                                status_code=401)
        return await response(scope, receive, send)


def build_app():
    db.init_db()
    if config.SEED_ON_START:
        from . import seed
        seed.run()
    token = config.require_token()
    inner = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    return TokenAuth(inner, token, config.BASE_PATH, config.TOKEN_PATH_SEGMENT)


def main() -> None:
    import uvicorn

    app = build_app()
    base = config.PUBLIC_URL + config.BASE_PATH
    print(f"[roundtable] board  {base}/?token={config.ROUNDTABLE_TOKEN}")
    print(f"[roundtable] mcp    {base}/mcp  (Bearer)  or  {base}/{config.TOKEN_PATH_SEGMENT}/{config.ROUNDTABLE_TOKEN}/mcp")
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="info")


if __name__ == "__main__":
    main()
