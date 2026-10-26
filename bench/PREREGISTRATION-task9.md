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

## Addendum 3: the sample is the 16 that built (2026-10-24, before select)

**Status:** signed by SurendharVr on 2026-10-24. Written by Claude on 2026-10-24; every
choice below was proposed by Claude and accepted as written.

**When.** After the build check, before `select` and before any data from the window.
Which candidates built is known, so each choice here is made knowing it. That is stated in
the report.

**The build check, as run.** All 41 candidates in `bench/task9/candidates.json` (#103)
were built on GitHub Actions run 40051480416 on 2026-10-24, each at its default branch's
head on the draw date. Every outcome is in `bench/task9/builds.csv`:

| Stack | Built / checked | Built (P: has a preview) |
|---|---|---|
| Docusaurus | 6 / 17 | mia-platform/documentation, sdkman/sdkman.github.io, apache/cloudstack-www, actix/actix-website (P), qmBase/docs, knorrlabs/ignition-guides |
| Astro | 8 / 17 | jonathanbell/jonathanbell.github.io, emish89/italiapersonalfinance (P), r4ai/r4ai.dev (P), nx-academy/nx-academy.github.io, nuthatch-org/nuthatch-frontend, area44/SYWYKE (P), maxswinkels/busybar-apps, zelavis/zelavis |
| VitePress | 1 / 3 | honojs/website |
| Hugo | 0 / 0 | none |
| Next.js | 1 / 4 | disfordave/provence (P) |

The other 25:
- **19 did not build under Addendum 5's rule 5.** Their dependencies were not installed in
  the site's own folder, a tool was missing, the Node version was wrong, the project's
  build failed, or the output was not in the stack's default folder.
- **5 failed the homepage check** (2.2).
- **1 built no HTML pages** (Addendum 7).

`builds.csv` gives as each failure's reason the last line of its build log. The build check
does not tell a failed build apart from one that put its output somewhere other than the
stack's default folder: both count as a missing output folder (Addendum 5, rule 6). For
three of the 19, the last line reads like success:
- shlinkio/shlink.io: "[build] Complete!";
- myissue-studio/vue-website-page-builder: "built in 21.72s";
- ot-nemoto/combine-pdf-files: "(Static) prerendered as static content".

They most likely built into a non-default folder. The logs were not kept, so this is
recorded as a known ambiguity, not corrected.

Addendum 2 fills the sample to 30 from the frame, but every frame is read to its end, so
`select` can take only 16. The rules as signed cannot produce a sample.

**1. The sample.** Decided: the 16 that built, as listed above, are the sample; 2.2's 6 per
stack and Addendum 2's fill to 30 do not apply. Two alternatives were
considered and are not taken here:
- **A new, dated frame search,** not drafted, which would delay the window.
- **A change to the build rule,** rejected. Installing dependencies in the site's own folder,
  or looking for the output in a non-default folder, would rescue several of the 19. But it
  changes an eligibility rule after seeing which candidates it helps.

**2. Previews.** 5 of the 16 have the preview flag, and no further flagged candidate built,
so 2.2's top-up to 10 cannot be met. Decided: no top-up; url mode is measured on what
those 5 sites' PRs give, and is reported apart, as section 5 already does.

**3. Precision's 20-finding minimum.** Decided: unchanged, at least 20 blocking findings in
folder mode. What 16 sites mean for it:
- **The PRs.** The 16 had 772 PRs merged into their default branch in the 8 weeks before
  the draw date: 460 by people and 312 by bots, mostly Dependabot. An author counts as a bot
  if GitHub types it Bot or its login ends in `[bot]`.

  | Site | Merged PRs | By people | By bots |
  |---|---|---|---|
  | zelavis/zelavis | 309 | 163 | 146 |
  | nuthatch-org/nuthatch-frontend | 100 | 100 | 0 |
  | mia-platform/documentation | 78 | 24 | 54 |
  | qmBase/docs | 55 | 55 | 0 |
  | nx-academy/nx-academy.github.io | 29 | 29 | 0 |
  | jonathanbell/jonathanbell.github.io | 29 | 0 | 29 |
  | disfordave/provence | 25 | 25 | 0 |
  | apache/cloudstack-www | 25 | 10 | 15 |
  | area44/SYWYKE | 23 | 2 | 21 |
  | actix/actix-website | 17 | 2 | 15 |
  | maxswinkels/busybar-apps | 16 | 16 | 0 |
  | honojs/website | 15 | 15 | 0 |
  | sdkman/sdkman.github.io | 15 | 2 | 13 |
  | r4ai/r4ai.dev | 15 | 12 | 3 |
  | knorrlabs/ignition-guides | 11 | 4 | 7 |
  | emish89/italiapersonalfinance | 10 | 1 | 9 |

- **The estimate.** The 1.9.0 replay found 86 blocking findings in 556 comparisons (0.155 a
  comparison), all of them in 22 failing comparisons. A dependency bump rarely changes a
  site's output, so only PRs by people are counted. If the window has as many of those, and
  the gate fails them at the replay's rate, 8 weeks would give about 70 blocking findings.
  Without zelavis/zelavis, the site with the most PRs by people, it is about 46.
- **Why it is a weak estimate:**
  - the replay's commits are not PRs;
  - its findings came from a sample the rules were tuned on;
  - merged PRs leave out the PRs closed without merging, which the window also counts (3.2);
  - an account GitHub types as a person can still be automated.
- **What 20 would show.** At exactly 20 findings with 19 true (95%), the 95% Wilson interval
  for precision runs from about 76% to 99%. With 16 sites, findings are clustered by site,
  so the interval is wider still. The report states the interval and the number of sites
  the findings came from.

**4. Bot PRs in the thresholds.** Section 3.2 counts PRs opened by bots, and reports them
apart. With 16 sites, bots made 312 of the 772 PRs, and five sites are nearly all bots:
jonathanbell 29 of 29, area44/SYWYKE 21 of 23, actix 15 of 17, sdkman 13 of 15 and
italiapersonalfinance 9 of 10. Counted, those PRs enlarge frequency's denominator (PRs
compared) while rarely holding a regression, so a few sites' dependency bumps could take
frequency below 1 in 100, whatever the gate does on PRs by people. Precision is unaffected,
since it counts findings. Decided: (a).
- **(a) Thresholds on PRs by people** (accepted). Frequency and tool failures (section 5)
  count PRs by people only, and are also reported for all PRs and for bot PRs apart.
  Precision counts every blocking finding, from any author. This changes 3.2 before any
  window data. Five of the 16 sites then contribute few or no PRs to the thresholds, which
  the report states.
