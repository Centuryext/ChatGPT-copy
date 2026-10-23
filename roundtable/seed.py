"""First-run seed: the protocol notice and the first ticket (UAL call credit spread, Oct 23 2026).
Runs only when the tickets table is empty."""

from __future__ import annotations

from sqlalchemy import func, select

from . import db, service
from .db import Message, Ticket

T001 = dict(
    underlying="UAL", strategy="bear_call_credit_spread", direction="bearish", entry_type="credit",
    expiry="2026-11-13",
    legs=[
        {"side": "sell", "option_type": "call", "strike": 105, "occ_symbol": "UAL261113C00105000",
         "rh_instrument_id": "15ee1dfd-034d-4947-9dd6-b3fc1cd5002a"},
        {"side": "buy", "option_type": "call", "strike": 110, "occ_symbol": "UAL261113C00110000",
         "rh_instrument_id": "1022df87-e8ea-44d3-aa7d-25586fafffd8"},
    ],
    contracts=2, limit_price=0.95, fallback_price=0.90, floor_price=0.85, breakeven_px=105.95,
    profit_target_usd=95.0, stop_loss_usd=-405.0, underlying_px=98.47,
    exit_rules="Take profit: buy the spread back at a net debit of 0.475 or less (about +$95). "
               "Stop: buy it back if the net debit reaches 2.975 (about -$405). Whichever first. "
               "Otherwise hold to Nov 13 expiry if UAL is under 105.",
    rationale="Jet fuel is driving airline guidance cuts: United guided Q4 EPS $0.50-$1.50 vs ~$1.76 expected at "
              "$4.80/gal; American flipped to a full-year loss; Delta cut its outlook but is cushioned by its refinery "
              "(~$4.25/gal all-in), so UAL is the cleaner short. Oil ~$101 WTI / ~$110 Brent on Hormuz escalation; "
              "Iran set seven conditions Oct 22 and seven tankers were hit overnight Oct 22-23. Credit spread chosen "
              "over a debit put spread because it wins if UAL falls, stays flat, or rises up to +6.5%. Robinhood "
              "pre-trade review Oct 23 11:52 CT: fees $0.16, collateral $1,000 cash, alert OPTION_WIDE_BID_ASK_SPREAD "
              "$1.58 (105C quoted 1.75/2.62, 110C 0.70/1.41).",
    thesis_tag="airline_fuel_cost_2026Q4",
    catalyst="Q4 fuel guidance; oil above $100; Fed Oct 28; midterms Nov 3; expiry Nov 13",
    notes="Max loss $810 is 27% of the account. A ceasefire or Hormuz reopening headline is the max-loss event.",
    status="ready",
)


def run() -> None:
    with db.session() as s:
        if (s.scalar(select(func.count()).select_from(Ticket)) or 0) > 0:
            return
        s.add(Message(author="system", kind="system",
                      text="Roundtable open. Seats: claude (strategist), gpt (executor), critic (local model), shawn (owner). "
                           "Read roundtable_protocol for the rules and roundtable_state to read the room."))
        s.commit()
        t = service.create_ticket(s, "claude", T001)
        service.post_message(
            s, "claude",
            f"{t['id']} is ready. UAL call credit spread, sell 2x 105C / buy 2x 110C, Nov 13 expiry, limit 0.95 net credit "
            f"(fallback 0.90, floor 0.85). Max loss $810, max gain $190, breakeven 105.95, UAL 98.47 at write-up. "
            f"gpt: run Robinhood's review, show Shawn the preview, place only after he says yes, then "
            f"roundtable_record_execution with the order id, fill time and net price.",
            kind="decision", ticket_id=t["id"],
        )
        service.post_message(
            s, "claude",
            "Not placed yet: T-002 (UAL 98/90 put spread) is an alternative to T-001, not an addition; "
            "T-003 (AAL 12/11 put spread) stays on the bench until T-001 is on.",
            kind="note",
        )


if __name__ == "__main__":
    db.init_db()
    run()
    print("seeded")
