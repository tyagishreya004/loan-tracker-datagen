# Evaluation metrics

## Anomaly detection (validator vs ground truth)

| Issue type | Labelled | Detected | TP | FP | FN | Precision | Recall |
|---|---|---|---|---|---|---|---|
| TERM_OUTSIDE_PRODUCT_RANGE | 40 | 40 | 40 | 0 | 0 | 1.0 | 1.0 |
| SCHEDULE_TOTALS_NOT_RECONCILED | 40 | 40 | 40 | 0 | 0 | 1.0 | 1.0 |
| DECISION_BEFORE_REQUIRED_CHECKS | 40 | 40 | 40 | 0 | 0 | 1.0 | 1.0 |
| INCOME_CONFLICT_ACROSS_SOURCES | 40 | 40 | 40 | 0 | 0 | 1.0 | 1.0 |
| DUPLICATE_APPLICATION_DISBURSED_TWICE | 40 | 40 | 40 | 0 | 0 | 1.0 | 1.0 |

Unexplained findings (not tied to a labelled anomaly): **0**

Baseline expected-vs-actual decision agreement: **1.0** over 5800 applications
Anomalous applications whose actual decision/rule differs from the correct one: 120 of 200

## Application status

{"REJECTED": 1918, "CANCELLED": 227, "DISBURSED": 3420, "MANUAL_REVIEW": 435}

## First decision by product

- PRD-AUTO: {'REJECTED': 479, 'APPROVED': 723, 'MANUAL_REVIEW': 336, 'approval_rate': 0.47}
- PRD-EDUCATION: {'APPROVED': 477, 'MANUAL_REVIEW': 216, 'REJECTED': 214, 'approval_rate': 0.526}
- PRD-HOMEIMP: {'APPROVED': 626, 'REJECTED': 294, 'MANUAL_REVIEW': 271, 'approval_rate': 0.526}
- PRD-PERSONAL: {'APPROVED': 1260, 'REJECTED': 499, 'MANUAL_REVIEW': 605, 'approval_rate': 0.533}

## Manual review

{"cases": 1428, "resolved_by_analyst": 993, "open_queue": 435}

## Scenario coverage

{"BORDERLINE_DTI": 361, "BORDERLINE_SCORE": 160, "CLEAN": 3399, "DUPLICATE_APPLICATION": 131, "HIGH_DEBT_BURDEN": 1370, "INCOME_CONFLICT": 40, "MISSING_INCOME_PROOF": 529, "UNSTABLE_EMPLOYMENT": 706}

## Fairness audit

{
 "by_gender": {
  "F": {
   "n": 2536,
   "approval_rate": 0.516
  },
  "M": {
   "n": 3352,
   "approval_rate": 0.51
  },
  "X": {
   "n": 112,
   "approval_rate": 0.616
  }
 },
 "by_age_band": {
  "30-44": {
   "n": 3538,
   "approval_rate": 0.514
  },
  "45+": {
   "n": 1099,
   "approval_rate": 0.531
  },
  "<30": {
   "n": 1363,
   "approval_rate": 0.503
  }
 },
 "max_gap_gender_pp": 10.6,
 "max_gap_age_pp": 2.8,
 "note": "Synthetic protected attributes are drawn independently of everything else; gaps should be sampling noise only."
}
