# SOC 2 reliance review: msg91_soc2.pdf (as of 2026-10-29)

**Nothing below is a finding until a reviewer approves it.** Status shows PROPOSED / APPROVED / REJECTED.

Extraction hash: `9f924e28cd239efc` (decisions are bound to it)

## What the extractor read

| Field | Value | Page |
|---|---|---|
| Report type | SOC2_TYPE2 | 1 |
| Period | 2024-01-26 to 2024-04-26 | 1 |
| Report date | 2024-05-15 | 9 |
| Opinion | UNQUALIFIED | 8 |
| Categories in scope | Security, Availability, Confidentiality | 6 |
| Subservice orgs (carve-out) | Amazon Web services(AWS), Github(Github Inc), MongoDB, MySQL, Google LLC (Google Workspace) | 6 |
| CUECs | 12 | 30 |
| CSOC criteria | A1.2, A1.3, C1.1, C1.2, CC6.1, CC6.2, CC6.3, CC6.4, CC6.5, CC7.2 | 31 |
| Auditor | Neha Mishra / Atom Assurances | 9 |
| Test results | 144 clean, 0 with exceptions | 34+ |

## Proposed findings

| ID | Rule | Detail | Page | Source | Status |
|---|---|---|---|---|---|
| msg91-soc2:PERIOD_SHORT:1 | PERIOD_SHORT | 2024-01-26 to 2024-04-26 is 3 months | 1 | S3 ('commonly 6 or 12 months') | PROPOSED |
| msg91-soc2:REPORT_STALE:1 | REPORT_STALE | period ended 2024-04-26 (30 months ago) | 1 | S3 | PROPOSED |
| msg91-soc2:CATEGORY_WORDING_MIXED:1 | CATEGORY_WORDING_MIXED | in scope ['Security', 'Availability', 'Confidentiality']; also named ['Processing Integrity', 'Privacy'] | 6 | S5 observation | PROPOSED |
| msg91-soc2:CARVE_OUT_NO_ASSURANCE:amazon-web-services-aws | CARVE_OUT_NO_ASSURANCE | Amazon Web services(AWS) (carve-out) | 6 | S3 | PROPOSED |
| msg91-soc2:CARVE_OUT_NO_ASSURANCE:github-github-inc | CARVE_OUT_NO_ASSURANCE | Github(Github Inc) (carve-out) | 6 | S3 | PROPOSED |
| msg91-soc2:CARVE_OUT_NO_ASSURANCE:mongodb | CARVE_OUT_NO_ASSURANCE | MongoDB (carve-out) | 6 | S3 | PROPOSED |
| msg91-soc2:CARVE_OUT_NO_ASSURANCE:mysql | CARVE_OUT_NO_ASSURANCE | MySQL (carve-out) | 6 | S3 | PROPOSED |
| msg91-soc2:CARVE_OUT_NO_ASSURANCE:google-llc-google-workspace | CARVE_OUT_NO_ASSURANCE | Google LLC (Google Workspace) (carve-out) | 6 | S3 | PROPOSED |
| msg91-soc2:CUEC_UNOWNED:1 | CUEC_UNOWNED | 12 CUECs, 0 owned | 30 | S3 | PROPOSED |

Sources: SOURCES.md. Context (services used, owners, reports held) is the reviewer's input, not a fact about the vendor.
