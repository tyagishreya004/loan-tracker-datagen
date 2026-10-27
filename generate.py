#!/usr/bin/env python3
"""Synthetic loan-origination data generator (stdlib only, fully deterministic).

    python generate.py --profile full    --out data/full      # 10,000 applicants / 6,000 applications
    python generate.py --profile starter --out data/starter   # 500 / 300, same code path

Pipeline
  A  master data   : LoanProduct, Applicant, Employment, IncomeRecord, CreditFacility (+bridges)
  B  plan          : application requests (baseline incl. legitimate duplicates / re-applications)
  C  baseline pass : documents -> affordability check -> decision (-> manual-review resolution)
                     -> approval/disbursement plan.  All outcomes come from rules.py.
  D  injection     : labelled edge cases that need a *faulty* pipeline run (term range,
                     income conflict ignored, duplicate disbursed twice)
  E  loans         : LOAN ids, repayment schedules, disbursements
  F  injection     : post-hoc labelled defects (schedule totals, decision before checks)
  G  ground truth  : expected decisions + anomaly labels -> separate directory
  H  finalize      : chronological APP ids, validation of ids, export CSV/JSON/SQL/manifest
"""
import argparse
import csv
import hashlib
import json
import math
import os
import random
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

import rules
import schema
from rules import add_months, build_schedule, pdate, pdt

GENERATOR_VERSION = "1.0.0"
DEFAULT_SEED = 20261022
SNAPSHOT = "2026-10-22T00:00:00"          # fixed "now": no wall-clock dependence
REF_DATE = date(2025, 12, 31)             # master data is as of this date
WINDOW_START = date(2026, 1, 5)
WINDOW_END = date(2026, 9, 30)

PROFILES = {"full": (10000, 6000), "starter": (500, 300)}

PRODUCTS = [  # id, name, min_p, max_p, min_t, max_t, rate, max_dti, min_score, min_disposable, share
    ("PRD-PERSONAL", "Personal Loan", 50000, 1500000, 12, 60, 13.50, 45, 650, 10000, 0.40),
    ("PRD-AUTO", "Auto Loan", 200000, 2500000, 12, 84, 9.50, 50, 630, 12000, 0.25),
    ("PRD-HOMEIMP", "Home Improvement Loan", 100000, 2000000, 12, 84, 10.75, 50, 640, 12000, 0.20),
    ("PRD-EDUCATION", "Education Loan", 100000, 3000000, 12, 120, 9.00, 55, 620, 10000, 0.15),
]
REQUIRED_DOCS = {
    "PRD-PERSONAL": ["ID_PROOF", "ADDRESS_PROOF", "INCOME_PROOF"],
    "PRD-AUTO": ["ID_PROOF", "ADDRESS_PROOF", "INCOME_PROOF", "VEHICLE_QUOTE"],
    "PRD-HOMEIMP": ["ID_PROOF", "ADDRESS_PROOF", "INCOME_PROOF", "CONTRACTOR_QUOTE"],
    "PRD-EDUCATION": ["ID_PROOF", "ADDRESS_PROOF", "INCOME_PROOF", "ADMISSION_LETTER"],
}
TERM_CHOICES = {
    "PRD-PERSONAL": ([12, 24, 36, 48, 60], [.15, .30, .30, .12, .13]),
    "PRD-AUTO": ([24, 36, 48, 60, 72, 84], [.10, .20, .25, .25, .10, .10]),
    "PRD-HOMEIMP": ([12, 24, 36, 48, 60, 84], [.10, .25, .25, .15, .15, .10]),
    "PRD-EDUCATION": ([12, 24, 36, 60, 84, 120], [.05, .15, .20, .30, .15, .15]),
}
INCOME_MULT = {"PRD-PERSONAL": 3.5, "PRD-AUTO": 9, "PRD-HOMEIMP": 5.5, "PRD-EDUCATION": 8}
PURPOSE_BY_PRODUCT = {
    "PRD-PERSONAL": ["DEBT_CONSOLIDATION", "MEDICAL", "TRAVEL", "WEDDING", "OTHER_PERSONAL"],
    "PRD-AUTO": ["NEW_VEHICLE", "USED_VEHICLE"],
    "PRD-HOMEIMP": ["RENOVATION", "REPAIR", "SOLAR_INSTALL"],
    "PRD-EDUCATION": ["TUITION", "STUDY_ABROAD"],
}
FIRST = ["Aarav", "Vivaan", "Aditya", "Arjun", "Rohan", "Karan", "Ishaan", "Rahul", "Amit", "Vikram", "Sanjay",
         "Anil", "Manoj", "Deepak", "Suresh", "Ananya", "Diya", "Priya", "Neha", "Pooja", "Kavya", "Sneha",
         "Riya", "Meera", "Sunita", "Anjali", "Divya", "Nisha", "Farhan", "Imran", "Zoya", "Ayesha", "Harpreet",
         "Gurpreet", "Lakshmi", "Venkat", "Ramesh", "Kiran", "Sourav", "Debashis"]
LAST = ["Sharma", "Verma", "Gupta", "Singh", "Kumar", "Patel", "Reddy", "Nair", "Iyer", "Das", "Mehta", "Jain",
        "Khan", "Ansari", "Chauhan", "Yadav", "Mishra", "Pandey", "Joshi", "Bose", "Banerjee", "Rao", "Menon",
        "Kapoor", "Malhotra", "Sethi", "Saxena", "Tiwari", "Agarwal", "Bhatt"]
EMP_WORDS = ["Apex", "Nova", "Zenith", "Orbit", "Vertex", "Lumen", "Prime", "Axis", "Delta", "Summit", "Helix",
             "Vanguard", "Pioneer", "Crest", "Aurora"]
