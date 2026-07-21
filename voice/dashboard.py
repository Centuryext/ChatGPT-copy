"""
Call center dashboard.

Serves a live view of campaigns, call outcomes, durations, recordings, and
transcripts from the shared Postgres `calls` table.

Run:  uvicorn dashboard:app --host 0.0.0.0 --port 8080
Open: http://localhost:8080
"""
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text

from db import get_engine

app = FastAPI()


@app.get("/api/stats")
async def stats(campaign: str | None = None):
    where = "WHERE campaign=:c" if campaign else ""
    params = {"c": campaign} if campaign else {}
    with get_engine().connect() as conn:
        total = conn.execute(text(f"SELECT count(*) FROM calls {where}"), params).scalar()
        completed = conn.execute(text(
            f"SELECT count(*) FROM calls {where + (' AND' if where else 'WHERE')} status='completed'"),
            params).scalar()
        booked = conn.execute(text(
            f"SELECT count(*) FROM calls {where + (' AND' if where else 'WHERE')} outcome='booked'"),
            params).scalar()
        total_min = conn.execute(text(
            f"SELECT COALESCE(sum(duration_sec),0)/60.0 FROM calls {where}"), params).scalar()
    return {"total": total, "completed": completed, "booked": booked,
            "connect_rate": round((completed / total * 100) if total else 0, 1),
            "book_rate": round((booked / completed * 100) if completed else 0, 1),
            "total_minutes": round(total_min or 0, 1)}


@app.get("/api/campaigns")
async def campaigns():
    with get_engine().connect() as conn:
        rows = conn.execute(text(
            "SELECT campaign, count(*) n FROM calls GROUP BY campaign ORDER BY n DESC")).all()
    return [{"campaign": r[0], "count": r[1]} for r in rows]


@app.get("/api/calls")
async def calls(campaign: str | None = None, limit: int = 100):
    where = "WHERE campaign=:c" if campaign else ""
    params = {"c": campaign, "l": limit} if campaign else {"l": limit}
    with get_engine().connect() as conn:
        rows = conn.execute(text(
            f"SELECT id,campaign,name,phone,status,outcome,duration_sec,recording_url,"
            f"transcript,created_at FROM calls {where} ORDER BY created_at DESC LIMIT :l"),
            params).mappings().all()
    return JSONResponse([dict(r) | {"created_at": str(r["created_at"])} for r in rows])


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML


HTML = """
<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>AI Call Center</title>
<style>
:root{--bg:#0b0e14;--card:#151a23;--line:#232a36;--fg:#e6eaf0;--mut:#8a94a6;--ok:#3fb950;--acc:#54aeff}
*{box-sizing:border-box}body{margin:0;font:14px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg)}
header{padding:18px 24px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:16px}
h1{font-size:18px;margin:0}select{background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:6px 10px}
main{padding:24px;max-width:1100px;margin:0 auto}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin-bottom:24px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
.stat .v{font-size:26px;font-weight:700}.stat .l{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);font-size:13px}
th{color:var(--mut);font-weight:600}tr:last-child td{border-bottom:none}
.badge{padding:2px 8px;border-radius:999px;font-size:12px;background:#1f2733}
.badge.completed{color:var(--ok)}.badge.booked{background:#12351f;color:var(--ok)}
a{color:var(--acc)}.tx{cursor:pointer;color:var(--acc)}
dialog{background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:12px;max-width:640px;width:90%}
dialog pre{white-space:pre-wrap;font:13px/1.6 ui-monospace,monospace}
.mut{color:var(--mut)}
</style></head><body>
<header><h1>📞 AI Call Center</h1>
<select id=camp onchange=load()><option value="">All campaigns</option></select>
<span class=mut id=updated></span></header>
<main>
<div class=grid id=stats></div>
<table><thead><tr><th>Contact</th><th>Phone</th><th>Campaign</th><th>Status</th>
<th>Outcome</th><th>Dur</th><th>Recording</th><th>Transcript</th><th>Time</th></tr></thead>
<tbody id=rows></tbody></table>
</main>
<dialog id=dlg><pre id=dlgtx></pre><br><form method=dialog><button>Close</button></form></dialog>
<script>
async function j(u){return (await fetch(u)).json()}
function q(){const c=document.getElementById('camp').value;return c?('?campaign='+encodeURIComponent(c)):''}
async function loadCampaigns(){const cs=await j('/api/campaigns');const s=document.getElementById('camp');
 cs.forEach(c=>{const o=document.createElement('option');o.value=c.campaign;o.textContent=c.campaign+' ('+c.count+')';s.appendChild(o)})}
async function load(){
 const st=await j('/api/stats'+q());
 document.getElementById('stats').innerHTML=[
  ['Total calls',st.total],['Connected',st.completed],['Booked',st.booked],
  ['Connect rate',st.connect_rate+'%'],['Book rate',st.book_rate+'%'],['Talk minutes',st.total_minutes]
 ].map(([l,v])=>`<div class=stat><div class=v>${v}</div><div class=l>${l}</div></div>`).join('');
 const cs=await j('/api/calls'+q());
 document.getElementById('rows').innerHTML=cs.map(c=>`<tr>
  <td>${c.name||'-'}</td><td>${c.phone}</td><td>${c.campaign}</td>
  <td><span class="badge ${c.status}">${c.status}</span></td>
  <td>${c.outcome?`<span class="badge booked">${c.outcome}</span>`:'-'}</td>
  <td>${c.duration_sec?Math.round(c.duration_sec)+'s':'-'}</td>
  <td>${c.recording_url?`<a href="${c.recording_url}" target=_blank>▶</a>`:'-'}</td>
  <td>${c.transcript?`<span class=tx onclick='showTx(${JSON.stringify(c.transcript)})'>view</span>`:'-'}</td>
  <td class=mut>${c.created_at?.slice(0,19).replace('T',' ')||''}</td></tr>`).join('');
 document.getElementById('updated').textContent='updated '+new Date().toLocaleTimeString();
}
function showTx(t){document.getElementById('dlgtx').textContent=t;document.getElementById('dlg').showModal()}
loadCampaigns();load();setInterval(load,5000);
</script></body></html>
"""
