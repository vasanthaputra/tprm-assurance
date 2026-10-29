# Vendor-Rely

**Decide whether you can rely on a vendor's assurance evidence, and show why.**

Third-party risk teams spend their time on two questions: *is our vendor inventory complete and current?* and *can we rely on this vendor's SOC 2 report?* Most open-source TPRM tools either run the whole GRC programme or summarise SOC 2 reports with AI and assert time savings. Vendor-Rely does the reviewer's actual checks, ties every rule to a published source, and (in later modules) measures how often its AI extraction is right.

## Status

| Module | What it does | Status |
|---|---|---|
| 1. Register check | Inventory completeness against accounts payable; reassessment by tier; DPA for personal data; report type, staleness, bridge letters | **Done**: 10 tests |
| 2. Risk acceptance | Approver by delegated authority, conditions, expiry, aging | Planned |
| 3. SOC 2 reader | AI extracts period, opinion, scope, exceptions, CUECs, carve-outs, each with a page citation; rules decide; a human approves | Planned |
| 4. Evaluation | Extraction accuracy per field, published here | Planned |

## Run it

```bash
pip install pyyaml pytest
python -m vendor_rely.cli register data/sample/vendor_register.csv data/sample/ap_vendors.csv
python -m pytest
```

Output: [`data/sample/sample_report.md`](data/sample/sample_report.md), an exposure-by-tier summary, findings by rule with their source, then every finding.

## Where the rules come from

Every rule cites a source in [`SOURCES.md`](SOURCES.md): the 2023 Fed/FDIC/OCC interagency third-party guidance, GDPR Art. 28, and an MIT-licensed practitioner SOC 2 review method. Where a source deliberately leaves a value to the organisation (for example, how often to reassess a medium-risk vendor), [`policy.yaml`](policy.yaml) marks it **ORG POLICY** so you can change it.

[`docs/soc2_report_anatomy.md`](docs/soc2_report_anatomy.md) walks through the structure of a real, vendor-published SOC 2 Type 2 report and what a reviewer checks in each section.

## Data

Sample data is **synthetic** and labelled as such. Real assessment results are confidential, and pinning invented findings on a real company would be false. The answer key (`data/sample/answer_key.csv`) lists every planted problem plus look-alike rows that must *not* be flagged. The tests require an exact match.
