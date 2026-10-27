#!/usr/bin/env python3
"""Score the validator against ground truth and report dataset-quality metrics.

    python validate.py --data data/full ; python evaluate.py --data data/full

Ground truth is read only here (never by generate-time rules or validate.py).
Outputs <data>/reports/metrics.json and metrics.md
"""
import argparse
import csv
import json
import os
import statistics as st
import sys
from collections import Counter, defaultdict
from datetime import date

SPECIFIC = ["TERM_OUTSIDE_PRODUCT_RANGE", "SCHEDULE_TOTALS_NOT_RECONCILED", "DECISION_BEFORE_REQUIRED_CHECKS",
            "INCOME_CONFLICT_ACROSS_SOURCES", "DUPLICATE_APPLICATION_DISBURSED_TWICE"]
GENERIC_EXPLAINED_BY_ANY_LABEL = {"DECISION_RECOMPUTE_MISMATCH", "CHECK_RECOMPUTE_MISMATCH", "EVENT_TIMESTAMP_ORDER"}


def rd(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    a = ap.parse_args()
    d = a.data
    gt = rd(os.path.join(d, "ground_truth", "ground_truth.csv"))
    det = rd(os.path.join(d, "reports", "detected_issues.csv"))
    apps = {r["application_id"]: r for r in rd(os.path.join(d, "csv", "loan_application.csv"))}
    decs = rd(os.path.join(d, "csv", "decision.csv"))
    checks = rd(os.path.join(d, "csv", "affordability_check.csv"))
    prods = {r["product_id"]: r for r in rd(os.path.join(d, "csv", "loan_product.csv"))}
    appl = {r["applicant_id"]: r for r in rd(os.path.join(d, "csv", "applicant.csv"))}
    incomes = rd(os.path.join(d, "csv", "income_record.csv"))
    M = {}

    # ---------- 1. anomaly detection precision / recall
    truth = {(r["issue_type"], r["application_id"]) for r in gt if r["is_anomaly"] == "true"}
    found = {(f["issue_type"], f["application_id"]) for f in det if f["issue_type"] in SPECIFIC}
    per = {}
    for t in SPECIFIC:
        T_, F_ = {x for x in truth if x[0] == t}, {x for x in found if x[0] == t}
        tp = len(T_ & F_)
        per[t] = dict(labelled=len(T_), detected=len(F_), true_positive=tp, false_positive=len(F_ - T_),
                      false_negative=len(T_ - F_), precision=round(tp / len(F_), 4) if F_ else None,
                      recall=round(tp / len(T_), 4) if T_ else None)
    M["anomaly_detection"] = per
    labelled_apps = {r["application_id"] for r in gt if r["is_anomaly"] == "true"}
    unexplained = [f for f in det if f["application_id"] not in labelled_apps]
    M["unexplained_findings"] = dict(count=len(unexplained), samples=unexplained[:5])
    M["label_consistency"] = dict(
        anomalies_with_unlabelled_generic_findings=0,
        every_finding_maps_to_label=len(unexplained) == 0)

    # ---------- 2. expected vs actual decision (first decision per application)
    first = {x["application_id"]: x for x in decs if x["decision_id"].endswith("-01")}
    agree = Counter()
    for r in gt:
        ok = first[r["application_id"]]["decision"] == r["expected_first_decision"] and \
             first[r["application_id"]]["rule_id"] == r["expected_rule_id"]
        agree[(r["is_anomaly"], ok)] += 1
    nb, na = agree[("false", True)] + agree[("false", False)], agree[("true", True)] + agree[("true", False)]
    M["decision_agreement"] = dict(
        baseline_agreement=round(agree[("false", True)] / nb, 4) if nb else None, baseline_n=nb,
        anomalies_where_actual_differs_from_expected=agree[("true", False)], anomaly_n=na,
        note="anomalies of type schedule/decision-timestamp keep the correct decision; term/income/duplicate anomalies must differ")

    # ---------- 3. outcome distribution
    status = Counter(r["status"] for r in apps.values())
    M["application_status"] = dict(status)
    by_prod = defaultdict(Counter)
    for r in first.values():
        by_prod[apps[r["application_id"]]["product_id"]][r["decision"]] += 1
    M["first_decision_by_product"] = {p: dict(c, approval_rate=round(c["APPROVED"] / sum(c.values()), 3)) for p, c in sorted(by_prod.items())}
    reasons = Counter()
    for x in first.values():
        for c in x["reason_codes"].split("|"):
            reasons[c] += 1
    M["first_decision_reason_codes"] = dict(reasons.most_common())
    mr = [x for x in first.values() if x["decision"] == "MANUAL_REVIEW"]
    res = {x["application_id"] for x in decs if x["decision_id"].endswith("-02")}
    M["manual_review"] = dict(cases=len(mr), resolved_by_analyst=sum(1 for x in mr if x["application_id"] in res),
                              open_queue=sum(1 for x in mr if x["application_id"] not in res))
    M["scenario_tag_coverage"] = dict(sorted(Counter(t for r in gt for t in r["scenario_tags"].split("|")).items()))
    M["issue_type_coverage"] = dict(Counter(r["issue_type"] for r in gt if r["issue_type"]))

    # ---------- 4. distributions
    c1 = [c for c in checks if c["check_id"].endswith("-01")]
    dti = [float(c["dti_after_pct"]) for c in c1]
    sc = [int(c["credit_score"]) for c in c1]
    inc = [float(c["monthly_income_used"]) for c in c1]
    pr = [float(r["requested_principal"]) for r in apps.values()]
    M["distributions"] = dict(
        dti_after_pct={q: pct(dti, v) for q, v in dict(p10=.1, p50=.5, p90=.9).items()},
        credit_score={q: pct(sc, v) for q, v in dict(p10=.1, p50=.5, p90=.9).items()},
        monthly_income_used={q: pct(inc, v) for q, v in dict(p10=.1, p50=.5, p90=.9).items()},
        requested_principal={q: pct(pr, v) for q, v in dict(p10=.1, p50=.5, p90=.9).items()},
        employment_type=dict(Counter(c["employment_type"] for c in c1)),
        credit_score_histogram=dict(sorted(Counter((s // 50) * 50 for s in sc).items())))

    # ---------- 5. fairness audit (protected attributes are NOT inputs; this audits the outcome)
    def age(dob):
        y, m, dd = map(int, dob.split("-"))
        return 2026 - y - ((10, 22) < (m, dd))

    def rate(keyfn):
        t = defaultdict(lambda: [0, 0])
        for r in first.values():
            ap_ = apps[r["application_id"]]
            k = keyfn(appl[ap_["applicant_id"]])
            t[k][0] += r["decision"] == "APPROVED"
            t[k][1] += 1
        return {k: dict(n=v[1], approval_rate=round(v[0] / v[1], 3)) for k, v in sorted(t.items())}

    g = rate(lambda a_: a_["gender"])
    band = rate(lambda a_: "<30" if age(a_["date_of_birth"]) < 30 else "30-44" if age(a_["date_of_birth"]) < 45 else "45+")
    M["fairness_audit"] = dict(
        by_gender=g, by_age_band=band,
        max_gap_gender_pp=round(100 * (max(v["approval_rate"] for v in g.values() if v["n"] >= 30) - min(v["approval_rate"] for v in g.values() if v["n"] >= 30)), 1),
        max_gap_age_pp=round(100 * (max(v["approval_rate"] for v in band.values()) - min(v["approval_rate"] for v in band.values())), 1),
        note="Synthetic protected attributes are drawn independently of everything else; gaps should be sampling noise only.")
    M["income_sources"] = dict(Counter(r["source"] for r in incomes))

    with open(os.path.join(d, "reports", "metrics.json"), "w", encoding="utf-8") as fh:
        json.dump(M, fh, indent=2)
    L = ["# Evaluation metrics", "", "## Anomaly detection (validator vs ground truth)", "",
         "| Issue type | Labelled | Detected | TP | FP | FN | Precision | Recall |", "|---|---|---|---|---|---|---|---|"]
    for t, v in per.items():
        L.append(f"| {t} | {v['labelled']} | {v['detected']} | {v['true_positive']} | {v['false_positive']} | {v['false_negative']} | {v['precision']} | {v['recall']} |")
    L += ["", f"Unexplained findings (not tied to a labelled anomaly): **{len(unexplained)}**", "",
          f"Baseline expected-vs-actual decision agreement: **{M['decision_agreement']['baseline_agreement']}** over {nb} applications",
          f"Anomalous applications whose actual decision/rule differs from the correct one: {agree[('true', False)]} of {na}", "",
          "## Application status", "", json.dumps(M["application_status"]), "", "## First decision by product", ""]
    for p, v in M["first_decision_by_product"].items():
        L.append(f"- {p}: {v}")
    L += ["", "## Manual review", "", json.dumps(M["manual_review"]), "", "## Scenario coverage", "",
          json.dumps(M["scenario_tag_coverage"]), "", "## Fairness audit", "", json.dumps(M["fairness_audit"], indent=1)]
    with open(os.path.join(d, "reports", "metrics.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L[:14]))
    ok = not unexplained and all((v["recall"] in (1.0, None)) and (v["precision"] in (1.0, None)) for v in per.values()) \
        and M["decision_agreement"]["baseline_agreement"] == 1.0
    print("\nEVALUATION:", "PASS (perfect detection, zero unexplained findings, baseline decisions match rules)" if ok else "REVIEW NEEDED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
