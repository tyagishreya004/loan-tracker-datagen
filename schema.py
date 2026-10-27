#!/usr/bin/env python3
"""Single source of truth for the data model.

The data dictionary below drives:
  * CSV/JSON/SQL export column order and typing   (generate.py)
  * type / enum / range / pattern / FK validation  (validate.py)
  * DDL (schema.sql) and DATA_DICTIONARY.md        (python schema.py --write DIR)
"""
import argparse
import os
import re
from collections import OrderedDict

RULE_VERSION = "LT-RULES-1.0"
CURRENCY = "INR"

# ----------------------------------------------------------------- enums
GENDER = ["F", "M", "X"]
MARITAL = ["SINGLE", "MARRIED", "DIVORCED", "WIDOWED"]
EMP_TYPES = ["SALARIED", "SELF_EMPLOYED", "CONTRACT"]
CHECK_EMP_TYPES = EMP_TYPES + ["UNEMPLOYED"]
INCOME_SOURCES = ["PAYSLIP", "BANK_STATEMENT", "TAX_RETURN", "DECLARED"]
VERIF = ["VERIFIED", "UNVERIFIED"]
FAC_TYPES = ["CREDIT_CARD", "PERSONAL_LOAN", "AUTO_LOAN", "HOME_LOAN", "BNPL"]
DOC_TYPES = ["ID_PROOF", "ADDRESS_PROOF", "INCOME_PROOF", "VEHICLE_QUOTE",
             "CONTRACTOR_QUOTE", "ADMISSION_LETTER"]
DOC_STATUS = ["VERIFIED", "MISSING", "REJECTED"]
APP_STATUS = ["SUBMITTED", "UNDER_REVIEW", "MANUAL_REVIEW", "APPROVED",
              "REJECTED", "DISBURSED", "CANCELLED"]
DECISIONS = ["APPROVED", "REJECTED", "MANUAL_REVIEW"]
RULE_IDS = ["R00_PRODUCT_LIMITS", "R01_DUPLICATE", "R02_INCOME_FLOOR",
            "R03_HARD_DECLINE", "R04_MANUAL_REVIEW", "R05_AUTO_APPROVE",
            "R06_ANALYST_APPROVE", "R07_ANALYST_DECLINE"]
REASONS = ["TERM_OUT_OF_RANGE", "PRINCIPAL_OUT_OF_RANGE", "DUPLICATE_APPLICATION",
           "NO_VERIFIABLE_INCOME", "HIGH_DTI", "LOW_DISPOSABLE_INCOME",
           "LOW_CREDIT_SCORE", "BORDERLINE_DTI", "BORDERLINE_SCORE",
           "UNSTABLE_EMPLOYMENT", "INCOME_CONFLICT", "DOCS_INCOMPLETE",
           "INCOME_PROOF_MISSING", "ALL_CHECKS_PASSED", "ANALYST_POLICY_PASS",
           "ANALYST_POLICY_FAIL", "DOCS_NOT_PROVIDED", "INCOME_NOT_VERIFIED"]
SCHED_STATUS = ["SCHEDULED", "PAID", "OVERDUE", "CANCELLED"]
EVENT_TYPES = ["SUBMITTED", "REVIEW_STARTED", "DECISION_MADE",
               "MANUAL_REVIEW_RESOLVED", "DISBURSED", "CANCELLED"]
PURPOSES = ["DEBT_CONSOLIDATION", "MEDICAL", "TRAVEL", "WEDDING", "OTHER_PERSONAL",
            "NEW_VEHICLE", "USED_VEHICLE", "RENOVATION", "REPAIR", "SOLAR_INSTALL",
            "TUITION", "STUDY_ABROAD"]
CHANNELS = ["ONLINE", "BRANCH", "PARTNER"]

# legal lifecycle transitions for LoanApplication.status
TRANSITIONS = {
    None: ["SUBMITTED"],
    "SUBMITTED": ["UNDER_REVIEW"],
    "UNDER_REVIEW": ["APPROVED", "REJECTED", "MANUAL_REVIEW"],
    "MANUAL_REVIEW": ["APPROVED", "REJECTED"],
    "APPROVED": ["DISBURSED", "CANCELLED"],
    "REJECTED": [], "DISBURSED": [], "CANCELLED": [],
}

# attributes that must never be a decision input
PROTECTED_ATTRIBUTES = ["gender", "marital_status", "date_of_birth", "age",
                        "region_code", "full_name"]
