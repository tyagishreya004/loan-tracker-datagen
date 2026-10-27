#!/usr/bin/env python3
"""Deterministic business rules (version LT-RULES-1.0).

Used by BOTH the generator (to create outcomes) and the validator (to re-derive
them independently from the persisted tables). No randomness in this module.

Decision rules, evaluated in order, first match wins
  R00 PRODUCT_LIMITS  term or principal outside product range            -> REJECTED
  R01 DUPLICATE       same applicant+product, principal within 10%, <=7d,
                      earlier application not rejected                    -> REJECTED
  R02 INCOME_FLOOR    income used < 12,000/month                          -> REJECTED
  R03 HARD_DECLINE    DTI after > max_dti+5 | disposable < product min |
                      score < min_score-25                                -> REJECTED
  R04 MANUAL_REVIEW   DTI in (max, max+5] | score in [min-25, min) |
                      tenure < 6m (contract < 12m) | income conflict |
                      documents / income proof not verified               -> MANUAL_REVIEW
  R05 AUTO_APPROVE    otherwise                                           -> APPROVED
  R06/R07 analyst policy re-evaluates a manual-review case on a new check.
Protected attributes (gender, marital status, date of birth/age, region, name)
are never read by any function here.
"""
import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from schema import RULE_VERSION

MIN_INCOME = 12000.0
DTI_BORDER = 5.0
SCORE_BORDER = 25
CONFLICT_TOL = 0.20
DUP_DAYS = 7
DUP_TOL = 0.10
UNSTABLE_MONTHS = 6
UNSTABLE_CONTRACT_MONTHS = 12
VERIFIED_SOURCES = ("PAYSLIP", "BANK_STATEMENT", "TAX_RETURN")
DPD_PENALTY = {0: 0, 30: -35, 60: -75, 90: -130}


# ---------------------------------------------------------------- date utils
def pdate(s):
    return date.fromisoformat(s[:10])


def pdt(s):
    return datetime.fromisoformat(s)


def months_between(a, b):
    """Whole months from date-string a to date-string b."""
    d1, d2 = pdate(a), pdate(b)
    m = (d2.year - d1.year) * 12 + d2.month - d1.month
    return max(0, m - (1 if d2.day < d1.day else 0))


def add_months(d, m):
    y = d.year + (d.month - 1 + m) // 12
    mo = (d.month - 1 + m) % 12 + 1
    return date(y, mo, min(d.day, calendar.monthrange(y, mo)[1]))


# ------------------------------------------------------------------ finance
def _hu(x):
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def emi_paise(principal, annual_rate_pct, n):
    r = annual_rate_pct / 1200.0
    if r == 0:
        return _hu(principal * 100 / n)
    return _hu(principal * r / (1 - (1 + r) ** (-n)) * 100)


def installment(principal, annual_rate_pct, n):
    return emi_paise(principal, annual_rate_pct, n) / 100.0


