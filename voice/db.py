"""
Single source of truth for the calls database (shared by campaign.py, server.py,
dashboard.py). Postgres via SQLAlchemy.
"""
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/callcenter")

DDL = """
CREATE TABLE IF NOT EXISTS calls (
    id SERIAL PRIMARY KEY,
    campaign TEXT DEFAULT 'default',
    name TEXT,
    phone TEXT NOT NULL,
    note TEXT,
    call_sid TEXT UNIQUE,
    status TEXT DEFAULT 'queued',      -- queued|dialing|in-progress|completed|no-answer|busy|failed|voicemail
    outcome TEXT,                      -- booked|rescheduled|declined|callback|no-answer|dnc (set by agent/logic)
    duration_sec INTEGER DEFAULT 0,
    recording_url TEXT,
    transcript TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    ended_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_calls_campaign ON calls(campaign);
CREATE INDEX IF NOT EXISTS idx_calls_status ON calls(status);
"""

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(DB_URL, pool_pre_ping=True)
        with _engine.begin() as conn:
            for stmt in DDL.strip().split(";"):
                if stmt.strip():
                    conn.execute(text(stmt))
    return _engine


def record_dial(campaign, name, phone, note, call_sid):
    with get_engine().begin() as conn:
        conn.execute(text(
            "INSERT INTO calls (campaign,name,phone,note,call_sid,status) "
            "VALUES (:c,:n,:p,:no,:s,'dialing') ON CONFLICT (call_sid) DO NOTHING"),
            {"c": campaign, "n": name, "p": phone, "no": note, "s": call_sid})


def update_status(call_sid, status=None, duration_sec=None, recording_url=None,
                  ended=False):
    sets, params = [], {"s": call_sid}
    if status is not None:
        sets.append("status=:st"); params["st"] = status
    if duration_sec is not None:
        sets.append("duration_sec=:d"); params["d"] = duration_sec
    if recording_url is not None:
        sets.append("recording_url=:r"); params["r"] = recording_url
    if ended:
        sets.append("ended_at=now()")
    if not sets:
        return
    with get_engine().begin() as conn:
        conn.execute(text(f"UPDATE calls SET {', '.join(sets)} WHERE call_sid=:s"), params)


def save_transcript(call_sid, transcript, outcome=None):
    with get_engine().begin() as conn:
        conn.execute(text(
            "UPDATE calls SET transcript=:t, outcome=COALESCE(:o, outcome) WHERE call_sid=:s"),
            {"t": transcript, "o": outcome, "s": call_sid})