EMP_SUFFIX = ["Logistics", "Technologies", "Foods", "Textiles", "Healthcare", "Constructions", "Retail",
              "Consulting", "Motors", "Education", "Agro", "Finserv"]
LENDERS = ["Alpha Bank", "Bharat Finance", "Civic Credit", "Delta Housing", "Evergreen NBFC", "Fortune Bank",
           "Garuda Capital", "Horizon Lending"]
REGIONS = (["UP", "MH", "DL", "KA", "TN", "GJ", "RJ", "WB", "TS", "AP", "KL", "PB", "HR", "MP", "BR"],
           [.15, .13, .08, .08, .08, .07, .06, .07, .05, .04, .04, .03, .03, .05, .04])


# ----------------------------------------------------------------- utilities
def R(seed, stage):
    return random.Random(f"{seed}:{stage}")


def iso(dt):
    return dt.replace(microsecond=0).isoformat()


def wchoice(rng, items, weights):
    return rng.choices(items, weights=weights, k=1)[0]


def rand_dt(rng, d0, d1):
    """Random working-hours timestamp between two dates."""
    days = (d1 - d0).days
    d = d0 + timedelta(days=rng.randint(0, days))
    return datetime(d.year, d.month, d.day, rng.randint(8, 20), rng.randint(0, 59), rng.randint(0, 59))


def round_to(x, base):
    return int(round(x / base) * base)


# ============================================================== A. master data
def gen_products():
    rows = []
    for pid, name, mn, mx, tmn, tmx, rate, dti, score, disp, _ in PRODUCTS:
        rows.append(dict(product_id=pid, product_name=name, min_principal=mn, max_principal=mx,
                         min_term_months=tmn, max_term_months=tmx, annual_rate_pct=rate, max_dti_pct=dti,
                         min_credit_score=score, min_disposable_income=disp,
                         effective_from="2026-01-01", effective_to=None, status="ACTIVE"))
    reqs = [dict(product_id=p, document_type=d, is_mandatory=True)
            for p, docs in REQUIRED_DOCS.items() for d in docs]
    return rows, reqs


