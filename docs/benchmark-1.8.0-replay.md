# Benchmark: the same 600 commits through sitemend 1.8.0

## Outcome

**Precision failed its pre-registered threshold again, so the 1.7.0 decision stands:
outreach stays stopped, the rules are fixed under the stability policy, and every
confirmed false positive becomes a permanent test. The prospective run (Task 9) does not
start.**

| Measure | 1.7.0 | 1.8.0 | Pre-registered threshold | 1.8.0 |
|---|---|---|---|---|
| Blocking precision (per finding) | 76 of 1,442 (5.3%) | **82 of 100 (82.0%)** | at least 95% | **not met** |
| Frequency (per commit) | 20 of 517 (3.9%) | **21 of 549 (3.8%)** | at least 1 per 100 | met |
| Seeded recall (critical and high, pooled) | 73 of 75 (97.3%)¹ | **57 of 58 (98.3%)** | at least 90% | met |

¹ As published, with only the rating mutation set apart. Pooled the way 1.8.0 is (three
types apart), 1.7.0 is 54 of 55.

The decision rules are unchanged from the 1.7.0 run (`bench/PREREGISTRATION.md`, section
5, and Addendum 9). Precision rose from 5.3% to 82%: the gate blocked 100 findings
instead of 1,442. 82 of those 100 were real regressions. That is still below 95%, and
the rule is applied as written.

As on 1.7.0, most of the shortfall is one sitemend bug, not scattered misjudgements:
13 of the 18 findings that did not count were false positives from a single cause (below).

**This result is optimistic, as Addendum 9 says it would be.** Four of the five fixes in
1.8.0 came from sites in this sample, so this measures whether the fixed rules stop
misfiring on the data that exposed them, not how they behave on sites they have never
seen.

This page gives totals only and names no sites. Every number comes from a data file in
`bench/`, produced by a script.

## Method

Unchanged from the 1.7.0 run (`docs/benchmark-2026-11-replay.md`), except:

- **Frozen version:** sitemend 1.8.0 (tag `v1.8.0`, commit `1f0a77d`), fixed in Addendum 9
  before any 1.8.0 data existed.
- **Sample:** the same 15 repositories, the same 40 commits each and the same build
  commands, so the same 600 comparisons.
- **Verdicts:**
  - A 1.8.0 blocking finding that matched a judged 1.7.0 finding on all five ledger key
    fields (repository, commit, rule, URL, evidence) kept that verdict: 75 of the 100.
  - The other 25 were judged fresh, in five groups, each with its evidence. They are
    recorded as Claude's reading of the evidence, accepted by B.
  - The ledger is `bench/ledger-1.8.0.csv`; the 1.7.0 ledger is unchanged.
