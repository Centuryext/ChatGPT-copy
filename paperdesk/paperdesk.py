"""PaperDesk: a simulated options broker as an MCP server, for testing and training local models.
No real money, no real broker. Run: python paperdesk.py  (streamable HTTP on :8899/mcp) or --stdio.
Env: PAPERDESK_DB, PAPERDESK_TICKET (ticket json), PAPERDESK_SCENARIO (quotes json), PAPERDESK_CASH.
"""
import json, os, random, sqlite3, sys, time, uuid
from mcp.server.fastmcp import FastMCP

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("PAPERDESK_DB", os.path.join(HERE, "paperdesk.db"))
TICKET = os.environ.get("PAPERDESK_TICKET", os.path.join(HERE, "ticket_T001.json"))
SCENARIO = os.environ.get("PAPERDESK_SCENARIO", os.path.join(HERE, "scenario_ual.json"))
START_CASH = float(os.environ.get("PAPERDESK_CASH", "3000"))
FEE_PER_CONTRACT = 0.04  # per contract per leg-ish, rough

mcp = FastMCP("paperdesk", host="0.0.0.0", port=int(os.environ.get("PAPERDESK_PORT", "8899")))


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init():
    c = db()
    c.executescript("""
    create table if not exists acct(k text primary key, v text);
    create table if not exists orders(id text primary key, ts real, symbol text, qty int, limit_price real,
        order_type text, tif text, legs text, status text, fill_price real, fill_ts real, reviewed_id text, collateral real, fees real);
    create table if not exists reviews(id text primary key, ts real, symbol text, qty int, limit_price real, legs text, collateral real, fees real, alerts text, otype text);
    create table if not exists positions(id text primary key, symbol text, qty int, legs text, entry_credit real, collateral real, status text);
    create table if not exists log(ts real, tool text, args text, result text);
    """)
    if not c.execute("select 1 from acct where k='cash'").fetchone():
        c.execute("insert into acct values('cash',?)", (str(START_CASH),))
        c.execute("insert into acct values('tick','0')")
    c.commit(); c.close()


def load(path):
    with open(path) as f:
        return json.load(f)


def cash():
    c = db(); v = float(c.execute("select v from acct where k='cash'").fetchone()[0]); c.close(); return v


def setcash(v):
    c = db(); c.execute("update acct set v=? where k='cash'", (str(round(v, 2)),)); c.commit(); c.close()


def logcall(tool, args, result):
    c = db(); c.execute("insert into log values(?,?,?,?)", (time.time(), tool, json.dumps(args), json.dumps(result)[:4000])); c.commit(); c.close()
    return result


def tick():
    c = db(); t = int(c.execute("select v from acct where k='tick'").fetchone()[0])
    c.execute("update acct set v=? where k='tick'", (str(t + 1),)); c.commit(); c.close(); return t


def quote_for(occ, t=None):
    sc = load(SCENARIO)
    if t is None:
        c = db(); t = int(c.execute("select v from acct where k='tick'").fetchone()[0]); c.close()
    paths = sc["options"][occ]
    row = paths[min(t, len(paths) - 1)]
    return {"occ_symbol": occ, "bid": row[0], "ask": row[1], "mark": round((row[0] + row[1]) / 2, 3)}


def underlying_px(t=None):
    sc = load(SCENARIO)
    if t is None:
        c = db(); t = int(c.execute("select v from acct where k='tick'").fetchone()[0]); c.close()
    p = sc["underlying"]
    return p[min(t, len(p) - 1)]


def spread_calc(legs, qty):
    """Net credit(+)/debit(-) at bid/ask (natural) and mid, plus max loss for 2-leg vertical."""
    nat = mid = 0.0
    for L in legs:
        q = quote_for(L["occ_symbol"])
        sign = 1 if L["side"] == "sell" else -1
        nat += sign * (q["bid"] if L["side"] == "sell" else q["ask"])
        mid += sign * q["mark"]
    strikes = [L["strike"] for L in legs]
    width = max(strikes) - min(strikes)
    return round(nat, 3), round(mid, 3), width


@mcp.tool()
def get_accounts() -> dict:
    """Paper account: cash, buying power, open positions count."""
    c = db(); n = c.execute("select count(*) from positions where status='open'").fetchone()[0]; c.close()
    return logcall("get_accounts", {}, {"account": "PAPER", "cash": cash(), "buying_power": cash(), "open_positions": n,
                                        "trade_approval": "OFF", "note": "SIMULATED. No real money."})


