# Two-minute walkthrough (for an interview or a demo)

**The problem.** Third-party risk teams answer two questions all day: *is our vendor inventory complete and current?* and *can we rely on this vendor's SOC 2 report?* Most tooling either runs the whole GRC programme or summarises SOC 2 reports with AI and claims time savings without measuring accuracy.

**What this does.** Four small modules, each with a check that can fail:

1. **Register check.** Reads the vendor register and the accounts-payable list. Flags vendors being paid but never assessed, overdue reassessments by tier, personal data without a DPA, expired or Type-1-only SOC 2 reports, missing bridge letters.
2. **Risk acceptance.** Every open acceptance needs an owner, an approver with enough authority for the rating, and an end date; it reports expiry, over-length acceptances, and an aging table.
3. **SOC 2 reliance.** Extracts the facts a reviewer needs from the PDF with page numbers (period, opinion, scope, carved-out providers, CUECs, test results), proposes findings, and **nothing counts until a human approves it**. Each approval is bound to a hash of the extraction, so it can't leak onto a different report.
4. **Evaluation.** Scores any extraction against hand-verified ground truth, field by field, and publishes the table.

**Three things to say out loud.**

- *"Every rule cites its source."* The 2023 interagency third-party guidance, GDPR Art. 28, NIST SP 800-53, and a practitioner SOC 2 review method. Where the regulators leave a number to the organisation (how often to reassess a medium vendor), it's marked ORG POLICY in one YAML file.
- *"The AI is optional and measured."* The default extractor is pattern-based and traceable. The AI path drops in with the same JSON shape, and module 4 scores it against ground truth before anyone trusts it. On the one public report tested, the rules extractor scores 100% of fields.
- *"The human gate is the product."* Proposed findings become findings only through a reviewer's decision, logged append-only with who, when, why, and what exactly was reviewed.

**Honest limits.** Verified on one public SOC 2 report; other auditors' wording will produce UNKNOWN fields, which route the reviewer to the page rather than guessing. The API extractor is written but not yet run. Sample data is synthetic.

**Demo in one command:** `py -3 -m tprm_assurance.cli demo` writes all three reports to `out/`.
