# Pre-registration: prospective run (Task 9)

Written before any prospective data exists. sitemend 1.9.0 gates real pull requests on
sites it was never tuned on, as they are opened. Every value below is fixed before the
window opens, and the decision rules in section 6 are applied to the results **exactly as
written**. A change after data exists is a dated, signed addendum at the end of this
file, and the report states it.

**Status:** signed by SurendharVr on 2026-10-22. Written by Claude on 2026-10-22 from
`bench/PREREGISTRATION.md` (sections 1 to 6, Addenda 1 to 10) and
`docs/benchmark-1.9.0-replay.md`. Every value B fills in below was proposed by Claude and
accepted as written. No part of Task 9 runs on a real repository until this file is
merged.

**Why this run.** The replay result on 1.9.0 (precision 82 of 86, frequency 21 of 556,
seeded recall 66 of 67) was measured on the sample every 1.8.0 and 1.9.0 fix came from,
so it is optimistic (Addendum 10, part 6). As pre-registered, it makes Task 9 eligible;
it does not reopen outreach. This run is the evidence for sites sitemend has never seen,
and for the two regression types replay under-counts (section 7).

## 1. Frozen version

- Package: `sitemend==1.9.0`
- Tag: `v1.9.0`
- Commit: `507367ca62f341e0925dd82b2674d17731d93158`

The harness pins it the way `FROZEN` in `bench/replay/replay.py` does. No rule,
threshold or severity changes until this run's report is published. A bug found during
the window is logged in the ledger and gets an issue, and is not fixed. If B lifts the
freeze, that is an addendum, and every pull request checked after it is reported apart.

## 2. Sites

### 2.1 Exclusions

A repository is excluded if it is any of:

- the 15 benchmark repositories in `bench/replay/repos.json`, the sample every 1.8.0 and
  1.9.0 fix came from;
- every repository built or audited by the robustness sweep (`bench/sweep/sweep.csv`),
  since its findings were logged as issues against these rules;
- every repository Addendum 5 lists as excluded: the source repositories of the 23
  tuning sites, any repository whose GitHub homepage is on one of those hosts, and the 20
  repositories this plan used before Addendum 5;
- a repository owned by, or with a maintainer who is, B.

### 2.2 Frame and draw

- **Frame:** Addendum 5's saved frame, `bench/sample/frame-<stack>.json`, with no new
  search, so the draw needs no new judgement.
- **Order:** each stack's saved draw order, `bench/sample/order-<stack>.json`, continued
  after the last repository the sample and the sweep looked at. Same seed (`20261017`),
  so nothing is shuffled again.
