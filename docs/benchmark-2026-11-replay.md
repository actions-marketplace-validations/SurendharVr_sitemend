# Benchmark: replaying 600 real commits through sitemend's gate

## Outcome

**Precision failed its pre-registered threshold, so, as decided in advance: all outreach
stops, the rules are fixed under the stability policy, and every confirmed false positive
becomes a permanent test.**

| Measure | Result | Pre-registered threshold | |
|---|---|---|---|
| Blocking precision (per finding) | **76 of 1,442 (5.3%)** | at least 95% | **not met** |
| Frequency (per commit) | **20 of 517 commits (3.9%)** | at least 1 per 100 | met |
| Seeded recall (critical and high) | **73 of 75 (97.3%)** | at least 90% | met |

The decision rules were written before any data (`bench/PREREGISTRATION.md`, section 5).
"All three met" did not happen; "precision fails" did, and it is applied as written. The
frequency result says real pull requests do introduce the regressions sitemend checks
for. The precision result says that, on this sample, most of what the gate blocked was
not a regression: almost all of it came from two sitemend bugs, now issues #69 and #73.

This page gives totals only and names no sites. Every number comes from a data file in
`bench/`, produced by a script.

## Method

- **Frozen version:** sitemend 1.7.0 (tag `v1.7.0`), fixed before any data on this sample
  (Addendum 3). No rule, threshold or severity changed during the run.
- **Sample:** 15 public repositories, 3 for each supported stack (Docusaurus,
  Astro/Starlight, VitePress, Hugo, Next.js static export), drawn by a procedure fixed
  and signed before anything was drawn (Addendum 5):
  - **Frame:** one GitHub code search per stack, saved on 2026-10-18.
  - **Order:** shuffled with the published seed 20261017.
  - **Eligibility:** public, not a fork, at least 75 commits in the 12 months before the
    cutoff, and not used to tune sitemend. 2,528 repositories were looked at, every
    outcome recorded.
  - **Build check:** the build command is derived by a mechanical rule, and the first 3
    per stack, in draw order, that built at their cutoff commit were taken. 54 candidates
    were build-checked.
  - **Rule corrections, before any measurement:** two, each a dated addendum (Node
    version, Addendum 6; an output with no pages, Addendum 7).
- **Replay:** for each repository, the last 40 first-parent commits before 2026-10-01 were
  each built and audited, and every commit was compared with its parent by the gate
  (`sitemend verify`). 615 builds on GitHub's Ubuntu runners; 600 comparisons.
- **Verdicts:** every blocking finding went to `bench/ledger.csv` with its evidence (the
  finding, the base-to-head change, live-site checks where they helped). Every verdict
  was a person's call. The 1,442 findings fell into nine groups; each group was judged
  once with its evidence, and the verdict recorded on every row.
- **Seeded recall:** each of the 15 was built once, ten known regressions were applied one
  at a time to copies of the build, and the gate was run on each. The rule the
  "rating" mutation tests was fixed after an earlier run showed it missed, so that
  mutation is reported apart from the pooled figure (Addendum 3).

## What happened to the 600 comparisons

| | Comparisons |
|---|---|
| Compared | 517 |
| Passed the gate | 483 |
| Failed the gate | 34 |
| Skipped: a build failed | 44 |
| Skipped: sitemend did not finish the audit | 39 |

Build failures are the projects' own state at those commits: one site became a static
export only partway through the window (29 of its commits produce no static site); the
rest are broken commits or lockfile mismatches. They count toward neither measure.

## Precision, per rule

| Rule | Findings | true_regression | false_positive | unclear | Precision |
|---|---|---|---|---|---|
| S1-HREFLANG-BROKEN | 488 | 16 | 472 | 0 | 3.3% |
| S1-CANONICAL-BROKEN | 375 | 0 | 236 | 139 | 0.0% |
| S1-SITEMAP-ORPHAN | 276 | 0 | 243 | 33 | 0.0% |
| S1-BROKEN-LINK | 243 | 0 | 242 | 1 | 0.0% |
| S2-H1-MISSING | 38 | 38 | 0 | 0 | 100.0% |
| S3-TITLE-DUPLICATE | 11 | 11 | 0 | 0 | 100.0% |
| S3-DUPLICATE-EXACT | 8 | 8 | 0 | 0 | 100.0% |
| S2-ORPHAN | 1 | 1 | 0 | 0 | 100.0% |
| S2-UNREACHABLE | 1 | 1 | 0 | 0 | 100.0% |
| S3-DESC-MISSING | 1 | 1 | 0 | 0 | 100.0% |
| **All** | **1,442** | **76** | **1,193** | **173** | **5.3%** |

