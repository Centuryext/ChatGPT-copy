"""Business logic shared by the MCP tools, the REST API and the critic.
Every function takes an open Session and returns JSON-serialisable data."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config
from .db import (
    ALLOWED_TRANSITIONS,
    MESSAGE_KINDS,
    SNAPSHOT_KINDS,
    STATUSES,
    AgentState,
    Fill,
    Message,
    Snapshot,
    Ticket,
    utcnow,
)


class RoundtableError(ValueError):
    """Raised for protocol or validation problems; the message is meant for the agent."""


# ----------------------------------------------------------------- helpers

def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value: str | None) -> datetime:
    """Accept ISO 8601 (with Z or offset). Naive values are treated as UTC."""
    if not value:
        return utcnow()
    v = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(v)
    except ValueError as e:
        raise RoundtableError(f"Bad timestamp {value!r}; use ISO 8601 such as 2026-10-23T17:05:12Z") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _author(name: str) -> str:
    a = (name or "").strip().lower()
    if not a:
        raise RoundtableError("author is required: one of claude, gpt, critic, shawn")
    return a[:32]


def ticket_to_dict(t: Ticket, with_fills: bool = False) -> dict[str, Any]:
    d = {
        "id": t.id, "status": t.status, "author": t.author,
        "created_at": _iso(t.created_at), "updated_at": _iso(t.updated_at),
        "underlying": t.underlying, "strategy": t.strategy, "direction": t.direction,
        "entry_type": t.entry_type, "expiry": t.expiry, "legs": t.legs, "contracts": t.contracts,
        "multiplier": t.multiplier, "order_type": t.order_type, "time_in_force": t.time_in_force,
        "limit_price": t.limit_price, "fallback_price": t.fallback_price, "floor_price": t.floor_price,
        "spread_width": t.spread_width, "max_loss_usd": t.max_loss_usd, "max_gain_usd": t.max_gain_usd,
        "breakeven_px": t.breakeven_px, "profit_target_usd": t.profit_target_usd,
        "stop_loss_usd": t.stop_loss_usd, "underlying_px_at_create": t.underlying_px_at_create,
        "exit_rules": t.exit_rules, "rationale": t.rationale, "thesis_tag": t.thesis_tag,
        "catalyst": t.catalyst, "notes": t.notes, "decided_by": t.decided_by, "placed_by": t.placed_by,
        "entry_order_id": t.entry_order_id, "entry_net_price": t.entry_net_price,
        "entry_filled_at": _iso(t.entry_filled_at), "entry_fees_usd": t.entry_fees_usd,
        "underlying_px_at_entry": t.underlying_px_at_entry,
        "exit_order_id": t.exit_order_id, "exit_net_price": t.exit_net_price,
        "exit_filled_at": _iso(t.exit_filled_at), "exit_fees_usd": t.exit_fees_usd,
        "underlying_px_at_exit": t.underlying_px_at_exit,
        "current_mark_net": t.current_mark_net, "mark_updated_at": _iso(t.mark_updated_at),
        "unrealized_pnl_usd": unrealized_pnl(t), "realized_pnl_usd": t.realized_pnl_usd,
        "close_reason": t.close_reason,
    }
    if with_fills:
        d["fills"] = [fill_to_dict(f) for f in t.fills]
    return d


def fill_to_dict(f: Fill) -> dict[str, Any]:
    return {
        "id": f.id, "ticket_id": f.ticket_id, "phase": f.phase, "leg_index": f.leg_index, "side": f.side,
        "option_type": f.option_type, "strike": f.strike, "contracts": f.contracts, "price": f.price,
        "filled_at": _iso(f.filled_at), "order_id": f.order_id, "author": f.author,
        "created_at": _iso(f.created_at), "raw": f.raw,
    }


def message_to_dict(m: Message) -> dict[str, Any]:
    return {"id": m.id, "created_at": _iso(m.created_at), "author": m.author, "kind": m.kind,
            "ticket_id": m.ticket_id, "text": m.text}


def snapshot_to_dict(s: Snapshot, with_payload: bool = True) -> dict[str, Any]:
    d = {"id": s.id, "created_at": _iso(s.created_at), "author": s.author, "kind": s.kind, "note": s.note}
    if with_payload:
        d["payload"] = s.payload
    return d


def pnl_for(t: Ticket, exit_net: float | None) -> float | None:
    """Signed P&L in dollars for a credit or debit spread given an exit net price."""
    if t.entry_net_price is None or exit_net is None:
        return None
    per_share = (t.entry_net_price - exit_net) if t.entry_type == "credit" else (exit_net - t.entry_net_price)
    return round(per_share * t.multiplier * t.contracts - (t.entry_fees_usd or 0.0) - (t.exit_fees_usd or 0.0), 2)


def unrealized_pnl(t: Ticket) -> float | None:
    if t.status not in ("open", "close_ready") or t.current_mark_net is None:
        return None
    return pnl_for(t, t.current_mark_net)


def next_ticket_id(db: Session) -> str:
    n = db.scalar(select(func.count()).select_from(Ticket)) or 0
    while True:
        candidate = f"T-{n + 1:03d}"
        if db.get(Ticket, candidate) is None:
            return candidate
        n += 1


def get_ticket(db: Session, ticket_id: str) -> Ticket:
    t = db.get(Ticket, (ticket_id or "").strip().upper())
    if t is None:
        raise RoundtableError(f"No ticket {ticket_id!r}. Use roundtable_list_tickets to see ids.")
    return t


# ----------------------------------------------------------------- messages

def post_message(db: Session, author: str, text: str, kind: str = "note", ticket_id: str | None = None) -> dict:
    author = _author(author)
    text = (text or "").strip()
    if not text:
        raise RoundtableError("text is required")
    kind = (kind or "note").lower()
    if kind not in MESSAGE_KINDS:
        raise RoundtableError(f"kind must be one of {', '.join(MESSAGE_KINDS)}")
    tid = None
    if ticket_id:
        tid = get_ticket(db, ticket_id).id
    m = Message(author=author, text=text, kind=kind, ticket_id=tid)
    db.add(m)
    db.commit()
    return message_to_dict(m)


def read_thread(db: Session, limit: int = 50, since_id: int | None = None, ticket_id: str | None = None,
                author: str | None = None) -> list[dict]:
    q = select(Message)
    if since_id:
        q = q.where(Message.id > since_id)
    if ticket_id:
        q = q.where(Message.ticket_id == ticket_id.strip().upper())
    if author:
        q = q.where(Message.author == author.strip().lower())
    q = q.order_by(Message.id.desc()).limit(max(1, min(limit, 500)))
    rows = list(db.scalars(q))
    rows.reverse()  # chronological
    return [message_to_dict(m) for m in rows]


# ----------------------------------------------------------------- tickets

def _validate_legs(legs: list[dict]) -> list[dict]:
    if not legs or not isinstance(legs, list):
        raise RoundtableError("legs must be a non-empty list of {side, option_type, strike}")
    out = []
    for i, leg in enumerate(legs):
        if not isinstance(leg, dict):
            raise RoundtableError(f"leg {i} must be an object")
        side = str(leg.get("side", "")).lower()
        otype = str(leg.get("option_type", "")).lower()
        try:
            strike = float(leg.get("strike"))
        except (TypeError, ValueError) as e:
            raise RoundtableError(f"leg {i}: strike must be a number") from e
        if side not in ("buy", "sell"):
            raise RoundtableError(f"leg {i}: side must be buy or sell")
        if otype not in ("call", "put"):
            raise RoundtableError(f"leg {i}: option_type must be call or put")
        clean = {"side": side, "option_type": otype, "strike": strike}
        for k in ("occ_symbol", "rh_instrument_id", "rh_chain_id"):
            if leg.get(k):
                clean[k] = str(leg[k])
        out.append(clean)
    return out


def create_ticket(db: Session, author: str, data: dict[str, Any]) -> dict:
    author = _author(author)
    required = ("underlying", "strategy", "direction", "entry_type", "expiry", "legs", "contracts", "limit_price")
    missing = [k for k in required if data.get(k) in (None, "", [])]
    if missing:
        raise RoundtableError(f"Missing fields: {', '.join(missing)}")
    entry_type = str(data["entry_type"]).lower()
    if entry_type not in ("credit", "debit"):
        raise RoundtableError("entry_type must be credit or debit")
    direction = str(data["direction"]).lower()
    if direction not in ("bearish", "bullish", "neutral"):
        raise RoundtableError("direction must be bearish, bullish or neutral")
    status = str(data.get("status") or "proposed").lower()
    if status not in ("proposed", "ready"):
        raise RoundtableError("a new ticket starts as proposed or ready")
    legs = _validate_legs(data["legs"])
    strikes = sorted({l["strike"] for l in legs})
    width = (strikes[-1] - strikes[0]) if len(strikes) > 1 else None
    contracts = int(data["contracts"])
    limit_price = float(data["limit_price"])
    mult = int(data.get("multiplier") or 100)
    if contracts <= 0 or limit_price <= 0:
        raise RoundtableError("contracts and limit_price must be positive")

    max_loss = data.get("max_loss_usd")
    max_gain = data.get("max_gain_usd")
    if width is not None and len(legs) == 2:
        if max_loss is None:
            max_loss = (width - limit_price) * mult * contracts if entry_type == "credit" else limit_price * mult * contracts
        if max_gain is None:
            max_gain = limit_price * mult * contracts if entry_type == "credit" else (width - limit_price) * mult * contracts

    t = Ticket(
        id=next_ticket_id(db), status=status, author=author,
        underlying=str(data["underlying"]).upper()[:12], strategy=str(data["strategy"])[:48],
        direction=direction, entry_type=entry_type, expiry=str(data["expiry"]), legs=legs,
        contracts=contracts, multiplier=mult,
        order_type=str(data.get("order_type") or "limit"), time_in_force=str(data.get("time_in_force") or "gfd"),
        limit_price=limit_price,
        fallback_price=_opt_float(data.get("fallback_price")), floor_price=_opt_float(data.get("floor_price")),
        spread_width=width, max_loss_usd=_opt_float(max_loss), max_gain_usd=_opt_float(max_gain),
        breakeven_px=_opt_float(data.get("breakeven_px")),
        profit_target_usd=_opt_float(data.get("profit_target_usd")), stop_loss_usd=_opt_float(data.get("stop_loss_usd")),
        underlying_px_at_create=_opt_float(data.get("underlying_px")),
        exit_rules=str(data.get("exit_rules") or ""), rationale=str(data.get("rationale") or ""),
        thesis_tag=str(data.get("thesis_tag") or "")[:64], catalyst=str(data.get("catalyst") or ""),
        notes=str(data.get("notes") or ""), decided_by=author if status == "ready" else "",
    )
    db.add(t)
    db.flush()
    db.add(Message(author=author, kind="proposal", ticket_id=t.id,
                   text=f"{t.id} {status}: {t.strategy} on {t.underlying} {t.expiry}, {t.contracts}x at {t.limit_price:.2f} net {t.entry_type}. "
                        f"Max loss ${t.max_loss_usd:,.0f} / max gain ${t.max_gain_usd:,.0f}."
                        if t.max_loss_usd is not None and t.max_gain_usd is not None else
                        f"{t.id} {status}: {t.strategy} on {t.underlying} {t.expiry}, {t.contracts}x at {t.limit_price:.2f} net {t.entry_type}."))
    db.commit()
    return ticket_to_dict(t)


def _opt_float(v: Any) -> float | None:
    if v in (None, ""):
        return None
    return float(v)


def list_tickets(db: Session, status: str | None = None, limit: int = 50) -> list[dict]:
    q = select(Ticket)
    if status:
        statuses = [s.strip().lower() for s in status.split(",") if s.strip()]
        bad = [s for s in statuses if s not in STATUSES]
        if bad:
            raise RoundtableError(f"unknown status {bad}; valid: {', '.join(STATUSES)}")
        q = q.where(Ticket.status.in_(statuses))
    q = q.order_by(Ticket.created_at.desc()).limit(max(1, min(limit, 500)))
    return [ticket_to_dict(t) for t in db.scalars(q)]


def set_status(db: Session, ticket_id: str, author: str, status: str, reason: str = "") -> dict:
    author = _author(author)
    t = get_ticket(db, ticket_id)
    status = (status or "").lower()
    if status not in STATUSES:
        raise RoundtableError(f"status must be one of {', '.join(STATUSES)}")
    if status == t.status:
        return ticket_to_dict(t)
    if author != "shawn" and status not in ALLOWED_TRANSITIONS[t.status]:
        raise RoundtableError(
            f"{t.id} is {t.status}; allowed next: {sorted(ALLOWED_TRANSITIONS[t.status]) or 'none'}. "
            f"Use roundtable_record_execution to move placed->open or close_ready->closed.")
    if author == "critic":
        raise RoundtableError("critic cannot change ticket status; post a message instead")
    if status in ("open", "closed") and author != "shawn":
        raise RoundtableError("open and closed are set by roundtable_record_execution, not by hand")
    old = t.status
    t.status = status
    if status == "ready":
        t.decided_by = author
    if status == "placed":
        t.placed_by = author
    if status in ("rejected", "cancelled", "expired"):
        t.close_reason = status
    db.add(Message(author=author, kind="decision", ticket_id=t.id,
                   text=f"{t.id}: {old} -> {status}" + (f". {reason.strip()}" if reason else "")))
    db.commit()
    return ticket_to_dict(t)


EDITABLE_FIELDS = {
    "limit_price", "fallback_price", "floor_price", "exit_rules", "rationale", "notes", "catalyst", "thesis_tag",
    "profit_target_usd", "stop_loss_usd", "breakeven_px", "max_loss_usd", "max_gain_usd", "current_mark_net",
    "underlying_px_at_create", "contracts", "entry_order_id", "exit_order_id",
}


def update_fields(db: Session, ticket_id: str, author: str, fields: dict[str, Any]) -> dict:
    author = _author(author)
    t = get_ticket(db, ticket_id)
    if not fields:
        raise RoundtableError("fields is empty")
    unknown = sorted(set(fields) - EDITABLE_FIELDS)
    if unknown:
        raise RoundtableError(f"cannot edit {unknown}; editable: {sorted(EDITABLE_FIELDS)}")
    if "contracts" in fields and t.status not in ("proposed", "ready"):
        raise RoundtableError("contracts can only change before the order is placed")
    changed = []
    for k, v in fields.items():
        if k in ("exit_rules", "rationale", "notes", "catalyst", "thesis_tag", "entry_order_id", "exit_order_id"):
            v = str(v)
        elif k == "contracts":
            v = int(v)
        else:
            v = _opt_float(v)
        setattr(t, k, v)
        changed.append(k)
    if "current_mark_net" in fields:
        t.mark_updated_at = utcnow()
    db.add(Message(author=author, kind="note", ticket_id=t.id, text=f"{t.id}: updated {', '.join(changed)}"))
    db.commit()
    return ticket_to_dict(t)


def record_execution(db: Session, ticket_id: str, author: str, phase: str, order_id: str, filled_at: str,
                     net_price: float, fees_usd: float = 0.0, leg_prices: list[float] | None = None,
                     underlying_px: float | None = None, close_reason: str = "", raw: dict | None = None) -> dict:
    """Record a filled opening or closing order. Moves the ticket to open (entry) or closed (exit)."""
    author = _author(author)
    t = get_ticket(db, ticket_id)
    phase = (phase or "").lower()
    if phase not in ("entry", "exit"):
        raise RoundtableError("phase must be entry or exit")
    if author == "critic":
        raise RoundtableError("critic cannot record executions")
    if phase == "entry" and t.status not in ("ready", "placed") and author != "shawn":
        raise RoundtableError(f"{t.id} is {t.status}; an entry execution needs status ready or placed")
    if phase == "exit" and t.status not in ("open", "close_ready") and author != "shawn":
        raise RoundtableError(f"{t.id} is {t.status}; an exit execution needs status open or close_ready")
    if net_price is None or float(net_price) < 0:
        raise RoundtableError("net_price is the net per share for the whole spread, zero or positive")
    when = parse_time(filled_at)
    net = float(net_price)
    fees = float(fees_usd or 0.0)
    legs = t.legs or []
    if leg_prices is not None and len(leg_prices) != len(legs):
        raise RoundtableError(f"leg_prices must have {len(legs)} entries in ticket leg order")

    for i, leg in enumerate(legs):
        price = float(leg_prices[i]) if leg_prices is not None else float("nan")
        # On exit, each leg is reversed (sell what was bought, buy what was sold).
        side = leg["side"] if phase == "entry" else ("sell" if leg["side"] == "buy" else "buy")
        db.add(Fill(ticket_id=t.id, phase=phase, leg_index=i, side=side, option_type=leg["option_type"],
                    strike=leg["strike"], contracts=t.contracts,
                    price=price if price == price else net, filled_at=when, order_id=order_id or "",
                    author=author, raw=raw))

    if phase == "entry":
        t.entry_order_id = order_id or t.entry_order_id
        t.entry_net_price = net
        t.entry_filled_at = when
        t.entry_fees_usd = fees
        t.underlying_px_at_entry = _opt_float(underlying_px)
        t.placed_by = t.placed_by or author
        t.status = "open"
        summary = f"{t.id} OPEN: filled {t.contracts}x at {net:.2f} net {t.entry_type}, fees ${fees:.2f}, order {order_id or 'n/a'}"
    else:
        t.exit_order_id = order_id or t.exit_order_id
        t.exit_net_price = net
        t.exit_filled_at = when
        t.exit_fees_usd = fees
        t.underlying_px_at_exit = _opt_float(underlying_px)
        t.realized_pnl_usd = pnl_for(t, net)
        t.close_reason = close_reason or t.close_reason or "closed"
        t.status = "closed"
        pnl = t.realized_pnl_usd
        summary = (f"{t.id} CLOSED: exit at {net:.2f} net, realized P&L ${pnl:,.2f}"
                   f" ({pnl / t.max_loss_usd:+.1%} on max risk)" if pnl is not None and t.max_loss_usd else
                   f"{t.id} CLOSED: exit at {net:.2f} net")
    db.add(Message(author=author, kind="execution", ticket_id=t.id, text=summary))
    db.commit()
    return ticket_to_dict(t, with_fills=True)


# ----------------------------------------------------------------- snapshots

def record_snapshot(db: Session, author: str, kind: str, payload: dict | list, note: str = "") -> dict:
    author = _author(author)
    kind = (kind or "other").lower()
    if kind not in SNAPSHOT_KINDS:
        raise RoundtableError(f"kind must be one of {', '.join(SNAPSHOT_KINDS)}")
    if payload in (None, {}, []):
        raise RoundtableError("payload is required (a JSON object or list)")
    s = Snapshot(author=author, kind=kind, payload=payload, note=note or "")
    db.add(s)
    db.commit()
    return snapshot_to_dict(s, with_payload=False)


def list_snapshots(db: Session, kind: str | None = None, limit: int = 20, with_payload: bool = False) -> list[dict]:
    q = select(Snapshot)
    if kind:
        q = q.where(Snapshot.kind == kind.lower())
    q = q.order_by(Snapshot.id.desc()).limit(max(1, min(limit, 200)))
    return [snapshot_to_dict(s, with_payload) for s in db.scalars(q)]


def latest_snapshot(db: Session, kind: str) -> dict | None:
    s = db.scalar(select(Snapshot).where(Snapshot.kind == kind).order_by(Snapshot.id.desc()).limit(1))
    return snapshot_to_dict(s) if s else None


# ----------------------------------------------------------------- summary

def pnl_summary(db: Session) -> dict[str, Any]:
    tickets = list(db.scalars(select(Ticket)))
    closed = [t for t in tickets if t.status == "closed" and t.realized_pnl_usd is not None]
    open_ = [t for t in tickets if t.status in ("open", "close_ready")]
    wins = [t for t in closed if t.realized_pnl_usd > 0]
    losses = [t for t in closed if t.realized_pnl_usd < 0]
    ror = [t.realized_pnl_usd / t.max_loss_usd for t in closed if t.max_loss_usd]
    held = [(t.exit_filled_at - t.entry_filled_at).total_seconds() / 86400 for t in closed
            if t.exit_filled_at and t.entry_filled_at]
    unreal = [u for u in (unrealized_pnl(t) for t in open_) if u is not None]
    by_status = {}
    for t in tickets:
        by_status[t.status] = by_status.get(t.status, 0) + 1
    return {
        "tickets_total": len(tickets),
        "by_status": by_status,
        "closed": len(closed), "wins": len(wins), "losses": len(losses),
        "win_rate": round(len(wins) / len(closed), 4) if closed else None,
        "realized_pnl_usd": round(sum(t.realized_pnl_usd for t in closed), 2),
        "avg_return_on_risk": round(sum(ror) / len(ror), 4) if ror else None,
        "avg_days_held": round(sum(held) / len(held), 2) if held else None,
        "open_tickets": len(open_),
        "open_max_loss_usd": round(sum(t.max_loss_usd or 0 for t in open_), 2),
        "unrealized_pnl_usd": round(sum(unreal), 2) if unreal else None,
        "ready_tickets": by_status.get("ready", 0),
        "close_ready_tickets": by_status.get("close_ready", 0),
    }


def state(db: Session, limit_messages: int = 30) -> dict[str, Any]:
    """Everything an agent needs to read the room in one call."""
    return {
        "server_time_utc": _iso(utcnow()),
        "display_timezone": config.DISPLAY_TZ,
        "account": config.ACCOUNT_LABEL,
        "summary": pnl_summary(db),
        "actionable": {
            "ready_for_gpt": list_tickets(db, "ready"),
            "close_ready_for_gpt": list_tickets(db, "close_ready"),
            "awaiting_discussion": list_tickets(db, "proposed"),
        },
        "open": list_tickets(db, "open,placed"),
        "recent_closed": list_tickets(db, "closed,rejected,cancelled,expired", limit=10),
        "recent_messages": read_thread(db, limit=limit_messages),
        "latest_positions_snapshot": latest_snapshot(db, "positions"),
    }


# ----------------------------------------------------------------- export

EXPORT_TABLES = ("tickets", "fills", "messages", "snapshots")


def export_rows(db: Session, table: str, limit: int = 5000) -> list[dict]:
    table = (table or "").lower()
    if table == "tickets":
        return [ticket_to_dict(t) for t in db.scalars(select(Ticket).order_by(Ticket.created_at).limit(limit))]
    if table == "fills":
        return [fill_to_dict(f) for f in db.scalars(select(Fill).order_by(Fill.id).limit(limit))]
    if table == "messages":
        return [message_to_dict(m) for m in db.scalars(select(Message).order_by(Message.id).limit(limit))]
    if table == "snapshots":
        return [snapshot_to_dict(s) for s in db.scalars(select(Snapshot).order_by(Snapshot.id).limit(limit))]
    raise RoundtableError(f"table must be one of {', '.join(EXPORT_TABLES)}")


def rows_to_csv(rows: list[dict]) -> str:
    if not rows:
        return ""
    keys: list[str] = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=keys)
    w.writeheader()
    for r in rows:
        w.writerow({k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in r.items()})
    return buf.getvalue()


# ----------------------------------------------------------------- agent state

def get_state_value(db: Session, key: str, default: str = "") -> str:
    row = db.get(AgentState, key)
    return row.value if row else default


def set_state_value(db: Session, key: str, value: str) -> None:
    row = db.get(AgentState, key)
    if row is None:
        row = AgentState(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    db.commit()
