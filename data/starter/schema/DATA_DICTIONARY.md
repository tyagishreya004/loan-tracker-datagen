# Data dictionary

Currency: **INR**. Dates `YYYY-MM-DD`, datetimes `YYYY-MM-DDTHH:MM:SS` (no timezone, synthetic). Rule version `LT-RULES-1.0`.

## Relationships and cardinality

| Parent | Child | Cardinality | Optionality | Note |
|---|---|---|---|---|
| Applicant | Employment | 1:N | required | history; <=1 current row (end_date null) |
| Applicant | IncomeRecord | 1:N | required | append-only evidence; Employment link optional |
| Employment | IncomeRecord | 1:N | optional | declared other income has no employment |
| Applicant | CreditFacility | N:M | optional | via ApplicantFacility (joint facilities, share_pct) |
| LoanProduct | Document types | N:M | required | via ProductDocumentRequirement |
| Applicant | LoanApplication | 1:N | optional | an applicant may never apply, or apply several times |
| LoanProduct | LoanApplication | 1:N | required |  |
| LoanApplication | Document | 1:N | required | one row per required type + re-upload rows |
| LoanApplication | AffordabilityCheck | 1:N | required | check -01, plus -02 after manual-review resolution |
| AffordabilityCheck | Decision | 1:N | required | each decision cites the check it used |
| LoanApplication | Decision | 1:N | required | DEC-..-01 system, DEC-..-02 analyst |
| LoanApplication | ApplicationEvent | 1:N | required | full state history |
| LoanApplication | RepaymentSchedule | 1:N | optional | only when approved (loan_id assigned) |
| LoanApplication | Disbursement | 1:1 | optional | only DISBURSED loans |

## Lifecycle (LoanApplication.status)

```
(start) -> SUBMITTED
SUBMITTED -> UNDER_REVIEW
UNDER_REVIEW -> APPROVED, REJECTED, MANUAL_REVIEW
MANUAL_REVIEW -> APPROVED, REJECTED
APPROVED -> DISBURSED, CANCELLED
REJECTED -> (terminal)
DISBURSED -> (terminal)
CANCELLED -> (terminal)
```

ID conventions: `APP-2026-000001`, `LOAN-2026-000001`, `DOC-<application-id>-001`, `DEC-<application-id>-01` (plus `AFC-`, `EVT-`, `SCH-`, `DSB-` derived the same way).

## LoanProduct

Product catalogue with limits, rates and decision thresholds (master).

**Primary key:** `product_id`  
**Foreign keys:** none

| Field | Type | Required | Unique | Allowed values / range / pattern | Unit | Description |
|---|---|---|---|---|---|---|
| product_id | string | yes | yes | `^PRD-[A-Z]+$` |  | Product key |
| product_name | string | yes |  |  |  | Display name |
| min_principal | decimal | yes |  | 1000 .. 100000000.0 | INR | Minimum principal |
| max_principal | decimal | yes |  | 1000 .. 100000000.0 | INR | Maximum principal (>= min_principal) |
| min_term_months | int | yes |  | 1 .. 360 | months | Minimum term |
| max_term_months | int | yes |  | 1 .. 360 | months | Maximum term (>= min_term_months) |
| annual_rate_pct | decimal | yes |  | 0 .. 60 | % p.a. | Nominal annual interest rate, monthly compounding |
| max_dti_pct | decimal | yes |  | 1 .. 100 | % | Max debt-to-income after the new instalment |
| min_credit_score | int | yes |  | 300 .. 900 |  | Minimum acceptable derived credit score |
| min_disposable_income | decimal | yes |  | 0 .. 10000000.0 | INR | Minimum monthly income left after all obligations |
| effective_from | date | yes |  |  |  | Start of validity of these terms |
| effective_to | date | no |  |  |  | End of validity (null = open) |
| status | string | yes |  | ACTIVE, RETIRED |  | Lifecycle state |

## Applicant

Synthetic customer / account holder (master). Contains protected attributes that are stored for fairness audit only and are never decision inputs.

**Primary key:** `applicant_id`  
**Foreign keys:** none

| Field | Type | Required | Unique | Allowed values / range / pattern | Unit | Description |
|---|---|---|---|---|---|---|
| applicant_id | string | yes | yes | `^APL-\d{6}$` |  | Applicant key |
| full_name | string | yes |  |  |  | Synthetic name (not a real person) [protected] |
| date_of_birth | date | yes |  |  |  | Date of birth, applicants are 21-64 at snapshot [protected] |
| gender | string | yes |  | F, M, X |  | Gender [protected] |
| marital_status | string | yes |  | SINGLE, MARRIED, DIVORCED, WIDOWED |  | Marital status [protected] |
| region_code | string | yes |  | `^[A-Z]{2}$` |  | Indian state/UT code [protected proxy] |
| customer_since | date | yes |  |  |  | Account holder since |