# columns that exist only in ground-truth files and must never appear in inputs
GROUND_TRUTH_COLUMNS = ["expected_first_decision", "expected_rule_id", "expected_reason_codes",
                        "scenario_tags", "is_anomaly", "issue_type", "issue_entity",
                        "issue_entity_id", "issue_note"]


def F(name, typ, desc, req=True, enum=None, rng=None, unit=None, uniq=False,
      pattern=None, scale=2):
    return dict(name=name, type=typ, desc=desc, required=req, enum=enum, range=rng,
                unit=unit, unique=uniq, pattern=pattern, scale=scale)


TABLES = OrderedDict()


def table(name, desc, pk, fields, fks=()):
    TABLES[name] = dict(name=name, desc=desc, pk=pk, fields=fields, fks=list(fks))


MONEY = CURRENCY

table("LoanProduct", "Product catalogue with limits, rates and decision thresholds (master).",
      ["product_id"], [
    F("product_id", "string", "Product key", uniq=True, pattern=r"^PRD-[A-Z]+$"),
    F("product_name", "string", "Display name"),
    F("min_principal", "decimal", "Minimum principal", unit=MONEY, rng=(1000, 1e8)),
    F("max_principal", "decimal", "Maximum principal (>= min_principal)", unit=MONEY, rng=(1000, 1e8)),
    F("min_term_months", "int", "Minimum term", unit="months", rng=(1, 360)),
    F("max_term_months", "int", "Maximum term (>= min_term_months)", unit="months", rng=(1, 360)),
    F("annual_rate_pct", "decimal", "Nominal annual interest rate, monthly compounding", unit="% p.a.", rng=(0, 60)),
    F("max_dti_pct", "decimal", "Max debt-to-income after the new instalment", unit="%", rng=(1, 100)),
    F("min_credit_score", "int", "Minimum acceptable derived credit score", rng=(300, 900)),
    F("min_disposable_income", "decimal", "Minimum monthly income left after all obligations", unit=MONEY, rng=(0, 1e7)),
    F("effective_from", "date", "Start of validity of these terms"),
    F("effective_to", "date", "End of validity (null = open)", req=False),
    F("status", "string", "Lifecycle state", enum=["ACTIVE", "RETIRED"]),
])

table("Applicant", "Synthetic customer / account holder (master). Contains protected attributes "
      "that are stored for fairness audit only and are never decision inputs.",
      ["applicant_id"], [
    F("applicant_id", "string", "Applicant key", uniq=True, pattern=r"^APL-\d{6}$"),
    F("full_name", "string", "Synthetic name (not a real person) [protected]"),
    F("date_of_birth", "date", "Date of birth, applicants are 21-64 at snapshot [protected]"),
    F("gender", "string", "Gender [protected]", enum=GENDER),
    F("marital_status", "string", "Marital status [protected]", enum=MARITAL),
    F("region_code", "string", "Indian state/UT code [protected proxy]", pattern=r"^[A-Z]{2}$"),
    F("customer_since", "date", "Account holder since"),
])

table("Employment", "Employment history; one applicant has 1-3 rows, at most one current.",
      ["employment_id"], [
    F("employment_id", "string", "Employment key", uniq=True, pattern=r"^EMP-\d{6}$"),
    F("applicant_id", "string", "FK Applicant", pattern=r"^APL-\d{6}$"),
    F("employer_name", "string", "Synthetic employer"),
    F("employment_type", "string", "Type of employment", enum=EMP_TYPES),
    F("start_date", "date", "Start date"),
    F("end_date", "date", "End date (null = current). Must be >= start_date.", req=False),
    F("is_current", "bool", "True iff end_date is null"),
], fks=[("applicant_id", "Applicant", "applicant_id")])

table("IncomeRecord", "Monthly income evidence per source; append-only (new evidence = new row).",
      ["income_id"], [
    F("income_id", "string", "Income key", uniq=True, pattern=r"^INC-\d{6}$"),
    F("applicant_id", "string", "FK Applicant", pattern=r"^APL-\d{6}$"),
    F("employment_id", "string", "FK Employment (optional: e.g. declared other income)", req=False, pattern=r"^EMP-\d{6}$"),
    F("source", "string", "Evidence source", enum=INCOME_SOURCES),
    F("monthly_income", "decimal", "Gross monthly income", unit=MONEY, rng=(0, 1e8)),
    F("verification_status", "string", "VERIFIED only for PAYSLIP/BANK_STATEMENT/TAX_RETURN", enum=VERIF),
    F("recorded_date", "date", "Date evidence was recorded (effective date)"),
], fks=[("applicant_id", "Applicant", "applicant_id"), ("employment_id", "Employment", "employment_id")])

