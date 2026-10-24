# PaperDesk: simulated broker + executor training harness (no real money)

Trains a local model to execute roundtable tickets exactly, against a fake broker whose tools
mirror the real ones (quotes, review, place, orders, positions). Every call is logged and graded.

## Run on aiserver
    cd ~/stock-roundtable && git pull origin stock-roundtable
    docker compose --profile paper build
    # one training pass: 4 scenarios x 5 trials against Ollama gemma4:12b on the host
    docker compose --profile paper run --rm trainer --model gemma4:12b --trials 5
    # self-test of the harness without a model (expect CLEAN 4/4 then CLEAN 0/4)
    docker compose --profile paper run --rm trainer --mock good --trials 1
    docker compose --profile paper run --rm trainer --mock bad  --trials 1

Results land in ./paperdesk/runs/: results.json (score + flags per run), trajectories.jsonl (all),
sft.jsonl (clean runs only, chat format, for few-shot or LoRA).

Loop: run, read the flags, edit paperdesk/system_prompt.txt, rerun until CLEAN = 20/20.
Then add tickets (copy ticket_T001.json) and price paths (copy scenarios/base.json) so the data
covers puts, debit spreads and closes. Env: OLLAMA_URL (default http://host.docker.internal:11434).

Ollama inference is the lowest GPU class on the ask sheet; add a row before long runs.

Standalone broker for other MCP clients (Open WebUI, n8n): docker compose --profile paper up -d paperdesk
then http://aiserver:8899/mcp. Not on the Funnel.
