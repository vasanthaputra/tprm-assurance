# tprm-assurance

**Decide whether you can rely on a vendor's assurance evidence, and show why.**

Third-party risk teams spend their time on two questions: *is our vendor inventory complete and current?* and *can we rely on this vendor's SOC 2 report?* Most open-source TPRM tools either run the whole GRC programme or summarise SOC 2 reports with AI and assert time savings. tprm-assurance does the reviewer's actual checks, ties every rule to a published source, and (in later modules) measures how often its AI extraction is right.

## Status

| Module | What it does | Status |
|---|---|---|
| 1. Register check | Inventory completeness against accounts payable; reassessment by tier; DPA for personal data; report type, staleness, bridge letters | **Done**: 10 tests |
| 2. Risk acceptance | Approver by delegated authority; owner; time-boxed expiry; max duration by rating; aging KRI | **Done**: 8 tests |
| 3. SOC 2 reliance | Extracts period, opinion, scope, subservice carve-outs, CUECs, CSOC criteria, auditor and test results from the PDF, each with its page; reliance rules propose findings; **a human approves or rejects each one** (append-only log, each decision bound to a hash of the extraction so it can't leak onto another report) | **Done**: 6 tests, verified against a real public report |
| 4. Evaluation | `soc2 score` compares any extraction to hand-verified ground truth, field by field | **Done**: rules extractor = [26/26 fields](data/fixtures/s5_msg91_rules_accuracy.md) on the one public report; the AI paths are not yet measured |

## Run it

```bash
pip install -r requirements.txt
python -m tprm_assurance.cli demo            # every check on the sample data -> out/
python -m tprm_assurance.cli register data/sample/vendor_register.csv data/sample/ap_vendors.csv
python -m tprm_assurance.cli acceptances data/sample/risk_acceptances.csv
python -m tprm_assurance.cli soc2 extract vendor_report.pdf --out extraction.json
python -m tprm_assurance.cli soc2 review extraction.json --context data/sample/soc2_context.yaml --out review.md
python -m tprm_assurance.cli soc2 decide extraction.json "vendor-report:REPORT_STALE:1" approve --reviewer "your name" --note "confirmed on page 1"
python -m tprm_assurance.cli soc2 score extraction.json        # accuracy vs ground truth
python -m pytest
```

Two-minute version for a demo or interview: [`docs/WALKTHROUGH.md`](docs/WALKTHROUGH.md).

### Three ways to extract facts from a SOC 2 report

| Path | Needs | How |
|---|---|---|
| `--extractor rules` (default) | `pypdf` | Pattern matching on the page text. Deterministic, traceable, no AI. |
| **Copy-paste** | a Claude (or other assistant) chat window | `soc2 prompt report.pdf --out prompt.txt`, paste the file into the chat, save the JSON reply, run `soc2 review` on it. No API key. |
| `--extractor anthropic` | `pip install anthropic` + credentials | Sends the PDF to the API with a strict JSON schema. **Written but not yet run.** |

Whatever produced the extraction, the reliance rules and the human gate are the same. The reviewer's context file (what services you use, which categories you need, which subservice reports and CUEC owners you already have) changes the outcome, and it is your input, not a fact about the vendor.

Output: [`data/sample/sample_report.md`](data/sample/sample_report.md), an exposure-by-tier summary, findings by rule with their source, then every finding.

## Where the rules come from

Every rule cites a source in [`SOURCES.md`](SOURCES.md): the 2023 Fed/FDIC/OCC interagency third-party guidance, GDPR Art. 28, and an MIT-licensed practitioner SOC 2 review method. Where a source deliberately leaves a value to the organisation (for example, how often to reassess a medium-risk vendor), [`policy.yaml`](policy.yaml) marks it **ORG POLICY** so you can change it.

[`docs/soc2_report_anatomy.md`](docs/soc2_report_anatomy.md) walks through the structure of a real, vendor-published SOC 2 Type 2 report and what a reviewer checks in each section.

## Data

Sample data is **synthetic** and labelled as such. Real assessment results are confidential, and pinning invented findings on a real company would be false. The answer key (`data/sample/answer_key.csv`) lists every planted problem plus look-alike rows that must *not* be flagged. The tests require an exact match.