`unclear` counts against precision, as pre-registered. No finding was judged
`true_but_preexisting`.

## The false positives

- **1,193 on one site served from a base path** (a GitHub Pages project site at
  `/<repo>/`), across 10 commits. A folder audit treats the build folder as `/`, so every
  link, canonical, hreflang alternate and sitemap URL under the base path read as broken.
  The live URLs return 200. Issue #69.
- **173 judged unclear on one site with non-ASCII paths**, across 16 commits. 111 of its
  143 sitemap URLs are percent-encoded; sitemend stores page URLs decoded and compares
  them without decoding, so existing pages read as missing. Issue #73.

These two sites carry 1,366 of the 1,442 findings. Per failing commit rather than per
finding: of the 34 commits that failed the gate, 20 had at least one verified regression,
9 had only false positives and 5 had only unclear findings (59% of blocks justified).
That view was not pre-registered and does not change the outcome. It is given because one
site's systematic misfire weighs so much in a per-finding count.

## What it caught (verified)

The 76 verified regressions come from 20 commits on 6 sites:

- New pages without an H1, and tag pages whose text duplicates another's (one site,
  11 commits). That site's build had no headings at all at those commits.
- hreflang alternates to language versions that return 404 on the live site.
- New pages reusing another page's title: release posts and their translated copies,
  a subscription page and its locale copy, section pages sharing one title.
- A new page linked from nowhere that also reuses the home page's title.
- A home page that lost its H1 and meta description.

More than half of the verified commits (11 of 20) are on one site, so the frequency
figure leans on it: without that site, 9 of the remaining 482 commits compared (1.9%) carry a verified
regression, still above the threshold.

## Seeded recall

| | |
|---|---|
| Critical and high mutations caught | 73 of 75 (97.3%) |
| Controls (an unmutated copy) that passed | 15 of 15 |
| Rating mutation, reported apart | 10 of 13 |

Both pooled misses still failed the gate, through a different rule: one site's own
production host is a preview-host domain, so a preview-host canonical surfaced as a host
mismatch; on a site whose own URLs are all on localhost, one preview-host sitemap URL made
sitemend infer the wrong base and report mixed content instead (issue #70).

## Tool failures

sitemend took about 2.5 hours to audit each commit of one site, so its job hit the time
limit after 2 of 41 commits; the other 39 are tool failures (Addendum 8). The cause is a
regular expression in `crawl.py` that is quadratic on long runs in minified JavaScript
(issue #71). Elsewhere, the median audit took 5.0 s (90th percentile 100.9 s) and the
median build 18.4 s (112.9 s), over 537 builds.

## Limitations

- **Replay cannot see runtime, hosting or environment.** Preview-host leaks and soft 404s
  happen at deploy time and are under-counted here; a low count for them is not evidence
  they are rare.
- **Folder audits only.** Every finding comes from a built folder, which is exactly where
  issues #69 and #73 come from. Audits of a deployed URL would not hit #69 the same way.
- **The frame is what GitHub code search returns,** ranked and capped at 1,000 per query,
  so the sample is reproducible but not a uniform draw of all sites. It is mostly docs,
  project and personal sites, because those are what is public.
- **Hugo sites qualified only with an npm build script,** and several were skipped because
  their build calls the `hugo` binary, which the runner did not have.
- **Verdicts were given per group, by one person,** with the evidence for each group;
  every row is recorded. Several sites are small (an audit under a second).
- **Build commands are mechanical.** A project whose real deploy needs more than its own
  `build` script was skipped, not fixed.

## What happens next

As pre-registered: no outreach; issues #69 and #73 (and #70, #71) are fixed under the
stability policy, which makes it a minor release that names the affected rules; each
confirmed false-positive pattern becomes a permanent test. The measurement can then be
repeated on the same sample with the new version, under a new dated addendum.

## How to rerun it

Everything is in `bench/`: the signed pre-registration and its addenda
(`PREREGISTRATION.md`), the saved frame and every draw outcome (`sample/`), the sample
(`replay/repos.json`), the replay data (`replay/results.csv`, `replay/builds.csv`), the
verdicts (`ledger.csv`), the seeded runs (`seeded/addendum-5/`) and the scripts that made
each of them. The replay itself runs through the manual `replay` workflow
(`.github/workflows/replay.yml`).
