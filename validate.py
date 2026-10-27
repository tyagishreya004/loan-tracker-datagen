#!/usr/bin/env python3
"""Validate an exported dataset using ONLY the input tables (never ground truth).

    python validate.py --data data/full

Part 1  structural checks (must pass): schema conformance, PK/unique, FK, enums, ranges,
        id conventions, SQL seed loads into SQLite with foreign keys enforced, no
        ground-truth leakage, no protected attributes used by rules.
Part 2  business-rule checks (violations are *findings*; the dataset deliberately contains
        labelled defects): date ordering, arithmetic reconciliation, lifecycle transitions,
        disbursement prerequisites, duplicate checks, full re-derivation of every
        affordability check and decision from source records.

Findings are written to <data>/reports/detected_issues.csv; evaluate.py scores them
against ground truth.
"""
import argparse
import ast
import csv
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

import rules
import schema

TOL = 0.006
MAX_SAMPLES = 8


class Report:
    def __init__(self):
        self.checks = []          # (group, name, passed, count, samples)
        self.findings = []        # business findings

    def add(self, group, name, errors):
        self.checks.append(dict(group=group, name=name, passed=not errors, violations=len(errors),
                                samples=errors[:MAX_SAMPLES]))

    def finding(self, issue_type, entity, entity_id, app_id, detail):
        self.findings.append(dict(issue_type=issue_type, entity=entity, entity_id=entity_id,
                                  application_id=app_id, detail=detail))


# ------------------------------------------------------------------ loading
def parse(f, raw):
    if raw == "":
        return None
    t = f["type"]
    if t == "int":
        return int(raw)
    if t == "decimal":
        return float(raw)
    if t == "bool":
        if raw not in ("true", "false"):
            raise ValueError(f"bad bool {raw!r}")
        return raw == "true"
    if t == "date":
        date.fromisoformat(raw)
        return raw
    if t == "datetime":
        datetime.fromisoformat(raw)
        return raw
    if t == "json":
        return json.loads(raw)
    return raw


def load(data_dir, rep):
    T, errs = {}, defaultdict(list)
    for name, t in schema.TABLES.items():
        path = os.path.join(data_dir, "csv", schema.snake(name) + ".csv")
        rows = []
        with open(path, encoding="utf-8", newline="") as fh:
            rd = csv.reader(fh)
            header = next(rd)
            if header != schema.field_names(name):
                errs["header"].append(f"{name}: header mismatch")
            for ln, rec in enumerate(rd, 2):
                row = {}
                for f, raw in zip(t["fields"], rec):
                    try:
                        v = parse(f, raw)
                    except Exception as e:      # noqa: BLE001
                        errs["type"].append(f"{name} line {ln} {f['name']}: {e}")
                        v = None
                    if v is None and f["required"]:
                        errs["required"].append(f"{name} line {ln}: {f['name']} is empty")
                    if v is not None:
                        if f["enum"] is not None and v not in f["enum"]:
                            errs["enum"].append(f"{name} line {ln}: {f['name']}={v!r}")
                        if f["range"] and isinstance(v, (int, float)) and not isinstance(v, bool) \
                                and not f["range"][0] <= v <= f["range"][1]:
                            errs["range"].append(f"{name} line {ln}: {f['name']}={v}")
                        if f["pattern"] and not re.match(f["pattern"], str(v)):
                            errs["pattern"].append(f"{name} line {ln}: {f['name']}={v!r}")
                    row[f["name"]] = v
                rows.append(row)
        T[name] = rows
    for k, label in [("header", "csv headers match data dictionary"), ("type", "all values parse to declared type"),
                     ("required", "required fields populated"), ("enum", "values within allowed enums"),
                     ("range", "numeric values within declared ranges"), ("pattern", "id/code patterns")]:
        rep.add("schema", label, errs[k])
    return T