## Employment

Employment history; one applicant has 1-3 rows, at most one current.

**Primary key:** `employment_id`  
**Foreign keys:** `applicant_id` -> Applicant.applicant_id

| Field | Type | Required | Unique | Allowed values / range / pattern | Unit | Description |
|---|---|---|---|---|---|---|
| employment_id | string | yes | yes | `^EMP-\d{6}$` |  | Employment key |
| applicant_id | string | yes |  | `^APL-\d{6}$` |  | FK Applicant |
| employer_name | string | yes |  |  |  | Synthetic employer |
| employment_type | string | yes |  | SALARIED, SELF_EMPLOYED, CONTRACT |  | Type of employment |
| start_date | date | yes |  |  |  | Start date |
| end_date | date | no |  |  |  | End date (null = current). Must be >= start_date. |
| is_current | bool | yes |  |  |  | True iff end_date is null |

## IncomeRecord

Monthly income evidence per source; append-only (new evidence = new row).

**Primary key:** `income_id`  
**Foreign keys:** `applicant_id` -> Applicant.applicant_id, `employment_id` -> Employment.employment_id

| Field | Type | Required | Unique | Allowed values / range / pattern | Unit | Description |
|---|---|---|---|---|---|---|
| income_id | string | yes | yes | `^INC-\d{6}$` |  | Income key |
| applicant_id | string | yes |  | `^APL-\d{6}$` |  | FK Applicant |
| employment_id | string | no |  | `^EMP-\d{6}$` |  | FK Employment (optional: e.g. declared other income) |
| source | string | yes |  | PAYSLIP, BANK_STATEMENT, TAX_RETURN, DECLARED |  | Evidence source |
| monthly_income | decimal | yes |  | 0 .. 100000000.0 | INR | Gross monthly income |
| verification_status | string | yes |  | VERIFIED, UNVERIFIED |  | VERIFIED only for PAYSLIP/BANK_STATEMENT/TAX_RETURN |
| recorded_date | date | yes |  |  |  | Date evidence was recorded (effective date) |

## CreditFacility

Existing credit facility (master). Linked to applicants through ApplicantFacility (N:M).

**Primary key:** `facility_id`  
**Foreign keys:** none

| Field | Type | Required | Unique | Allowed values / range / pattern | Unit | Description |
|---|---|---|---|---|---|---|
| facility_id | string | yes | yes | `^FAC-\d{6}$` |  | Facility key |
| facility_type | string | yes |  | CREDIT_CARD, PERSONAL_LOAN, AUTO_LOAN, HOME_LOAN, BNPL |  | Facility type |
| lender_name | string | yes |  |  |  | Synthetic lender |
| sanctioned_amount | decimal | yes |  | 0 .. 1000000000.0 | INR | Sanctioned amount / credit limit |
| outstanding_balance | decimal | yes |  | 0 .. 1000000000.0 | INR | Outstanding balance (0 when closed) |
| monthly_obligation | decimal | yes |  | 0 .. 100000000.0 | INR | Monthly repayment / minimum due (0 when closed) |
| max_dpd_12m | int | yes |  | 0, 30, 60, 90 |  | Worst days-past-due in last 12 months |
| status | string | yes |  | ACTIVE, CLOSED |  | Facility state |
| opened_date | date | yes |  |  |  | Opened |
| closed_date | date | no |  |  |  | Closed (null while ACTIVE) |

## ApplicantFacility

Bridge table: Applicant N:M CreditFacility (joint facilities).

**Primary key:** `applicant_id, facility_id`  
**Foreign keys:** `applicant_id` -> Applicant.applicant_id, `facility_id` -> CreditFacility.facility_id

| Field | Type | Required | Unique | Allowed values / range / pattern | Unit | Description |
|---|---|---|---|---|---|---|
| applicant_id | string | yes |  | `^APL-\d{6}$` |  | FK Applicant |
| facility_id | string | yes |  | `^FAC-\d{6}$` |  | FK CreditFacility |
| role | string | yes |  | PRIMARY, JOINT |  | Role on the facility |
| share_pct | int | yes |  | 1 .. 100 | % | Share of obligation borne by this applicant |

