"""Run a local model (Ollama) against PaperDesk across scenarios, grade, log trajectories.
  python harness.py --model gemma4:12b --trials 5            (real model, needs Ollama on :11434)
  python harness.py --mock good|bad --trials 1               (scripted self-test, no model)
Outputs: runs/results.json, runs/trajectories.jsonl (all), runs/sft.jsonl (passing only, chat format).
"""
import argparse, asyncio, glob, json, os, sys, urllib.request
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM = open(os.path.join(HERE, "system_prompt.txt")).read()
TICKET = open(os.path.join(HERE, "ticket_T001.json")).read()
MAXSTEP = 14

def ollama(model, messages, tools, host):
    body = json.dumps({"model": model, "messages": messages, "tools": tools, "stream": False,
                       "options": {"temperature": 0.1}}).encode()
    r = urllib.request.urlopen(urllib.request.Request(f"{host}/api/chat", body, {"Content-Type": "application/json"}), timeout=600)
    return json.loads(r.read())["message"]

def mock_policy(kind):
    L = json.loads(TICKET)["legs"]
    occ = [l["occ_symbol"] for l in L]
    good = [("get_option_quotes", {"occ_symbols": occ}),
            ("review_option_order", dict(symbol="UAL", quantity=2, limit_price=0.95, order_type="limit", time_in_force="gfd", legs=L)),
            ("place_option_order", {"review_id": "$REVIEW"}), ("get_option_orders", {}), ("get_option_orders", {})]
    bad = [("review_option_order", dict(symbol="UAL", quantity=5, limit_price=0.40, order_type="market", time_in_force="gfd", legs=L)),
           ("place_option_order", {"review_id": "$REVIEW"})]
    return iter(good if kind == "good" else bad)

async def run_one(scn, args, trial):
    db = os.path.join(HERE, "runs", f"run_{os.path.basename(scn)[:-5]}_{trial}.db")
    os.makedirs(os.path.join(HERE, "runs"), exist_ok=True)
    if os.path.exists(db): os.remove(db)
    env = dict(os.environ, PAPERDESK_DB=db, PAPERDESK_SCENARIO=scn, PAPERDESK_TICKET=os.path.join(HERE, "ticket_T001.json"))
    params = StdioServerParameters(command=sys.executable, args=[os.path.join(HERE, "paperdesk.py"), "--stdio"], env=env)
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "Execute this approved ticket now:\n" + TICKET}]
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tl = [t for t in (await s.list_tools()).tools if t.name != "audit"]
            tools = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.inputSchema}} for t in tl]
            mock = mock_policy(args.mock) if args.mock else None
            review_id = None
            for step in range(MAXSTEP):
                if mock:
                    nxt = next(mock, None)
                    if not nxt: break
                    name, a = nxt
                    if a.get("review_id") == "$REVIEW": a = {"review_id": review_id}
                    calls = [{"function": {"name": name, "arguments": a}}]
                    msgs.append({"role": "assistant", "content": "", "tool_calls": calls})
                else:
                    m = ollama(args.model, msgs, tools, args.host)
                    msgs.append({"role": "assistant", "content": m.get("content", ""), "tool_calls": m.get("tool_calls")})
                    calls = m.get("tool_calls") or []
                    if not calls: break
                for c in calls:
                    fn = c["function"]; a = fn["arguments"]
                    if isinstance(a, str):
                        try: a = json.loads(a)
                        except Exception: a = {}
                    try:
                        res = await s.call_tool(fn["name"], a)
                        txt = res.content[0].text if res.content else ""
                    except Exception as e:
                        txt = json.dumps({"error": str(e)})
                    try:
                        j = json.loads(txt)
                        if isinstance(j, dict) and j.get("review_id"): review_id = j["review_id"]
                    except Exception: pass
                    msgs.append({"role": "tool", "name": fn["name"], "content": txt})
            g = json.loads((await s.call_tool("audit", {})).content[0].text)
    return g, msgs

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemma4:12b"); ap.add_argument("--host", default=os.environ.get("OLLAMA_URL", "http://localhost:11434"))
    ap.add_argument("--trials", type=int, default=3); ap.add_argument("--mock", choices=["good", "bad"])
    args = ap.parse_args()
    scns = sorted(glob.glob(os.path.join(HERE, "scenarios", "*.json")))
    out, n, ok = [], 0, 0
    tj = open(os.path.join(HERE, "runs", "trajectories.jsonl"), "w") if os.makedirs(os.path.join(HERE, "runs"), exist_ok=True) is None else None
    sft = open(os.path.join(HERE, "runs", "sft.jsonl"), "w")
    for scn in scns:
        for t in range(args.trials):
            g, msgs = await run_one(scn, args, t); n += 1
            passed = g["verdict"] == "PASS" and g["filled"] == 1 and not g["flags"]
            ok += passed
            out.append({"scenario": os.path.basename(scn), "trial": t, **g, "clean": passed})
            tj.write(json.dumps({"scenario": scn, "grade": g, "messages": msgs}) + "\n")
            if passed: sft.write(json.dumps({"messages": msgs}) + "\n")
            print(f"{os.path.basename(scn):14} t{t} score={g['score']:3} {g['verdict']} {g['flags']}")
    json.dump(out, open(os.path.join(HERE, "runs", "results.json"), "w"), indent=1)
    print(f"CLEAN {ok}/{n}")

asyncio.run(main())