def gen_masters(seed, n_app):
    rng = R(seed, "masters")
    T = defaultdict(list)
    latent = {}
    T["LoanProduct"], T["ProductDocumentRequirement"] = gen_products()
    emp_n = inc_n = fac_n = 0
    for i in range(1, n_app + 1):
        aid = f"APL-{i:06d}"
        age = int(min(64, max(21, rng.gauss(36, 9))))
        dob = REF_DATE - timedelta(days=age * 365 + rng.randint(0, 364))
        T["Applicant"].append(dict(
            applicant_id=aid, full_name=f"{rng.choice(FIRST)} {rng.choice(LAST)}", date_of_birth=dob.isoformat(),
            gender=wchoice(rng, schema.GENDER, [.42, .56, .02]),
            marital_status=wchoice(rng, schema.MARITAL, [.35, .55, .07, .03]),
            region_code=wchoice(rng, *REGIONS),
            customer_since=(date(2018, 1, 1) + timedelta(days=rng.randint(0, 2900))).isoformat()))
        # ---- employment history
        etype = wchoice(rng, ["SALARIED", "SELF_EMPLOYED", "CONTRACT", "UNEMPLOYED"], [.62, .19, .13, .06])
        base = rng.lognormvariate(math.log(45000), 0.55) * {"SALARIED": 1.0, "SELF_EMPLOYED": 1.1,
                                                              "CONTRACT": 0.9, "UNEMPLOYED": 0.35}[etype]
        base = round(min(400000, max(8000, base)), -2)
        min_start = dob + timedelta(days=int(20 * 365.25))
        if rng.random() < 0.28:
            tenure = rng.uniform(0.5, 11)
        else:
            tenure = max(6.0, rng.lognormvariate(math.log(36), 0.7))
        n_hist = wchoice(rng, [0, 1, 2], [.45, .35, .20])
        cur_start = max(min_start + timedelta(days=200), REF_DATE - timedelta(days=int(tenure * 30.4)))
        cur_start = min(cur_start, REF_DATE - timedelta(days=30))
        emps = []

        def new_emp(kind, start, end):
            nonlocal emp_n
            emp_n += 1
            e = dict(employment_id=f"EMP-{emp_n:06d}", applicant_id=aid,
                     employer_name=f"{rng.choice(EMP_WORDS)} {rng.choice(EMP_SUFFIX)} Pvt Ltd",
                     employment_type=kind, start_date=start.isoformat(),
                     end_date=end.isoformat() if end else None, is_current=end is None)
            T["Employment"].append(e)
            return e

        if etype == "UNEMPLOYED":
            last_end = REF_DATE - timedelta(days=rng.randint(30, 540))
            start = max(min_start, last_end - timedelta(days=rng.randint(180, 1500)))
            if start >= last_end:                       # very young applicant: keep a valid, ordered interval
                last_end = min(REF_DATE - timedelta(days=30), start + timedelta(days=rng.randint(120, 400)))
            new_emp(wchoice(rng, schema.EMP_TYPES, [.6, .2, .2]), start, last_end)
            cur = None
        else:
            cur = new_emp(etype, cur_start, None)
            prev_end = cur_start - timedelta(days=rng.randint(0, 180))
            for _ in range(n_hist):
                start = prev_end - timedelta(days=rng.randint(365, 1800))
                if start < min_start:
                    break
                new_emp(wchoice(rng, schema.EMP_TYPES, [.6, .2, .2]), start, prev_end)
                prev_end = start - timedelta(days=rng.randint(0, 180))
        latent[aid] = dict(base_income=base, etype=etype)
        # ---- income evidence (append-only; one row per source)
        def new_inc(src, val, ver):
            nonlocal inc_n
            inc_n += 1
            T["IncomeRecord"].append(dict(
                income_id=f"INC-{inc_n:06d}", applicant_id=aid,
                employment_id=cur["employment_id"] if cur else None,
                source=src, monthly_income=round(val, 2), verification_status=ver,
                recorded_date=(date(2025, 9, 1) + timedelta(days=rng.randint(0, 120))).isoformat()))
        new_inc("DECLARED", base * rng.uniform(1.0, 1.10), "UNVERIFIED")
        if cur:
            p = {"SALARIED": [.88, .82, .20], "CONTRACT": [.55, .80, .15], "SELF_EMPLOYED": [0, .78, .70]}[etype]
            for src, pr in zip(["PAYSLIP", "BANK_STATEMENT", "TAX_RETURN"], p):
                if rng.random() < pr:
                    noise = max(-0.08, min(0.08, rng.gauss(0, 0.035)))
                    new_inc(src, base * (1 + noise), "VERIFIED" if rng.random() < 0.96 else "UNVERIFIED")
        # ---- facilities
        n = wchoice(rng, [0, 1, 2, 3, 4, 5], [.18, .25, .25, .17, .10, .05])
        if n:
            rho = rng.uniform(.45, .75) if rng.random() < .08 else min(.85, rng.betavariate(1.3, 7))
            total = rho * base
            w = [rng.random() + .2 for _ in range(n)]
            sw = sum(w)
            facs = []
            for k in range(n):
                fac_n += 1
                ftype = wchoice(rng, schema.FAC_TYPES, [.38, .17, .12, .12, .21])
                obl = max(500.0, round(total * w[k] / sw, 0))
                months_back = rng.randint(3, 120)
                opened = REF_DATE - timedelta(days=int(months_back * 30.4))
                closed = rng.random() < .22
                if ftype == "CREDIT_CARD":
                    util = max(.05, min(.98, rng.betavariate(2, 3)))
                    bal = obl / 0.05
                    limit = max(10000.0, round(bal / util, -3))
                    bal = min(bal, limit)
                    obl = round(0.05 * bal, 2)
                    sanc = limit
                else:
                    m = {"PERSONAL_LOAN": (6, 48), "AUTO_LOAN": (12, 72), "HOME_LOAN": (60, 240), "BNPL": (2, 9)}[ftype]
                    bal = obl * rng.randint(*m) * 0.85
                    sanc = bal / rng.uniform(.4, .95)
                cdate = None
                if closed:
                    cdate = min(REF_DATE, opened + timedelta(days=rng.randint(180, 1800)))
                    if cdate <= opened:
                        closed, cdate = False, None
                facs.append(dict(facility_id=f"FAC-{fac_n:06d}", facility_type=ftype, lender_name=rng.choice(LENDERS),
                                 sanctioned_amount=round(sanc, 2), outstanding_balance=0.0 if closed else round(bal, 2),
                                 monthly_obligation=0.0 if closed else round(obl, 2), max_dpd_12m=0,
                                 status="CLOSED" if closed else "ACTIVE", opened_date=opened.isoformat(),
                                 closed_date=cdate.isoformat() if cdate else None))
            u = rng.random()
            dpd = 0 if u < .74 else 30 if u < .87 else 60 if u < .95 else 90
            if dpd:
                rng.choice(facs)["max_dpd_12m"] = dpd
            for f in facs:
                T["CreditFacility"].append(f)
                if rng.random() < .04 and n_app > 1:     # joint facility -> N:M bridge row
                    other = f"APL-{rng.randint(1, n_app):06d}"
                    if other != aid:
                        T["ApplicantFacility"].append(dict(applicant_id=aid, facility_id=f["facility_id"], role="PRIMARY", share_pct=50))
                        T["ApplicantFacility"].append(dict(applicant_id=other, facility_id=f["facility_id"], role="JOINT", share_pct=50))
                        continue
                T["ApplicantFacility"].append(dict(applicant_id=aid, facility_id=f["facility_id"], role="PRIMARY", share_pct=100))
    return T, latent


# ================================================================ B. planning
def make_request(rng, latent, pid, prod_by_id):
    p = prod_by_id[pid]
    terms, w = TERM_CHOICES[pid]
    term = wchoice(rng, terms, w)
    mult = rng.lognormvariate(math.log(INCOME_MULT[pid]), 0.55)
    principal = round_to(latent["base_income"] * mult, 5000)
    principal = max(p["min_principal"], min(p["max_principal"], principal))
    return principal, term


def new_app(rng, aid, pid, principal, term, submitted_at):
    return dict(application_id=None, applicant_id=aid, product_id=pid, requested_principal=float(principal),
                requested_term_months=term, purpose=rng.choice(PURPOSE_BY_PRODUCT[pid]),
                channel=wchoice(rng, schema.CHANNELS, [.6, .2, .2]), submitted_at=iso(submitted_at),
                status="SUBMITTED", status_updated_at=iso(submitted_at), loan_id=None)