- **(b) As signed.** Bot PRs count toward every threshold, and are also reported apart.

**5. The extension rule (3.1).** Decided: unchanged: 4 weeks at a time, up to 16 weeks in
all, and precision not met if 20 are never reached. With 16 sites rather
than 30, an extension is more likely if the estimate in part 3 is too high. If 20 blocking
findings are not reached by week 16, section 6's precision rule applies: outreach stays
stopped.

**6. One busy site.** zelavis/zelavis alone made 40% of the 16 sites' PRs before the draw,
and 35% of those by people (163 of 460), so it could carry most of the frequency and
precision results. Decided: no cap on any site; every measure is also reported per site,
and once more without the site with the most PRs compared.

**7. What else 16 sites mean, stated in the report:**
- **Per stack:** Docusaurus 6, Astro 8, VitePress 1, Next.js 1, Hugo 0. Results for
  VitePress and Next.js are single sites; nothing is claimed per stack for them.
- **Production on a preview platform's host:** 2 of the 16, nuthatch-org/nuthatch-frontend
  and area44/SYWYKE. Addendum 2, part 3 applies.
- **What the sample excludes:** every site whose real deploy needs more than its own
  `build` script (Addendum 5's limitation) is left out, so the sample leans toward
  simple, conventionally built sites.

**8. Unchanged:** everything else, including the frozen version (1.9.1), the window's
length, verdicts, thresholds and decision rules.

**Code that follows if this is signed,** in a PR merged before `select` runs:
- `select` takes every candidate that built when fewer than 30 did, instead of refusing. It
  still writes https homepages (Addendum 2, part 4) and `window.json`.
- With part 4 (a), `report` computes frequency and tool failures on PRs by people, and gives
  all PRs and bot PRs beside them.

Decided by (B): SurendharVr. Date: 2026-10-24.

## Addendum 4: postpone the window and widen the sample (2026-10-24, before the window)

**Status:** signed by SurendharVr on 2026-10-24. Written by Claude on 2026-10-24; every
choice below was proposed by Claude and accepted as written.

**When.** After `select` wrote the 16-site sample and `window.json` (#107, merged at 04:54
UTC on 2026-10-24), and before the window opens at 00:00 UTC on 2026-10-25. No PR has been
checked.

**Why.** 16 sites is a thin sample (Addendum 3, parts 3 and 6). The frame it came from was
cut short by GitHub, not used up. Each of Addendum 5's code searches returned exactly 1,000
results, the most GitHub returns for one query: Docusaurus, Astro, VitePress and Next.js
1,000 each, and Hugo 1,000 for each of its two queries. So repositories that search
could find were never in the frame. A frame that gets past the cap can supply more sites by
the same rules.

**1. Postpone the window.** Decided: the window does not open on
2026-10-25. It opens at 00:00 UTC on the day after the widened sample's `repos.json` and
`window.json` are committed, and runs 8 weeks from then. `window.json` is removed until
then, so the task9 workflow's polls do nothing.

This takes effect only if it is on `main` before 2026-10-25T00:00:00Z. If it is merged
later, the window has already opened with the 16: this addendum then records only the
finding about the first frame, parts 1 to 5 lapse, and the 16 are the sample as Addendum 3
says. Adding sites after that would need a further addendum, as a separate group.

**2. A second frame.** Decided: the same five stacks and code searches as Addendum 5, each
split by file size so that no slice reaches the cap.
- **Splitting:** each search runs over size ranges in bytes, starting at `size:0..1000`,
  `size:1001..3000`, `size:3001..10000` and `size:>10000`. A slice that returns 1,000 results
  is halved and searched again, until every slice returns fewer.
- **Saving:** every result is saved, with the date it was taken and the slices used, to
  `bench/task9/frame2-<stack>.json`, before any filtering. It is taken once.
- **Speed:** code search allows 10 requests a minute, and a slice takes up to 10 pages of
  100, so the second frame may take tens of minutes per stack.
- **Limitation:** code search still returns only what GitHub has indexed and ranks, so the
  frame is still not every site. That is stated in the report, as for the first frame.

**3. The draw from it.** Decided: by the same rules, with these differences.
- **Leave out first:** every repository in the first frame, in any stack, so that no
  repository is looked at twice.
- **Order:** sorted by `owner/name`, then shuffled with a fresh `random.Random(20261017)` per
  stack, in the table's order, and saved to `bench/task9/order2-<stack>.json`.
- **Eligibility:** as before. 2.1 with Addendum 2's same-owner rule, Addendum 5's rules 4
  and 5 with Addendum 6, at least 8 merged PRs in the 8 weeks before the draw date, and a
  homepage.
- **The draw date stays 2026-10-22,** so every site meets the same history. Homepage and
  preview checks are read on the day the draw runs, as before.
- **Recorded in** `bench/task9/draw2.csv` and `candidates2.json`.

**4. Build check and selection.** Decided: the second draw's candidates are
build-checked as 2.2 says. Then `select` works in this order:
- **The 16 first.** All 16 already selected stay in the sample, whatever their stack:
  Docusaurus 6, Astro 8, VitePress 1, Next.js 1.
- **New candidates up to 6 per stack.** Only the second draw's candidates that built are
  added, in draw order, each stack up to 6, counting the 16 toward it. Docusaurus and Astro
  are already full, so new ones go to VitePress, Hugo and Next.js first.
- **Fill to 30.** The places left, up to 30, come from the new candidates left, one stack at
  a time in the table's order.
- **Preview top-up:** to 10 flagged, at most 40 in all, from new candidates only.

No site of the 16 is ever dropped.

**5. If the second frame still falls short of 30.** Decided: once every slice of the second
frame has been drawn to its end, the sample is everyone who built, as in Addendum 3, and the
window opens. No third frame.

**6. What this replaces, and what it keeps:**
- **Replaces Addendum 3, part 1:** "the sample is the 16". The sample is the 16 plus part
  4's additions, or everyone who built under part 5.
- **Replaces Addendum 3, part 2:** "no preview top-up". Part 4's top-up applies to the new
  candidates.
- **Keeps Addendum 3, parts 3 to 7:**
  - the 20-finding precision minimum;
  - thresholds on PRs by people;
  - the extension rule;
  - every measure per site and without the busiest site;
  - what the report states.
- **Keeps Addendum 2,** apart from its fill being applied here only to new candidates.
- **Unchanged:** the frozen version (1.9.1), the draw date (2026-10-22), the window's length
  (8 weeks), verdicts, thresholds and decision rules.

**7. Each site's frame.** `repos.json` records for every site which frame it came from, 1 or
2. The second frame comes from results below what GitHub ranked first, so its sites may
differ, for example newer or smaller projects. The report gives the precision and
frequency of each frame's sites beside the pooled figures, and states that the sample was
widened after the first selection, and why.

**Code that follows if this is signed,** in a PR merged before the second draw:
- `task9.py frame2`: the sliced searches, saved before filtering;
- `task9.py draw --frame 2`: the first frame left out, the new order, the same rules;
- `select`: the 16 kept, and the second draw's candidates that built added by part 4's rule,
  each site marked with its frame;
- `report`: each frame's figures beside the pooled ones (part 7).

Decided by (B): SurendharVr. Date: 2026-10-24.

## Addendum 5 (Task 9): the second frame's splitting rule (2026-10-24, before the search)

**Status:** signed by SurendharVr on 2026-10-24. Written by Claude on 2026-10-24; every
choice below was proposed by Claude and accepted as written.

**Name.** This is the fifth addendum to this file. Everywhere else in this file, "Addendum
5" means Addendum 5 of `bench/PREREGISTRATION.md`, which drew the replay sample and saved
the first frame. This one is always called "Task 9 Addendum 5".

**When.** After Addendum 4 was signed (#108), before the second frame's code is written or
any search runs.

**Why.** Addendum 4, part 2 splits each code search by file size, but leaves three things
open, each of which decides which repositories enter the frame.

**1. The open range.** `size:>10000` has no upper end, so it cannot be halved. Decided:
it becomes `size:10001..384000`. GitHub's code search indexes only files smaller than 384 KB,
so no file above that can be found in any case.

**2. When a slice is split.** Decided: by the response's `total_count`. A
slice `size:lo..hi` with a `total_count` of 1,000 or more is split into `lo..mid` and
`mid+1..hi`, with `mid = (lo + hi) // 2`, and each half is searched again. The number of
results returned is not the test. Every slice's `total_count` and `incomplete_results` are
saved with the frame.

**3. A one-byte slice still at the cap.** Many sites keep a starter config untouched, so
thousands of files can share one exact size, and a slice `size:n..n` can still hold 1,000 or
more. It cannot be split by size. Decided: (a).
- **(a) Keep what GitHub returns** (accepted). The slice's results, up to GitHub's 1,000, are
  kept as returned, and the slice is marked capped in `frame2-<stack>.json` with its
  `total_count`. The report states how many slices were capped, and how many files they
  held beyond the 1,000 kept.
- **(b) Split it further by path,** for example the repository root against everything
  else. This adds a rule chosen for these files, and may still leave a capped slice.

**4. Unchanged:** everything else in Addendum 4 and before.

Decided by (B): SurendharVr. Date: 2026-10-24.

## Addendum 6 (Task 9): Task 9 is decoupled from the product (2026-10-24, before the window)

**Status:** signed by SurendharVr on 2026-10-24. Written by Claude on 2026-10-24.

**Name.** This is always called "Task 9 Addendum 6". Addendum 6 of
`bench/PREREGISTRATION.md` is the Node version rule.

**1. Task 9 continues unchanged.** It stays pinned to `sitemend==1.9.1` (Addendum 1), with
the same sample, window, contact rule (section 2.3) and decision rules. Its result will be
published as planned.

**2. The freeze is on the version Task 9 measures, not on `main`.** "No rule, threshold or
severity changes until this run's report is published" (section 1, Addendum 1) applies to
1.9.1 as Task 9 runs it. `main` may ship rule changes as minor releases under
`RELEASING.md`. Every pull request Task 9 checks is still checked with 1.9.1.

**3. Outreach reopens now.** This overrides the lines in Addenda 9 and 10 of
`bench/PREREGISTRATION.md` that say a replay pass "does not reopen outreach on its own".
Why: the 1.9.0 replay met every threshold set before it ran
(`docs/benchmark-1.9.0-replay.md`):
- blocking precision 82 of 86 (95.3%), against at least 95%;
- frequency 21 of 556 commits (3.8%), against at least 1 per 100;
- seeded recall 66 of 67 (98.5%), against at least 90%.

Evidence on sites sitemend has never seen will come from real installs as well as from
Task 9.

**4. The claims rule stays.** Section 6's rule on preview-host leaks and soft 404s stays in
force, and applies to all public material: `README.md`, `SKILL.md`, `action.yml`, the
package description and the Marketplace listing.

**5. No further addenda for product decisions.** This is the last addendum or
pre-registration document that decides anything about the product. The replay and seeded
benchmarks continue as release checks.

**6. Section 6, with outreach already open.** Section 6's first rule ("all met: reopen
outreach ... the only result that reopens it") is superseded by part 3: outreach is
already open. Every other rule in section 6 stays in force, as a brake on that outreach:
- precision fails: outreach stops, and the rules are fixed under `RELEASING.md`;
- tool failures above the threshold: outreach stops until they are fixed and re-measured;
- frequency fails: sitemend is repositioned as a pre-launch audit;
- the claims rule (preview-host leaks, soft 404s) applies to all public material.

Section 2.3's no-contact rule stays. In addition, there is no outreach to any repository
in `bench/task9/repos.json`, or to the next repositories in draw order that a fresh draw
would use (`bench/sample/order-*.json`), so a future prospective run stays uncontaminated.

Decided by (B): SurendharVr. Date: 2026-10-24.
