# tprm-assurance

**Decide whether you can rely on a vendor's assurance evidence, and show why.**

Third-party risk teams spend their time on two questions: *is our vendor inventory complete and current?* and *can we rely on this vendor's SOC 2 report?* Most open-source TPRM tools either run the whole GRC programme or summarise SOC 2 reports with AI and assert time savings. tprm-assurance does the reviewer's actual checks, ties every rule to a published source, and (in later modules) measures how often its AI extraction is right.

**Live showcase:** [domaskai.com/projects/tprm](https://domaskai.com/projects/tprm): the method, the measured results (anonymized) and a click-through demo on a fictional report. Source: `site/index.html`, served by a Cloudflare Worker built with `site/build_worker.py`.

## Status

| Module | What it does | Status |
|---|---|---|
| 1. Register check | Inventory completeness against accounts payable; reassessment by tier; DPA for personal data; report type, staleness, bridge letters | **Done**: 10 tests |
| 2. Risk acceptance | Approver by delegated authority; owner; time-boxed expiry; max duration by rating; aging KRI | **Done**: 8 tests |
| 3. SOC 2 reliance | Extracts period, opinion, scope, subservice carve-outs, CUECs, CSOC criteria, auditor and test results from the PDF, each with its page; reliance rules propose findings; **a human approves or rejects each one** (append-only log, each decision bound to a hash of the extraction so it can't leak onto another report) | **Done**: verified against a real report (kept local; restricted use) |
| 4. Evaluation | `soc2 score` compares any extraction to hand-read ground truth, field by field | **Measured on 2 real reports** ([results](docs/results_2026-11-10.md)): on the report it was not built from, the rules extractor scored 10/27 and missed every real reliance finding; Claude scored 25-26/27 with **0 factual errors** on both reports and produced the same 13 findings as the answer key, at $0.18-0.36 per report (page-text route) |
| 5. Conflict queue | When two extractions of one report disagree (rules vs AI), each disagreement is listed for a person to resolve: take A, take B, or type the value from the report. Append-only log bound to a hash of the pair. `soc2 merge` is refused while a disagreement that decides a reliance rule is open; the gate in `policy.yaml` has no "off" setting | **Done**: 14 tests on synthetic disagreements; not yet run on a real AI reply |

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
| `--extractor anthropic` or `anthropic-text` | `pip install anthropic` + `ANTHROPIC_API_KEY` | Sends the PDF (or its page text) to Claude with a strict JSON schema. Token use and cost are written next to the output as `.meta.json`. Measured 2026-11-10, see the run results. |

Whatever produced the extraction, the reliance rules and the human gate are the same.

### When two extractors disagree

Neither extractor is the record; the report is. Run two (for example rules and copy-paste) and compare them instead of trusting either:

```bash
python -m tprm_assurance.cli soc2 conflicts rules.json ai.json            # the queue, with BLOCKED or not
python -m tprm_assurance.cli soc2 resolve rules.json ai.json cuecs.count manual --value 12 --reviewer "your name" --note "12 bullets on page 30"
python -m tprm_assurance.cli soc2 merge rules.json ai.json --out merged.json   # exit 2 while blocked
python -m tprm_assurance.cli soc2 review merged.json --context data/sample/soc2_context.yaml
```

Optional: ask TypeSafe's Jev decision model which reading the cited page supports (needs `pip install typesafe-sdk` and `TYPESAFE_API_KEY`). One yes/no question per disputed value; at or above `jev_yes` (0.8) it is supported, at or below `jev_no` (0.2) it is not, in between the person decides. Counts and dates are never sent to Jev (its own docs say it does not count reliably and reads dates as text). The suggestion is a column in the queue; it never resolves anything.

```bash
python -m tprm_assurance.cli soc2 jev-check rules.json ai.json --pdf vendor_report.pdf --out suggestions.json
python -m tprm_assurance.cli soc2 conflicts rules.json ai.json --suggestions suggestions.json
```

Status: measured 2026-11-10 ([results](docs/results_2026-11-10.md)). Planted-error test, 46 questions on 2 real reports: **0 planted wrong values accepted, 0 true values rejected**; 43 settled, 3 sent to a person (two of them the self-contradicting scope page marked hard before the run). On real rules-vs-Claude disagreements: 11 of 12 settled correctly, 1 to a person, 0 wrong.

**HIGH** = the field decides whether a reliance rule fires (report type, period, opinion, categories, subservice organisations, CUEC count, exceptions). **LOW** = a page citation or detail text; a test checks that changing any LOW field changes no rule outcome. Differences in capitalisation, spacing or list order are not conflicts; one extractor saying "not found" while the other found a value is. Resolve every conflict before approving findings: the merged file is a new extraction with its own hash, so findings decided on it do not carry over if it is merged again. The reviewer's context file (what services you use, which categories you need, which subservice reports and CUEC owners you already have) changes the outcome, and it is your input, not a fact about the vendor.

Output: [`data/sample/sample_report.md`](data/sample/sample_report.md), an exposure-by-tier summary, findings by rule with their source, then every finding.

## Web app (local)

```bash
pip install -r requirements.txt fastapi uvicorn jinja2 python-multipart
python -m tprm_assurance.web          # then open http://127.0.0.1:8765
```

Upload a SOC 2 PDF (or open the fictional sample), read it with the rules extractor and, if `ANTHROPIC_API_KEY` is set,
with Claude; approve or reject each proposed finding; compare the two readings, ask Jev to check the cited pages
(`TYPESAFE_API_KEY`), resolve each disagreement and merge. It is a thin layer over the same modules as the command line,
with no decision logic of its own.

It runs on your machine only, by design: SOC 2 reports are restricted-use documents, and files stay in `workspace/`
(git-ignored). It answers only on localhost (blocks DNS rebinding), every form carries a per-process token and
cross-site posts are refused (OWASP synchronizer-token pattern), uploads must be PDFs (checked by content, 40 MB
limit), state changes redirect so a refresh never repeats a decision, and API keys are never rendered.

## Where the rules come from

Every rule cites a source in [`SOURCES.md`](SOURCES.md): the 2023 Fed/FDIC/OCC interagency third-party guidance, GDPR Art. 28, and an MIT-licensed practitioner SOC 2 review method. Where a source deliberately leaves a value to the organisation (for example, how often to reassess a medium-risk vendor), [`policy.yaml`](policy.yaml) marks it **ORG POLICY** so you can change it.


## Related work

Open-source GRC platforms such as [CISO Assistant](https://github.com/intuitem/ciso-assistant-community), [Probo](https://github.com/getprobo/probo) and [Openlane](https://github.com/theopenlane/core) store vendors, controls and evidence, and Probo exposes its data to AI agents through MCP. [HoundDog](https://github.com/hounddogai/hounddog) takes the same deterministic-first, AI-where-it-earns-it stance as this project. None of them, as far as their READMEs say, decide whether a SOC 2 report can be *relied on* (period and bridge letter, scope against the services used, carve-outs, CUEC ownership), publish how accurate their AI extraction is, or model the risk-acceptance lifecycle. That is the narrow slice this project covers.

## Data

Sample data is **synthetic** and labelled as such. Real assessment results are confidential, and pinning invented findings on a real company would be false. The answer key (`data/sample/answer_key.csv`) lists every planted problem plus look-alike rows that must *not* be flagged. The tests require an exact match.