table("CreditFacility", "Existing credit facility (master). Linked to applicants through ApplicantFacility (N:M).",
      ["facility_id"], [
    F("facility_id", "string", "Facility key", uniq=True, pattern=r"^FAC-\d{6}$"),
    F("facility_type", "string", "Facility type", enum=FAC_TYPES),
    F("lender_name", "string", "Synthetic lender"),
    F("sanctioned_amount", "decimal", "Sanctioned amount / credit limit", unit=MONEY, rng=(0, 1e9)),
    F("outstanding_balance", "decimal", "Outstanding balance (0 when closed)", unit=MONEY, rng=(0, 1e9)),
    F("monthly_obligation", "decimal", "Monthly repayment / minimum due (0 when closed)", unit=MONEY, rng=(0, 1e8)),
    F("max_dpd_12m", "int", "Worst days-past-due in last 12 months", enum=[0, 30, 60, 90]),
    F("status", "string", "Facility state", enum=["ACTIVE", "CLOSED"]),
    F("opened_date", "date", "Opened"),
    F("closed_date", "date", "Closed (null while ACTIVE)", req=False),
])

table("ApplicantFacility", "Bridge table: Applicant N:M CreditFacility (joint facilities).",
      ["applicant_id", "facility_id"], [
    F("applicant_id", "string", "FK Applicant", pattern=r"^APL-\d{6}$"),
    F("facility_id", "string", "FK CreditFacility", pattern=r"^FAC-\d{6}$"),
    F("role", "string", "Role on the facility", enum=["PRIMARY", "JOINT"]),
    F("share_pct", "int", "Share of obligation borne by this applicant", unit="%", rng=(1, 100)),
], fks=[("applicant_id", "Applicant", "applicant_id"), ("facility_id", "CreditFacility", "facility_id")])

table("ProductDocumentRequirement", "Bridge table: LoanProduct N:M document types required.",
      ["product_id", "document_type"], [
    F("product_id", "string", "FK LoanProduct", pattern=r"^PRD-[A-Z]+$"),
    F("document_type", "string", "Required document type", enum=DOC_TYPES),
    F("is_mandatory", "bool", "Mandatory for approval"),
], fks=[("product_id", "LoanProduct", "product_id")])

table("LoanApplication", "Loan application; status is the projection of ApplicationEvent.",
      ["application_id"], [
    F("application_id", "string", "APP-2026-000001 style key", uniq=True, pattern=r"^APP-2026-\d{6}$"),
    F("applicant_id", "string", "FK Applicant", pattern=r"^APL-\d{6}$"),
    F("product_id", "string", "FK LoanProduct", pattern=r"^PRD-[A-Z]+$"),
    F("requested_principal", "decimal", "Requested principal", unit=MONEY, rng=(1, 1e9)),
    F("requested_term_months", "int", "Requested term", unit="months", rng=(1, 600)),
    F("purpose", "string", "Loan purpose", enum=PURPOSES),
    F("channel", "string", "Submission channel", enum=CHANNELS),
    F("submitted_at", "datetime", "Submission timestamp"),
    F("status", "string", "Current lifecycle state", enum=APP_STATUS),
    F("status_updated_at", "datetime", "Timestamp of last state change"),
    F("loan_id", "string", "LOAN-2026-000001 style id, set once the application is approved", req=False,
      uniq=True, pattern=r"^LOAN-2026-\d{6}$"),
], fks=[("applicant_id", "Applicant", "applicant_id"), ("product_id", "LoanProduct", "product_id")])

table("Document", "Document status rows (append-only; a re-upload is a new row superseding the old one).",
      ["document_id"], [
    F("document_id", "string", "DOC-<application-id>-001", uniq=True, pattern=r"^DOC-APP-2026-\d{6}-\d{3}$"),
    F("application_id", "string", "FK LoanApplication", pattern=r"^APP-2026-\d{6}$"),
    F("document_type", "string", "Document type", enum=DOC_TYPES),
    F("status", "string", "Verification status", enum=DOC_STATUS),
    F("received_at", "datetime", "Received timestamp (null when MISSING)", req=False),
    F("status_at", "datetime", "When this status was recorded (effective timestamp)"),
    F("supersedes_document_id", "string", "Earlier row of same type replaced by this one", req=False,
      pattern=r"^DOC-APP-2026-\d{6}-\d{3}$"),
], fks=[("application_id", "LoanApplication", "application_id"),
        ("supersedes_document_id", "Document", "document_id")])

