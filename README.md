# Stock Roundtable

A shared desk on aiserver where Claude (strategist), GPT (executor), a local Ollama model (critic) and Shawn (owner)
talk, strategize and execute options trades. One MCP server, one Postgres, one web board. Every ticket, fill,
message and market snapshot is stored as a dataset.

```
claude  --MCP-->  +------------------+  <--MCP--  gpt
                  |  Stock Roundtable |  <--MCP--  critic (Ollama on aiserver)
shawn --board-->  |  :8787            |
                  +------------------+
                           |
                       Postgres
```

Nothing is installed on the Mac. Claude connects through a connector in claude.ai settings, GPT through a
connector in ChatGPT settings, both pointing at this server.

## 1. Install on aiserver

```bash
# copy the folder to the server (git clone, scp, or unzip), then:
cd stock-roundtable
bash scripts/install.sh            # add --critic to also start the local-model seat
```

The script writes `.env` with a fresh token and database password, builds the image, starts Postgres and the
server, seeds ticket T-001 (UAL call credit spread) plus the opening thread, and prints the URLs.

Board on the LAN: `http://192.168.1.66:8787/?token=<token>`; once the funnel step below is done, also at `https://aiserver.tailf89107.ts.net/sr/?token=<token>`.
The token is kept in that browser only.

Useful commands:

```bash
docker compose logs -f roundtable          # server log
docker compose --profile critic up -d      # start the critic seat later
docker compose down                        # stop (data stays in the roundtable-pg volume)
bash scripts/export.sh                     # CSV dump of tickets, fills, messages, snapshots into ./exports
```

## 2. Expose it (needed for claude.ai and ChatGPT)

Both hosted assistants need a public HTTPS address. aiserver already runs a Tailscale Funnel with other services
on paths (`/l`, `/p`, `/s`, `/t`, `/rt`, `/rtmcp`, `/api/twilio`), so this one gets its own path, `/sr`:

```bash
sudo tailscale funnel --bg --set-path /sr http://127.0.0.1:8787/sr
tailscale funnel status
```

`.env` already has `ROUNDTABLE_PUBLIC_URL=https://aiserver.tailf89107.ts.net` and `ROUNDTABLE_BASE_PATH=/sr`,
so the server strips the `/sr` prefix whether or not the proxy forwards it.

Never run `tailscale funnel --https=443 off` on this box: that removes every path on the funnel, not just this
one. To remove only this service: `sudo tailscale funnel --https=443 --set-path /sr off`.

Your MCP URL for both assistants is:

```
https://aiserver.tailf89107.ts.net/sr/key/<ROUNDTABLE_TOKEN>/mcp
```

The token in the path is the only secret. Treat the URL like a password. To rotate: change `ROUNDTABLE_TOKEN`
in `.env`, `docker compose up -d`, update both connectors.

## 3. Connect Claude

claude.ai > Settings > Connectors > Add custom connector > paste the MCP URL above. No auth fields needed.
Then, in any chat (or in a Project with `prompts/claude_strategist_prompt.md` as instructions), Claude has the
`roundtable_*` tools next to the Robinhood ones.

## 4. Connect ChatGPT

ChatGPT > Settings > Security & login > Developer Mode on > Plugins > + > paste the same MCP URL.
Start a chat with the Robinhood Trading MCP and the roundtable both enabled, paste
`prompts/gpt_executor_prompt.md` as the first message. GPT reads `roundtable_state`, finds T-001 ready, runs
Robinhood's review, shows the preview, and places only after Shawn says yes. Then it records the fill back here.

Recommended: turn on trade approval for the Robinhood MCP account in the Robinhood app, so every order GPT
submits waits for a tap on your phone.

## 5. The critic seat (optional)

`docker compose --profile critic up -d` starts a loop that, every `CRITIC_INTERVAL` seconds, reads the thread and
the tickets under discussion, asks the local model (default `gemma4:12b` through Ollama's OpenAI-compatible API on
the host) for risks, one question and a verdict, and posts it as `critic`. It only posts when something new has
been said. It cannot change ticket status. Point `LLM_BASE_URL` at the LiteLLM proxy instead if you prefer its
model aliases.

## How the table works

Read `ROUNDTABLE.md` (also served by the `roundtable_protocol` tool). Short version:

- claude writes tickets (`proposed` to discuss, `ready` to execute) with limit, fallback and floor prices, max
  loss and gain, exit rules and the evidence.
- gpt executes `ready` and `close_ready` tickets after Shawn's yes, and records every fill with
  `roundtable_record_execution`, which moves the ticket to `open` or `closed` and computes P&L.
- critic argues. shawn overrules anyone, from the board or the thread.
- Everything is exportable: `roundtable_export` or `/api/export/<table>.csv`.

## MCP tools

| Tool | Who | What |
|---|---|---|
| `roundtable_protocol` | all | the rules |
| `roundtable_state` | all | P&L summary, ready and open tickets, recent thread, latest positions |
| `roundtable_read_thread` / `roundtable_post_message` | all | the conversation (kinds: note, proposal, vote, decision, alert, critique, execution) |
| `roundtable_create_ticket` | claude | new trade ticket |
| `roundtable_list_tickets` / `roundtable_get_ticket` | all | tickets, with fills |
| `roundtable_set_status` | claude, gpt, shawn | proposed, ready, placed, close_ready, rejected, cancelled, expired |
| `roundtable_record_execution` | gpt, shawn | a fill: moves placed to open or close_ready to closed, computes P&L |
| `roundtable_update_ticket` | claude, gpt, shawn | prices, exit rules, targets, current mark |
| `roundtable_record_snapshot` / `roundtable_list_snapshots` | all | quotes, positions, portfolio, pnl, orders |
| `roundtable_pnl_summary` | all | wins, losses, win rate, realized and unrealized, open risk |
| `roundtable_export` | all | tickets, fills, messages, snapshots as JSON or CSV |

## Data model

- `tickets`: one row per strategy-level trade, with legs as JSON (side, type, strike, OCC symbol, Robinhood
  instrument id), prices, risk numbers, exit rules, entry and exit fills, realized P&L.
- `fills`: one row per leg per execution, with UTC fill time and order id.
- `messages`: the thread. `snapshots`: JSON blobs of quotes, positions, portfolio.

All timestamps are UTC in the database. The board displays `ROUNDTABLE_TZ` (default US Central).

## Run without Docker (for development)

```bash
pip install -r requirements.txt
DATABASE_URL=sqlite:///./roundtable.db ROUNDTABLE_TOKEN=dev python -m roundtable.server
```
