# Loan Application Tracker – Synthetic Data Generator & Validator

YottaFlex.ai Round 2 – *Associate AI Forward Deployed Engineer* code challenge.
Tracks **loan applications, affordability checks, documents, credit attributes, decisions and disbursement eligibility**
as a fully synthetic, deterministic, relational dataset with labelled edge cases, a separate ground truth,
an independent validator, evaluation metrics and a reproducibility proof.

* **Pure Python standard library** – nothing to `pip install` (Python 3.9+, tested on 3.12).
* **One generator, any scale** – `--profile starter` (500 applicants / 300 apps) and `--profile full`
  (10,000 applicants / 6,000 apps, 4 products) share the same code path; scale is parameterised.
* **Fixed seed `20261022`**, no wall-clock or environment dependence.
* Currency is INR (all amounts synthetic).

## Quick start

```bash
./run_all.sh                       # ~1 minute: generate -> validate -> evaluate -> reproducibility, both profiles
# or step by step
python generate.py --profile full --seed 20261022 --out data/full
python validate.py --data data/full          # inputs only, never reads ground truth
python evaluate.py --data data/full          # scores validator vs ground truth + distribution/fairness metrics
python repro_check.py --profile full --compare data/full   # regenerate twice, compare row counts + SHA-256
python generate.py --applicants 2000 --applications 1200 --seed 7 --out /tmp/small   # custom scale
```

Verified results (see `data/*/reports/`): 0 structural failures; all 5 required defect types detected with
**precision = recall = 1.0** (40/40 each in `full`); 0 unexplained findings; baseline decisions match the rules for
5,800/5,800 non-anomalous applications; two regenerations are byte-identical (SHA-256 per file).

## See it as a website

```bash
python viewer.py --data data/starter     # or data/full
# open http://localhost:8000
```
Summary cards, defect-detection table, filterable application list, and a per-application trace (documents, check, decisions with cited rule inputs, events, schedule reconciliation, validator findings, ground truth).

## Repository layout

| Path | Purpose |
|---|---|
| `schema.py` | **Single source of truth** data dictionary → DDL, validation, `DATA_DICTIONARY.md` |
| `rules.py` | Deterministic business rules (affordability, credit score, decision rules R00–R07, annuity schedule). Shared by generator and validator; no randomness; never touches protected attributes |
| `generate.py` | Seeded generator (stages A–H below) and CSV/JSON/SQL/manifest export |
| `validate.py` | Independent validation (PK/FK/enum/range/date/arithmetic/lifecycle/duplicates + full re-derivation of every check and decision) |
| `evaluate.py` | Detection precision/recall vs ground truth, outcome & distribution metrics, fairness audit |
| `repro_check.py` | Step 10: two regenerations + different-seed sanity check |
| `docs/` | `DATA_DICTIONARY.md`, `schema.sql`, `DESIGN.md` (assumptions, trade-offs, limitations), `AI_USAGE.md`, `PROMPT_HISTORY.md` |
| `data/starter/` | Committed starter dataset (all formats + reports) |
| `data/full/` | Full dataset: `csv/`, `ground_truth/`, `reports/`, `schema/`, `manifest.json`. `json/` and `sql/` (≈136 MB) are git-ignored but regenerate bit-identically (checksums in `manifest.json`) |

Output directory layout: `csv/` (input tables) · `json/` · `sql/seed.sql` (DDL + inserts, loads into SQLite/PostgreSQL) ·
`ground_truth/` (**separate**) · `schema/` · `reports/` · `manifest.json` (command, seed, parameters, row counts,
SHA-256 per file, source statement).

## Data model (14 tables)

Required: Applicant, Employment, IncomeRecord, CreditFacility, LoanProduct, LoanApplication, Document,
AffordabilityCheck, Decision, RepaymentSchedule.
Added for traceability: **ApplicationEvent** (state history), **Disbursement** (disbursement eligibility/event),
and bridge tables **ApplicantFacility** (Applicant N:M CreditFacility – joint facilities) and
**ProductDocumentRequirement** (LoanProduct N:M document types). Cardinality, optionality, lifecycle and every
field's type/required/allowed values/units/uniqueness/validation rule: [`docs/DATA_DICTIONARY.md`](docs/DATA_DICTIONARY.md).

IDs: `APL-000001`, `APP-2026-000001` (contiguous, in submission order), `LOAN-2026-000001` (in approval order),
`DOC-<application-id>-001`, `DEC-<application-id>-01`, plus the same pattern for `AFC-`, `EVT-`, `SCH-<loan-id>-001`, `DSB-<loan-id>`.

## Business logic (all outcomes derive from documented rules, not random labels)