def plan_baseline(seed, S, n_apps, n_base, perm):
    rng = R(seed, "plan")
    pids = [p[0] for p in PRODUCTS]
    pw = [p[10] for p in PRODUCTS]
    n_dup = round(0.02 * n_apps)
    n_reapp = round(0.03 * n_apps)
    n_orig = n_base - n_dup - n_reapp
    prim = []
    for i in range(n_orig):
        aid = perm[i]
        pid = wchoice(rng, pids, pw)
        pr, term = make_request(rng, S.latent[aid], pid, S.world.products)
        prim.append(new_app(rng, aid, pid, pr, term, rand_dt(rng, WINDOW_START, WINDOW_END)))
    extra = []
    for o in rng.sample(prim, n_dup):                                  # legitimate duplicate submissions
        t = pdt(o["submitted_at"]) + timedelta(hours=rng.uniform(12, 120))
        pr = min(S.world.products[o["product_id"]]["max_principal"],
                 max(S.world.products[o["product_id"]]["min_principal"], round_to(o["requested_principal"] * rng.uniform(.97, 1.03), 1000)))
        extra.append(new_app(rng, o["applicant_id"], o["product_id"], pr, o["requested_term_months"], t))
    early = [a for a in prim if pdt(a["submitted_at"]) < datetime(2026, 4, 25)]
    for o in rng.sample(early, min(n_reapp, len(early))):             # genuine re-application later
        t = pdt(o["submitted_at"]) + timedelta(days=rng.randint(30, 150), hours=rng.randint(0, 5))
        pid = wchoice(rng, pids, pw)
        pr, term = make_request(rng, S.latent[o["applicant_id"]], pid, S.world.products)
        extra.append(new_app(rng, o["applicant_id"], pid, pr, term, t))
    allapps = sorted(prim + extra, key=lambda a: a["submitted_at"])
    return allapps, perm[n_orig:]


# ============================================================ C. case builder
class State:
    pass


def draw_doc_status(rng, dtype):
    p = {"ID_PROOF": (.97, .015), "INCOME_PROOF": (.91, .07)}.get(dtype, (.96, .02))
    u = rng.random()
    return "VERIFIED" if u < p[0] else "MISSING" if u < p[0] + p[1] else "REJECTED"


def build_case(S, app, rng, bypass=frozenset()):
    W = S.world
    aid = app["application_id"]
    req = W.required[app["product_id"]]
    t0 = pdt(app["submitted_at"])
    docs, smap, last = [], {}, t0
    for i, dt in enumerate(req, 1):
        st = draw_doc_status(rng, dt)
        if st == "MISSING":
            rec, at = None, t0 + timedelta(minutes=rng.uniform(120, 1800))
        else:
            rec = (t0 + timedelta(minutes=rng.uniform(0, 1200))).replace(microsecond=0)
            at = rec + timedelta(minutes=rng.uniform(60, 600))
        at = at.replace(microsecond=0)
        docs.append(dict(document_id=f"DOC-{aid}-{i:03d}", application_id=aid, document_type=dt, status=st,
                         received_at=iso(rec) if rec else None, status_at=iso(at), supersedes_document_id=None))
        smap[dt] = st
        last = max(last, at)
    t_chk = (last + timedelta(minutes=rng.uniform(5, 90))).replace(microsecond=0)
    asof = iso(t_chk)
    check1 = dict(check_id=f"AFC-{aid}-01", application_id=aid, checked_at=asof,
                  **rules.build_check(W, app, smap, asof, bypass))
    dec1 = rules.decide(W, app, check1, smap, asof, bypass)
    expected = dec1
    if bypass:
        exp_check = rules.build_check(W, app, smap, asof)
        expected = rules.decide(W, app, exp_check, smap, asof)
    t_dec = (t_chk + timedelta(minutes=rng.uniform(1, 10))).replace(microsecond=0)

    def drow(n, check, d, ts, by, sup):
        return dict(decision_id=f"DEC-{aid}-{n:02d}", application_id=aid, check_id=check["check_id"],
                    decided_at=iso(ts), decision=d["decision"], rule_id=d["rule_id"],
                    reason_codes="|".join(d["reasons"]), rule_inputs=d["inputs"], decided_by=by,
                    supersedes_decision_id=sup)

    checks = [check1]
    decisions = [drow(1, check1, dec1, t_dec, "SYSTEM", None)]
    ev = [("SUBMITTED", None, "SUBMITTED", t0, "APPLICANT", None),
          ("REVIEW_STARTED", "SUBMITTED", "UNDER_REVIEW", t_chk, "SYSTEM", check1["check_id"]),
          ("DECISION_MADE", "UNDER_REVIEW", dec1["decision"], t_dec, "SYSTEM", decisions[0]["decision_id"])]
    final, final_ts, final_dec = dec1["decision"], t_dec, decisions[0]
    if dec1["decision"] == "MANUAL_REVIEW" and rng.random() < 0.70:      # analyst resolution
        smap2, tmax, nxt = dict(smap), t_dec + timedelta(hours=rng.uniform(6, 72)), len(docs) + 1
        for d in list(docs):
            if d["status"] != "VERIFIED":
                if rng.random() < 0.85:
                    rec = (t_dec + timedelta(hours=rng.uniform(6, 72))).replace(microsecond=0)
                    at = (rec + timedelta(hours=rng.uniform(1, 8))).replace(microsecond=0)
                    docs.append(dict(document_id=f"DOC-{aid}-{nxt:03d}", application_id=aid, document_type=d["document_type"],
                                     status="VERIFIED", received_at=iso(rec), status_at=iso(at),
                                     supersedes_document_id=d["document_id"]))
                    nxt += 1
                    smap2[d["document_type"]] = "VERIFIED"
                    tmax = max(tmax, at)
        t_chk2 = (tmax + timedelta(minutes=rng.uniform(5, 60))).replace(microsecond=0)
        check2 = dict(check_id=f"AFC-{aid}-02", application_id=aid, checked_at=iso(t_chk2),
                      **rules.build_check(W, app, smap2, iso(t_chk2)))
        dec2 = rules.analyst_decide(W, app, check2, smap2)
        t_dec2 = (t_chk2 + timedelta(minutes=rng.uniform(10, 240))).replace(microsecond=0)
        by = f"ANALYST-{rng.randint(1, 8):02d}"
        checks.append(check2)
        decisions.append(drow(2, check2, dec2, t_dec2, by, decisions[0]["decision_id"]))
        ev.append(("MANUAL_REVIEW_RESOLVED", "MANUAL_REVIEW", dec2["decision"], t_dec2, by, decisions[1]["decision_id"]))
        final, final_ts, final_dec = dec2["decision"], t_dec2, decisions[1]
    events = [dict(event_type=a, from_status=b, to_status=c, event_ts=iso(d), actor=e, ref_id=f)
              for a, b, c, d, e, f in ev]
    case = dict(app=app, docs=docs, checks=checks, decisions=decisions, events=events, expected=expected,
                first_decision=dec1["decision"], first_decided_at=iso(t_dec), approved=final == "APPROVED",
                approved_at=iso(final_ts) if final == "APPROVED" else None,
                approving_decision_id=final_dec["decision_id"] if final == "APPROVED" else None,
                disburse_at=None, final_status=final, final_ts=final_ts, final_event=None)
    if final == "APPROVED":                                           # post-approval path
        u = rng.random()
        cancel_ts = final_ts + timedelta(days=rng.uniform(1, 4))
        disb_ts = (final_ts + timedelta(days=rng.uniform(1, 5))).replace(hour=10, minute=rng.randint(0, 59), second=0, microsecond=0)
        if u < 0.07 and iso(cancel_ts) <= SNAPSHOT:
            case["final_status"], case["final_ts"] = "CANCELLED", cancel_ts.replace(microsecond=0)
            events.append(dict(event_type="CANCELLED", from_status="APPROVED", to_status="CANCELLED",
                               event_ts=iso(case["final_ts"]), actor="APPLICANT", ref_id=None))
        elif iso(disb_ts) <= SNAPSHOT:
            case["final_status"], case["final_ts"], case["disburse_at"] = "DISBURSED", disb_ts, iso(disb_ts)
            ev_d = dict(event_type="DISBURSED", from_status="APPROVED", to_status="DISBURSED",
                        event_ts=iso(disb_ts), actor="SYSTEM", ref_id=None)
            events.append(ev_d)
            case["final_event"] = ev_d
    return case


