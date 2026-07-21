"""
Outbound campaign runner.

Loads a CSV of contacts, originates calls through Twilio (each call connects to
your voice server's /twiml), and logs outcomes to Postgres.

CSV format (header required):
    name,phone,note
    Jane Doe,+15551230001,Appt Tue 3pm with Dr. Lee

Usage:
    python campaign.py contacts.csv --max-concurrent 20 --dry-run
    python campaign.py contacts.csv --max-concurrent 20

COMPLIANCE: only dial numbers that have consented / are on an opted-in list, and
scrub against DNC. Respect calling-hours laws (typically 8am-9pm local). This
runner enforces a simple concurrency cap; add your own DNC check in should_dial().
"""
import os
import csv
import time
import argparse
from dotenv import load_dotenv
from twilio.rest import Client
from sqlalchemy import create_engine, text

load_dotenv()

TWILIO_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
FROM_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER")
BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
DB_URL = os.environ.get("DATABASE_URL")

DDL = """
CREATE TABLE IF NOT EXISTS calls (
    id SERIAL PRIMARY KEY,
    name TEXT,
    phone TEXT NOT NULL,
    note TEXT,
    call_sid TEXT,
    status TEXT DEFAULT 'queued',
    created_at TIMESTAMPTZ DEFAULT now()
);
"""


def db():
    if not DB_URL:
        return None
    engine = create_engine(DB_URL)
    with engine.begin() as conn:
        conn.execute(text(DDL))
    return engine


def should_dial(phone: str) -> bool:
    # TODO: plug in DNC list + calling-hours check here before going to production.
    return bool(phone and phone.startswith("+"))


def load_contacts(path):
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            yield {"name": row.get("name", ""),
                   "phone": row.get("phone", "").strip(),
                   "note": row.get("note", "")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--max-concurrent", type=int, default=20)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.dry_run:
        for k, v in {"TWILIO_ACCOUNT_SID": TWILIO_SID, "TWILIO_AUTH_TOKEN": TWILIO_TOKEN,
                     "TWILIO_PHONE_NUMBER": FROM_NUMBER, "PUBLIC_BASE_URL": BASE_URL}.items():
            if not v:
                raise SystemExit(f"Missing env var {k} (fill voice/.env)")

    client = None if args.dry_run else Client(TWILIO_SID, TWILIO_TOKEN)
    engine = db()
    twiml_url = f"{BASE_URL}/twiml"

    active = 0
    for c in load_contacts(args.csv):
        if not should_dial(c["phone"]):
            print(f"SKIP (dnc/invalid): {c['phone']}")
            continue

        if args.dry_run:
            print(f"[dry-run] would dial {c['name']} {c['phone']} -> {twiml_url}")
            continue

        # crude concurrency gate; replace with Twilio status callbacks for accuracy
        while active >= args.max_concurrent:
            time.sleep(1)
            active = max(0, active - 1)

        call = client.calls.create(to=c["phone"], from_=FROM_NUMBER, url=twiml_url,
                                   machine_detection="Enable")
        active += 1
        print(f"dialing {c['name']} {c['phone']} sid={call.sid}")
        if engine:
            with engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO calls (name, phone, note, call_sid, status) "
                    "VALUES (:n,:p,:no,:s,'dialing')"),
                    {"n": c["name"], "p": c["phone"], "no": c["note"], "s": call.sid})


if __name__ == "__main__":
    main()