- **Seeded recall:** three mutation types are reported apart, not pooled. Each one's rule
  was changed after an earlier seeded run showed that type being missed:
  - the rating mutation (Addendum 3);
  - the preview-host sitemap mutation (#70);
  - the duplicate-title mutation (#60).

## What happened to the 600 comparisons

| | 1.7.0 | 1.8.0 |
|---|---|---|
| Compared | 517 | 549 |
| Passed the gate | 483 | 524 |
| Failed the gate | 34 | 25 |
| Skipped: a build failed | 44 | 51 |
| Skipped: sitemend did not finish the audit | 39 | 0 |

- **No tool failures.** On 1.7.0, one repository's audit took about 2.5 hours per commit
  (issue #71) and 39 of its commits were never audited. On 1.8.0 every one of its 41
  builds was audited. Across all 572 commits audited, the median audit took 7.1 s
  (90th percentile 87.6 s).
- **Build failures** are mostly the projects' own state at those commits, as on 1.7.0.
  There are 7 more skipped comparisons, all from one repository. Four of its commits
  that built on 1.7.0 failed this time: the build timed out fetching from the network.
  All 7 comparisons they touch passed the gate on 1.7.0, so no blocking finding was lost
  to them.

## Precision, per rule

| Rule | Blocking findings | true_regression | Other verdicts | Precision |
|---|---|---|---|---|
| S2-H1-MISSING | 38 | 38 | 0 | 100% |
| S1-HREFLANG-BROKEN | 16 | 16 | 0 | 100% |
| S1-BROKEN-LINK | 16 | 6 | 6 false_positive, 4 unclear | 37.5% |
| S3-TITLE-DUPLICATE | 12 | 11 | 1 true_but_preexisting | 91.7% |
| S3-DUPLICATE-EXACT | 8 | 8 | 0 | 100% |
| S1-SITEMAP-ORPHAN | 7 | 0 | 7 false_positive | 0% |
| S2-ORPHAN, S2-UNREACHABLE, S3-DESC-MISSING | 3 | 3 | 0 | 100% |

## The 18 findings that did not count

- **13 false positives, one cause: folders named `vendor`.**
  - `crawl.py` skips any directory named `vendor`, `out`, `build`, `tmp` and similar, at
    any depth (`EXCLUDE_DIRS`). That is right for a source tree, but in a built site
    those names can be real pages.
  - One site has content pages under `…/vendor/`, so links to them (6) and its own sitemap
    entries for them (7) read as broken or orphaned.
  - On 1.7.0 the 7 sitemap findings were attributed to the base-path bug (#69). That note
    is corrected in the ledger; the verdict stands.
- **4 unclear.** New links into a section that does not exist in the repository's own
  build. The site may be published inside a larger one where those pages exist, which was
  not checked. They count against precision, as pre-registered.
- **1 true but pre-existing.** 108 archive pages already shared one title. A commit
  translated that shared title, and since #60 (which identifies a duplicate group by its
  text) a group under new text reads as a new finding. The duplication itself was not
  new.

## Seeded recall

| | 1.7.0 | 1.8.0 |
|---|---|---|
| Pooled (critical and high, three types apart) | 54 of 55 (published as 73 of 75 with one apart) | **57 of 58 (98.3%)** |
| Rating mutation (apart) | 10 of 13 | 9 of 13 |
| Preview-host sitemap mutation (apart on 1.8.0) | 10 of 11 | 11 of 11 |
| Duplicate-title mutation (apart on 1.8.0) | 9 of 9 | 8 of 9 |

All 15 unmutated controls passed the gate. Both new misses are on one base-path site, where
the harness now picks the home page as its target:

- **Rating mutation: a real sitemend gap (issue #81).** The claim check strips non-Latin
  text, so on a page whose visible text is entirely Korean, Chinese or similar, ratings,
  offers and addresses are never checked.
- **Duplicate-title mutation: a harness flaw.** It judged a title unique without counting
  the 404 page, which already shared it.

## Limitations

- **Same sample as the fixes.** Four of the five 1.8.0 fixes came from sites in this sample.
  The 82% is optimistic about sites the rules have never seen.
- **Verdicts:** the 25 fresh verdicts are Claude's readings of the evidence, accepted by B
  per group. They are not independent judgements.
- **Everything else carries over** from the 1.7.0 report: replay cannot see runtime or
  hosting; folder audits only; the frame is what GitHub code search returns; Hugo needs an
  npm build script; build commands are mechanical.

## What happens next

As pre-registered, precision failing means fixing the rules, not starting Task 9:

- **The `vendor` exclusion (#82):** a built output should not skip real page folders. This
  accounts for 13 of the 18.
- **The duplicate rename (#82, a side effect of #60):** a group whose pages are unchanged and only
  whose shared text changed is the same defect, not a new one.
- **Non-Latin claim checks (#81).**

Each becomes a permanent test, in a minor release that names the affected rules. A new
dated addendum then fixes the next measurement before any data from it.

## How to rerun it

- **Data:** the 1.8.0 replay data is in `bench/replay/1.8.0/` (`results.csv`,
  `builds.csv`, `summary.md`), the verdicts in `bench/ledger-1.8.0.csv`, and the seeded
  run in `bench/seeded/1.8.0/`.
- **Rules of the run:** Addendum 9 in `bench/PREREGISTRATION.md`.
- **Running it:** the same manual `replay` and `seeded` workflows, pinned to
  `sitemend==1.8.0`.
