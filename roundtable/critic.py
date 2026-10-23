"""The critic seat: a local model (Ollama, OpenAI-compatible endpoint) that reads the thread and the
tickets under discussion and posts risks, questions and a verdict. It never changes status.

Run: python -m roundtable.critic     (docker compose --profile critic up -d)
"""

from __future__ import annotations

import json
import time

import httpx

from . import config, db, service

SYSTEM_PROMPT = """You are the critic at an options-trading roundtable. Your job is to find what the strategist missed:
hidden risks, bad assumptions, position sizing problems, timing around events, liquidity and fill problems,
and whether the exit rules actually protect the account. Be specific and short. Never place orders.
Treat official statements and headlines as sentiment, not fact; weigh price, flow, guidance and shipping data.
Reply in plain text, at most 150 words, in this shape:
RISKS: two or three bullets
QUESTION: one question for the strategist
VERDICT: agree | agree with changes | disagree, and one line why"""


def build_prompt(state: dict) -> str:
    tickets = state["actionable"]["ready_for_gpt"] + state["actionable"]["awaiting_discussion"] + state["open"]
    lines = ["ACCOUNT SUMMARY", json.dumps(state["summary"]), "", "TICKETS UNDER DISCUSSION"]
    for t in tickets:
        keep = {k: t[k] for k in ("id", "status", "underlying", "strategy", "entry_type", "expiry", "legs", "contracts",
                                  "limit_price", "fallback_price", "floor_price", "max_loss_usd", "max_gain_usd",
                                  "breakeven_px", "profit_target_usd", "stop_loss_usd", "exit_rules", "rationale",
                                  "catalyst", "notes", "entry_net_price", "current_mark_net", "unrealized_pnl_usd")}
        lines.append(json.dumps(keep, default=str))
    lines += ["", "RECENT THREAD (oldest first)"]
    for m in state["recent_messages"]:
        lines.append(f"[{m['created_at']}] {m['author']} ({m['kind']}{', ' + m['ticket_id'] if m['ticket_id'] else ''}): {m['text']}")
    return "\n".join(lines)


def ask_model(prompt: str) -> str:
    url = config.LLM_BASE_URL.rstrip("/") + "/chat/completions"
    body = {"model": config.LLM_MODEL, "temperature": 0.3,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]}
    with httpx.Client(timeout=180) as client:
        r = client.post(url, json=body, headers={"Authorization": f"Bearer {config.LLM_API_KEY}"})
        r.raise_for_status()
        data = r.json()
    return data["choices"][0]["message"]["content"].strip()


def run_once() -> bool:
    """Post one critique if there is something new since the last one. Returns True if it posted."""
    with db.session() as s:
        st = service.state(s, limit_messages=40)
        msgs = [m for m in st["recent_messages"] if m["author"] != config.CRITIC_AUTHOR]
        if not msgs:
            return False
        last_seen = int(service.get_state_value(s, "critic.last_seen_message_id", "0") or 0)
        newest = max(m["id"] for m in msgs)
        under_discussion = st["actionable"]["ready_for_gpt"] + st["actionable"]["awaiting_discussion"] + st["open"]
        if newest <= last_seen or not under_discussion:
            return False
        prompt = build_prompt(st)
    try:
        text = ask_model(prompt)
    except Exception as e:  # network or model error: report once in the thread, then wait
        text = None
        err = f"critic could not reach the model at {config.LLM_BASE_URL} ({type(e).__name__}: {e})"
    with db.session() as s:
        if text:
            focus = under_discussion[0]["id"] if under_discussion else None
            service.post_message(s, config.CRITIC_AUTHOR, text, kind="critique", ticket_id=focus)
        else:
            service.post_message(s, "system", err, kind="system")
        service.set_state_value(s, "critic.last_seen_message_id", str(newest))
    return bool(text)


def main() -> None:
    db.init_db()
    print(f"[critic] model {config.LLM_MODEL} at {config.LLM_BASE_URL}, every {config.CRITIC_INTERVAL}s")
    while True:
        try:
            if run_once():
                print("[critic] posted a critique")
        except Exception as e:  # keep the loop alive
            print(f"[critic] error: {type(e).__name__}: {e}")
        time.sleep(config.CRITIC_INTERVAL)


if __name__ == "__main__":
    main()
