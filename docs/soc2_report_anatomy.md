# What a real SOC 2 report looks like (and what a reviewer checks)

Built from a **real, vendor-published** SOC 2 Type 2 (S5: MSG91 / Walkover Web Solutions, period 26 Jan – 26 Apr 2024) and a practitioner review method (S3). The AICPA's official illustrative report (S7) is member-only and was not read.

## The sections, in the order they appear (S5 table of contents)

| Section | What's in it | What the reviewer checks (S3) |
|---|---|---|
| 1. Independent Service Auditor's Report | Scope, responsibilities, inherent limitations, **Opinion**, **Restricted use**, signature, license, date | Opinion type (unqualified / qualified / adverse / disclaimer); **period**; categories in scope; who signed it |
| 2. Management's Assertion | Management claims the description is fair, "based on the criteria… in DC section 200" | Management owns the claims; the auditor only opines on them |
| 3. System Description | Services, infrastructure, software, people, data, procedures; control environment, risk assessment, **vendor risk assessment**, monitoring | **Is the service you actually use inside the boundary?** |
| — CUECs | Controls the **customer** must run (S5 lists 12, e.g. "reviewing customer access… periodically", "removing terminated employee access") | Assign an internal owner to each. An unowned CUEC is a finding on your side |
| — CSOCs | Subservice organisations **carved out**, with criteria mapping (S5: AWS → CC6.1, CC6.2, CC6.3, CC6.5, CC7.2; also GitHub, MongoDB, Google Workspace) | Get those providers' own reports. The auditor states it "did not evaluate" them |
| 4. Tests of Operating Effectiveness | Testing matrix: control #, control activity, test applied, result. Clean = **"No exceptions noted."** | **Exceptions live here.** Anything other than that phrase is a deviation (S5's own definition) |

## Real-world observations from S5 (what a reviewer would raise)

These are **observations from reading the document, not conclusions about the vendor.** A reviewer would ask about them; they don't prove anything is wrong.

1. **Observation period is 3 months** (26 Jan – 26 Apr 2024). S3 says Type 2 periods are "commonly 6 or 12 months". A short first-year period is common, but ask.
2. **The next report is due 27 Apr 2025**, a year after a 3-month period. Most of that year has no coverage → **bridge letter** (S3: needed once the period ended more than ~3 months ago).
3. **Scope wording is inconsistent.** It lists "Security, Confidentiality, Availability, Processing Integrity & Privacy" and then "Security, Confidentiality and Availability", and uses the pre-2017 term "Trust Services **Principles**". Confirm which categories were actually tested.
4. **The signature block names an individual CPA with a licence number**; the firm ("Atom Assurances") appears only later, in the sampling section. Verify the issuer's licence and standing with the issuing body.
5. **Five subservice organisations are carved out**, including the whole hosting layer (AWS). S3 red flag: "carve-out of the entire hosting layer with no subservice assurance". Obtain AWS's own report.

## Second reference (S6, Netspective SOC 2 Type 1)
It labels an "Audit Period: November 1, 2024, to November 30, 2024" on a **Type 1** report. A Type 1 is as of a point in time; a date range on a Type 1 is a question for the issuer. It also names the audit firm and lead CPA, which S5 does not do in the same way.