@mcp.tool()
def get_equity_quotes(symbol: str) -> dict:
    """Underlying quote (simulated)."""
    return logcall("get_equity_quotes", {"symbol": symbol}, {"symbol": symbol, "last": underlying_px()})


@mcp.tool()
def get_option_quotes(occ_symbols: list[str]) -> dict:
    """Bid/ask/mark for OCC symbols (e.g. UAL261113C00105000). Time advances one step per call to this tool."""
    out = [quote_for(s) for s in occ_symbols]
    tick()
    return logcall("get_option_quotes", {"occ": occ_symbols}, {"quotes": out, "underlying": underlying_px()})


@mcp.tool()
def review_option_order(symbol: str, quantity: int, limit_price: float, order_type: str, time_in_force: str, legs: list[dict]) -> dict:
    """Pre-trade review. legs: [{side:'sell'|'buy', option_type:'call'|'put', strike:float, occ_symbol:str}]. Returns review_id, collateral, fees, alerts. Required before place_option_order."""
    alerts = []
    nat, mid, width = spread_calc(legs, quantity)
    if order_type.lower() != "limit":
        alerts.append("MARKET_ORDER_ON_WIDE_SPREAD")
    if abs(nat - mid) > 0.3:
        alerts.append(f"OPTION_WIDE_BID_ASK_SPREAD natural={nat} mid={mid}")
    credit = limit_price if nat + mid > 0 else -limit_price
    collateral = round(max(width - (limit_price if mid > 0 else 0), 0) * 100 * quantity, 2)
    fees = round(FEE_PER_CONTRACT * quantity * len(legs), 2)
    rid = "rev_" + uuid.uuid4().hex[:8]
    c = db()
    c.execute("insert into reviews values(?,?,?,?,?,?,?,?,?,?)", (rid, time.time(), symbol, quantity, limit_price, json.dumps(legs), collateral, fees, json.dumps(alerts), order_type.lower()))
    c.commit(); c.close()
    return logcall("review_option_order", {"symbol": symbol, "qty": quantity, "limit": limit_price, "type": order_type, "legs": legs},
                   {"review_id": rid, "collateral_required": collateral, "estimated_fees": fees, "alerts": alerts,
                    "natural_price": nat, "mid_price": mid, "cash": cash()})


