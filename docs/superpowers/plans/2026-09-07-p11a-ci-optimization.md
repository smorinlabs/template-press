# P11A CI measurement and optimization plan

The owner requested a CI speed and cost follow-up before P12, in parallel with
P11 closeout. This initial plan defines the investigation and delivery gates;
it does not claim that specific optimizations have already been selected.

**Project:** [P11A](../../../projects/P11A-ci-speed-and-cost-optimization.md).

## Phase 1: Establish the baseline

- Preserve commit IDs, run IDs, workflow versions and existing success evidence.
- Separate queue time, job wall time, step duration and cumulative runner minutes.
- Compare a bounded set of completed P10/P11 and comparable recent runs.
- Account for canceled or stalled work separately from ordinary passing runs.
- Inspect workflow overlap, platform scheduling, fixture subprocess work, caches,
  dependency setup and live native acceptance. Use existing logs before reruns.

The stalled P11 Windows run and its source findings remain P11 delivery gates.
Profiling may help diagnose them but must not turn unfinished validation into a
performance success.

## Phase 2: Choose and review an evidence-backed plan

For each candidate, state the current trigger, proposed change, expected benefit,
implementation cost, coverage risk and a discriminating validation method.
Label measured facts, causal inferences and hypotheses separately. Use actual
account pricing for monetary estimates; runner minutes are the fallback metric.

Prefer eliminating equivalent duplicate work, excessive setup and unnecessary
process startup. Evaluate worker counts and test distribution with controlled
benchmarks. Preserve required-check behavior for documentation-only changes,
path filtering, pull requests, main pushes and merge queues. Bound stalled jobs
without treating a timeout as a passing check.

Independent major review must challenge coverage equivalence, cache correctness,
required-check completion and the claimed source of savings. Request Muse Ultra
with a maximum of 100 steps. Record any provider fallback and actual completion;
use the already approved Opus fallback when Fable is unavailable. Resolve real
owner decisions only after the alternatives and their effects are concrete.

## Phase 3: Validate and deliver the selected work

Create targeted failing controls where behavior changes and an equivalent
before/after performance measurement. Do not add tests that merely mirror YAML
spelling. Preserve native Windows and committed-source acceptance proof.

Implement selected changes separately from P11 correctness delivery. For Windows
failures, first isolate the failed remote family, then validate the fix there,
then run the full batch. Complete relevant local checks, CI, review closure and
normal PR delivery. Report elapsed time and runner-time changes separately,
including regressions or inconclusive results. Close P11A before resuming the
P12 follow-up evaluation, or record the explicit decision to make no CI change.