1. Masters first (products, applicants with employment & income histories, facilities + bridge), then applications, then documents → affordability check → decision → events → loans → schedules → disbursements.
2. **Affordability check** (derived from source rows as of the check timestamp): income = lowest *verified* source (payslip / bank statement / tax return) when the income-proof document is verified, else declared income (flagged `DECLARED_UNVERIFIED`); existing obligations from active facilities × share; annuity instalment; DTI before/after; disposable income; credit score from card utilisation, days-past-due, history length and enquiries; employment tenure; document completeness.
3. **Decision rules** (first match wins): R00 product limits → R01 duplicate → R02 income floor → R03 hard decline (DTI > max+5, low disposable income, score < min−25) → R04 manual review (borderline DTI/score, unstable employment, income conflict, missing/failed documents) → R05 auto-approve. Manual-review cases may be resolved later by an analyst (new check `-02`, new decision `-02`, re-uploaded documents are new rows) under documented policy R06/R07 – nothing is overwritten.
4. Each `Decision.rule_inputs` stores the exact values and thresholds used. Protected attributes (gender, marital status, date of birth/age, region, name) are stored only for fairness audit and are never read by any rule (enforced by an AST check in `validate.py`).
5. Approved loans get an annuity **RepaymentSchedule** (integer-paise arithmetic, last instalment clears the balance); ~92% of approvals are disbursed, ~7% cancelled by the customer, recent ones remain pending.

## Coverage of required scenarios (full profile)

Normal, boundary, failure and exception paths all occur through the rules: missing income proof (529), high debt burden (1,370), unstable employment (706), duplicate applications (131 rejected by R01), borderline scores (160) and DTI (361), approved / rejected / manual-review outcomes (open manual-review queue 435; 993 analyst resolutions).

**Injected, labelled defects** (`ground_truth/ground_truth.csv`, 40 each in `full`, injected *after/alongside* a valid baseline and tagged `issue_type` – no unrelated row is silently corrupted):

| issue_type | How it is injected | How it is detected |
|---|---|---|
| `TERM_OUTSIDE_PRODUCT_RANGE` | application with term outside the product range runs through a pipeline that skips R00, gets approved, scheduled and disbursed | term vs product limits |
| `SCHEDULE_TOTALS_NOT_RECONCILED` | one instalment's principal (and total) inflated | Σprincipal ≠ principal, balance chain, level-instalment check |
| `DECISION_BEFORE_REQUIRED_CHECKS` | approving decision timestamp moved before its affordability check | `decided_at < check.checked_at` |
| `INCOME_CONFLICT_ACROSS_SOURCES` | a later evidence row conflicts by 40–80%; pipeline ignores the conflict and uses the higher income | re-derivation of the check from source rows |
| `DUPLICATE_APPLICATION_DISBURSED_TWICE` | duplicate bypasses R01 and is disbursed as well as the original | disbursed pair, same applicant/product/principal ±10% within 7 days |

`ground_truth.csv` holds, per application, `expected_first_decision`, `expected_rule_id`, `expected_reason_codes`,
`scenario_tags`, and the anomaly label. It lives in its own directory, shares no columns with input tables
(checked by `validate.py`) and is read only by `evaluate.py`.

## Validation (Step 8) – `python validate.py`

Schema conformance (types, required, enums, ranges, patterns) · PK uniqueness · FK integrity of all joins ·
ID conventions · SQL seed loaded into SQLite with `PRAGMA foreign_keys=ON` and row counts compared · date ordering ·
arithmetic reconciliation of schedules · lifecycle transitions from the event log · approval/disbursement prerequisites
(latest decision APPROVED, required documents VERIFIED, schedule exists) · duplicate checks · **independent re-derivation of every affordability check and every decision** from stored source rows · no ground-truth leakage · no protected attributes.
"Hard" checks must pass (exit code 1 otherwise); defect-related checks are reported as `FINDING`s and scored by `evaluate.py`.
The validator already paid for itself: it caught a real generator bug (employment end date before start date for very young applicants) during development – fixed in `generate.py`.

## Reproducibility (Step 10)

`repro_check.py` regenerates twice and compares row counts and SHA-256 of every exported file (also against the committed
data) and checks that a different seed changes the output. Each stage has its own `random.Random(f"{seed}:{stage}")`
stream, there is no set iteration or wall-clock input, and the fixed snapshot time is `2026-10-22T00:00:00`.
Python's `random` algorithms are stable across 3.x; checksums were produced on Python 3.12.

## Lawful provenance

No external or public data was used (`manifest.json → sources.external_data_used = false`). Names, employers and lenders are
fictional word combinations; any resemblance to real persons or companies is coincidental. No secrets, credentials or personal data are in the repo.

See [`docs/DESIGN.md`](docs/DESIGN.md) for assumptions, trade-offs and limitations and
[`docs/AI_USAGE.md`](docs/AI_USAGE.md) for the AI-use disclosure.