def commit_case(S, case):
    app = case["app"]
    app["status"], app["status_updated_at"] = case["final_status"], iso(case["final_ts"])
    S.T["LoanApplication"].append(app)
    S.T["Document"].extend(case["docs"])
    S.T["AffordabilityCheck"].extend(case["checks"])
    S.T["Decision"].extend(case["decisions"])
    for n, e in enumerate(case["events"], 1):
        e.update(event_id=f"EVT-{app['application_id']}-{n:02d}", application_id=app["application_id"], event_seq=n)
        S.T["ApplicationEvent"].append(e)
    S.world.add_prior(app, case["first_decision"], case["first_decided_at"])
    S.cases[app["application_id"]] = case


def next_tmp(S):
    S.tmp += 1
    return f"APP-TMP-{S.tmp:06d}"


# ======================================================= D. labelled injection
def inject_slot_anomalies(seed, S, k, pool):
    rng = R(seed, "inject_slots")
    pids = [p[0] for p in PRODUCTS]
    pw = [p[10] for p in PRODUCTS]
    pool = list(pool)
    used_orig = set()
    S.anoms = []

    def pick_applicant(need=lambda a: True):
        for _ in range(500):
            a = rng.choice(pool)
            if need(a):
                return a
        return None

    # D1 TERM_OUTSIDE_PRODUCT_RANGE: approved although term violates product range (R00 bypassed)
    for _ in range(k):
        for attempt in range(600):
            aid = pick_applicant()
            pid = wchoice(rng, pids, pw)
            prod = S.world.products[pid]
            pr, _t = make_request(rng, S.latent[aid], pid, S.world.products)
            term = rng.choice([prod["max_term_months"] + 12, prod["max_term_months"] + 24,
                               prod["max_term_months"] + 6, prod["min_term_months"] - 6])
            app = new_app(rng, aid, pid, pr, term, rand_dt(rng, WINDOW_START, WINDOW_END))
            app["application_id"] = next_tmp(S)
            case = build_case(S, app, rng, frozenset({"TERM_RANGE"}))
            if case["first_decision"] == "APPROVED" and case["final_status"] == "DISBURSED":
                commit_case(S, case)
                pool.remove(aid)
                S.anoms.append(dict(type="TERM_OUTSIDE_PRODUCT_RANGE", app=app["application_id"],
                                    note=f"term {term}m outside {prod['min_term_months']}-{prod['max_term_months']}m but approved and scheduled"))
                break
            S.tmp -= 1
        else:
            S.warn.append("could not place TERM anomaly")

    # D2 INCOME_CONFLICT_ACROSS_SOURCES: conflicting evidence ignored, higher income used
    def has_verified(a):
        return any(r["source"] in rules.VERIFIED_SOURCES and r["verification_status"] == "VERIFIED" for r in S.world.inc[a])

    for _ in range(k):
        for attempt in range(800):
            aid = pick_applicant(has_verified)
            have = {r["source"] for r in S.world.inc[aid] if r["verification_status"] == "VERIFIED"}
            free = [s for s in rules.VERIFIED_SOURCES if s not in have]
            if not free:
                continue
            pid = wchoice(rng, pids, pw)
            pr, term = make_request(rng, S.latent[aid], pid, S.world.products)
            app = new_app(rng, aid, pid, pr, term, rand_dt(rng, WINDOW_START, WINDOW_END))
            app["application_id"] = next_tmp(S)
            vals = [r["monthly_income"] for r in S.world.inc[aid] if r["source"] in rules.VERIFIED_SOURCES and r["verification_status"] == "VERIFIED"]
            cur = next((e for e in S.world.emp[aid] if e["end_date"] is None), None)
            extra = dict(income_id=f"INC-{S.inc_n + 1:06d}", applicant_id=aid,
                         employment_id=cur["employment_id"] if cur else None, source=rng.choice(free),
                         monthly_income=round(min(vals) * rng.uniform(1.4, 1.8), 2), verification_status="VERIFIED",
                         recorded_date=app["submitted_at"][:10])
            S.world.inc[aid].append(extra)
            case = build_case(S, app, rng, frozenset({"INCOME_CONFLICT"}))
            if case["first_decision"] == "APPROVED" and case["expected"]["decision"] != "APPROVED":
                S.inc_n += 1
                S.T["IncomeRecord"].append(extra)
                commit_case(S, case)
                pool.remove(aid)
                S.anoms.append(dict(type="INCOME_CONFLICT_ACROSS_SOURCES", app=app["application_id"],
                                    note=f"{extra['source']} income {extra['monthly_income']} vs lowest verified {min(vals)}; conflict ignored, higher income used"))
                break
            S.world.inc[aid].pop()
            S.tmp -= 1
        else:
            S.warn.append("could not place INCOME_CONFLICT anomaly")

    # D3 DUPLICATE_APPLICATION_DISBURSED_TWICE: duplicate bypasses R01 and is disbursed as well
    flagged = {a["app"] for a in S.anoms}
    cands = [c for c in S.cases.values() if c["final_status"] == "DISBURSED"
             and c["app"]["application_id"] not in flagged
             and len(S.world.prior[c["app"]["applicant_id"]]) == 1]
    rng.shuffle(cands)
    done = 0
    for c in cands:
        if done >= k:
            break
        o = c["app"]
        prod = S.world.products[o["product_id"]]
        for attempt in range(6):
            t = pdt(o["submitted_at"]) + timedelta(days=rng.uniform(1, 5), hours=rng.uniform(0, 8))
            pr = min(prod["max_principal"], max(prod["min_principal"], round_to(o["requested_principal"] * rng.uniform(.97, 1.03), 1000)))
            app = new_app(rng, o["applicant_id"], o["product_id"], pr, o["requested_term_months"], t)
            app["application_id"] = next_tmp(S)
            case = build_case(S, app, rng, frozenset({"DUPLICATE"}))
            if case["first_decision"] == "APPROVED" and case["final_status"] == "DISBURSED" \
                    and case["expected"]["rule_id"] == "R01_DUPLICATE":
                commit_case(S, case)
                S.anoms.append(dict(type="DUPLICATE_APPLICATION_DISBURSED_TWICE", app=app["application_id"],
                                    note=f"duplicate of {o['application_id']} (same applicant/product, principal within 10%) approved and disbursed again"))
                done += 1
                break
            S.tmp -= 1
    if done < k:
        S.warn.append(f"placed only {done}/{k} DUPLICATE_DISBURSED anomalies")


