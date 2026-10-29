# Risk acceptance review, as of 2026-10-29

## Open acceptances by age (days since approval)

| Rating | 0-90 | 91-180 | 181-365 | >365 |
|---|---|---|---|---|
| CRITICAL | 2 | 1 | 1 | 0 |
| HIGH | 2 | 0 | 1 | 0 |
| MEDIUM | 0 | 1 | 0 | 0 |
| LOW | 0 | 0 | 1 | 0 |

## Findings by rule

| Rule | Meaning | Count | Source |
|---|---|---|---|
| NOT_APPROVED | Open acceptance with no approver or approval date recorded | 1 | S8 (RA-7) |
| APPROVER_BELOW_AUTHORITY | Approver's role is below the authority set for this risk rating | 1 | S1, S8 (PM-28) |
| NO_OWNER | No accountable owner recorded | 1 | S1, S8 (CA-5) |
| NO_EXPIRY | Acceptance has no end date; acceptances must be time-boxed | 1 | S4, S8 (CA-5) |
| EXPIRED | End date has passed and the acceptance is still open | 2 | S8 (CA-5) |
| DURATION_OVER_MAX | Runs longer than the maximum allowed for this rating | 1 | ORG POLICY |

## All findings

| ID | Vendor | Rule | Detail |
|---|---|---|---|
| A2 | CloudStore | APPROVER_BELOW_AUTHORITY | HIGH needs SECURITY_DIRECTOR; approved by SECURITY_MANAGER |
| A3 | PayrollPro | DURATION_OVER_MAX | 2026-04-01 to 2026-09-30 is 5 months; CRITICAL max 3 |
| A10 | AuditPartners | EXPIRED | expired 2026-10-28, still open |
| A3 | PayrollPro | EXPIRED | expired 2026-09-30, still open |
| A11 | TravelEase | NOT_APPROVED | approver or approval date missing |
| A4 | SurveyNow | NO_EXPIRY | expires_on is blank |
| A6 | ExpenseIt | NO_OWNER | owner is blank |

Sources: see SOURCES.md. Approver ladder and maximum durations are ORG POLICY in policy.yaml.