table("AffordabilityCheck", "Derived affordability / credit attributes per check run (append-only).",
      ["check_id"], [
    F("check_id", "string", "AFC-<application-id>-01", uniq=True, pattern=r"^AFC-APP-2026-\d{6}-\d{2}$"),
    F("application_id", "string", "FK LoanApplication", pattern=r"^APP-2026-\d{6}$"),
    F("checked_at", "datetime", "Check timestamp (as-of for all derivations)"),
    F("income_basis", "string", "VERIFIED = proof document + verified income evidence; else declared income",
      enum=["VERIFIED", "DECLARED_UNVERIFIED"]),
    F("monthly_income_used", "decimal", "Income used: lowest verified source (conservative)", unit=MONEY, rng=(0, 1e8)),
    F("income_source_count", "int", "Number of verified sources compared", rng=(0, 3)),
    F("income_conflict_flag", "bool", "True if verified sources differ by more than 20%"),
    F("existing_obligations_monthly", "decimal", "Sum of active facility obligations x share", unit=MONEY, rng=(0, 1e8)),
    F("proposed_installment", "decimal", "Annuity instalment for requested principal/term", unit=MONEY, rng=(0, 1e9)),
    F("dti_before_pct", "decimal", "existing obligations / income x 100", unit="%", rng=(0, 999.99)),
    F("dti_after_pct", "decimal", "(existing + proposed) / income x 100", unit="%", rng=(0, 999.99)),
    F("disposable_income_after", "decimal", "income - existing - proposed", unit=MONEY, rng=(-1e9, 1e9)),
    F("credit_score", "int", "Derived credit score from facilities, DPD, history, enquiries", rng=(300, 900)),
    F("utilisation_pct", "decimal", "Card balance / card limit x 100 (null if no active card)", req=False, unit="%", rng=(0, 1000)),
    F("max_dpd_12m", "int", "Worst DPD over recent facilities", enum=[0, 30, 60, 90]),
    F("enquiries_180d", "int", "Earlier applications by same applicant in prior 180 days", rng=(0, 50)),
    F("employment_type", "string", "Employment type at check time", enum=CHECK_EMP_TYPES),
    F("employment_tenure_months", "int", "Months in current employment", unit="months", rng=(0, 600)),
    F("docs_complete", "bool", "All mandatory documents VERIFIED at check time"),
    F("rule_version", "string", "Rule-set version used", enum=[RULE_VERSION]),
], fks=[("application_id", "LoanApplication", "application_id")])

table("Decision", "Decision events (append-only: a manual-review outcome is a new row, never an update).",
      ["decision_id"], [
    F("decision_id", "string", "DEC-<application-id>-01", uniq=True, pattern=r"^DEC-APP-2026-\d{6}-\d{2}$"),
    F("application_id", "string", "FK LoanApplication", pattern=r"^APP-2026-\d{6}$"),
    F("check_id", "string", "FK AffordabilityCheck whose numbers the decision relies on", pattern=r"^AFC-APP-2026-\d{6}-\d{2}$"),
    F("decided_at", "datetime", "Decision timestamp"),
    F("decision", "string", "Outcome", enum=DECISIONS),
    F("rule_id", "string", "Rule that fired", enum=RULE_IDS),
    F("reason_codes", "string", "Pipe-separated reason codes (see REASONS)"),
    F("rule_inputs", "json", "Exact inputs and thresholds the rule evaluated (traceability)"),
    F("decided_by", "string", "SYSTEM or ANALYST-nn", pattern=r"^(SYSTEM|ANALYST-\d{2})$"),
    F("supersedes_decision_id", "string", "Earlier decision this one resolves", req=False,
      pattern=r"^DEC-APP-2026-\d{6}-\d{2}$"),
], fks=[("application_id", "LoanApplication", "application_id"),
        ("check_id", "AffordabilityCheck", "check_id"),
        ("supersedes_decision_id", "Decision", "decision_id")])