- **Eligibility,** checked in draw order on the draw date, every repository looked at
  recorded in `bench/task9/draw.csv` with its outcome and reason. All must hold:
  - Addendum 5, rule 4 (public, not a fork, not archived, site config present), with
    the draw date in place of the cutoff: the 12-month commit window ends on the draw
    date, and the site config is checked at the default branch's head on the draw date;
  - a GitHub homepage that serves the built site: it answers 200 over https and its
    home page has the same `<title>` as the build's home page. This is the production
    URL for url mode (3.3) and for the post-merge check (3.4);
  - at least 8 pull requests merged into the default branch in the 8 weeks before the
    draw date, about one a week, so the window has PRs to gate;
  - builds by Addendum 5, rule 5 (with Addendum 6's Node rule) at the default branch's
    head on the Ubuntu runner, and the output holds HTML pages (Addendum 7).
- **Preview flag,** recorded but not required: whether a public deploy preview (Netlify,
  Vercel, Cloudflare Pages or similar) was posted, as a commit status or bot comment, on
  at least one of those merged PRs. It decides which PRs get the url-mode check (3.3).
- **Size:** the first 6 eligible repositories per stack, so 30 in all. If fewer than 10
  of the 30 have the preview flag, the draw continues in order, taking only flagged
  repositories, until 10 are flagged or 40 repositories in all are taken.
- **Draw date (UTC):** the day this file is merged, 2026-10-22.

The draw is run once and committed (`bench/task9/repos.json`, `draw.csv`) before the
window opens. A repository that later archives itself, goes private or stops building on
every PR stays in the sample, and its PRs count as skipped (3.5).

### 2.3 No contact during the window

This is a shadow run: sitemend runs on B's own runner against each PR's public code and
public preview. It posts no comment, opens no issue and sends no message to any drawn
repository during the window, so maintainers cannot change what they do because of it.
True regressions are reported to maintainers after the report is published: one issue
per site, only after the report, and only for `true_regression` findings still present
on production.

## 3. Pull requests in the window

### 3.1 Window

- Opens (UTC): 00:00 on the day after the draw is committed.
- Length: 8 weeks.
- Extension: if fewer than 20 blocking findings exist in the measure precision uses
  (section 5) when the window closes, it is extended 4 weeks at a time, up to 16 weeks
  in all. Findings are counted, not verdicts, so a
  verdict still due (4.3) does not trigger an extension. Precision is computed once every
  finding has its verdict. If 20 are never reached, precision counts as not met (as in
  section 4 of the main pre-registration).

### 3.2 What counts as a pull request

A pull request counts when all hold:

- it targets the repository's default branch;
- it is opened during the window (a PR opened before the window does not count, even if
  it is updated during it);
- it is not a draft when it is checked (3.3).

PRs opened by bots (Dependabot, Renovate and the like) count, and are also reported
apart. PRs from forks count. A PR that changes no file the site build reads still
counts: that is the per-PR gate a maintainer would run.

### 3.3 What is checked

The harness polls every drawn repository every 15 minutes. Each new
head commit of a counted PR is checked when it is first seen, and in url mode as soon as
its preview reports a successful deploy, so the check runs while the preview is up.

Each counted PR is still **one comparison**: the check of its last head commit before it
is merged or closed, or at the window's close if it is still open. Checks of earlier heads
are kept in the results but are not counted. A last head that no poll saw before the PR
closed is checked after closing, from its commit, and in url mode from its preview if
that is still up. A PR reopened in the window is still one comparison.

- **Folder mode, every PR:** head built with the repository's rule-5 command, compared
  with the PR's base commit built the same way, through `verify.py` as the Action does.
- **URL mode, PRs with a public preview:** the preview deploy of the head commit is
  audited as `url` and production (the repository's GitHub homepage) as `baseline-url`,
  with the Action's default `max-pages` (200) and no secret header. A preview behind
  authentication is not checked in url mode. Soft 404s (`S1-SOFT-404`) are detected
  only here, since sitemend probes for them only on an HTTP crawl.

A finding counts as **blocking** exactly as the gate decides it: new or worsened,
critical or high, measured (high confidence), and not waived by the repository's own
`.sitemend-waivers.json` (`verify.py`, `blocks()`).

### 3.4 Production after each merge

A preview-host leak shows in production, after a PR is merged and deployed, and neither
check above can see it: a preview naming its own host is not a mismatch, and the folder
build runs without the host's deploy variables.

- Production is audited (`sitemend check <production>`, `max-pages` 200) at window open,
  and again after each merge into the default branch, once production has changed or
  2 hours after the merge, whichever comes first. Each audit is
  compared with the one before it.
- A new critical or high finding is attributed to the PRs merged between the two audits.
  B judges it like a gate finding (4.3), in a separate ledger,
  `bench/ledger-task9-production.csv`, with the same fields and `mode: production`.
- A `true_regression` there whose PR passed the gate is a **miss**. One that the gate
  also blocked on the same PR confirms the gate's finding, and is not counted twice.
- These findings are not gate findings, so they are outside precision and frequency.
  They are the run's measure of preview-host leaks, and its floor on misses (section 5).

### 3.5 Skips

As in the main pre-registration, none of these count toward frequency or precision:

- `build_failed`: the head or base build fails in folder mode;
- `preview_unavailable`: the preview is missing, private or unreachable in url mode
  (the PR's folder-mode check still counts);
- tool failures (Addendum 1): sitemend crashes, or an audit does not finish within 60
  minutes. Reported per repository with the reason, as a reliability
  finding.

## 4. Verdicts

### 4.1 Ledger

One ledger, `bench/ledger-task9.csv`, with the same fields as `bench/ledger.csv`:

`repo, head_sha, rule_id, severity, url, evidence_excerpt, verdict, verified_by,
verification_method, notes`

- `notes` starts with the mode: `mode: folder`, `mode: url` or `mode: both`. A finding
  with the same ledger key (repo, head_sha, rule_id, url, evidence_excerpt) in both modes
  is one row, `mode: both`.
- `verified_by` is the person who gave the verdict.
- Earlier ledgers are not edited, and no verdict is carried over from them: every site
  here is new.

### 4.2 Verdict values

The values used in `bench/ledger.csv`:

| Verdict | Meaning | Counted as |
|---|---|---|
| `true_regression` | the PR introduced it, and it harms crawling or indexing | true |
| `false_positive` | the PR did not introduce it, or it is not a problem | false |
| `unclear` | nobody can confirm it either way | false, as in section 4 of the main pre-registration |

`true_but_preexisting` (used once in `bench/ledger-1.8.0.csv`) is allowed here, counted
as false, since the gate blamed this PR for it. In url mode it
is the expected verdict when production lags the PR's base branch.

### 4.3 How a verdict is given

- **Evidence,** in this order, named in `verification_method`: the built HTML at the
  head and base commits (`build HTML at the commit`); the preview deploy at the head
  commit (`preview deploy at the head`); production after the PR was merged and deployed
  (`live site check`).
- **Timing:** a finding is judged within 7 days of its PR being checked, while its preview is still up. A preview that is gone before a verdict leaves
  the built HTML as the evidence.
- **What happened next** is recorded in `notes`, not used as the verdict: merged or
  closed, and whether a later PR in the window fixed the problem.
- **Claude's readings.** Claude may draft a reading of a finding; it is marked
  `reading drafted by Claude` in `notes`, and B accepts or changes it. The report counts
  how many verdicts started as Claude's readings.
- **Second look:** B re-judges a random 20% of findings, drawn with
  `random.Random(20261017)` after the window closes, without seeing the first verdict.
  Disagreements are reported, and the first verdict stands.
- No verdict changes after the window closes, except by addendum.

## 5. Thresholds

| Measure | Unit | Main pre-registration | Task 9 value |
|---|---|---|---|
| Blocking precision | per blocking finding: `true_regression` / all blocking findings with a verdict | at least 95%, with at least 20 verdicts | at least 95% with at least 20, folder mode only; url mode reported apart, see below |
| Frequency | per PR: PRs with at least one `true_regression` blocking finding / PRs compared | at least 1 per 100 commits | at least 1 per 100 PRs compared, in the same mode as precision |
| Tool failures | per PR: PRs with a tool failure / PRs counted | not a threshold | at most 5% |

**Which mode the thresholds use:** folder mode only. In url mode the
baseline is production, not the PR's base commit, so a gap between the two shows up as a
finding the PR did not cause, and would count against precision because of how the run
is set up rather than how the rules behave. Folder mode compares the PR with its own
base, as replay did.

Reported, not thresholds:

- precision and frequency per mode (folder, url), per stack and per rule;
- bot PRs apart from the rest;
- **preview-host leaks** (`S1-HOST-MISMATCH` at critical, the rule the seeded
  `sitemap-preview-host` mutation checks): blocking findings and verdicts in each gate
  mode, and `true_regression` findings in the post-merge production check (3.4), with
  how many of those the gate blocked and how many it missed;
- **soft 404s** (`S1-SOFT-404`, url mode only): blocking findings, verdicts and PRs;
- for either type with no `true_regression`, the rule-of-three upper bound on how often
  it occurs, instead of "none found": 3 / merged PRs for preview-host leaks, 3 / PRs
  checked in url mode for soft 404s;
- **misses, as a lower bound:** `true_regression` findings from the post-merge
  production check (3.4) on PRs the gate passed. A regression the PR's own preview or
  build could not show, or one fixed again before the next production audit, is not
  seen, so this is a floor, not recall.

Seeded recall is not re-run here; the 1.9.0 seeded result stands.

## 6. Decision rules

Applied to the window's results as written, with the outcome at the top of the report.

- **Precision, frequency and tool failures all met:** reopen outreach for the
  release-gate positioning (Phase 4). This is the only result that reopens it.
- **Precision fails:** outreach stays stopped, and the rules are fixed under the
  stability policy in `RELEASING.md`; every confirmed false positive becomes a permanent
  test. The next prospective run uses a fresh draw (the next repositories in draw order
  after this one), not this sample, for the reason in Addendum 10, part 7.
- **Precision passes, frequency fails:** re-position as a pre-launch and redesign audit,
  not a per-PR gate, as in section 5 of the main pre-registration.
- **Tool failures above the threshold:** outreach stays stopped until the failures are
  fixed and re-measured on a fresh draw, even if precision and frequency pass.
- **Preview-host leaks and soft 404s:** whatever the rest shows, no public material
  claims sitemend catches a type on real pull requests unless this run has at least 1
  `true_regression` blocking finding of that type from the gate. A type
  found only by the post-merge production check (3.4) may be described as found in
  production audits, not as caught on pull requests. With neither, the material says
  the type is tested by seeded mutation only.
- **Fewer than 20 blocking findings after the longest extension:** precision counts as not met,
  and the first rule above applies.

## 7. Known limitations

- **What this run is for.** Replay builds each commit locally and cannot see
  environment variables, hosting or runtime behaviour, so preview-host leaks and soft
  404s were under-counted there (section 6 of the main pre-registration). URL mode on
  real preview deploys is the first measurement that can see soft 404s, and the
  post-merge production check (3.4) the first that can see preview-host leaks. A gate
  run on a PR can rarely see a preview-host leak itself, so the run is likely to show
  most of them as misses: that is what it is set up to find out.
- **Previews skew the soft-404 sample.** Soft 404s are seen only on sites with public
  previews, which are not a random part of the sample. Vercel previews are behind
  Deployment Protection by default and are not checked, so those sites lean towards
  Netlify and Cloudflare Pages.
- **Production is not the base.** In url mode the baseline is production, which may lag
  or lead the PR's base branch. Differences that come from that gap are judged
  `true_but_preexisting` or `false_positive`, and count against precision.
- **The frame** is still GitHub code search from 2026-10-17 (capped, ranked by GitHub),
  mostly docs and project sites, and the build rule is mechanical (Addendum 5). Sites
  whose real deploy needs more than their own `build` script, and Hugo sites without an
  npm build script, are not in it.
- **URL mode crawls at most 200 pages** a side, so a regression on a larger site's deep
  pages can be missed in url mode while folder mode sees it.
- **Shadow, not installed.** Nobody acts on sitemend's result during the window, so the
  run measures what the gate would have said, not whether maintainers find it useful or
  how often they would waive a finding.
- **One judge.** B gives every verdict; Claude's readings and the second look (4.3) are
  stated, not a substitute for an independent rater.
- **Misses are a floor.** There is no seeded ground truth on live PRs, so recall here is
  only the lower bound in section 5.

## 8. Harness and data

- The harness (`bench/task9/`) is written and merged before the window opens. Before
  that, it is run only on the repository's own fixtures (`examples/demo-site`,
  `examples/demo-site-intl`), never on a drawn repository.
- Committed: `repos.json`, `draw.csv`, one results row per PR (repo, PR number, head and
  base SHA, mode, outcome, blocking count), one row per production audit (repo, time,
  PRs merged since the last one, new critical and high count), both ledgers and the
  report. Not committed:
  crawl output or built HTML, which hold the full text of the audited sites
  (`RELEASING.md`, step 5).
- The report gives totals and names no sites, like the replay reports.

## Sign-off

- Filled in and approved by (B): SurendharVr
- Date: 2026-10-22
- Merged before the draw and before any prospective run on real data (commit SHA of the
  merge): `9e34e2152e71857e5af430e208d5a1792e3c4798` (#90)

## Addendum 1: frozen on 1.9.1 (2026-10-22, before the draw)

**Why.** 1.9.1 is a patch release of four security fixes (#93, #94), made after this file
was signed. Task 9 crawls public previews that the authors of the pull requests control,
so the hardening protects the run's own runner and data. None of it changes a rule,
threshold or severity:
- `http-headers` go only to the host of the URL passed. Task 9 sends no secret header
  (3.3), so its crawls are unaffected.
- `<loc>`, `<lastmod>` and `<url>` values stop at the next tag. A sitemap of unclosed tags
  can no longer hold an audit for hours, which would have been a tool failure (3.5).
  Well-formed sitemaps parse as before.
- The PR comment quotes site text as code spans. Task 9 posts no comment (2.3).
- The Action's checkouts no longer keep the token on disk. Task 9 runs its own harness.

**1. Frozen version (supersedes section 1).**

- Package: `sitemend==1.9.1`
- Tag: `v1.9.1`
- Commit: `ad61ab753317ff5bfb82a0f163ca2f4fe439a5bb`

The harness pins it. No rule, threshold or severity changes until this run's report is
published; a bug found from here on is logged and gets an issue.

**2. Checked before this addendum.** The repository's own fixtures were audited with both
versions: `examples/demo-site` gave the same 24 findings on 1.9.0 and 1.9.1, and
`examples/demo-site-intl` the same 11 (same rule, severity, pages and evidence). No drawn
or benchmark repository was used.

**3. Unchanged:** everything else in this file, including the draw (section 2), the window
(section 3), verdicts (section 4), thresholds (section 5) and decision rules (section 6).
The replay and seeded benchmark workflows stay on `sitemend==1.9.0`, the version the
published replay report measured.

**4. Limitation, stated in the report.** The replay result that made Task 9 eligible was
measured on 1.9.0. 1.9.1 differs only by the fixes above. On well-formed sitemaps and
without `http-headers`, it emits the same findings, so the replay result carries over.
Where a site's sitemap is malformed, the two versions can read it differently. The report
states how many drawn sites that applies to.

Decided by (B): SurendharVr. Date: 2026-10-22.

## Addendum 2: the frame runs short, a sibling site, production on preview hosts (2026-10-23, before the build check)

**Status:** signed by SurendharVr on 2026-10-23. Written by Claude on 2026-10-23; every
choice below was proposed by Claude and accepted as written.

**When.** After the draw ran, before any build check and before any data from the window.
The candidate list below is known, so each choice here is made knowing it. That is stated
in the report.

**The draw, as run.** History and eligibility are as of the draw date, 2026-10-22, as
section 2.2 and Addendum 1 fix it. The draw was run on 2026-10-23, three times:
- **First run, from `8739619`, stopped:** 61 requests failed and were cached as empty
  answers, wrongly ruling out 26 readable repositories. Fixed in #99, so that a failed
  request is never cached and the draw stops instead.
- **Second run, from `586b3ff`, at 11:33 UTC:** completed.
- **Third run, from `1ed15f3`, at 15:12 UTC:** completed after #100, which stopped
  non-preview deployments (a PyPI release, GitHub Pages) counting as previews. It found the
  same 32 candidates as the second run; only rtl-buddy/rtl_buddy lost a false preview flag.

Three readings were not as of the draw date:
- the homepage and preview checks were read on the day the draw ran;
- some repository metadata (public, fork, archived) came from answers cached on 2026-10-17,
  during the Addendum 5 draw;
- `draw.csv` holds every repository looked at, with its outcome.

| Stack | Frame | Ranks used before (sample, sweep) | Looked at | Candidates | With a preview |
|---|---|---|---|---|---|
| Docusaurus | 612 | 208 | 246 | 12 | 1 |
| Astro | 707 | 200 | 301 | 12 | 4 |
| VitePress | 846 | 356 | 490, the rest of the frame | 4 | 1 |
| Hugo | 1,550 | 1,550, all of it | 0 | 0 | 0 |
| Next.js | 984 | 511 | 473, the rest of the frame | 4 | 2 |

Section 2.2 takes the first 6 per stack that build, and `select` refuses a shorter sample.
Three stacks cannot reach 6 even before the build check, so 2.2 cannot be applied as
written.

**1. The short stacks.** Decided: (a).
- **(a) Fill from the other stacks** (accepted). Per stack, take every candidate that
  builds, up to 6. Fill the places left, up to 30, with the next candidates that built from
  the stacks that still have some, one stack at a time in the table's order (Docusaurus,
  then Astro), in draw order. Then apply 2.2's preview top-up as written: 10 flagged, at
  most 40 in all.
  - **For it:** it needs no new search and no new judgement, and continues the order
    already fixed in 2026.
  - **Against it:** the sample leans toward Docusaurus and Astro, and Hugo is absent. The
    report says so, and gives every measure per stack.
- **(b) A new frame for the short stacks.** Run Addendum 5's code searches again for
  VitePress, Hugo and Next.js, dated and saved before any filtering. Leave out every
  repository already in the old frame, shuffle with `random.Random(20261017)`, and continue
  the draw in that order.
  - **For it:** it keeps 6 per stack where the new frame allows.
  - **Against it:** it means a second frame with its own date, and Hugo will likely still
    fall short, since most Hugo sites have no npm `build` script.
- **(c) A smaller sample.** Take what builds, with no fill. Precision and frequency then
  rest on fewer sites, and the extension rule (3.1) is more likely to apply.

**2. vuejs-translations/docs-ja.** It is the Japanese twin of
vuejs-translations/docs-zh-cn, one of the 15 benchmark repositories that every 1.8.0 and
1.9.0 fix came from. It is built from the same Vue docs template. Section 2.1 excludes
exact repositories only, so it passes. Decided: (a).
- **(a) Exclude it** (accepted). Add to 2.1: any repository whose owner also owns a
  benchmark repository. Checked on the draw: it applies to docs-ja and to no other
  candidate, and no candidate shares an owner with a sweep repository. A translation of the
  same docs is, for this run, a site the rules were tuned on. Its place goes to the next
  candidate by part 1.
- **(b) Keep it.** The report names it as a sibling of a benchmark site and gives its
  results apart.

**3. Production on a preview platform's host.** For four candidates the production site
itself is on a per-deploy host:
- algolia/api-clients-automation: `api-clients-automation.netlify.app`;
- nuthatch-org/nuthatch-frontend: `nuthatch-frontend.vercel.app`;
- area44/SYWYKE: `sywyke.vercel.app`;
- LATAMFILTERS/world-catalogue: `world-catalogue.vercel.app`.

Preview-host leak detection has a known blind spot on such a site: the one pooled seeded
miss, on learn-fips, was on a `vercel.app` production host. Their previews are still
recognised, since #100 never takes the production host for a preview. Decided: (a).
- **(a) Keep them, and report apart** (accepted). Precision and frequency are unaffected.
  The preview-host measure (section 5) is given with and without these sites, and the
  blind spot is stated.
- **(b) Exclude them.** That drops 4 of 32 candidates, all of them small sites.

**4. Homepages stored as http.** Two candidates' GitHub homepages are `http://` (mia-platform/documentation and nsc-de/JsTools). The build check already reads them over
https (2.2). Decided: the production URL in `repos.json` is the https form, so production audits and
url checks crawl what 2.2 checked.

**5. Unchanged:** everything else in this file and Addendum 1, including the frozen
version (1.9.1), the draw date, the window, verdicts, thresholds and decision rules.

**Code that follows if this is signed,** in a PR merged before the build check:
- `select` takes part 1's rule;
- the draw applies part 2's exclusion;
- `select` writes https homepages (part 4).

None of it changes which repositories were looked at, or their order.

Decided by (B): SurendharVr. Date: 2026-10-23.
