# Validation summary

| Group | Check | Result | Violations |
|---|---|---|---|
| schema | csv headers match data dictionary | PASS | 0 |
| schema | all values parse to declared type | PASS | 0 |
| schema | required fields populated | PASS | 0 |
| schema | values within allowed enums | PASS | 0 |
| schema | numeric values within declared ranges | PASS | 0 |
| schema | id/code patterns | PASS | 0 |
| structure | primary keys unique | PASS | 0 |
| structure | unique constraints hold | PASS | 0 |
| structure | foreign keys resolve (all joins valid) | PASS | 0 |
| structure | ID conventions deterministic, immutable-style and consistent | PASS | 0 |
| leakage | no ground-truth columns in input tables | PASS | 0 |
| fairness | protected attributes absent from every decision's rule_inputs | PASS | 0 |
| fairness | rules.py never references protected attributes | PASS | 0 |
| structure | SQL seed loads into SQLite (CHECK/PK/UNIQUE/FK enforced) and matches CSV counts | PASS | 0 |
| business | master-data date ordering and effective-date sanity | PASS | 0 |
| business | checks and documents never precede submission | PASS | 0 |
| business | [finding] decision never precedes the check it cites | FINDING | 3 |
| business | [finding] term/principal within product range for every application | FINDING | 3 |
| business | [finding] schedules reconcile to principal/interest (every loan) | FINDING | 3 |
| business | every approved loan has a schedule | PASS | 0 |
| lifecycle | event chains follow legal transitions and match LoanApplication.status | PASS | 0 |
| lifecycle | [finding] event timestamps non-decreasing | FINDING | 3 |
| lifecycle | approval and disbursement obey prerequisites | PASS | 0 |
| business | [finding] no duplicate application disbursed twice | FINDING | 3 |
| info | duplicate submissions caught by rule R01 | PASS | 0 |
| business | [finding] affordability checks reproducible from source records | FINDING | 3 |
| business | [finding] decisions reproducible by rules and cite exact inputs | FINDING | 9 |

`FINDING` = deliberate, labelled defect surfaced by the validator (scored by evaluate.py).

Findings by type: {"DECISION_BEFORE_REQUIRED_CHECKS": 3, "DECISION_RECOMPUTE_MISMATCH": 9, "DUPLICATE_APPLICATION_DISBURSED_TWICE": 3, "EVENT_TIMESTAMP_ORDER": 3, "INCOME_CONFLICT_ACROSS_SOURCES": 3, "SCHEDULE_TOTALS_NOT_RECONCILED": 3, "TERM_OUTSIDE_PRODUCT_RANGE": 3}