## ProductDocumentRequirement

Bridge table: LoanProduct N:M document types required.

**Primary key:** `product_id, document_type`  
**Foreign keys:** `product_id` -> LoanProduct.product_id

| Field | Type | Required | Unique | Allowed values / range / pattern | Unit | Description |
|---|---|---|---|---|---|---|
| product_id | string | yes |  | `^PRD-[A-Z]+$` |  | FK LoanProduct |
| document_type | string | yes |  | ID_PROOF, ADDRESS_PROOF, INCOME_PROOF, VEHICLE_QUOTE, CONTRACTOR_QUOTE, ADMISSION_LETTER |  | Required document type |
| is_mandatory | bool | yes |  |  |  | Mandatory for approval |

## LoanApplication

Loan application; status is the projection of ApplicationEvent.

**Primary key:** `application_id`  
**Foreign keys:** `applicant_id` -> Applicant.applicant_id, `product_id` -> LoanProduct.product_id

| Field | Type | Required | Unique | Allowed values / range / pattern | Unit | Description |
|---|---|---|---|---|---|---|
| application_id | string | yes | yes | `^APP-2026-\d{6}$` |  | APP-2026-000001 style key |
| applicant_id | string | yes |  | `^APL-\d{6}$` |  | FK Applicant |
| product_id | string | yes |  | `^PRD-[A-Z]+$` |  | FK LoanProduct |
| requested_principal | decimal | yes |  | 1 .. 1000000000.0 | INR | Requested principal |
| requested_term_months | int | yes |  | 1 .. 600 | months | Requested term |
| purpose | string | yes |  | DEBT_CONSOLIDATION, MEDICAL, TRAVEL, WEDDING, OTHER_PERSONAL, NEW_VEHICLE, USED_VEHICLE, RENOVATION, REPAIR, SOLAR_INSTALL, TUITION, STUDY_ABROAD |  | Loan purpose |
| channel | string | yes |  | ONLINE, BRANCH, PARTNER |  | Submission channel |
| submitted_at | datetime | yes |  |  |  | Submission timestamp |
| status | string | yes |  | SUBMITTED, UNDER_REVIEW, MANUAL_REVIEW, APPROVED, REJECTED, DISBURSED, CANCELLED |  | Current lifecycle state |
| status_updated_at | datetime | yes |  |  |  | Timestamp of last state change |
| loan_id | string | no | yes | `^LOAN-2026-\d{6}$` |  | LOAN-2026-000001 style id, set once the application is approved |

## Document

Document status rows (append-only; a re-upload is a new row superseding the old one).

**Primary key:** `document_id`  
**Foreign keys:** `application_id` -> LoanApplication.application_id, `supersedes_document_id` -> Document.document_id

| Field | Type | Required | Unique | Allowed values / range / pattern | Unit | Description |
|---|---|---|---|---|---|---|
| document_id | string | yes | yes | `^DOC-APP-2026-\d{6}-\d{3}$` |  | DOC-<application-id>-001 |
| application_id | string | yes |  | `^APP-2026-\d{6}$` |  | FK LoanApplication |
| document_type | string | yes |  | ID_PROOF, ADDRESS_PROOF, INCOME_PROOF, VEHICLE_QUOTE, CONTRACTOR_QUOTE, ADMISSION_LETTER |  | Document type |
| status | string | yes |  | VERIFIED, MISSING, REJECTED |  | Verification status |
| received_at | datetime | no |  |  |  | Received timestamp (null when MISSING) |
| status_at | datetime | yes |  |  |  | When this status was recorded (effective timestamp) |
| supersedes_document_id | string | no |  | `^DOC-APP-2026-\d{6}-\d{3}$` |  | Earlier row of same type replaced by this one |

## AffordabilityCheck

Derived affordability / credit attributes per check run (append-only).

**Primary key:** `check_id`  
**Foreign keys:** `application_id` -> LoanApplication.application_id