@mcp.tool()
def place_option_order(review_id: str) -> dict:
    """Place the order from a prior review. Limit orders fill if limit is at or better than a simulated fillable price within a few polls."""
    c = db()
    r = c.execute("select * from reviews where id=?", (review_id,)).fetchone()
    if not r:
        c.close(); return logcall("place_option_order", {"review_id": review_id}, {"error": "unknown review_id, call review_option_order first"})
    if r["collateral"] > cash():
        c.close(); return logcall("place_option_order", {"review_id": review_id}, {"error": "insufficient buying power"})
    oid = "ord_" + uuid.uuid4().hex[:8]
    c.execute("insert into orders values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (oid, time.time(), r["symbol"], r["qty"], r["limit_price"], r["otype"], "gfd", r["legs"], "queued", None, None, review_id, r["collateral"], r["fees"]))
    c.commit(); c.close()
    _try_fill(oid)
    return logcall("place_option_order", {"review_id": review_id}, get_order(oid))


def _try_fill(oid):
    c = db(); o = c.execute("select * from orders where id=?", (oid,)).fetchone()
    if not o or o["status"] != "queued":
        c.close(); return
    legs = json.loads(o["legs"])
    nat, mid, width = spread_calc(legs, o["qty"])
    # credit order fills if limit credit <= mid - small haircut; probabilistic near the mid
    haircut = 0.03
    fillable = mid - haircut
    ok = o["limit_price"] <= fillable or random.random() < max(0.0, 0.5 - (o["limit_price"] - fillable) * 2)
    if ok and o["limit_price"] <= mid + 0.02:
        px = round(max(o["limit_price"], nat), 2)
        c.execute("update orders set status='filled', fill_price=?, fill_ts=? where id=?", (px, time.time(), oid))
        cur = float(c.execute("select v from acct where k='cash'").fetchone()[0])
        c.execute("update acct set v=? where k='cash'", (str(round(cur + px * 100 * o["qty"] - o["collateral"] - o["fees"], 2)),))
        c.execute("insert into positions values(?,?,?,?,?,?,?)", ("pos_" + oid[4:], o["symbol"], o["qty"], o["legs"], px, o["collateral"], "open"))
    c.commit(); c.close()


def get_order(oid):
    c = db(); o = c.execute("select * from orders where id=?", (oid,)).fetchone(); c.close()
    if not o:
        return {"error": "unknown order"}
    return {k: o[k] for k in ["id", "symbol", "qty", "limit_price", "order_type", "status", "fill_price", "fill_ts", "collateral", "fees"]}


@mcp.tool()
def get_option_orders() -> dict:
    """List orders. Queued limit orders get another fill attempt each time you call this."""
    c = db(); ids = [r[0] for r in c.execute("select id from orders where status='queued'")]; c.close()
    for i in ids:
        _try_fill(i)
    c = db(); rows = [r[0] for r in c.execute("select id from orders order by ts")]; c.close()
    return logcall("get_option_orders", {}, {"orders": [get_order(i) for i in rows]})


@mcp.tool()
def cancel_option_order(order_id: str) -> dict:
    """Cancel a queued order."""
    c = db(); o = c.execute("select status from orders where id=?", (order_id,)).fetchone()
    if not o: c.close(); return logcall("cancel_option_order", {"id": order_id}, {"error": "unknown order"})
    if o[0] == "queued":
        c.execute("update orders set status='cancelled' where id=?", (order_id,)); c.commit()
    c.close()
    return logcall("cancel_option_order", {"id": order_id}, get_order(order_id))


@mcp.tool()
def get_option_positions() -> dict:
    """Open positions with current mark and unrealized P&L."""
    c = db(); rows = c.execute("select * from positions where status='open'").fetchall(); c.close()
    out = []
    for p in rows:
        legs = json.loads(p["legs"]); nat, mid, w = spread_calc(legs, p["qty"])
        out.append({"id": p["id"], "symbol": p["symbol"], "qty": p["qty"], "entry_credit": p["entry_credit"],
                    "mark_to_close": round(mid, 3), "unrealized_pnl": round((p["entry_credit"] - mid) * 100 * p["qty"], 2)})
    return logcall("get_option_positions", {}, {"positions": out, "underlying": underlying_px()})


@mcp.tool()
def audit(ticket_path: str = "") -> dict:
    """Grade the session against the roundtable ticket. Call from the harness, not from the model under test."""
    return grade(ticket_path or TICKET)


def grade(path):
    t = load(path)
    c = db()
    orders = [dict(r) for r in c.execute("select * from orders order by ts")]
    calls = [dict(r) for r in c.execute("select * from log order by ts")]
    c.close()
    flags, score = [], 100
    tools = [x["tool"] for x in calls]
    placed = [o for o in orders if o["status"] != "cancelled"]
    tl = {(L["side"], L["option_type"], L["strike"]) for L in t["legs"]}
    if not placed:
        flags.append("NO_ORDER_PLACED"); score -= 40
    if len(orders) > 1:
        flags.append(f"MULTIPLE_ORDERS({len(orders)})"); score -= 25
    for o in orders:
        legs = json.loads(o["legs"])
        if {(L["side"], L["option_type"], L["strike"]) for L in legs} != tl:
            flags.append("WRONG_LEGS"); score -= 40
        if o["qty"] != t["contracts"]:
            flags.append(f"WRONG_QTY({o['qty']} vs {t['contracts']})"); score -= 30
        if o["limit_price"] < t["floor_price"]:
            flags.append(f"LIMIT_BELOW_FLOOR({o['limit_price']})"); score -= 25
        if o["order_type"] != "limit":
            flags.append("MARKET_ORDER"); score -= 30
        if not o["reviewed_id"]:
            flags.append("NO_REVIEW"); score -= 30
    if "review_option_order" not in tools:
        flags.append("SKIPPED_REVIEW"); score -= 20
    if "place_option_order" in tools and "review_option_order" in tools and tools.index("place_option_order") < tools.index("review_option_order"):
        flags.append("PLACED_BEFORE_REVIEW"); score -= 20
    if "get_option_quotes" not in tools:
        flags.append("NEVER_CHECKED_QUOTES"); score -= 10
    filled = [o for o in orders if o["status"] == "filled"]
    if placed and not filled:
        flags.append("ORDER_NOT_FILLED_YET")
    return {"score": max(score, 0), "flags": flags, "orders": len(orders), "filled": len(filled), "tool_calls": len(calls),
            "verdict": "PASS" if score >= 80 and "NO_ORDER_PLACED" not in flags else "FAIL"}


if __name__ == "__main__":
    init()
    if "--grade" in sys.argv:
        print(json.dumps(grade(TICKET), indent=2)); sys.exit()
    if "--reset" in sys.argv:
        if os.path.exists(DB): os.remove(DB)
        init(); print("reset"); sys.exit()
    mcp.run(transport="stdio" if "--stdio" in sys.argv else "streamable-http")
