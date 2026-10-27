#!/usr/bin/env python3
"""Local web viewer (stdlib only):  python viewer.py --data data/starter  ->  http://localhost:8000"""
import argparse, csv, json, os
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Loan Tracker Viewer</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--tx:#1a1d21;--mu:#6b7280;--bd:#e2e5ea;--ac:#2563eb;--bad:#dc2626;--ok:#16a34a;--warn:#d97706}
@media(prefers-color-scheme:dark){:root{--bg:#14161a;--card:#1d2026;--tx:#e8eaed;--mu:#9aa0a8;--bd:#2c3037;--ac:#60a5fa;--bad:#f87171;--ok:#4ade80;--warn:#fbbf24}}
*{box-sizing:border-box}body{margin:0;font:14px system-ui,sans-serif;background:var(--bg);color:var(--tx)}
header{padding:14px 20px;border-bottom:1px solid var(--bd);background:var(--card)}h1{margin:0;font-size:17px}
main{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);gap:14px;padding:14px;max-width:1500px;margin:auto}
@media(max-width:900px){main{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:12px;overflow:auto}
h2{margin:0 0 8px;font-size:14px}.kpis{display:flex;gap:8px;flex-wrap:wrap}.k{border:1px solid var(--bd);border-radius:6px;padding:6px 10px}
.k b{display:block;font-size:18px}table{border-collapse:collapse;width:100%;font-size:12.5px}th,td{text-align:left;padding:4px 6px;border-bottom:1px solid var(--bd);white-space:nowrap}
tr.r{cursor:pointer}tr.r:hover{background:var(--bg)}input,select{padding:5px;border:1px solid var(--bd);border-radius:5px;background:var(--bg);color:var(--tx)}
.tag{padding:1px 6px;border-radius:9px;font-size:11px;border:1px solid var(--bd)}.APPROVED,.DISBURSED,.VERIFIED,.PAID{color:var(--ok)}.REJECTED,.MISSING,.OVERDUE,.bad{color:var(--bad)}.MANUAL_REVIEW,.CANCELLED,.warn{color:var(--warn)}
pre{margin:0;white-space:pre-wrap;font-size:12px;color:var(--mu)}.mu{color:var(--mu)}
</style></head><body>
<header><h1>Loan Application Tracker — data viewer</h1><div class="mu">Synthetic data · click an application to trace documents → check → decision → events → schedule</div></header>
<main><div>
<div class="card" id="sum"></div><div style="height:14px"></div>
<div class="card"><h2>Applications</h2><div style="display:flex;gap:6px;margin-bottom:8px;flex-wrap:wrap">
<input id="q" placeholder="search id / applicant" ><select id="st"><option value="">all statuses</option></select>
<select id="an"><option value="">all</option><option value="1">injected defects only</option></select></div>
<div style="max-height:520px;overflow:auto"><table id="tb"></table></div></div></div>
<div class="card" id="det"><h2>Trace</h2><div class="mu">Select an application.</div></div></main>
<script>
const $=s=>document.querySelector(s),j=u=>fetch(u).then(r=>r.json()),esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const tg=v=>`<span class="tag ${esc(v)}">${esc(v)}</span>`,tbl=(rows,cols)=>rows.length?`<table><tr>${cols.map(c=>`<th>${c}</th>`).join('')}</tr>${rows.map(r=>`<tr>${cols.map(c=>`<td>${['status','decision'].includes(c)?tg(r[c]):esc(r[c])}</td>`).join('')}</tr>`).join('')}</table>`:'<div class="mu">none</div>';
let A=[];
function list(){const q=$('#q').value.toLowerCase(),s=$('#st').value,a=$('#an').value;
 const r=A.filter(x=>(!q||x.id.toLowerCase().includes(q)||x.applicant.toLowerCase().includes(q))&&(!s||x.status==s)&&(!a||x.issue)).slice(0,300);
 $('#tb').innerHTML=`<tr><th>id</th><th>product</th><th>principal</th><th>term</th><th>status</th><th>defect</th></tr>`+r.map(x=>`<tr class="r" onclick="show('${x.id}')"><td>${x.id}</td><td>${x.product.slice(4)}</td><td>${(+x.principal).toLocaleString()}</td><td>${x.term}</td><td>${tg(x.status)}</td><td class="bad">${esc(x.issue)}</td></tr>`).join('')}
async function show(id){const d=await j('/api/app?id='+id),a=d.application,s=d.schedule,g=d.ground_truth;
 $('#det').innerHTML=`<h2>${a.application_id} ${tg(a.status)} <span class="mu">${a.loan_id||''}</span></h2>
 <p class="mu">${a.applicant_id} · ${a.product_id} · ${(+a.requested_principal).toLocaleString()} INR · ${a.requested_term_months} months · ${a.channel}</p>
 <h2>Documents</h2>${tbl(d.documents,['document_id','document_type','status','status_at'])}
 <h2 style="margin-top:10px">Affordability checks</h2>${tbl(d.checks.map(c=>({check:c.check_id,income:c.monthly_income_used,basis:c.income_basis,'DTI after %':c.dti_after_pct,score:c.credit_score,tenure:c.employment_tenure_months,docs_ok:c.docs_complete,conflict:c.income_conflict_flag})),['check','income','basis','DTI after %','score','tenure','docs_ok','conflict'])}
 <h2 style="margin-top:10px">Decisions (with cited rule inputs)</h2>${d.decisions.map(x=>`<p>${x.decision_id} ${tg(x.decision)} <b>${x.rule_id}</b> by ${x.decided_by} at ${x.decided_at}<br><span class="mu">${x.reason_codes}</span></p><pre>${esc(JSON.stringify(x.rule_inputs))}</pre>`).join('')}
 <h2 style="margin-top:10px">Event history</h2>${tbl(d.events,['event_seq','event_type','from_status','to_status','event_ts','actor'])}
 <h2 style="margin-top:10px">Repayment schedule</h2><p>${s.rows} instalments · Σprincipal ${s.sum_principal.toLocaleString()} vs requested ${s.requested.toLocaleString()} → <b class="${s.reconciles?'APPROVED':'bad'}">${s.rows?(s.reconciles?'reconciles':'DOES NOT RECONCILE'):'n/a'}</b></p>${s.rows?tbl(s.first,['installment_no','due_date','principal_due','interest_due','total_due','closing_balance','status']):''}
 <h2 style="margin-top:10px">Validator findings</h2>${tbl(d.validator_findings,['issue_type','detail'])}
 <h2 style="margin-top:10px">Ground truth (separate file)</h2><pre>${esc(JSON.stringify(g,null,1))}</pre>`}
j('/api/summary').then(m=>{const st=m.application_status,ad=m.anomaly_detection;
 $('#sum').innerHTML=`<h2>Summary</h2><div class="kpis">${Object.entries(st).map(([k,v])=>`<div class="k">${k}<b>${v}</b></div>`).join('')}<div class="k">baseline decision agreement<b>${m.decision_agreement.baseline_agreement}</b></div><div class="k">unexplained findings<b>${m.unexplained_findings.count}</b></div></div>
 <h2 style="margin-top:10px">Defect detection (validator vs ground truth)</h2>${tbl(Object.entries(ad).map(([k,v])=>({defect:k,labelled:v.labelled,detected:v.detected,precision:v.precision,recall:v.recall})),['defect','labelled','detected','precision','recall'])}`;
 Object.keys(st).forEach(k=>$('#st').insertAdjacentHTML('beforeend',`<option>${k}</option>`))});
j('/api/apps').then(r=>{A=r;list()});['#q','#st','#an'].forEach(s=>$(s).addEventListener('input',list));
</script></body></html>
"""


def rd(p):
    with open(p, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def group(rows, key):
    g = defaultdict(list)
    for r in rows:
        g[r[key]].append(r)
    return g


def load(d):
    c = lambda n: rd(os.path.join(d, "csv", n + ".csv"))
    D = dict(apps=c("loan_application"), docs=group(c("document"), "application_id"),
             checks=group(c("affordability_check"), "application_id"), decs=group(c("decision"), "application_id"),
             events=group(c("application_event"), "application_id"), sched=group(c("repayment_schedule"), "application_id"),
             disb=group(c("disbursement"), "application_id"),
             gt={r["application_id"]: r for r in rd(os.path.join(d, "ground_truth", "ground_truth.csv"))},
             metrics=json.load(open(os.path.join(d, "reports", "metrics.json"), encoding="utf-8")))
    D["det"] = rd(os.path.join(d, "reports", "detected_issues.csv"))
    return D


def make_handler(D):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, body, ctype="application/json"):
            b = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/":
                return self.send(HTML.encode("utf-8"), "text/html")
            if u.path == "/api/summary":
                return self.send(D["metrics"])
            if u.path == "/api/apps":
                return self.send([dict(id=a["application_id"], applicant=a["applicant_id"], product=a["product_id"],
                                       principal=a["requested_principal"], term=a["requested_term_months"], status=a["status"],
                                       issue=D["gt"][a["application_id"]]["issue_type"]) for a in D["apps"]])
            if u.path == "/api/app":
                i = parse_qs(u.query).get("id", [""])[0]
                app = next((a for a in D["apps"] if a["application_id"] == i), None)
                if not app:
                    return self.send(dict(error="not found"))
                s = D["sched"].get(i, [])
                sp = round(sum(float(r["principal_due"]) for r in s), 2)
                return self.send(dict(application=app, documents=D["docs"].get(i, []), checks=D["checks"].get(i, []),
                                      decisions=[dict(d, rule_inputs=json.loads(d["rule_inputs"])) for d in D["decs"].get(i, [])],
                                      events=D["events"].get(i, []), disbursement=D["disb"].get(i, []),
                                      schedule=dict(rows=len(s), sum_principal=sp, requested=float(app["requested_principal"]),
                                                    reconciles=abs(sp - float(app["requested_principal"])) < 0.01, first=s[:6]),
                                      ground_truth=D["gt"][i],
                                      validator_findings=[f for f in D["det"] if f["application_id"] == i]))
            self.send_response(404)
            self.end_headers()
    return H


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/starter")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    D = load(a.data)
    print(f"Serving {a.data} at http://localhost:{a.port}  (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(D)).serve_forever()
