# Sources

Every rule in Vendor-Rely comes from one of these. Nothing is invented. Where a source leaves a value to the organisation, `policy.yaml` marks it **ORG POLICY**.

| # | Source | What we take from it | Retrieved |
|---|---|---|---|
| S1 | Board / FDIC / OCC, *Interagency Guidance on Third-Party Relationships: Risk Management*, 88 FR 37920 (June 9, 2023). govinfo.gov/content/pkg/FR-2023-06-09/pdf/2023-12340.pdf | Keep a **complete inventory** of third parties; **periodically** reassess each; **more rigorous oversight for critical activities**; life cycle = planning, due diligence, contract, ongoing monitoring, termination; subcontractor risk | 2026-10-29 |
| S2 | GDPR Art. 28(3), Regulation (EU) 2016/679 | Processing by a processor "shall be governed by a contract" → personal data without a signed DPA is a finding | 2026-10-29 |
| S3 | Sushegaad, *Claude-Skills-Governance-Risk-and-Compliance*, `plugins/tprm/skills/tprm/references/soc2-report-review.md` (MIT, 1,012★) | SOC 2 report anatomy; bridge letter after ~3 months, issued by service-org management; report older than ~15 months = red flag; Type I where Type II expected = red flag; carve-out vs inclusive; CUEC ownership | 2026-10-29 |
| S4 | snehjeet1703/GRCWorks, `src/lib/lab/exercises.ts` (MIT) | Vendor-register review rules (DPA, overdue review 12/24 months by tier, expired report, never assessed); the fictional vendor names used in sample data | 2026-10-29 |
| S5 | MSG91 / Walkover Web Solutions, *SOC 2 Type 2 Report*, observation period 26 Jan – 26 Apr 2024, published at msg91.com/pdf/soc2.pdf | **Real** report structure: opinion, restricted use, management assertion (DC 200), system description, CUECs, CSOCs with criteria mapping (e.g. AWS → CC6.1, CC6.2…), testing matrix, "No exceptions noted" convention. Used as a structural reference only, not redistributed | 2026-10-29 |
| S6 | Netspective, public SOC 2 Type 1 report (github.com/netspective/www.netspective.com, GPL-3.0) | Second real structure reference (executive summary, auditor firm, categories in scope) | 2026-10-29 |
| S7 | AICPA & CIMA, *Illustrative SOC 2® Report with Illustrative System Description* (Sept 30, 2023) | Official template. **Member-access only, not read.** Listed so the gap is visible | not accessed |

## Sample data

`data/sample/` is **synthetic** and says so in every file. Real vendors' assessment results are confidential, and attributing invented findings to a real company would be false. The vendor names come from S4 (fictional). The columns follow S1, S2 and S3.
