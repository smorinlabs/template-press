# P11A first plan review and corrections

The first plan review required corrections. Revision 2 records the changes
below and still needs independent confirmation before implementation.
The plan's scope remains CI diagnostics, existing-gate repairs and measured
optimizations that preserve native behavioral coverage.

## Review evidence

- Internal Epicero review: three P2 plan findings. The reviewer verified all
  272 frozen manifest hashes and independently recomputed the timing summaries.
- Muse review: five findings, with four labeled blockers and one major item.
  Root read the complete report, checked its source claims and qualified the
  overstatements below instead of accepting every severity label literally.
- Requested Muse effort was Ultra with a maximum of 100 model steps. The service
  reported Ultra unavailable and used `xhigh`. It completed in 124.57 seconds;
  actual step count was not exposed. This was not a completed Ultra review.
- The first full-snapshot Muse invocation was rejected by automatic approval
  review and did not run. A reduced package was accepted: ten byte-verified
  public CI/test files plus three P11A plan/evidence documents. It excluded the
  rest of the checkout, raw account metadata and unrelated project documents.

The source reviewed was plan commit
`497bc0d3c4317d0a9445f2b181aad3b17915543c`; public CI/test source matched tree
`0ad63b29862c20d28479094ece5ded1f711e399f`.
Reports are retained in the session evidence directory.

| Finding | Assessment | Revision 2 correction |
|---|---|---|
| `P11A-INT-01`: missing `changes.code` can pass `ci-ok` | Confirmed existing source gap. | Assign production selector/result validation and passing, missing, invalid and unexpected-skip controls. |
| `P11A-INT-02`: required `trufflehog` lacks `merge_group` | Confirmed scheduling gap; no claim of an actual queue incident. | Add the event with existing non-PR full-history scan semantics, context/event mapping and outcome controls. |
| `P11A-INT-03`: moving external blueprint confounds benchmarks | Confirmed evidence gap. | Record the actual clone revision/input against each measured live test; reject missing or different provenance. |
| `F-P11A-01`: failed lint selector makes required jobs skip | Confirmed separate required-context gap. | Make failed/cancelled/invalid lint selection fail named lint contexts; preserve valid-false skips. |
| `F-P11A-02`: diagnostics need explicit upload conditioning | Useful implementation clarification; no new upload code exists yet. | Require bounded `if: always()` uploads, separate artifact paths and native failure controls. |
| `F-P11A-03`: preflight needs a concrete bound | Accept explicit value; an enclosing job bound already prevented an indefinite wait. | Set proposed preflight/full/job limits to 5/15/25 minutes and uploads to 2 minutes; verify actual margins. |
| `F-P11A-04`: baseline spread is ambiguous | Clarify that the intended baseline is the controlled experiment, not the changing-source historical sample. | Define positive paired deltas and compare their median with the three controlled baseline timings' range; include a labeled illustration. |
| `F-P11A-05`: flags, files and locked tools need specificity | Accepted clarification. | Name duration/fault-handler flags, separate JUnit files, Bun/CPU metadata, 7-day retention and no dependency upgrade. |

The new published-credit supplement distinguishes cost priorities from latency.
It models relative published rates without claiming an actual bill. The plan
also permits independent CI-only work in parallel with P11 closeout, but requires
accepted P11 integration before performance comparisons and final delivery.
No source/workflow optimization or behavioral control has been implemented by
these documentation corrections.