table("RepaymentSchedule", "Annuity repayment schedule for each approved loan (one row per instalment).",
      ["schedule_id"], [
    F("schedule_id", "string", "SCH-<loan-id>-001", uniq=True, pattern=r"^SCH-LOAN-2026-\d{6}-\d{3}$"),
    F("loan_id", "string", "FK LoanApplication.loan_id", pattern=r"^LOAN-2026-\d{6}$"),
    F("application_id", "string", "FK LoanApplication", pattern=r"^APP-2026-\d{6}$"),
    F("installment_no", "int", "1..term", rng=(1, 600)),
    F("due_date", "date", "Due date (monthly, strictly increasing)"),
    F("opening_balance", "decimal", "Balance before instalment", unit=MONEY, rng=(0, 1e9)),
    F("principal_due", "decimal", "Principal component", unit=MONEY, rng=(0, 1e9)),
    F("interest_due", "decimal", "Interest component = opening x rate/12", unit=MONEY, rng=(0, 1e9)),
    F("total_due", "decimal", "principal_due + interest_due", unit=MONEY, rng=(0, 1e9)),
    F("closing_balance", "decimal", "opening - principal", unit=MONEY, rng=(0, 1e9)),
    F("status", "string", "Instalment state at snapshot date", enum=SCHED_STATUS),
], fks=[("loan_id", "LoanApplication", "loan_id"), ("application_id", "LoanApplication", "application_id")])

table("Disbursement", "Disbursement event for an approved loan (1:1 with loan).",
      ["disbursement_id"], [
    F("disbursement_id", "string", "DSB-<loan-id>", uniq=True, pattern=r"^DSB-LOAN-2026-\d{6}$"),
    F("loan_id", "string", "FK LoanApplication.loan_id", uniq=True, pattern=r"^LOAN-2026-\d{6}$"),
    F("application_id", "string", "FK LoanApplication", pattern=r"^APP-2026-\d{6}$"),
    F("eligibility_decision_id", "string", "Approving decision that made the loan eligible", pattern=r"^DEC-APP-2026-\d{6}-\d{2}$"),
    F("amount", "decimal", "Disbursed amount = requested principal", unit=MONEY, rng=(1, 1e9)),
    F("disbursed_at", "datetime", "Disbursement timestamp"),
    F("status", "string", "Disbursement state", enum=["DISBURSED"]),
], fks=[("loan_id", "LoanApplication", "loan_id"), ("application_id", "LoanApplication", "application_id"),
        ("eligibility_decision_id", "Decision", "decision_id")])

table("ApplicationEvent", "Immutable state-change history of an application.",
      ["event_id"], [
    F("event_id", "string", "EVT-<application-id>-NN", uniq=True, pattern=r"^EVT-APP-2026-\d{6}-\d{2}$"),
    F("application_id", "string", "FK LoanApplication", pattern=r"^APP-2026-\d{6}$"),
    F("event_seq", "int", "1-based sequence within the application", rng=(1, 50)),
    F("event_type", "string", "Event type", enum=EVENT_TYPES),
    F("from_status", "string", "Previous state (null for first event)", req=False, enum=APP_STATUS),
    F("to_status", "string", "New state", enum=APP_STATUS),
    F("event_ts", "datetime", "Event timestamp"),
    F("actor", "string", "APPLICANT, SYSTEM or ANALYST-nn", pattern=r"^(APPLICANT|SYSTEM|ANALYST-\d{2})$"),
    F("ref_id", "string", "Related check/decision/disbursement id", req=False),
], fks=[("application_id", "LoanApplication", "application_id")])

RELATIONSHIPS = [
    ("Applicant", "Employment", "1:N", "required", "history; <=1 current row (end_date null)"),
    ("Applicant", "IncomeRecord", "1:N", "required", "append-only evidence; Employment link optional"),
    ("Employment", "IncomeRecord", "1:N", "optional", "declared other income has no employment"),
    ("Applicant", "CreditFacility", "N:M", "optional", "via ApplicantFacility (joint facilities, share_pct)"),
    ("LoanProduct", "Document types", "N:M", "required", "via ProductDocumentRequirement"),
    ("Applicant", "LoanApplication", "1:N", "optional", "an applicant may never apply, or apply several times"),
    ("LoanProduct", "LoanApplication", "1:N", "required", ""),
    ("LoanApplication", "Document", "1:N", "required", "one row per required type + re-upload rows"),
    ("LoanApplication", "AffordabilityCheck", "1:N", "required", "check -01, plus -02 after manual-review resolution"),
    ("AffordabilityCheck", "Decision", "1:N", "required", "each decision cites the check it used"),
    ("LoanApplication", "Decision", "1:N", "required", "DEC-..-01 system, DEC-..-02 analyst"),
    ("LoanApplication", "ApplicationEvent", "1:N", "required", "full state history"),
    ("LoanApplication", "RepaymentSchedule", "1:N", "optional", "only when approved (loan_id assigned)"),
    ("LoanApplication", "Disbursement", "1:1", "optional", "only DISBURSED loans"),
]