| Field | Type | Required | Unique | Allowed values / range / pattern | Unit | Description |
|---|---|---|---|---|---|---|
| check_id | string | yes | yes | `^AFC-APP-2026-\d{6}-\d{2}$` |  | AFC-<application-id>-01 |
| application_id | string | yes |  | `^APP-2026-\d{6}$` |  | FK LoanApplication |
| checked_at | datetime | yes |  |  |  | Check timestamp (as-of for all derivations) |
| income_basis | string | yes |  | VERIFIED, DECLARED_UNVERIFIED |  | VERIFIED = proof document + verified income evidence; else declared income |
| monthly_income_used | decimal | yes |  | 0 .. 100000000.0 | INR | Income used: lowest verified source (conservative) |
| income_source_count | int | yes |  | 0 .. 3 |  | Number of verified sources compared |
| income_conflict_flag | bool | yes |  |  |  | True if verified sources differ by more than 20% |
| existing_obligations_monthly | decimal | yes |  | 0 .. 100000000.0 | INR | Sum of active facility obligations x share |
| proposed_installment | decimal | yes |  | 0 .. 1000000000.0 | INR | Annuity instalment for requested principal/term |
| dti_before_pct | decimal | yes |  | 0 .. 999.99 | % | existing obligations / income x 100 |
| dti_after_pct | decimal | yes |  | 0 .. 999.99 | % | (existing + proposed) / income x 100 |
| disposable_income_after | decimal | yes |  | -1000000000.0 .. 1000000000.0 | INR | income - existing - proposed |
| credit_score | int | yes |  | 300 .. 900 |  | Derived credit score from facilities, DPD, history, enquiries |
| utilisation_pct | decimal | no |  | 0 .. 1000 | % | Card balance / card limit x 100 (null if no active card) |
| max_dpd_12m | int | yes |  | 0, 30, 60, 90 |  | Worst DPD over recent facilities |
| enquiries_180d | int | yes |  | 0 .. 50 |  | Earlier applications by same applicant in prior 180 days |
| employment_type | string | yes |  | SALARIED, SELF_EMPLOYED, CONTRACT, UNEMPLOYED |  | Employment type at check time |
| employment_tenure_months | int | yes |  | 0 .. 600 | months | Months in current employment |
| docs_complete | bool | yes |  |  |  | All mandatory documents VERIFIED at check time |
| rule_version | string | yes |  | LT-RULES-1.0 |  | Rule-set version used |

## Decision

Decision events (append-only: a manual-review outcome is a new row, never an update).

**Primary key:** `decision_id`  
**Foreign keys:** `application_id` -> LoanApplication.application_id, `check_id` -> AffordabilityCheck.check_id, `supersedes_decision_id` -> Decision.decision_id

| Field | Type | Required | Unique | Allowed values / range / pattern | Unit | Description |
|---|---|---|---|---|---|---|
| decision_id | string | yes | yes | `^DEC-APP-2026-\d{6}-\d{2}$` |  | DEC-<application-id>-01 |
| application_id | string | yes |  | `^APP-2026-\d{6}$` |  | FK LoanApplication |
| check_id | string | yes |  | `^AFC-APP-2026-\d{6}-\d{2}$` |  | FK AffordabilityCheck whose numbers the decision relies on |
| decided_at | datetime | yes |  |  |  | Decision timestamp |
| decision | string | yes |  | APPROVED, REJECTED, MANUAL_REVIEW |  | Outcome |
| rule_id | string | yes |  | R00_PRODUCT_LIMITS, R01_DUPLICATE, R02_INCOME_FLOOR, R03_HARD_DECLINE, R04_MANUAL_REVIEW, R05_AUTO_APPROVE, R06_ANALYST_APPROVE, R07_ANALYST_DECLINE |  | Rule that fired |
| reason_codes | string | yes |  |  |  | Pipe-separated reason codes (see REASONS) |
| rule_inputs | json | yes |  |  |  | Exact inputs and thresholds the rule evaluated (traceability) |
| decided_by | string | yes |  | `^(SYSTEM|ANALYST-\d{2})$` |  | SYSTEM or ANALYST-nn |
| supersedes_decision_id | string | no |  | `^DEC-APP-2026-\d{6}-\d{2}$` |  | Earlier decision this one resolves |

## RepaymentSchedule

Annuity repayment schedule for each approved loan (one row per instalment).

**Primary key:** `schedule_id`  
**Foreign keys:** `loan_id` -> LoanApplication.loan_id, `application_id` -> LoanApplication.application_id