# --------------------------------------------------------------- structural
def structural(T, rep, data_dir):
    pk_err, uq_err, fk_err = [], [], []
    for name, t in schema.TABLES.items():
        seen = set()
        for r in T[name]:
            k = tuple(r[c] for c in t["pk"])
            if k in seen:
                pk_err.append(f"{name}: duplicate PK {k}")
            seen.add(k)
        for f in t["fields"]:
            if f["unique"]:
                vals = [r[f["name"]] for r in T[name] if r[f["name"]] is not None]
                if len(vals) != len(set(vals)):
                    uq_err.append(f"{name}.{f['name']} not unique")
        for col, rt, rc in t["fks"]:
            parent = {r[rc] for r in T[rt]}
            for r in T[name]:
                if r[col] is not None and r[col] not in parent:
                    fk_err.append(f"{name}.{col}={r[col]} has no parent in {rt}.{rc}")
    rep.add("structure", "primary keys unique", pk_err)
    rep.add("structure", "unique constraints hold", uq_err)
    rep.add("structure", "foreign keys resolve (all joins valid)", fk_err)
    # id conventions
    errs = []
    apps = sorted(T["LoanApplication"], key=lambda a: a["application_id"])
    nums = [int(a["application_id"][-6:]) for a in apps]
    if nums != list(range(1, len(nums) + 1)):
        errs.append("application ids are not a contiguous zero-padded counter")
    chrono = [a["submitted_at"] for a in apps]
    if chrono != sorted(chrono):
        errs.append("application ids are not in submission order")
    loans = sorted(a["loan_id"] for a in apps if a["loan_id"])
    if [int(x[-6:]) for x in loans] != list(range(1, len(loans) + 1)):
        errs.append("loan ids are not a contiguous counter")
    for d in T["Document"]:
        if not d["document_id"].startswith(f"DOC-{d['application_id']}-"):
            errs.append(f"{d['document_id']} does not embed {d['application_id']}")
    for tbl, col, pre in [("Decision", "decision_id", "DEC-"), ("AffordabilityCheck", "check_id", "AFC-"),
                          ("ApplicationEvent", "event_id", "EVT-")]:
        for r in T[tbl]:
            if not r[col].startswith(f"{pre}{r['application_id']}-"):
                errs.append(f"{r[col]} does not embed {r['application_id']}")
    for r in T["RepaymentSchedule"]:
        if not r["schedule_id"].startswith(f"SCH-{r['loan_id']}-"):
            errs.append(f"{r['schedule_id']} does not embed {r['loan_id']}")
    for r in T["Disbursement"]:
        if r["disbursement_id"] != f"DSB-{r['loan_id']}":
            errs.append(f"{r['disbursement_id']} != DSB-{r['loan_id']}")
    rep.add("structure", "ID conventions deterministic, immutable-style and consistent", errs)
    # leakage / protected attributes
    leak = [f"{n}.{c}" for n in schema.TABLES for c in schema.field_names(n) if c in schema.GROUND_TRUTH_COLUMNS]
    rep.add("leakage", "no ground-truth columns in input tables", leak)
    used = set()
    for d in T["Decision"]:
        used |= set(d["rule_inputs"].keys())
    rep.add("fairness", "protected attributes absent from every decision's rule_inputs",
            sorted(used & set(schema.PROTECTED_ATTRIBUTES)))
    src = ast.parse(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules.py")).read())
    hits, doc = set(), ast.get_docstring(src)
    for n in ast.walk(src):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value != doc and n.value in schema.PROTECTED_ATTRIBUTES:
            hits.add(n.value)
        if isinstance(n, ast.Name) and n.id in schema.PROTECTED_ATTRIBUTES:
            hits.add(n.id)
    rep.add("fairness", "rules.py never references protected attributes", sorted(hits))
    # SQL seed loads with FK enforcement
    errs = []
    try:
        con = sqlite3.connect(":memory:")
        con.execute("PRAGMA foreign_keys=ON")
        con.executescript(open(os.path.join(data_dir, "sql", "seed.sql"), encoding="utf-8").read())
        bad = con.execute("PRAGMA foreign_key_check").fetchall()
        if bad:
            errs.append(f"{len(bad)} FK violations in SQLite")
        for name in schema.TABLES:
            n = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            if n != len(T[name]):
                errs.append(f"{name}: sql rows {n} != csv rows {len(T[name])}")
    except Exception as e:      # noqa: BLE001
        errs.append(f"seed.sql failed: {e}")
    rep.add("structure", "SQL seed loads into SQLite (CHECK/PK/UNIQUE/FK enforced) and matches CSV counts", errs)


# ------------------------------------------------------------ business rules
def build_world(T):
    W = rules.World(T["LoanProduct"], T["ProductDocumentRequirement"], T["Employment"], T["IncomeRecord"],
                    T["CreditFacility"], T["ApplicantFacility"])
    decs = defaultdict(list)
    for d in T["Decision"]:
        decs[d["application_id"]].append(d)
    for a in T["LoanApplication"]:
        first = min(decs[a["application_id"]], key=lambda d: d["decision_id"], default=None)
        W.add_prior(a, first["decision"] if first else None, first["decided_at"] if first else "9999")
    return W


def docs_as_of(docs, asof):
    latest = {}
    for d in sorted((d for d in docs if d["status_at"] <= asof), key=lambda d: (d["status_at"], d["document_id"])):
        latest[d["document_type"]] = d["status"]
    return latest


def r2(x):
    return Decimal(str(x)).quantize(Decimal("0.01"))


def business(T, rep):
    W = build_world(T)
    apps = {a["application_id"]: a for a in T["LoanApplication"]}
    docs, checks, decs, events = (defaultdict(list) for _ in range(4))
    for d in T["Document"]:
        docs[d["application_id"]].append(d)
    for c in T["AffordabilityCheck"]:
        checks[c["application_id"]].append(c)
    for d in T["Decision"]:
        decs[d["application_id"]].append(d)
    for e in T["ApplicationEvent"]:
        events[e["application_id"]].append(e)
    chk_by_id = {c["check_id"]: c for c in T["AffordabilityCheck"]}
    dec_by_id = {d["decision_id"]: d for d in T["Decision"]}
    F = rep.finding

    # --- date ordering
    errs = []
    for e in T["Employment"]:
        if e["end_date"] and e["end_date"] < e["start_date"]:
            errs.append(f"{e['employment_id']} end<start")
        if e["is_current"] != (e["end_date"] is None):
            errs.append(f"{e['employment_id']} is_current inconsistent")
    cur = defaultdict(int)
    for e in T["Employment"]:
        cur[e["applicant_id"]] += e["end_date"] is None
    errs += [f"{a} has {n} current employments" for a, n in cur.items() if n > 1]
    for f in T["CreditFacility"]:
        if f["closed_date"] and f["closed_date"] < f["opened_date"]:
            errs.append(f"{f['facility_id']} closed<opened")
        if (f["status"] == "CLOSED") != (f["closed_date"] is not None):
            errs.append(f"{f['facility_id']} status/closed_date inconsistent")
    for d in T["Document"]:
        if d["received_at"] and d["status_at"] < d["received_at"]:
            errs.append(f"{d['document_id']} status_at<received_at")
    for p in T["LoanProduct"]:
        if p["min_term_months"] > p["max_term_months"] or p["min_principal"] > p["max_principal"]:
            errs.append(f"{p['product_id']} inverted limits")
    rep.add("business", "master-data date ordering and effective-date sanity", errs)

    errs = []
    for aid, a in apps.items():
        for c in checks[aid]:
            if c["checked_at"] < a["submitted_at"]:
                errs.append(f"{c['check_id']} before submission")
        for d in docs[aid]:
            if d["status_at"] < a["submitted_at"]:
                errs.append(f"{d['document_id']} before submission")
    rep.add("business", "checks and documents never precede submission", errs)

    # --- decision before required checks  (finding)
    n = 0
    for d in T["Decision"]:
        c = chk_by_id[d["check_id"]]
        if d["decided_at"] < c["checked_at"]:
            n += 1
            F("DECISION_BEFORE_REQUIRED_CHECKS", "Decision", d["decision_id"], d["application_id"],
              f"decided_at {d['decided_at']} < {c['check_id']}.checked_at {c['checked_at']}")
    rep.add("business", "[finding] decision never precedes the check it cites", [""] * n)

    # --- product ranges (finding)
    n = 0
    for a in apps.values():
        p = W.products[a["product_id"]]
        if not p["min_term_months"] <= a["requested_term_months"] <= p["max_term_months"]:
            n += 1
            F("TERM_OUTSIDE_PRODUCT_RANGE", "LoanApplication", a["application_id"], a["application_id"],
              f"term {a['requested_term_months']} outside {p['min_term_months']}-{p['max_term_months']} and status={a['status']}")
        if not p["min_principal"] <= a["requested_principal"] <= p["max_principal"]:
            n += 1
            F("PRINCIPAL_OUTSIDE_PRODUCT_RANGE", "LoanApplication", a["application_id"], a["application_id"],
              f"principal {a['requested_principal']} outside product limits")
    rep.add("business", "[finding] term/principal within product range for every application", [""] * n)

    # --- schedule reconciliation (finding)
    sched = defaultdict(list)
    for r in T["RepaymentSchedule"]:
        sched[r["loan_id"]].append(r)
    loan_app = {a["loan_id"]: a for a in apps.values() if a["loan_id"]}
    n = 0
    missing = [l for l in loan_app if l not in sched]
    for loan, rows in sched.items():
        a = loan_app[loan]
        p = W.products[a["product_id"]]
        rows.sort(key=lambda r: r["installment_no"])
        P = int(r2(a["requested_principal"]) * 100)
        rate = Decimal(str(p["annual_rate_pct"])) / Decimal(1200)
        emi = rules.emi_paise(a["requested_principal"], p["annual_rate_pct"], a["requested_term_months"])
        probs = []
        if [r["installment_no"] for r in rows] != list(range(1, a["requested_term_months"] + 1)):
            probs.append("instalment count != term")
        sp = sum(int(r2(r["principal_due"]) * 100) for r in rows)
        if sp != P:
            probs.append(f"sum(principal_due)={sp / 100:.2f} != principal {P / 100:.2f}")
        prev = P
        for r in rows:
            o, pr, i, t, c = (int(r2(r[k]) * 100) for k in ("opening_balance", "principal_due", "interest_due", "total_due", "closing_balance"))
            if o != prev:
                probs.append(f"#{r['installment_no']} opening != previous closing")
            if t != pr + i:
                probs.append(f"#{r['installment_no']} total != principal+interest")
            if c != o - pr:
                probs.append(f"#{r['installment_no']} closing != opening-principal")
            if i != int((Decimal(o) * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)):
                probs.append(f"#{r['installment_no']} interest != opening x rate/12")
            if r["installment_no"] < len(rows) and t != emi:
                probs.append(f"#{r['installment_no']} total != level instalment {emi / 100:.2f}")
            prev = c
        if rows and prev != 0:
            probs.append("final closing balance != 0")
        if any(rows[k]["due_date"] >= rows[k + 1]["due_date"] for k in range(len(rows) - 1)):
            probs.append("due dates not strictly increasing")
        if probs:
            n += 1
            F("SCHEDULE_TOTALS_NOT_RECONCILED", "RepaymentSchedule", loan, a["application_id"], "; ".join(probs[:4]))
    rep.add("business", "[finding] schedules reconcile to principal/interest (every loan)", [""] * n)
    rep.add("business", "every approved loan has a schedule", missing)

    # --- lifecycle
    errs = []
    for aid, a in apps.items():
        ev = sorted(events[aid], key=lambda e: e["event_seq"])
        if [e["event_seq"] for e in ev] != list(range(1, len(ev) + 1)):
            errs.append(f"{aid} event_seq gaps")
            continue
        prev = None
        for e in ev:
            if e["from_status"] != prev:
                errs.append(f"{aid} event {e['event_seq']} from_status {e['from_status']} != previous {prev}")
            if e["to_status"] not in schema.TRANSITIONS.get(prev, []):
                errs.append(f"{aid} illegal transition {prev}->{e['to_status']}")
            prev = e["to_status"]
        if prev != a["status"]:
            errs.append(f"{aid} status {a['status']} != last event {prev}")
        if ev and ev[-1]["event_ts"] != a["status_updated_at"]:
            errs.append(f"{aid} status_updated_at != last event_ts")
        if bool(a["loan_id"]) != (a["status"] in ("APPROVED", "DISBURSED", "CANCELLED")):
            errs.append(f"{aid} loan_id presence inconsistent with status {a['status']}")
    rep.add("lifecycle", "event chains follow legal transitions and match LoanApplication.status", errs)
    errs = []
    for aid in apps:
        ev = sorted(events[aid], key=lambda e: e["event_seq"])
        for x, y in zip(ev, ev[1:]):
            if y["event_ts"] < x["event_ts"]:
                errs.append(f"{aid} event {y['event_seq']} earlier than {x['event_seq']}")
                F("EVENT_TIMESTAMP_ORDER", "ApplicationEvent", y["event_id"], aid, f"{y['event_ts']} < {x['event_ts']}")
    rep.add("lifecycle", "[finding] event timestamps non-decreasing", errs)

    # --- disbursement prerequisites
    errs, disb_by_app = [], {}
    for d in T["Disbursement"]:
        a = apps[d["application_id"]]
        disb_by_app[a["application_id"]] = d
        latest = max(decs[a["application_id"]], key=lambda x: x["decision_id"])
        if latest["decision"] != "APPROVED" or d["eligibility_decision_id"] != latest["decision_id"]:
            errs.append(f"{d['disbursement_id']} not backed by latest APPROVED decision")
        if d["disbursed_at"] < latest["decided_at"]:
            errs.append(f"{d['disbursement_id']} precedes approval")
        if a["loan_id"] != d["loan_id"] or a["status"] != "DISBURSED":
            errs.append(f"{d['disbursement_id']} application not DISBURSED/loan mismatch")
        if abs(d["amount"] - a["requested_principal"]) > TOL:
            errs.append(f"{d['disbursement_id']} amount != principal")
        status = docs_as_of(docs[a["application_id"]], d["disbursed_at"])
        for t in W.required[a["product_id"]]:
            if status.get(t) != "VERIFIED":
                errs.append(f"{d['disbursement_id']} required doc {t} not VERIFIED")
        if d["loan_id"] not in sched:
            errs.append(f"{d['disbursement_id']} no schedule")
    for a in apps.values():
        if a["status"] == "DISBURSED" and a["application_id"] not in disb_by_app:
            errs.append(f"{a['application_id']} DISBURSED without Disbursement row")
        if a["status"] != "DISBURSED" and a["application_id"] in disb_by_app:
            errs.append(f"{a['application_id']} has Disbursement but status {a['status']}")
        if a["status"] in ("APPROVED", "DISBURSED", "CANCELLED"):
            if max(decs[a["application_id"]], key=lambda x: x["decision_id"])["decision"] != "APPROVED":
                errs.append(f"{a['application_id']} approved without APPROVED decision")
    rep.add("lifecycle", "approval and disbursement obey prerequisites", errs)

    # --- duplicates
    by_app = defaultdict(list)
    for d in T["Disbursement"]:
        a = apps[d["application_id"]]
        by_app[a["applicant_id"]].append((a, d))
    n = 0
    for aid_, lst in by_app.items():
        lst.sort(key=lambda x: x[0]["submitted_at"])
        for i in range(len(lst)):
            for j in range(i + 1, len(lst)):
                a, b = lst[i][0], lst[j][0]
                if a["product_id"] == b["product_id"] and abs(a["requested_principal"] - b["requested_principal"]) <= rules.DUP_TOL * a["requested_principal"] \
                        and (rules.pdt(b["submitted_at"]) - rules.pdt(a["submitted_at"])).total_seconds() <= rules.DUP_DAYS * 86400:
                    n += 1
                    F("DUPLICATE_APPLICATION_DISBURSED_TWICE", "Disbursement", lst[j][1]["disbursement_id"], b["application_id"],
                      f"also disbursed {a['application_id']} ({lst[i][1]['disbursement_id']})")
    rep.add("business", "[finding] no duplicate application disbursed twice", [""] * n)
    dup_rejected = sum(1 for d in T["Decision"] if d["rule_id"] == "R01_DUPLICATE")
    rep.checks.append(dict(group="info", name="duplicate submissions caught by rule R01", passed=True,
                           violations=0, samples=[f"{dup_rejected} applications rejected as duplicates"]))

    # --- full re-derivation of checks and decisions
    ch_err, ch_n, dec_err, dec_n = [], 0, [], 0
    fields = ["income_basis", "monthly_income_used", "income_source_count", "income_conflict_flag",
              "existing_obligations_monthly", "proposed_installment", "dti_before_pct", "dti_after_pct",
              "disposable_income_after", "credit_score", "utilisation_pct", "max_dpd_12m", "enquiries_180d",
              "employment_type", "employment_tenure_months", "docs_complete", "rule_version"]
    for aid, a in apps.items():
        for c in sorted(checks[aid], key=lambda c: c["check_id"]):
            smap = docs_as_of(docs[aid], c["checked_at"])
            re_c = rules.build_check(W, a, smap, c["checked_at"])
            diffs = []
            for f in fields:
                x, y = c[f], re_c[f]
                same = (x is None and y is None) or (x is not None and y is not None and
                       (abs(x - y) <= TOL if isinstance(x, float) or isinstance(y, float) and not isinstance(x, bool) else x == y))
                if not same:
                    diffs.append(f"{f}: stored {x} vs recomputed {y}")
            if diffs:
                ch_n += 1
                ch_err.append(f"{c['check_id']}: {diffs[0]}")
                if re_c["income_conflict_flag"] and not c["income_conflict_flag"]:
                    F("INCOME_CONFLICT_ACROSS_SOURCES", "AffordabilityCheck", c["check_id"], aid,
                      "; ".join(diffs[:3]))
                else:
                    F("CHECK_RECOMPUTE_MISMATCH", "AffordabilityCheck", c["check_id"], aid, "; ".join(diffs[:3]))
            d = next((d for d in decs[aid] if d["check_id"] == c["check_id"]), None)
            if d is None:
                dec_err.append(f"{c['check_id']} has no decision")
                continue
            exp = rules.decide(W, a, re_c, smap, c["checked_at"]) if d["decision_id"].endswith("-01") \
                else rules.analyst_decide(W, a, re_c, smap)
            if (d["decision"], d["rule_id"], d["reason_codes"]) != (exp["decision"], exp["rule_id"], "|".join(exp["reasons"])):
                dec_n += 1
                dec_err.append(f"{d['decision_id']}: stored {d['decision']}/{d['rule_id']} vs recomputed {exp['decision']}/{exp['rule_id']}")
                F("DECISION_RECOMPUTE_MISMATCH", "Decision", d["decision_id"], aid,
                  f"stored {d['decision']}/{d['rule_id']}/{d['reason_codes']} vs recomputed {exp['decision']}/{exp['rule_id']}/{'|'.join(exp['reasons'])}")
            cited = d["rule_inputs"]
            if abs(cited.get("dti_after_pct", -1) - c["dti_after_pct"]) > TOL or cited.get("credit_score") != c["credit_score"]:
                dec_err.append(f"{d['decision_id']} rule_inputs do not match cited check")
    rep.add("business", "[finding] affordability checks reproducible from source records", ch_err)
    rep.add("business", "[finding] decisions reproducible by rules and cite exact inputs", dec_err)


# ---------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    a = ap.parse_args()
    rep = Report()
    T = load(a.data, rep)
    structural(T, rep, a.data)
    business(T, rep)
    out = os.path.join(a.data, "reports")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "detected_issues.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, ["issue_type", "entity", "entity_id", "application_id", "detail"], lineterminator="\n")
        w.writeheader()
        for f in sorted(rep.findings, key=lambda f: (f["issue_type"], f["entity_id"])):
            w.writerow(f)
    structural_groups = {"schema", "structure", "leakage", "fairness"}
    hard = [c for c in rep.checks if c["group"] in structural_groups or (c["group"] in ("lifecycle", "business") and "[finding]" not in c["name"])]
    summary = dict(structural_failures=sum(1 for c in hard if not c["passed"]), checks=rep.checks,
                   findings_by_type={t: sum(1 for f in rep.findings if f["issue_type"] == t)
                                     for t in sorted({f["issue_type"] for f in rep.findings})})
    with open(os.path.join(out, "validation_report.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
    lines = ["# Validation summary", "", "| Group | Check | Result | Violations |", "|---|---|---|---|"]
    for c in rep.checks:
        tag = "PASS" if c["passed"] else ("FINDING" if "[finding]" in c["name"] else "FAIL")
        lines.append(f"| {c['group']} | {c['name']} | {tag} | {c['violations']} |")
    lines += ["", "`FINDING` = deliberate, labelled defect surfaced by the validator (scored by evaluate.py).", "",
              "Findings by type: " + json.dumps(summary["findings_by_type"])]
    with open(os.path.join(out, "validation_summary.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nstructural/hard failures: {summary['structural_failures']}")
    sys.exit(1 if summary["structural_failures"] else 0)


if __name__ == "__main__":
    main()