# ============================================ E. loans, schedules, disbursement
def build_loans(seed, S):
    rng = R(seed, "loans")
    approved = sorted((c for c in S.cases.values() if c["approved"]), key=lambda c: (c["approved_at"], c["app"]["application_id"]))
    for n, c in enumerate(approved, 1):
        app = c["app"]
        loan = f"LOAN-2026-{n:06d}"
        app["loan_id"] = loan
        prod = S.world.products[app["product_id"]]
        disb = c["disburse_at"]
        start = pdate(disb) if disb else (pdt(c["approved_at"]) + timedelta(days=3)).date()
        sched = build_schedule(app["requested_principal"], prod["annual_rate_pct"], app["requested_term_months"], start)
        cancelled = c["final_status"] == "CANCELLED"
        miss_from = None
        if disb and rng.random() < 0.04:
            miss_from = rng.randint(2, 12)
        for r in sched:
            if cancelled:
                st = "CANCELLED"
            elif disb and r["due_date"] <= SNAPSHOT[:10]:
                st = "OVERDUE" if (miss_from and r["installment_no"] >= miss_from) else "PAID"
            else:
                st = "SCHEDULED"
            S.T["RepaymentSchedule"].append(dict(
                schedule_id=f"SCH-{loan}-{r['installment_no']:03d}", loan_id=loan, application_id=app["application_id"],
                installment_no=r["installment_no"], due_date=r["due_date"], opening_balance=r["opening"] / 100,
                principal_due=r["principal"] / 100, interest_due=r["interest"] / 100, total_due=r["total"] / 100,
                closing_balance=r["closing"] / 100, status=st))
        if disb:
            did = f"DSB-{loan}"
            S.T["Disbursement"].append(dict(disbursement_id=did, loan_id=loan, application_id=app["application_id"],
                                            eligibility_decision_id=c["approving_decision_id"],
                                            amount=app["requested_principal"], disbursed_at=disb, status="DISBURSED"))
            c["final_event"]["ref_id"] = did


# ===================================================== F. post-hoc injection
def inject_posthoc(seed, S, k):
    rng = R(seed, "inject_posthoc")
    flagged = {a["app"] for a in S.anoms}
    by_loan = defaultdict(list)
    for r in S.T["RepaymentSchedule"]:
        by_loan[r["loan_id"]].append(r)
    cands = sorted(l for l, rows in by_loan.items() if len(rows) >= 12 and rows[0]["application_id"] not in flagged)
    for loan in rng.sample(cands, min(k, len(cands))):
        rows = by_loan[loan]
        row = rows[rng.randint(3, len(rows) - 3)]
        delta = rng.randint(500, 5000)
        row["principal_due"] = round(row["principal_due"] + delta, 2)
        row["total_due"] = round(row["total_due"] + delta, 2)      # row still adds up; schedule as a whole does not
        flagged.add(row["application_id"])
        S.anoms.append(dict(type="SCHEDULE_TOTALS_NOT_RECONCILED", app=row["application_id"], entity="RepaymentSchedule",
                            entity_id=row["schedule_id"], note=f"principal_due of instalment {row['installment_no']} inflated by {delta}"))
    dec_by_app = {d["application_id"]: d for d in S.T["Decision"] if d["decision_id"].endswith("-01")}
    chk_by_id = {c["check_id"]: c for c in S.T["AffordabilityCheck"]}
    cands = sorted(a for a, d in dec_by_app.items() if d["decision"] == "APPROVED" and a not in flagged)
    for a in rng.sample(cands, min(k, len(cands))):
        d = dec_by_app[a]
        chk = chk_by_id[d["check_id"]]
        new = pdt(chk["checked_at"]) - timedelta(minutes=rng.uniform(5, 60))
        d["decided_at"] = iso(new)
        for e in S.T["ApplicationEvent"]:
            if e["application_id"] == a and e["event_type"] == "DECISION_MADE":
                e["event_ts"] = iso(new)
        flagged.add(a)
        S.anoms.append(dict(type="DECISION_BEFORE_REQUIRED_CHECKS", app=a, entity="Decision", entity_id=d["decision_id"],
                            note=f"decision timestamp moved before affordability check {chk['check_id']}"))