| Field | Type | Required | Unique | Allowed values / range / pattern | Unit | Description |
|---|---|---|---|---|---|---|
| schedule_id | string | yes | yes | `^SCH-LOAN-2026-\d{6}-\d{3}$` |  | SCH-<loan-id>-001 |
| loan_id | string | yes |  | `^LOAN-2026-\d{6}$` |  | FK LoanApplication.loan_id |
| application_id | string | yes |  | `^APP-2026-\d{6}$` |  | FK LoanApplication |
| installment_no | int | yes |  | 1 .. 600 |  | 1..term |
| due_date | date | yes |  |  |  | Due date (monthly, strictly increasing) |
| opening_balance | decimal | yes |  | 0 .. 1000000000.0 | INR | Balance before instalment |
| principal_due | decimal | yes |  | 0 .. 1000000000.0 | INR | Principal component |
| interest_due | decimal | yes |  | 0 .. 1000000000.0 | INR | Interest component = opening x rate/12 |
| total_due | decimal | yes |  | 0 .. 1000000000.0 | INR | principal_due + interest_due |
| closing_balance | decimal | yes |  | 0 .. 1000000000.0 | INR | opening - principal |
| status | string | yes |  | SCHEDULED, PAID, OVERDUE, CANCELLED |  | Instalment state at snapshot date |

## Disbursement

Disbursement event for an approved loan (1:1 with loan).

**Primary key:** `disbursement_id`  
**Foreign keys:** `loan_id` -> LoanApplication.loan_id, `application_id` -> LoanApplication.application_id, `eligibility_decision_id` -> Decision.decision_id

| Field | Type | Required | Unique | Allowed values / range / pattern | Unit | Description |
|---|---|---|---|---|---|---|
| disbursement_id | string | yes | yes | `^DSB-LOAN-2026-\d{6}$` |  | DSB-<loan-id> |
| loan_id | string | yes | yes | `^LOAN-2026-\d{6}$` |  | FK LoanApplication.loan_id |
| application_id | string | yes |  | `^APP-2026-\d{6}$` |  | FK LoanApplication |
| eligibility_decision_id | string | yes |  | `^DEC-APP-2026-\d{6}-\d{2}$` |  | Approving decision that made the loan eligible |
| amount | decimal | yes |  | 1 .. 1000000000.0 | INR | Disbursed amount = requested principal |
| disbursed_at | datetime | yes |  |  |  | Disbursement timestamp |
| status | string | yes |  | DISBURSED |  | Disbursement state |

## ApplicationEvent

Immutable state-change history of an application.

**Primary key:** `event_id`  
**Foreign keys:** `application_id` -> LoanApplication.application_id

| Field | Type | Required | Unique | Allowed values / range / pattern | Unit | Description |
|---|---|---|---|---|---|---|
| event_id | string | yes | yes | `^EVT-APP-2026-\d{6}-\d{2}$` |  | EVT-<application-id>-NN |
| application_id | string | yes |  | `^APP-2026-\d{6}$` |  | FK LoanApplication |
| event_seq | int | yes |  | 1 .. 50 |  | 1-based sequence within the application |
| event_type | string | yes |  | SUBMITTED, REVIEW_STARTED, DECISION_MADE, MANUAL_REVIEW_RESOLVED, DISBURSED, CANCELLED |  | Event type |
| from_status | string | no |  | SUBMITTED, UNDER_REVIEW, MANUAL_REVIEW, APPROVED, REJECTED, DISBURSED, CANCELLED |  | Previous state (null for first event) |
| to_status | string | yes |  | SUBMITTED, UNDER_REVIEW, MANUAL_REVIEW, APPROVED, REJECTED, DISBURSED, CANCELLED |  | New state |
| event_ts | datetime | yes |  |  |  | Event timestamp |
| actor | string | yes |  | `^(APPLICANT|SYSTEM|ANALYST-\d{2})$` |  | APPLICANT, SYSTEM or ANALYST-nn |
| ref_id | string | no |  |  |  | Related check/decision/disbursement id |

## Reason codes

`TERM_OUT_OF_RANGE`, `PRINCIPAL_OUT_OF_RANGE`, `DUPLICATE_APPLICATION`, `NO_VERIFIABLE_INCOME`, `HIGH_DTI`, `LOW_DISPOSABLE_INCOME`, `LOW_CREDIT_SCORE`, `BORDERLINE_DTI`, `BORDERLINE_SCORE`, `UNSTABLE_EMPLOYMENT`, `INCOME_CONFLICT`, `DOCS_INCOMPLETE`, `INCOME_PROOF_MISSING`, `ALL_CHECKS_PASSED`, `ANALYST_POLICY_PASS`, `ANALYST_POLICY_FAIL`, `DOCS_NOT_PROVIDED`, `INCOME_NOT_VERIFIED`

## Protected attributes (stored, never used by any rule)

`gender`, `marital_status`, `date_of_birth`, `age`, `region_code`, `full_name`