def build_schedule(principal, annual_rate_pct, n, start):
    """Annuity schedule in integer paise; last instalment clears the balance."""
    P = _hu(principal * 100)
    r = Decimal(str(annual_rate_pct)) / Decimal(1200)
    e = emi_paise(principal, annual_rate_pct, n)
    bal, rows = P, []
    for k in range(1, n + 1):
        interest = int((Decimal(bal) * r).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        princ = bal if k == n else e - interest
        rows.append(dict(installment_no=k, due_date=add_months(start, k).isoformat(),
                         opening=bal, principal=princ, interest=interest,
                         total=princ + interest, closing=bal - princ))
        bal -= princ
    return rows


# -------------------------------------------------------------------- world
class World:
    """Read-only lookup indexes over the persisted tables."""

    def __init__(self, products, required_docs, employments, incomes, facilities, links):
        self.products = {p["product_id"]: p for p in products}
        self.required = defaultdict(list)
        for r in required_docs:
            if r["is_mandatory"]:
                self.required[r["product_id"]].append(r["document_type"])
        self.emp = defaultdict(list)
        for e in employments:
            self.emp[e["applicant_id"]].append(e)
        self.inc = defaultdict(list)
        for i in incomes:
            self.inc[i["applicant_id"]].append(i)
        fac = {f["facility_id"]: f for f in facilities}
        self.fac = defaultdict(list)
        for l in links:
            self.fac[l["applicant_id"]].append((fac[l["facility_id"]], l["share_pct"]))
        self.prior = defaultdict(list)   # applicant -> earlier applications

    def add_prior(self, app, first_decision, first_decided_at):
        self.prior[app["applicant_id"]].append(dict(
            application_id=app["application_id"], product_id=app["product_id"],
            principal=app["requested_principal"], submitted_at=app["submitted_at"],
            first_decision=first_decision, first_decided_at=first_decided_at))


# ------------------------------------------------------------ derived values
def income_as_of(world, aid, asof, docs_income_ok, bypass=frozenset()):
    d = asof[:10]
    latest = {}
    for r in sorted((r for r in world.inc[aid] if r["recorded_date"] <= d),
                    key=lambda r: (r["recorded_date"], r["income_id"])):
        latest[r["source"]] = r
    ver = [latest[s] for s in VERIFIED_SOURCES
           if s in latest and latest[s]["verification_status"] == "VERIFIED"]
    if docs_income_ok and ver:
        vals = [r["monthly_income"] for r in ver]
        conflict = len(vals) >= 2 and max(vals) / min(vals) - 1 > CONFLICT_TOL
        if conflict and "INCOME_CONFLICT" in bypass:      # injected defect: conflict ignored
            return max(vals), "VERIFIED", len(vals), False
        return min(vals), "VERIFIED", len(vals), conflict
    if "DECLARED" in latest:
        return latest["DECLARED"]["monthly_income"], "DECLARED_UNVERIFIED", 0, False
    return 0.0, "DECLARED_UNVERIFIED", 0, False


def employment_as_of(world, aid, asof):
    d = asof[:10]
    cur = [e for e in world.emp[aid]
           if e["start_date"] <= d and (e["end_date"] is None or e["end_date"] > d)]
    if not cur:
        return "UNEMPLOYED", 0
    e = max(cur, key=lambda e: e["start_date"])
    return e["employment_type"], months_between(e["start_date"], d)


def credit_profile(world, aid, asof, n_enq):
    d = asof[:10]
    one_year_ago = (pdate(d) - timedelta(days=365)).isoformat()
    facs = [f for f, _ in world.fac[aid] if f["opened_date"] <= d]
    active = [f for f in facs if f["closed_date"] is None or f["closed_date"] > d]
    recent = [f for f in facs if f["closed_date"] is None or f["closed_date"] >= one_year_ago]
    dpd = max((f["max_dpd_12m"] for f in recent), default=0)
    cards = [f for f in active if f["facility_type"] == "CREDIT_CARD"]
    limit = sum(f["sanctioned_amount"] for f in cards)
    util = round(sum(f["outstanding_balance"] for f in cards) / limit * 100, 2) if limit > 0 else None
    months = max((months_between(f["opened_date"], d) for f in facs), default=0)
    score = 760 if facs else 680
    if util is not None:
        score -= round(max(0.0, util - 30.0) * 1.8)
    score += DPD_PENALTY[dpd]
    if facs:
        score += min(30, months // 4)
        if months < 12:
            score -= 20
    score -= 10 * min(n_enq, 4)
    return max(300, min(900, int(score))), util, dpd


def obligations_as_of(world, aid, asof):
    d = asof[:10]
    tot = 0.0
    for f, share in world.fac[aid]:
        if f["opened_date"] <= d and (f["closed_date"] is None or f["closed_date"] > d):
            tot += f["monthly_obligation"] * share / 100.0
    return round(tot, 2)


def enquiries(world, app):
    lo = (pdt(app["submitted_at"]) - timedelta(days=180)).isoformat()
    return sum(1 for p in world.prior[app["applicant_id"]]
               if lo <= p["submitted_at"] < app["submitted_at"]
               and p["application_id"] != app["application_id"])


def find_duplicate(world, app, asof):
    sub = pdt(app["submitted_at"])
    for p in sorted(world.prior[app["applicant_id"]], key=lambda p: p["submitted_at"]):
        if p["application_id"] == app["application_id"] or p["submitted_at"] >= app["submitted_at"]:
            continue
        if p["product_id"] != app["product_id"]:
            continue
        if abs(p["principal"] - app["requested_principal"]) > DUP_TOL * p["principal"]:
            continue
        if (sub - pdt(p["submitted_at"])).total_seconds() > DUP_DAYS * 86400:
            continue
        if p["first_decision"] == "REJECTED" and p["first_decided_at"] <= asof:
            continue
        return p["application_id"]
    return None


def build_check(world, app, docs_status, asof, bypass=frozenset()):
    """Derive every affordability / credit attribute from source records."""
    prod = world.products[app["product_id"]]
    req = world.required[app["product_id"]]
    docs_complete = all(docs_status.get(t) == "VERIFIED" for t in req)
    income_doc_ok = docs_status.get("INCOME_PROOF") == "VERIFIED"
    income, basis, nsrc, conflict = income_as_of(world, app["applicant_id"], asof, income_doc_ok, bypass)
    emp_type, tenure = employment_as_of(world, app["applicant_id"], asof)
    obl = obligations_as_of(world, app["applicant_id"], asof)
    inst = installment(app["requested_principal"], prod["annual_rate_pct"], app["requested_term_months"])
    if income > 0:
        dti_b = round(min(999.99, obl / income * 100), 2)
        dti_a = round(min(999.99, (obl + inst) / income * 100), 2)
    else:
        dti_b = dti_a = 999.99
    score, util, dpd = credit_profile(world, app["applicant_id"], asof, enquiries(world, app))
    return dict(income_basis=basis, monthly_income_used=round(income, 2), income_source_count=nsrc,
                income_conflict_flag=conflict, existing_obligations_monthly=obl,
                proposed_installment=round(inst, 2), dti_before_pct=dti_b, dti_after_pct=dti_a,
                disposable_income_after=round(income - obl - inst, 2), credit_score=score,
                utilisation_pct=util, max_dpd_12m=dpd, enquiries_180d=enquiries(world, app),
                employment_type=emp_type, employment_tenure_months=tenure,
                docs_complete=docs_complete, rule_version=RULE_VERSION)


def _inputs(check, prod, app, extra=None):
    d = dict(requested_principal=app["requested_principal"], requested_term_months=app["requested_term_months"],
             product_min_term=prod["min_term_months"], product_max_term=prod["max_term_months"],
             product_min_principal=prod["min_principal"], product_max_principal=prod["max_principal"],
             monthly_income_used=check["monthly_income_used"], income_basis=check["income_basis"],
             income_conflict_flag=check["income_conflict_flag"], dti_after_pct=check["dti_after_pct"],
             max_dti_pct=prod["max_dti_pct"], disposable_income_after=check["disposable_income_after"],
             min_disposable_income=prod["min_disposable_income"], credit_score=check["credit_score"],
             min_credit_score=prod["min_credit_score"], max_dpd_12m=check["max_dpd_12m"],
             employment_type=check["employment_type"],
             employment_tenure_months=check["employment_tenure_months"],
             docs_complete=check["docs_complete"])
    if extra:
        d.update(extra)
    return d


def _hard_reasons(check, prod):
    r = []
    if check["dti_after_pct"] > prod["max_dti_pct"] + DTI_BORDER:
        r.append("HIGH_DTI")
    if check["disposable_income_after"] < prod["min_disposable_income"] and "HIGH_DTI" not in r:
        r.append("LOW_DISPOSABLE_INCOME")
    if check["credit_score"] < prod["min_credit_score"] - SCORE_BORDER:
        r.append("LOW_CREDIT_SCORE")
    return r


def decide(world, app, check, docs_status, asof, bypass=frozenset()):
    """System decision for the first check of an application."""
    prod = world.products[app["product_id"]]
    out = lambda dec, rule, reasons, extra=None: dict(
        decision=dec, rule_id=rule, reasons=reasons, inputs=_inputs(check, prod, app, extra))
    if "TERM_RANGE" not in bypass:
        rs = []
        if not prod["min_term_months"] <= app["requested_term_months"] <= prod["max_term_months"]:
            rs.append("TERM_OUT_OF_RANGE")
        if not prod["min_principal"] <= app["requested_principal"] <= prod["max_principal"]:
            rs.append("PRINCIPAL_OUT_OF_RANGE")
        if rs:
            return out("REJECTED", "R00_PRODUCT_LIMITS", rs)
    if "DUPLICATE" not in bypass:
        dup = find_duplicate(world, app, asof)
        if dup:
            return out("REJECTED", "R01_DUPLICATE", ["DUPLICATE_APPLICATION"], dict(duplicate_of=dup))
    if check["monthly_income_used"] < MIN_INCOME:
        return out("REJECTED", "R02_INCOME_FLOOR", ["NO_VERIFIABLE_INCOME"], dict(min_income=MIN_INCOME))
    hard = _hard_reasons(check, prod)
    if hard:
        return out("REJECTED", "R03_HARD_DECLINE", hard)
    mr = []
    if check["dti_after_pct"] > prod["max_dti_pct"]:
        mr.append("BORDERLINE_DTI")
    if check["credit_score"] < prod["min_credit_score"]:
        mr.append("BORDERLINE_SCORE")
    t = check["employment_tenure_months"]
    if t < UNSTABLE_MONTHS or (check["employment_type"] == "CONTRACT" and t < UNSTABLE_CONTRACT_MONTHS):
        mr.append("UNSTABLE_EMPLOYMENT")
    if check["income_conflict_flag"]:
        mr.append("INCOME_CONFLICT")
    if check["income_basis"] != "VERIFIED" or docs_status.get("INCOME_PROOF") != "VERIFIED":
        mr.append("INCOME_PROOF_MISSING")
    if not all(docs_status.get(x) == "VERIFIED" for x in world.required[app["product_id"]] if x != "INCOME_PROOF"):
        mr.append("DOCS_INCOMPLETE")
    if mr:
        return out("MANUAL_REVIEW", "R04_MANUAL_REVIEW", mr)
    return out("APPROVED", "R05_AUTO_APPROVE", ["ALL_CHECKS_PASSED"])


def analyst_decide(world, app, check, docs_status):
    """Documented analyst policy applied to the second check of a manual-review case."""
    prod = world.products[app["product_id"]]
    out = lambda dec, rule, reasons: dict(
        decision=dec, rule_id=rule, reasons=reasons, inputs=_inputs(check, prod, app, dict(policy="ANALYST-1.0")))
    if not check["docs_complete"]:
        return out("REJECTED", "R07_ANALYST_DECLINE", ["DOCS_NOT_PROVIDED"])
    if check["income_basis"] != "VERIFIED":
        return out("REJECTED", "R07_ANALYST_DECLINE", ["INCOME_NOT_VERIFIED"])
    if check["monthly_income_used"] < MIN_INCOME:
        return out("REJECTED", "R07_ANALYST_DECLINE", ["NO_VERIFIABLE_INCOME"])
    hard = _hard_reasons(check, prod)
    if hard:
        return out("REJECTED", "R07_ANALYST_DECLINE", hard)
    dti, mx = check["dti_after_pct"], prod["max_dti_pct"]
    ok = True
    if dti > mx:      # borderline DTI: need cushion and clean recent history
        ok &= check["disposable_income_after"] >= 1.25 * prod["min_disposable_income"] and check["max_dpd_12m"] <= 30
    if check["credit_score"] < prod["min_credit_score"]:
        ok &= check["credit_score"] >= prod["min_credit_score"] - 10 and check["max_dpd_12m"] <= 30 and dti <= mx
    t = check["employment_tenure_months"]
    if t < UNSTABLE_MONTHS or (check["employment_type"] == "CONTRACT" and t < UNSTABLE_CONTRACT_MONTHS):
        ok &= t >= 3 and dti <= 0.9 * mx
    if check["income_conflict_flag"]:
        ok &= dti <= mx - 5
    if ok:
        return out("APPROVED", "R06_ANALYST_APPROVE", ["ANALYST_POLICY_PASS"])
    return out("REJECTED", "R07_ANALYST_DECLINE", ["ANALYST_POLICY_FAIL"])
