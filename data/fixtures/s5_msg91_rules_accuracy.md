# Extraction accuracy: msg91_soc2.pdf via `rules`

**26 / 26 fields correct (100%)** against `s5_msg91_ground_truth.json`.

| Field | Key | Expected | Got | OK |
|---|---|---|---|---|
| report_type | value | SOC2_TYPE2 | SOC2_TYPE2 | yes |
| report_type | page | 1 | 1 | yes |
| period | start | 2024-01-26 | 2024-01-26 | yes |
| period | end | 2024-04-26 | 2024-04-26 | yes |
| period | page | 1 | 1 | yes |
| next_report_due | value | 2025-04-27 | 2025-04-27 | yes |
| next_report_due | page | 1 | 1 | yes |
| report_date | value | 2024-05-15 | 2024-05-15 | yes |
| report_date | page | 9 | 9 | yes |
| opinion | value | UNQUALIFIED | UNQUALIFIED | yes |
| opinion | page | 8 | 8 | yes |
| categories | in_scope | ['Availability', 'Confidentiality', 'Security'] | ['Availability', 'Confidentiality', 'Security'] | yes |
| categories | also_mentioned | ['Privacy', 'Processing Integrity'] | ['Privacy', 'Processing Integrity'] | yes |
| categories | page | 6 | 6 | yes |
| subservice_orgs | values | ['Amazon Web services(AWS)', 'Github(Github Inc)', 'Google LLC (Google Workspace)', 'MongoDB', 'MySQL'] | ['Amazon Web services(AWS)', 'Github(Github Inc)', 'Google LLC (Google Workspace)', 'MongoDB', 'MySQL'] | yes |
| subservice_orgs | method | carve-out | carve-out | yes |
| subservice_orgs | page | 6 | 6 | yes |
| cuecs | count | 12 | 12 | yes |
| cuecs | page | 30 | 30 | yes |
| csoc_criteria | values | ['A1.2', 'A1.3', 'C1.1', 'C1.2', 'CC6.1', 'CC6.2', 'CC6.3', 'CC6.4', 'CC6.5', 'CC7.2'] | ['A1.2', 'A1.3', 'C1.1', 'C1.2', 'CC6.1', 'CC6.2', 'CC6.3', 'CC6.4', 'CC6.5', 'CC7.2'] | yes |
| csoc_criteria | page | 31 | 31 | yes |
| auditor | signer | Neha Mishra | Neha Mishra | yes |
| auditor | firm | Atom Assurances | Atom Assurances | yes |
| auditor | page | 9 | 9 | yes |
| test_results | exceptions_noted | 0 | 0 | yes |
| test_results | from_page | 34 | 34 | yes |

Ground truth was read by hand from the document; see SOURCES.md.