# ===================================================== G. ground truth labels
def build_ground_truth(S):
    anom = {a["app"]: a for a in S.anoms}
    dsb = {d["application_id"]: d["disbursement_id"] for d in S.T["Disbursement"]}
    rows = []
    for app in S.T["LoanApplication"]:
        aid = app["application_id"]
        c = S.cases[aid]
        prod = S.world.products[app["product_id"]]
        ex = c["expected"]
        chk = c["checks"][0]
        tags = []
        if not all(d["status"] == "VERIFIED" for d in c["docs"] if d["document_type"] == "INCOME_PROOF" and d["supersedes_document_id"] is None):
            tags.append("MISSING_INCOME_PROOF")
        if chk["dti_after_pct"] > prod["max_dti_pct"]:
            tags.append("HIGH_DEBT_BURDEN")
        t = chk["employment_tenure_months"]
        if t < rules.UNSTABLE_MONTHS or (chk["employment_type"] == "CONTRACT" and t < rules.UNSTABLE_CONTRACT_MONTHS):
            tags.append("UNSTABLE_EMPLOYMENT")
        if ex["rule_id"] == "R01_DUPLICATE":
            tags.append("DUPLICATE_APPLICATION")
        if abs(chk["credit_score"] - prod["min_credit_score"]) <= 15:
            tags.append("BORDERLINE_SCORE")
        if abs(chk["dti_after_pct"] - prod["max_dti_pct"]) <= 3:
            tags.append("BORDERLINE_DTI")
        if chk["income_conflict_flag"] or (aid in anom and anom[aid]["type"] == "INCOME_CONFLICT_ACROSS_SOURCES"):
            tags.append("INCOME_CONFLICT")
        a = anom.get(aid)
        ent, eid = "", ""
        if a:
            ent = a.get("entity")
            eid = a.get("entity_id")
            if a["type"] == "TERM_OUTSIDE_PRODUCT_RANGE":
                ent, eid = "LoanApplication", aid
            elif a["type"] == "INCOME_CONFLICT_ACROSS_SOURCES":
                ent, eid = "AffordabilityCheck", c["checks"][0]["check_id"]
            elif a["type"] == "DUPLICATE_APPLICATION_DISBURSED_TWICE":
                ent, eid = "Disbursement", dsb[aid]
        rows.append(dict(application_id=aid, expected_first_decision=ex["decision"], expected_rule_id=ex["rule_id"],
                         expected_reason_codes="|".join(ex["reasons"]), scenario_tags="|".join(tags) if tags else "CLEAN",
                         is_anomaly=bool(a), issue_type=a["type"] if a else "", issue_entity=ent or "",
                         issue_entity_id=eid or "", issue_note=a["note"] if a else ""))
    return rows


# ========================================================= H. finalize + export
def finalize_ids(S, gt_rows):
    apps = sorted(S.T["LoanApplication"], key=lambda a: (a["submitted_at"], a["application_id"]))
    mp = {a["application_id"][-6:]: f"{n:06d}" for n, a in enumerate(apps, 1)}
    rx = re.compile(r"APP-TMP-(\d{6})")

    def fix(v):
        if isinstance(v, str):
            return rx.sub(lambda m: f"APP-2026-{mp[m.group(1)]}", v)
        if isinstance(v, dict):
            return {k: fix(x) for k, x in v.items()}
        return v

    for t in list(S.T):
        S.T[t] = [{k: fix(v) for k, v in r.items()} for r in S.T[t]]
    gt_rows = [{k: fix(v) for k, v in r.items()} for r in gt_rows]
    for t, rows in S.T.items():
        pk = schema.TABLES[t]["pk"]
        rows.sort(key=lambda r: tuple(r[c] for c in pk))
    gt_rows.sort(key=lambda r: r["application_id"])
    return gt_rows


def ser(table, row):
    out = {}
    for f in schema.TABLES[table]["fields"]:
        v = row[f["name"]]
        if v is not None:
            if f["type"] == "decimal":
                v = round(float(v), f["scale"])
            elif f["type"] == "int":
                v = int(v)
            elif f["type"] == "bool":
                v = bool(v)
        out[f["name"]] = v
    return out


def csv_val(f, v):
    if v is None:
        return ""
    if f["type"] == "decimal":
        return f"{v:.{f['scale']}f}"
    if f["type"] == "bool":
        return "true" if v else "false"
    if f["type"] == "json":
        return json.dumps(v, sort_keys=True, separators=(",", ":"))
    return str(v)


