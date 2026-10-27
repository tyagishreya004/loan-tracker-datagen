# Design, assumptions, trade-offs, limitations

## Problem understanding
Build a reproducible synthetic dataset for an end-to-end loan workflow (application -> documents -> affordability ->
decision -> approval -> schedule -> disbursement) where outcomes come from documented rules, state changes are
append-only events, and a separate ground truth enables measurable evaluation.

## Key decisions
1. **Single schema module** drives DDL, validation and docs, so data dictionary, SQL and validator cannot drift.
2. **Shared rules, independent re-derivation.** `rules.py` produces outcomes in the generator and is re-run by the
   validator from the persisted tables only. Agreement proves traceability; disagreement is a finding.
3. **Defects are injected by running a faulty pipeline** (bypass flags) or by labelled post-hoc edits, so every defect
   is internally plausible and exactly one row set is affected. Each is labelled in ground truth with the *correct* expected decision.
4. **Append-only history.** Manual-review resolution = new check `-02`, new decision `-02`, new document rows
   (`supersedes_*`), new event rows. Nothing is updated except the `LoanApplication.status` projection of the event log.
5. **Application IDs are assigned last**, in submission order, via a temp-id remap, so `APP-2026-000001..N` is contiguous and chronological even though injected cases are created after the baseline.
6. **Money in integer paise** for schedules so reconciliation is exact.
7. **Per-stage RNG streams** (`Random(f"{seed}:{stage}")`) keep stages independent and reproducible.

## Assumptions
- Currency INR; monthly compounding annuity; first due one month after disbursement (or planned date for undisbursed loans).
- "Verified income" = lowest of the latest verified payslip / bank statement / tax return; sources differing >20% = conflict.
- Credit score is a transparent synthetic formula (not a bureau model) derived from facilities, DPD, history and enquiries.
- Snapshot date is fixed at 2026-10-22; applications span 2026-01-05..2026-09-30.
- Protected attributes are stored for fairness audit and drawn independently of outcomes.
- Duplicate = same applicant + product, principal within 10%, within 7 days of an earlier non-rejected application.

## Trade-offs
- Stdlib only: slower than pandas/numpy but zero setup and easy to review (~1 min for full).
- JSON/SQL of the full profile (~136 MB) are not committed; they regenerate bit-identically.
- Distributions are calibrated by hand (lognormal incomes, beta debt ratios) to give ~50% auto-approval, not fitted to real data.

## Limitations / known gaps
- Existing in-system loans are not added to a borrower's obligations in later applications (only bureau facilities are).
- Rule thresholds are illustrative, not regulatory advice; no calibration against real portfolios.
- Gender "X" is a small group (~2%), so the audit shows a ~10pp gap for it that is sampling noise at n≈120; F vs M is near parity.
- The evaluator's perfect scores partly reflect that detectors and injectors share the same rule definitions; a stricter test would use an independently written detector.
- Reproducibility is verified on CPython 3.12; float `**` could in theory differ by platform at a rounding boundary.
- No automated unit-test suite (not required); verification = validator + evaluator + repro_check, run by `run_all.sh`.

## How I know it works
`validate.py` structural checks: 0 failures. `evaluate.py`: precision = recall = 1.0 for all five defect types, 0 unexplained findings, 5,800/5,800 baseline decisions equal ground truth. `repro_check.py`: identical SHA-256 across two runs and the committed data; a different seed changes output.
