# Benchmark: the same 600 commits through sitemend 1.9.0

## Outcome

**All three pre-registered thresholds are met. As decided in advance, the prospective run
(Task 9) is now eligible to start. Outreach does not reopen on this result alone
(Addenda 9 and 10).**

| Measure | 1.7.0 | 1.8.0 | 1.9.0 | Pre-registered threshold | 1.9.0 |
|---|---|---|---|---|---|
| Blocking precision (per finding) | 76 of 1,442 (5.3%) | 82 of 100 (82.0%) | **82 of 86 (95.3%)** | at least 95%, with 20+ verdicts | met |
| Frequency (per commit) | 20 of 517 (3.9%) | 21 of 549 (3.8%) | **21 of 556 (3.8%)** | at least 1 per 100 | met |
| Seeded recall (critical and high, pooled) | 73 of 75¹ | 57 of 58¹ | **66 of 67 (98.5%)** | at least 90% | met |

¹ Pooled with different types set apart each run (Addenda 3, 9 and 10), so the recall
figures are not strictly comparable across runs.

**What changed from 1.8.0 is what the fixes targeted, and nothing else.**
- **Removed:** the 14 blocking findings on 1.8.0 that did not count (13 false positives
  and 1 true but pre-existing) are gone. Those are what the two parts of #82 were written
  for.
- **Kept:** all 82 true regressions found on 1.8.0 are still found.
- **Added:** no new blocking finding appeared.

**Two cautions, stated as plainly as the result:**
- **The margin is zero.** 82 of 86 is 95.3%; 82 of 87 would be 94.3%.
  - The 4 findings that do not count are all `unclear`: links into a section that does
    not exist in the repository's own build, which a larger published site may serve.
  - They count against precision, as pre-registered, and were not checked against the
    live site.
  - One more misfire on this sample would have failed the threshold.
- **The result is optimistic, as Addendum 10 says.** This is the third measurement on the
  sample that every fix in 1.8.0 and 1.9.0 came from. It shows the fixed rules no longer
  misfire on the data that exposed them. It is not evidence of how they behave on sites
  they have never seen; Task 9 is that evidence.

This page gives totals only and names no sites. Every number comes from a data file in
`bench/`, produced by a script, except the two job durations below, which are GitHub's own
job timestamps for the runs.

## Method

Unchanged from the 1.8.0 run (`docs/benchmark-1.8.0-replay.md`), except:

- **Frozen version:** sitemend 1.9.0 (tag `v1.9.0`, commit `507367c`), fixed in Addendum 10
  before any 1.9.0 data existed.
- **Verdicts:** a blocking finding that matched a judged finding on all five ledger key
  fields kept its verdict. The 1.8.0 ledger was checked first, then 1.7.0. All 86 matched
  a 1.8.0 finding, so no verdict was given fresh in this run. The ledger is
  `bench/ledger-1.9.0.csv`; earlier ledgers are unchanged.
- **Seeded recall:** the harness now counts title duplicates over every crawled page
  (Addendum 10), so the duplicate-title mutation is pooled again. The rating and
  preview-host sitemap mutations are still reported apart.

## What happened to the 600 comparisons

| | 1.7.0 | 1.8.0 | 1.9.0 |
|---|---|---|---|
| Compared | 517 | 549 | 556 |
| Passed the gate | 483 | 524 | 534 |
| Failed the gate | 34 | 25 | 22 |
| Skipped: a build failed | 44 | 51 | 44 |
| Skipped: sitemend did not finish the audit | 39 | 0 | 0 |

- **No tool failures.** Across the 576 commits audited, the median audit took 7.3 s
  (90th percentile 118.9 s).
- **Build failures** are back to the 1.7.0 count. On 1.8.0, four of one repository's builds
  timed out fetching from the network, costing 7 comparisons; this time those builds
  succeeded.
- **One repository's job took longer** (4 h 8 min, against 2 h 41 min on 1.8.0). Both its
  median build time (72 s to 122 s) and its median audit time (171 s to 250 s) rose by a
  similar factor. The build is the project's own code, so a slower runner is the likelier
  cause than the 1.9.0 changes. It is noted, not measured further.

## Precision, per rule

| Rule | Blocking findings | true_regression | Other verdicts | Precision |
|---|---|---|---|---|
| S2-H1-MISSING | 38 | 38 | 0 | 100% |
| S1-HREFLANG-BROKEN | 16 | 16 | 0 | 100% |
| S3-TITLE-DUPLICATE | 11 | 11 | 0 | 100% |
| S1-BROKEN-LINK | 10 | 6 | 4 unclear | 60% |
| S3-DUPLICATE-EXACT | 8 | 8 | 0 | 100% |
| S2-ORPHAN, S2-UNREACHABLE, S3-DESC-MISSING | 3 | 3 | 0 | 100% |

## Seeded recall

| Mutation | 1.8.0 | 1.9.0 |
|---|---|---|
| Pooled (critical and high) | 57 of 58 (three types apart) | **66 of 67 (two types apart)** |
| Duplicate-title (pooled on 1.9.0) | 8 of 9 | 9 of 9 |
| Rating (apart) | 9 of 13 | 10 of 13 |
| Preview-host sitemap (apart) | 11 of 11 | 11 of 11 |

All 15 unmutated controls passed the gate. Both 1.8.0 misses now fire: the rating, through
the claim-check fix (#81), and the duplicate title, through the harness correction.

The misses left are the same ones as on 1.7.0 and 1.8.0, on the same pages:
- one preview-host canonical;
- three rating mutations.

Why those four are missed has not been investigated; it is the same on all three
versions.

## Limitations

- **Same sample as every fix.** Three measurements and two rounds of fixes on these 15
  repositories. 95.3% is the result on data the rules were corrected against.
- **No fresh verdicts.** Every 1.9.0 verdict was carried over from 1.8.0. 18 of them are
  among the 25 that were Claude's readings, accepted by B.
- **The 4 unclear findings were never resolved.** Checking them against the live site
  could move precision to 100% or leave it where it is; the pre-registration counts them
  against it either way.
- **Everything else carries over** from the earlier reports: replay cannot see runtime or
  hosting; folder audits only; the frame is what GitHub code search returns; Hugo needs an
  npm build script; build commands are mechanical.

## What happens next

As pre-registered:
- **Task 9 is eligible to start:** the prospective run, measuring sitemend on real pull
  requests on sites it was not tuned on, as they happen. It is the evidence this result
  cannot give.
- **Outreach does not reopen on this result alone** (Addenda 9 and 10).
- **Addendum 10, part 7 does not apply,** because precision did not fail.

## How to rerun it

- **Data:** the 1.9.0 replay data is in `bench/replay/1.9.0/` (`results.csv`,
  `builds.csv`, `summary.md`), the verdicts in `bench/ledger-1.9.0.csv`, and the seeded
  run in `bench/seeded/1.9.0/`.
- **Rules of the run:** Addendum 10 in `bench/PREREGISTRATION.md`.
- **Running it:** the manual `replay` and `seeded` workflows, pinned to `sitemend==1.9.0`.
