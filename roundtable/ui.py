"""The board: one static page that talks to /api with the shared token."""

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stock Roundtable</title>
<style>
  :root { --bg:#0f1115; --panel:#171a21; --line:#262b35; --text:#e6e8ee; --muted:#8b93a7; --accent:#4f8cff;
          --green:#2ecc71; --red:#ff5c5c; --amber:#f5b342; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text); font:14px/1.45 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; }
  header { display:flex; align-items:center; gap:12px; padding:12px 16px; border-bottom:1px solid var(--line); position:sticky; top:0; background:var(--bg); z-index:2; }
  header h1 { font-size:16px; margin:0; }
  header .stamp { color:var(--muted); font-size:12px; margin-left:auto; }
  .tiles { display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:8px; padding:12px 16px; }
  .tile { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:10px 12px; }
  .tile .k { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.04em; }
  .tile .v { font-size:20px; font-weight:600; margin-top:2px; }
  .pos { color:var(--green); } .neg { color:var(--red); }
  main { display:grid; grid-template-columns:1fr 1fr; gap:12px; padding:0 16px 24px; }
  @media (max-width: 900px) { main { grid-template-columns:1fr; } }
  section { background:var(--panel); border:1px solid var(--line); border-radius:8px; min-height:200px; display:flex; flex-direction:column; }
  section h2 { font-size:13px; margin:0; padding:10px 12px; border-bottom:1px solid var(--line); color:var(--muted); text-transform:uppercase; letter-spacing:.04em; }
  .thread { padding:8px 12px; overflow:auto; max-height:70vh; flex:1; }
  .msg { padding:8px 10px; margin:6px 0; border-radius:8px; background:#1e222b; border-left:3px solid var(--line); }
  .msg.claude { border-left-color:#c77dff; } .msg.gpt { border-left-color:#19c37d; } .msg.critic { border-left-color:var(--amber); }
  .msg.shawn { border-left-color:var(--accent); } .msg.system { border-left-color:#555; }
  .msg .meta { color:var(--muted); font-size:11px; margin-bottom:3px; }
  .msg .meta b { color:var(--text); text-transform:capitalize; }
  .msg .kind { display:inline-block; font-size:10px; padding:0 6px; border:1px solid var(--line); border-radius:10px; margin-left:6px; }
  .msg .text { white-space:pre-wrap; word-break:break-word; }
  form.post { display:flex; gap:6px; padding:8px 12px; border-top:1px solid var(--line); }
  form.post select, form.post input, form.post button { background:#0f1115; color:var(--text); border:1px solid var(--line); border-radius:6px; padding:8px; font-size:14px; }
  form.post input { flex:1; min-width:0; }
  form.post button { background:var(--accent); border-color:var(--accent); color:#fff; }
  .tickets { padding:8px 12px; overflow:auto; max-height:70vh; }
  .ticket { border:1px solid var(--line); border-radius:8px; padding:10px; margin:6px 0; background:#1e222b; }
  .ticket .top { display:flex; align-items:center; gap:8px; }
  .ticket .id { font-weight:700; }
  .badge { font-size:11px; padding:1px 8px; border-radius:10px; border:1px solid var(--line); color:var(--muted); }
  .badge.ready, .badge.close_ready { color:var(--amber); border-color:var(--amber); }
  .badge.open, .badge.placed { color:var(--green); border-color:var(--green); }
  .badge.closed { color:var(--muted); } .badge.rejected, .badge.cancelled, .badge.expired { color:var(--red); border-color:var(--red); }
  .ticket .legs { color:var(--muted); font-size:12px; margin:4px 0; }
  .ticket .nums { display:grid; grid-template-columns:repeat(auto-fit,minmax(90px,1fr)); gap:4px 10px; font-size:12px; margin-top:6px; }
  .ticket .nums span { color:var(--muted); }
  .ticket .actions { margin-top:8px; display:flex; gap:6px; flex-wrap:wrap; }
  .ticket .actions button { font-size:12px; padding:4px 8px; background:#0f1115; color:var(--text); border:1px solid var(--line); border-radius:6px; cursor:pointer; }
  .muted { color:var(--muted); }
  #gate { padding:24px 16px; }
  #gate input { font-size:16px; padding:8px; width:100%; max-width:420px; }
</style>
</head>
<body>
<header><h1>Stock Roundtable</h1><span class="stamp" id="stamp"></span></header>
<div id="gate" hidden>
  <p>Enter the roundtable token (from <code>.env</code>, <code>ROUNDTABLE_TOKEN</code>). It stays in this browser only.</p>
  <input id="tok" placeholder="token"> <button onclick="saveTok()">Open</button>
</div>
<div id="app" hidden>
  <div class="tiles" id="tiles"></div>
  <main>
    <section>
      <h2>Thread</h2>
      <div class="thread" id="thread"></div>
      <form class="post" onsubmit="return post(event)">
        <select id="author"><option>shawn</option><option>claude</option><option>gpt</option></select>
        <select id="kind"><option>note</option><option>decision</option><option>vote</option><option>alert</option></select>
        <input id="text" placeholder="Say something to the table" autocomplete="off">
        <button type="submit">Post</button>
      </form>
    </section>
    <section>
      <h2>Tickets</h2>
      <div class="tickets" id="tickets"></div>
    </section>
  </main>
</div>
<script>
const TZ = "__TZ__";
const qs = new URLSearchParams(location.search);
if (qs.get("token")) { localStorage.setItem("rt_token", qs.get("token")); history.replaceState({}, "", location.pathname); }
let token = localStorage.getItem("rt_token") || "";
const money = v => v == null ? "–" : (v < 0 ? "-" : "") + "$" + Math.abs(v).toLocaleString(undefined,{maximumFractionDigits:2});
const pct = v => v == null ? "–" : (v*100).toFixed(1) + "%";
const when = iso => iso ? new Date(iso).toLocaleString("en-US",{timeZone:TZ, month:"short", day:"numeric", hour:"numeric", minute:"2-digit"}) : "";
const esc = s => (s||"").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function saveTok(){ token = document.getElementById("tok").value.trim(); localStorage.setItem("rt_token", token); boot(); }
const BASE = location.pathname.endsWith("/") ? location.pathname : location.pathname + "/";
async function api(path, opts={}) {
  const r = await fetch(BASE + path.replace(/^\//, ""), {...opts, headers: {"Authorization":"Bearer "+token, "Content-Type":"application/json", ...(opts.headers||{})}});
  if (r.status === 401) { localStorage.removeItem("rt_token"); token=""; boot(); throw new Error("bad token"); }
  return r.json();
}
function tile(k, v, cls="") { return `<div class="tile"><div class="k">${k}</div><div class="v ${cls}">${v}</div></div>`; }
function render(s) {
  const sm = s.summary;
  document.getElementById("stamp").textContent = "updated " + when(s.server_time_utc) + " " + (TZ==="America/Chicago"?"CT":TZ);
  document.getElementById("tiles").innerHTML =
    tile("Realized P&L", money(sm.realized_pnl_usd), sm.realized_pnl_usd>0?"pos":sm.realized_pnl_usd<0?"neg":"") +
    tile("Unrealized", money(sm.unrealized_pnl_usd), sm.unrealized_pnl_usd>0?"pos":sm.unrealized_pnl_usd<0?"neg":"") +
    tile("Win rate", sm.closed ? pct(sm.win_rate) + ` (${sm.wins}-${sm.losses})` : "–") +
    tile("Open risk", money(sm.open_max_loss_usd)) +
    tile("Open", sm.open_tickets) + tile("Ready for GPT", sm.ready_tickets + sm.close_ready_tickets, (sm.ready_tickets+sm.close_ready_tickets)?"pos":"");
  const th = document.getElementById("thread");
  th.innerHTML = s.recent_messages.map(m => `<div class="msg ${esc(m.author)}"><div class="meta"><b>${esc(m.author)}</b> · ${when(m.created_at)}${m.ticket_id?" · "+esc(m.ticket_id):""}<span class="kind">${esc(m.kind)}</span></div><div class="text">${esc(m.text)}</div></div>`).join("");
  th.scrollTop = th.scrollHeight;
  const all = [...s.actionable.ready_for_gpt, ...s.actionable.close_ready_for_gpt, ...s.open, ...s.actionable.awaiting_discussion, ...(s.recent_closed||[])];
  const seen = new Set();
  document.getElementById("tickets").innerHTML = all.filter(t => !seen.has(t.id) && seen.add(t.id)).map(t => {
    const legs = t.legs.map(l => `${l.side==="sell"?"S":"L"} ${l.strike}${l.option_type[0].toUpperCase()}`).join(" / ");
    const pnl = t.realized_pnl_usd ?? t.unrealized_pnl_usd;
    const acts = {proposed:["ready","rejected"], ready:["placed","proposed","cancelled"], placed:["ready","cancelled"], open:["close_ready"], close_ready:["open"]}[t.status]||[];
    return `<div class="ticket"><div class="top"><span class="id">${esc(t.id)}</span><span class="badge ${esc(t.status)}">${esc(t.status)}</span><span>${esc(t.underlying)} · ${esc(t.strategy.replace(/_/g," "))}</span></div>
      <div class="legs">${legs} · exp ${esc(t.expiry)} · ${t.contracts}x · ${t.entry_type} ${t.limit_price.toFixed(2)}${t.fallback_price?` → ${t.fallback_price.toFixed(2)}`:""}${t.floor_price?` (floor ${t.floor_price.toFixed(2)})`:""}</div>
      <div class="nums"><div><span>max loss</span><br>${money(t.max_loss_usd)}</div><div><span>max gain</span><br>${money(t.max_gain_usd)}</div><div><span>breakeven</span><br>${t.breakeven_px??"–"}</div><div><span>target / stop</span><br>${money(t.profit_target_usd)} / ${money(t.stop_loss_usd)}</div>${t.entry_net_price!=null?`<div><span>entry net</span><br>${t.entry_net_price.toFixed(2)}</div>`:""}${pnl!=null?`<div><span>P&amp;L</span><br><b class="${pnl>0?"pos":pnl<0?"neg":""}">${money(pnl)}</b></div>`:""}</div>
      ${t.exit_rules?`<div class="muted" style="margin-top:6px;font-size:12px">${esc(t.exit_rules)}</div>`:""}
      <div class="actions">${acts.map(a=>`<button onclick="setStatus('${t.id}','${a}')">${a.replace(/_/g," ")}</button>`).join("")}</div></div>`;
  }).join("") || '<p class="muted">No tickets yet.</p>';
}
async function refresh(){ try { render(await api("/api/state")); } catch(e) { console.warn(e); } }
async function post(ev){ ev.preventDefault(); const text=document.getElementById("text").value.trim(); if(!text) return false;
  await api("/api/messages",{method:"POST",body:JSON.stringify({author:document.getElementById("author").value,kind:document.getElementById("kind").value,text})});
  document.getElementById("text").value=""; refresh(); return false; }
async function setStatus(id, status){ const reason = prompt(`${id} → ${status}. Reason (optional):`) ?? null; if(reason===null) return;
  const r = await api(`/api/tickets/${id}/status`,{method:"POST",body:JSON.stringify({author:"shawn",status,reason})}); if(r.error) alert(r.error); refresh(); }
function boot(){ const has = !!token; document.getElementById("gate").hidden = has; document.getElementById("app").hidden = !has; if (has) refresh(); }
boot(); setInterval(() => { if (token) refresh(); }, 10000);
</script>
</body>
</html>
"""


def page(display_tz: str) -> str:
    return PAGE.replace("__TZ__", display_tz)
