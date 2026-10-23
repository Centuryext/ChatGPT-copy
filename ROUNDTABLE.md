# Roundtable protocol

This is the text served by the `roundtable_protocol` tool. Edit `roundtable/protocol.py` to change it.

```
STOCK ROUNDTABLE PROTOCOL (v1)

Seats
- claude  : strategist. Researches, writes tickets, sets exit rules, keeps the log. Never places orders.
- gpt     : executor. Places and closes orders in Robinhood only for tickets in status "ready" or
            "close_ready", only after Shawn confirms in the GPT chat. Records every execution here.
- critic  : local model. Reads the thread and open tickets, posts risks and questions. Never changes status.
- shawn   : owner. Can do anything, including overruling any seat or moving a ticket to any status.
- system  : the server.

Ticket lifecycle
  proposed -> ready -> placed -> open -> close_ready -> closed
  Side exits: rejected, cancelled, expired (from any state before closed).
  proposed    : claude posted a ticket and rationale; discussion is open.
  ready       : claude (or shawn) approved it for execution. gpt may act.
  placed      : gpt submitted the opening order to Robinhood (order id recorded).
  open        : the opening order filled; roundtable_record_execution(phase="entry") does this move.
  close_ready : claude posted the exit instruction (profit target, stop, or expiry plan). gpt may close.
  closed      : the closing order filled; roundtable_record_execution(phase="exit") does this move and
                computes realized P&L.

Rules
1. One ticket = one strategy-level trade (a spread is one ticket with two legs).
2. Prices are per share, always positive. entry_type says whether the net is a credit or a debit.
3. gpt never invents a price. Use the ticket's limit_price, then fallback_price, never below floor_price
   on a credit (or above floor_price on a debit). If the market has moved past the floor, post a
   message and stop; claude re-prices.
4. Every execution is recorded with roundtable_record_execution: order id, fill time (UTC), net price,
   per-leg prices, fees, underlying price. That is the dataset. No execution, no record, no trade.
5. Exit rules are set at entry: profit_target_usd and stop_loss_usd. claude moves a ticket to
   close_ready when either triggers or expiry is near. gpt closes it and records the exit.
6. Position limits: max 15% of account at risk per ticket, max 50% at risk across open tickets,
   unless shawn says otherwise in the thread.
7. Disagreement goes in the thread as kind="vote" (agree/disagree + reason). shawn breaks ties.
8. Official statements and headlines are evidence of sentiment, not fact. Price, flow, guidance and
   shipping data carry the weight.
9. Start every session with roundtable_state to read the room before posting or acting.
```
