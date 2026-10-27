# Evaluation metrics

## Anomaly detection (validator vs ground truth)

| Issue type | Labelled | Detected | TP | FP | FN | Precision | Recall |
|---|---|---|---|---|---|---|---|
| TERM_OUTSIDE_PRODUCT_RANGE | 3 | 3 | 3 | 0 | 0 | 1.0 | 1.0 |
| SCHEDULE_TOTALS_NOT_RECONCILED | 3 | 3 | 3 | 0 | 0 | 1.0 | 1.0 |
| DECISION_BEFORE_REQUIRED_CHECKS | 3 | 3 | 3 | 0 | 0 | 1.0 | 1.0 |
| INCOME_CONFLICT_ACROSS_SOURCES | 3 | 3 | 3 | 0 | 0 | 1.0 | 1.0 |
| DUPLICATE_APPLICATION_DISBURSED_TWICE | 3 | 3 | 3 | 0 | 0 | 1.0 | 1.0 |

Unexplained findings (not tied to a labelled anomaly): **0**

Baseline expected-vs-actual decision agreement: **1.0** over 285 applications
Anomalous applications whose actual decision/rule differs from the correct one: 9 of 15

## Application status

{"DISBURSED": 175, "REJECTED": 80, "MANUAL_REVIEW": 31, "CANCELLED": 14}

## First decision by product

- PRD-AUTO: {'MANUAL_REVIEW': 16, 'REJECTED': 21, 'APPROVED': 38, 'approval_rate': 0.507}
- PRD-EDUCATION: {'APPROVED': 25, 'MANUAL_REVIEW': 11, 'REJECTED': 5, 'approval_rate': 0.61}
- PRD-HOMEIMP: {'MANUAL_REVIEW': 18, 'APPROVED': 36, 'REJECTED': 17, 'approval_rate': 0.507}
- PRD-PERSONAL: {'MANUAL_REVIEW': 31, 'REJECTED': 19, 'APPROVED': 63, 'approval_rate': 0.558}

## Manual review

{"cases": 76, "resolved_by_analyst": 45, "open_queue": 31}

## Scenario coverage

{"BORDERLINE_DTI": 15, "BORDERLINE_SCORE": 5, "CLEAN": 181, "DUPLICATE_APPLICATION": 7, "HIGH_DEBT_BURDEN": 59, "INCOME_CONFLICT": 3, "MISSING_INCOME_PROOF": 24, "UNSTABLE_EMPLOYMENT": 30}

## Fairness audit

{
 "by_gender": {
  "F": {
   "n": 136,
   "approval_rate": 0.537
  },
  "M": {
   "n": 155,
   "approval_rate": 0.542
  },
  "X": {
   "n": 9,
   "approval_rate": 0.556
  }
 },
 "by_age_band": {
  "30-44": {
   "n": 180,
   "approval_rate": 0.533
  },
  "45+": {
   "n": 53,
   "approval_rate": 0.509
  },
  "<30": {
   "n": 67,
   "approval_rate": 0.582
  }
 },
 "max_gap_gender_pp": 0.5,
 "max_gap_age_pp": 7.3,
 "note": "Synthetic protected attributes are drawn independently of everything else; gaps should be sampling noise only."
}