def sql_val(f, v):
    if v is None:
        return "NULL"
    if f["type"] == "decimal":
        return f"{v:.{f['scale']}f}"
    if f["type"] == "bool":
        return "TRUE" if v else "FALSE"
    if f["type"] == "int":
        return str(v)
    if f["type"] == "json":
        v = json.dumps(v, sort_keys=True, separators=(",", ":"))
    return "'" + str(v).replace("'", "''") + "'"


def write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def export(S, gt_rows, out, args):
    for d in ("csv", "json", "sql", "ground_truth", "schema", "reports"):
        os.makedirs(os.path.join(out, d), exist_ok=True)
    files, counts = {}, {}
    sql = [schema.ddl(), "BEGIN;"]
    for t in schema.TABLES:
        rows = [ser(t, r) for r in S.T[t]]
        counts[t] = len(rows)
        flds = schema.TABLES[t]["fields"]
        base = schema.snake(t)
        with open(os.path.join(out, "csv", base + ".csv"), "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow([f["name"] for f in flds])
            for r in rows:
                w.writerow([csv_val(f, r[f["name"]]) for f in flds])
        write_text(os.path.join(out, "json", base + ".json"),
                   "[\n" + ",\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n]\n")
        names = ", ".join(f["name"] for f in flds)
        for i in range(0, len(rows), 500):
            vals = ",\n".join("(" + ", ".join(sql_val(f, r[f["name"]]) for f in flds) + ")" for r in rows[i:i + 500])
            sql.append(f"INSERT INTO {t} ({names}) VALUES\n{vals};")
    sql.append("COMMIT;")
    write_text(os.path.join(out, "sql", "seed.sql"), "\n".join(sql) + "\n")
    # ground truth (separate directory; never referenced by input tables)
    cols = ["application_id"] + schema.GROUND_TRUTH_COLUMNS
    with open(os.path.join(out, "ground_truth", "ground_truth.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(cols)
        for r in gt_rows:
            w.writerow([("true" if r[c] else "false") if isinstance(r[c], bool) else r[c] for c in cols])
    write_text(os.path.join(out, "ground_truth", "ground_truth.json"),
               "[\n" + ",\n".join(json.dumps({c: r[c] for c in cols}) for r in gt_rows) + "\n]\n")
    write_text(os.path.join(out, "schema", "schema.sql"), schema.ddl())
    write_text(os.path.join(out, "schema", "DATA_DICTIONARY.md"), schema.markdown())
    # manifest
    for d in ("csv", "json", "sql", "ground_truth", "schema"):
        for fn in sorted(os.listdir(os.path.join(out, d))):
            p = os.path.join(d, fn)
            files[p.replace(os.sep, "/")] = dict(sha256=sha256(os.path.join(out, p)), bytes=os.path.getsize(os.path.join(out, p)))
    manifest = dict(
        generator="loan-tracker-datagen", generator_version=GENERATOR_VERSION, rule_version=schema.RULE_VERSION,
        command=" ".join(["python generate.py"] + args.cmd), seed=args.seed, snapshot=SNAPSHOT,
        parameters=dict(applicants=args.applicants, applications=args.applications, anomalies_per_type=args.k),
        python=f"{sys.version_info.major}.{sys.version_info.minor}", row_counts=counts, files=files,
        sources=dict(external_data_used=False, note="All data is synthetic and generated from the seed. "
                     "No external dataset, URL, license or personal data is involved; no public reference data was ingested.",
                     fields_discarded=[], transformations=[]),
        warnings=S.warn)
    write_text(os.path.join(out, "manifest.json"), json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return counts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", choices=PROFILES, default="full")
    ap.add_argument("--applicants", type=int)
    ap.add_argument("--applications", type=int)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--anomalies-per-type", dest="k", type=int, help="default: ~0.67%% of applications per type")
    ap.add_argument("--out", default="data/full")
    args = ap.parse_args(argv)
    args.cmd = list(sys.argv[1:] if argv is None else argv)
    args.applicants = args.applicants or PROFILES[args.profile][0]
    args.applications = args.applications or PROFILES[args.profile][1]
    args.k = args.k if args.k is not None else max(3, round(args.applications * 0.0067))
    if args.applications < 50 or args.applicants < args.applications * 1.2:
        sys.exit("need applications >= 50 and applicants >= 1.2 x applications")

    S = State()
    S.T, S.latent = gen_masters(args.seed, args.applicants)
    S.world = rules.World(S.T["LoanProduct"], S.T["ProductDocumentRequirement"], S.T["Employment"],
                          S.T["IncomeRecord"], S.T["CreditFacility"], S.T["ApplicantFacility"])
    S.cases, S.tmp, S.warn, S.anoms = {}, 0, [], []
    S.inc_n = len(S.T["IncomeRecord"])
    perm = [f"APL-{i:06d}" for i in range(1, args.applicants + 1)]
    R(args.seed, "perm").shuffle(perm)
    n_base = args.applications - 3 * args.k
    apps, pool = plan_baseline(args.seed, S, args.applications, n_base, perm)
    rng = R(args.seed, "cases")
    for a in apps:                                  # C: baseline pass in chronological order
        a["application_id"] = next_tmp(S)
        commit_case(S, build_case(S, a, rng))
    inject_slot_anomalies(args.seed, S, args.k, pool)           # D
    build_loans(args.seed, S)                                   # E
    inject_posthoc(args.seed, S, args.k)                        # F
    gt = build_ground_truth(S)                                  # G
    gt = finalize_ids(S, gt)                                    # H
    counts = export(S, gt, args.out, args)
    print(f"seed={args.seed} out={args.out}")
    for t, n in counts.items():
        print(f"  {t:28s}{n:>9,d}")
    print(f"  {'ground_truth rows':28s}{len(gt):>9,d}   anomalies={sum(1 for r in gt if r['is_anomaly'])}")
    for w in S.warn:
        print("WARNING:", w)


if __name__ == "__main__":
    main()