# ------------------------------------------------------------------ helpers
def snake(name):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def field_names(table_name):
    return [f["name"] for f in TABLES[table_name]["fields"]]


SQL_TYPES = {"string": "VARCHAR(255)", "int": "INTEGER", "decimal": "NUMERIC(16,2)",
             "date": "DATE", "datetime": "TIMESTAMP", "bool": "BOOLEAN", "json": "TEXT"}


def _lit(v):
    return "'" + str(v) + "'" if isinstance(v, str) else str(v)


def ddl():
    out = ["-- Generated by schema.py (SQLite / PostgreSQL compatible)", ""]
    for t in TABLES.values():
        lines = []
        for f in t["fields"]:
            col = f"  {f['name']} {SQL_TYPES[f['type']]}"
            if f["required"]:
                col += " NOT NULL"
            if f["enum"]:
                col += f" CHECK ({f['name']} IN ({', '.join(_lit(e) for e in f['enum'])}))"
            lines.append(col)
        lines.append(f"  PRIMARY KEY ({', '.join(t['pk'])})")
        for f in t["fields"]:
            if f["unique"] and t["pk"] != [f["name"]]:
                lines.append(f"  UNIQUE ({f['name']})")
        for col, rt, rc in t["fks"]:
            lines.append(f"  FOREIGN KEY ({col}) REFERENCES {rt}({rc})")
        out.append(f"CREATE TABLE {t['name']} (\n" + ",\n".join(lines) + "\n);\n")
    return "\n".join(out)


def markdown():
    md = ["# Data dictionary", "",
          f"Currency: **{CURRENCY}**. Dates `YYYY-MM-DD`, datetimes `YYYY-MM-DDTHH:MM:SS` (no timezone, synthetic). "
          f"Rule version `{RULE_VERSION}`.", "",
          "## Relationships and cardinality", "",
          "| Parent | Child | Cardinality | Optionality | Note |", "|---|---|---|---|---|"]
    for p, c, card, opt, note in RELATIONSHIPS:
        md.append(f"| {p} | {c} | {card} | {opt} | {note} |")
    md += ["", "## Lifecycle (LoanApplication.status)", "", "```"]
    for k, v in TRANSITIONS.items():
        md.append(f"{k or '(start)'} -> {', '.join(v) if v else '(terminal)'}")
    md += ["```", "", "ID conventions: `APP-2026-000001`, `LOAN-2026-000001`, "
           "`DOC-<application-id>-001`, `DEC-<application-id>-01` (plus `AFC-`, `EVT-`, `SCH-`, `DSB-` derived the same way).", ""]
    for t in TABLES.values():
        md += [f"## {t['name']}", "", t["desc"], "", f"**Primary key:** `{', '.join(t['pk'])}`  ",
               "**Foreign keys:** " + (", ".join(f"`{c}` -> {rt}.{rc}" for c, rt, rc in t["fks"]) or "none"), "",
               "| Field | Type | Required | Unique | Allowed values / range / pattern | Unit | Description |",
               "|---|---|---|---|---|---|---|"]
        for f in t["fields"]:
            allowed = ""
            if f["enum"]:
                allowed = ", ".join(str(e) for e in f["enum"])
            elif f["range"]:
                allowed = f"{f['range'][0]} .. {f['range'][1]}"
            elif f["pattern"]:
                allowed = f"`{f['pattern']}`"
            md.append(f"| {f['name']} | {f['type']} | {'yes' if f['required'] else 'no'} | "
                      f"{'yes' if f['unique'] else ''} | {allowed} | {f['unit'] or ''} | {f['desc']} |")
        md.append("")
    md += ["## Reason codes", "", ", ".join(f"`{r}`" for r in REASONS), "",
           "## Protected attributes (stored, never used by any rule)", "",
           ", ".join(f"`{p}`" for p in PROTECTED_ATTRIBUTES), ""]
    return "\n".join(md)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", help="directory to write schema.sql and DATA_DICTIONARY.md")
    a = ap.parse_args()
    if a.write:
        os.makedirs(a.write, exist_ok=True)
        with open(os.path.join(a.write, "schema.sql"), "w") as fh:
            fh.write(ddl())
        with open(os.path.join(a.write, "DATA_DICTIONARY.md"), "w") as fh:
            fh.write(markdown())
        print("written", a.write)
    else:
        print(markdown())
