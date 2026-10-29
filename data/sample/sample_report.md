# Vendor register review, as of 2026-10-29

## Exposure by tier

| Tier | Vendors | Vendors with findings | Findings |
|---|---|---|---|
| CRITICAL | 4 | 2 | 3 |
| HIGH | 4 | 3 | 3 |
| MEDIUM | 3 | 2 | 2 |
| LOW | 3 | 1 | 1 |

**Paid but not in the register:** 2

## Findings by rule

| Rule | Meaning | Count | Source |
|---|---|---|---|
| NOT_IN_REGISTER | Paid through accounts payable but missing from the vendor register | 2 | S1 |
| NEVER_ASSESSED | In the register but never assessed | 1 | S1, S4 |
| REVIEW_OVERDUE | Reassessment is past due for this tier | 2 | S1, S4 |
| NO_DPA | Processes personal data with no signed data processing agreement | 2 | S2, S4 |
| NO_ASSURANCE_REPORT | Critical/high vendor with no SOC 2 or ISO report on file | 1 | S3 |
| TYPE1_WHERE_TYPE2 | Only a SOC 2 Type 1 (point in time) where a Type 2 is expected | 1 | S3 |
| REPORT_STALE | Report period ended too long ago to rely on | 1 | S3 |
| BRIDGE_LETTER_NEEDED | Report period ended over 3 months ago and no bridge letter is on file | 1 | S3 |

## All findings

| Vendor | Rule | Detail |
|---|---|---|
| PayrollPro | BRIDGE_LETTER_NEEDED | period ended 2026-05-31 (4 months ago), no bridge letter |
| SecureShred | NEVER_ASSESSED | no assessment date recorded |
| CloudStore EU | NOT_IN_REGISTER | paid 2026-09-18, not in register |
| TravelEase APAC | NOT_IN_REGISTER | paid 2026-10-14, not in register |
| AuditPartners | NO_ASSURANCE_REPORT | CRITICAL vendor with no report on file |
| CloudStore | NO_DPA | personal data = yes, DPA signed = no |
| SurveyNow | NO_DPA | personal data = yes, DPA signed = no |
| ExpenseIt | REPORT_STALE | period ended 2025-04-30 (17 months ago; limit 15) |
| CleanCo | REVIEW_OVERDUE | LOW vendors every 24 months; last assessed 2024-09-01 (25 months ago) |
| PayrollPro | REVIEW_OVERDUE | CRITICAL vendors every 12 months; last assessed 2025-06-01 (16 months ago) |
| LegalLink | TYPE1_WHERE_TYPE2 | HIGH vendor relies on a Type 1 report |

Sources: see SOURCES.md. Review intervals marked ORG POLICY in policy.yaml.
