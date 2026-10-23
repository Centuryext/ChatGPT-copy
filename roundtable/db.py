"""SQLAlchemy models. Works on Postgres (production) and SQLite (tests)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from . import config

# Ticket lifecycle. Side states (rejected, cancelled, expired) can be reached from any pre-close state.
STATUSES = ("proposed", "ready", "placed", "open", "close_ready", "closed", "rejected", "cancelled", "expired")
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "proposed": {"ready", "rejected", "cancelled"},
    "ready": {"placed", "proposed", "rejected", "cancelled"},
    "placed": {"open", "ready", "cancelled"},
    "open": {"close_ready", "closed", "expired"},
    "close_ready": {"closed", "open", "expired"},
    "closed": set(),
    "rejected": {"proposed"},
    "cancelled": {"proposed"},
    "expired": set(),
}
MESSAGE_KINDS = ("note", "proposal", "vote", "decision", "alert", "critique", "execution", "system")
SNAPSHOT_KINDS = ("quotes", "positions", "portfolio", "pnl", "orders", "other")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)  # T-001
    status: Mapped[str] = mapped_column(String(16), default="proposed", index=True)
    author: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    underlying: Mapped[str] = mapped_column(String(12), index=True)
    strategy: Mapped[str] = mapped_column(String(48))
    direction: Mapped[str] = mapped_column(String(12))  # bearish | bullish | neutral
    entry_type: Mapped[str] = mapped_column(String(8))  # credit | debit
    expiry: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    legs: Mapped[list] = mapped_column(JSON)  # [{side, option_type, strike, occ_symbol?, rh_instrument_id?}]
    contracts: Mapped[int] = mapped_column(Integer)
    multiplier: Mapped[int] = mapped_column(Integer, default=100)

    order_type: Mapped[str] = mapped_column(String(12), default="limit")
    time_in_force: Mapped[str] = mapped_column(String(8), default="gfd")
    limit_price: Mapped[float] = mapped_column(Float)  # net per share, positive
    fallback_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    floor_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread_width: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_loss_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_gain_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    breakeven_px: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit_target_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    underlying_px_at_create: Mapped[float | None] = mapped_column(Float, nullable=True)

    exit_rules: Mapped[str] = mapped_column(Text, default="")
    rationale: Mapped[str] = mapped_column(Text, default="")
    thesis_tag: Mapped[str] = mapped_column(String(64), default="")
    catalyst: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")

    decided_by: Mapped[str] = mapped_column(String(32), default="")
    placed_by: Mapped[str] = mapped_column(String(32), default="")
    entry_order_id: Mapped[str] = mapped_column(String(64), default="")
    entry_net_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    entry_fees_usd: Mapped[float] = mapped_column(Float, default=0.0)
    underlying_px_at_entry: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_order_id: Mapped[str] = mapped_column(String(64), default="")
    exit_net_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_fees_usd: Mapped[float] = mapped_column(Float, default=0.0)
    underlying_px_at_exit: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_mark_net: Mapped[float | None] = mapped_column(Float, nullable=True)
    mark_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    realized_pnl_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_reason: Mapped[str] = mapped_column(String(64), default="")

    fills: Mapped[list["Fill"]] = relationship(back_populates="ticket", cascade="all, delete-orphan")
    messages: Mapped[list["Message"]] = relationship(back_populates="ticket")


class Fill(Base):
    __tablename__ = "fills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id"), index=True)
    phase: Mapped[str] = mapped_column(String(8))  # entry | exit
    leg_index: Mapped[int] = mapped_column(Integer)
    side: Mapped[str] = mapped_column(String(4))
    option_type: Mapped[str] = mapped_column(String(4))
    strike: Mapped[float] = mapped_column(Float)
    contracts: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    order_id: Mapped[str] = mapped_column(String(64), default="")
    author: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    ticket: Mapped[Ticket] = relationship(back_populates="fills")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    author: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="note")
    ticket_id: Mapped[str | None] = mapped_column(ForeignKey("tickets.id"), nullable=True, index=True)
    text: Mapped[str] = mapped_column(Text)

    ticket: Mapped[Ticket | None] = relationship(back_populates="messages")


class Snapshot(Base):
    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    author: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16), index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict | list] = mapped_column(JSON)


class AgentState(Base):
    __tablename__ = "agent_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


_engine = None
_Session = None


def engine():
    global _engine, _Session
    if _engine is None:
        url = config.DATABASE_URL
        kwargs = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(url, **kwargs)
        _Session = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def session():
    engine()
    return _Session()


def init_db() -> None:
    Base.metadata.create_all(engine())
