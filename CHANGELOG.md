# Changelog

## 1.10.0 - 2026-10-24

The example workflows and README pin `@v1.10.0`. A minor release: one new rule,
`S1-HOST-DRIFT`. Task 9 stays pinned to 1.9.1 (Task 9 Addendum 6, signed in #114).

- **New rule: `S1-HOST-DRIFT` (#115).** `sitemend check --base`
  passed a build whose site-URL variable fell back to the preview URL, so every canonical,
  `og:url`, sitemap URL and robots `Sitemap:` line named `*.vercel.app`. One build that
  agrees with itself is not `S1-HOST-MISMATCH`, and the comparison never looked at hosts.
  The comparison (`verify.py`) now compares the hosts each build publishes, read from the
  `crawl.json` beside each `findings.json`, as `sitemend check` leaves them. When the head
  publishes none of the base's hosts, it reports `S1-HOST-DRIFT` with both hosts and where
  each appears:
  - **critical**, blocking, when a new host is a preview host (`PREVIEW_HOSTS`);
  - **high, confidence medium** otherwise (a domain move, usually deliberate): advisory in
    the PR comment, never fails the gate.

  The crawled origin is not a published host, so the preview workflow (production
  canonicals on a preview URL) and a site whose production lives on a `*.vercel.app` host
  pass as before. A head that mixes both hosts is still `S1-HOST-MISMATCH` alone. A
  `verify` run without both crawls (`sitemend verify --baseline`) skips the check. No
  single-build audit changes: `examples/demo-site` and `examples/demo-site-intl` give the
  same 24 and 11 findings. No other rule, threshold or severity changes.
- **Task 9 harness (`bench/task9/task9.py`, `.github/workflows/task9.yml`).** The prospective
  run as pre-registered: the draw (eligibility, build check, the size rule), a poll every 15
  minutes that checks each new PR head in folder and url mode, production audits after
  merges, the two ledgers, and the summary with section 6's decision rules. The checks that
  build strangers' code run with a read-only token, no secrets and no saved credentials;
  only the poll job, which runs this repository's code, may push, and only to the
  `task9-data` branch. A poll never waits for checks: it files the results of earlier runs'
  finished checks, so one slow check delays only its own result. Tested on fixtures only: nothing has run on a drawn repository.
  `replay.audit` takes an optional timeout (default none, as before).

## 1.9.1 - 2026-10-22

The example workflows and README pin `@v1.9.1`. A patch release of security fixes. Three
of them leave every finding as it was. One can change findings in a single case, stated
here as the stability policy asks:
- **A protected site served from another host than the one passed.** When the URL given
  to `sitemend check` (the Action's `url` or `baseline-url`) redirects to a different
  host, apex to www included, that host no longer receives the `http-headers` secrets.
  If it needs them, it now answers without them (a 401 or a login page), so its crawl,
  and every finding built on it, can differ from 1.9.0. That is the leak being closed,
  not a rule change. Pass the URL the site is served from to keep the 1.9.0 result.

No rule, threshold or severity changes. The benchmark workflows stay on 1.9.0, the
version the published replay report measured and Task 9 is frozen on.

- **Task 9 pre-registration (`bench/PREREGISTRATION-task9.md`), signed by SurendharVr on
  2026-10-22 and merged in #90 (`9e34e21`).** The prospective run of `sitemend==1.9.0`
  on real pull requests of 30 sites drawn from Addendum 5's frame, none of them a site
  the rules were tuned on, over an 8-week window. Nothing has run on a real repository.
- **Bench harness (#91).** The replay cache is keyed by the sitemend that made each audit,
  so a re-run on another version never reuses an old audit, and `recall.md` also reports
  what the gate did. 1.9.0's numbers are unchanged; the one pooled seeded miss was failed
  by another rule.
- **Security: three hardening fixes from the same review.**
  - **The Action's checkouts no longer keep the token on disk.** Both use
    `persist-credentials: false`, so the PR's build and the install scripts it runs cannot
    read the job's token from `.git/config`.
  - **The PR comment lets no site text act as markup.** Evidence and page paths are
    quoted as code spans; messages and waiver reasons are escaped, and an `@` is followed
    by a word joiner, so text from the audited site (in the preview workflow, the PR's own
    deploy) cannot @mention anyone or render as a link or image in the bot's comment.
  - **Sitemap parsing is linear.** `<loc>`, `<lastmod>` and `<url>` values stop at the next
    tag, so a sitemap of unclosed tags can no longer hold the audit for hours (48 KB took
    10 s before). Well-formed sitemaps read exactly as before.
- **Security: `http-headers` no longer follow a redirect to another host.** The headers
  from `SITEMEND_HTTP_HEADERS` (the Action's `http-headers` input, such as a Vercel
  protection-bypass secret) were set on every request, and `requests` keeps custom headers
  when a redirect leaves the host. A preview page that redirected off-site, for example
  through a fork PR's `_redirects` rule, sent the secret to that host. They now go only to
  the host of the URL passed to `sitemend check`, by requests' own rule for
  `Authorization`: an http -> https upgrade and an explicit default port count as the same
  site, while another host (apex to www included) or port does not. The rule covers the
  crawl, the robots.txt and sitemap fetch, the soft-404 probe and every redirect hop. If
  you set `http-headers` on previews that fork PRs can change, consider rotating the
  secret. This can change findings for a protected site served from another host than
  the one passed (see above).
- **The 1.9.0 benchmark: `docs/benchmark-1.9.0-replay.md`.** The same 600 commits
  replayed through 1.9.0 (Addendum 10), and all three pre-registered thresholds are met:
  - **Precision:** 82 of 86 (95.3%), with no margin; the 4 that do not count are
    `unclear`.
  - **Frequency:** 21 of 556 commits (3.8%).
  - **Seeded recall:** 66 of 67 (98.5%).
  - **What changed from 1.8.0:** exactly the 14 findings that did not count are gone, and
    all 82 true regressions are still caught.
  - **What it means:** as pre-registered, the prospective run (Task 9) is eligible to
    start, and outreach waits for it. The result is optimistic: every fix came from this
    sample.
  - **Data:** `bench/replay/1.9.0/`, `bench/ledger-1.9.0.csv` and `bench/seeded/1.9.0/`.
- **Re-measurement on 1.9.0 (Addendum 10, signed by SurendharVr on 2026-10-21).** Replay and
  seeded recall re-run on the same 15 repositories with `sitemend==1.9.0`.
  - Verdicts carry over only to identical findings, from the 1.8.0 ledger first, then
    1.7.0.
  - The seeded harness counts title duplicates over every crawled page, fixing its 1.8.0
    `title-duplicated` miss (#81). That type is pooled again, and `rating-unsupported`
    and `sitemap-preview-host` stay apart.
  - The limitation is stated more strongly: this is the third measurement on the sample
    every fix came from.
  - If precision fails again, the next measurement uses a fresh sample, drawn by
    Addendum 5's procedure.

## 1.9.0 - 2026-10-21

The example workflows and README pin `@v1.9.0`. A minor release under the stability policy:
it fixes the false positives and the recall gap that the 1.8.0 benchmark found, and those
fixes change findings:
- pages in folders named `vendor`, `out`, `build` or `tmp` (#82) change `S1-BROKEN-LINK`,
  `S1-SITEMAP-ORPHAN` and any rule that now sees those pages;
- in `verify`, a duplicate group reworded on the same pages pairs as changed (#82):
  `S3-TITLE-DUPLICATE` and `S3-DESC-DUPLICATE`;
- claims on pages in any script (#81): `S5-SCHEMA-UNSUPPORTED-CLAIM` and
  `S5-SCHEMA-CLAIM-OFFPAGE`.

The benchmark workflows stay on 1.8.0, the version its published report measured.
Measuring 1.9.0 needs a new dated addendum.

- **Structured-data claims are checked on pages in any script (#81).** Claim text was
  reduced to `[a-z0-9]`, so a page written entirely in Korean, Chinese, Arabic and the like
  came out empty and its claim checks were skipped: a fabricated 4.7-star rating there
  raised nothing (found by the 1.8.0 seeded run). Text is now casefolded letters and digits
  in any script, accents ignored on both sides. Claim tokens are whole words in any script
  (3+ letters where the script has case, 2+ where it does not, as in 北京), and words in a
  caseless script count as identifying terms. Affected rules: `S5-SCHEMA-UNSUPPORTED-CLAIM`
  and `S5-SCHEMA-CLAIM-OFFPAGE`.
- **A duplicate group whose shared text is reworded is the same finding (#82).** Since #60
  `verify` identifies a duplicate-title or duplicate-description group by its text, so
  translating the title 108 archive pages already shared read as a new duplicate and
  failed the gate. A group on exactly the same pages now pairs as changed whatever its
  text; a new pair on an overlapping page under different text (#60) is still new.
  Affected rules (in `verify` only): `S3-TITLE-DUPLICATE`, `S3-DESC-DUPLICATE`.
- **Pages in folders named `vendor`, `out`, `build` or `tmp` are crawled when the site
  uses them (#82).** A folder audit skipped every such folder at any depth, which is right
  for dependencies in a source tree but wrong for a built site whose routes use those
  names (a Docusaurus page at `b2b/stats/purchases/vendor/`). Those folders are now
  walked. A page in one is kept only when a page of the site links to it or its sitemap
  lists it, so a library's bundled HTML still stays out. `node_modules`, virtualenvs and
  sitemend's own output are never walked. The 1.8.0 replay found 13 false positives from
  this on one site. Affected rules: `S1-BROKEN-LINK`, `S1-SITEMAP-ORPHAN`, and any rule
  that now sees those pages (`S2-*`, `S3-*`, `S5-*`).
- **The 1.8.0 benchmark: `docs/benchmark-1.8.0-replay.md`.** The same 600 commits
  replayed through 1.8.0 (Addendum 9):
  - **Precision** rose from 5.3% to 82.0% (82 of 100 blocking findings) and still fails
    its 95% threshold, so outreach stays stopped and Task 9 does not start.
  - **Frequency** (21 of 549 commits, 3.8%) and **seeded recall** (57 of 58, 98.3%)
    met theirs.
  - **The shortfall:** 13 of the 18 findings that did not count come from one cause,
    `crawl.py` skipping folders named `vendor` (and `out`, `build`, `tmp`) inside a
    built site.
  - **Data:** `bench/replay/1.8.0/`, `bench/ledger-1.8.0.csv` and `bench/seeded/1.8.0/`.
- **Re-measurement on 1.8.0 (Addendum 9, signed by SurendharVr on 2026-10-20).** Replay and
  seeded recall are re-run on the same 15 repositories and 600 comparisons with
  `sitemend==1.8.0`. The thresholds and decision rules are unchanged, and the results
  are kept apart from the 1.7.0 record. A 1.7.0 verdict carries over only to an
  identical finding. The `sitemap-preview-host` and `title-duplicated` mutations join
  `rating-unsupported` in being reported apart. The fixes came from this sample, so the
  result is stated as optimistic, and a pass makes the prospective run (Task 9) eligible
  to start rather than reopening outreach.

## 1.8.0 - 2026-10-20

The example workflows and README pin `@v1.8.0`. A minor release under the stability policy,
because it fixes the false positives and misses that the 1.7.0 benchmark found, and those
fixes change findings:
- base-path sites (#69) and percent-encoded URLs (#73) change the link, canonical,
  hreflang, sitemap, orphan and asset rules named in their entries;
- a preview URL on a localhost site (#70) now fires `S1-HOST-MISMATCH` instead of
  `S1-MIXED-CONTENT`;
- in `verify`, `S3-TITLE-DUPLICATE` and `S3-DESC-DUPLICATE` now pair by their shared
  text (#60).

#71 is a performance fix that leaves findings unchanged. The benchmark itself stays on
1.7.0; re-measuring on 1.8.0 needs a new dated addendum.

- **A site served from a base path is audited as served (#69).** A GitHub Pages project
  site at `/<repo>/` (Docusaurus `baseUrl`, VitePress `base`, Astro `base`) writes every
  link, canonical and sitemap URL under that path, while its build folder starts at `/`.
  A folder audit now infers the base path from the home page, when its canonical (or
  `og:url`) names a folder that is not a real top-level entry of the build and most of
  its root-relative links follow it, and names every page, asset and robots-declared
  sitemap as served. A link that forgets the base path is still reported broken. The
  replay benchmark found 1,193 false positives from this on one site. Affected rules:
  `S1-BROKEN-LINK`, `S1-CANONICAL-BROKEN`, `S1-CANONICAL-CROSS`, `S1-HREFLANG-BROKEN`,
  `S1-SITEMAP-ORPHAN`, `S1-SITEMAP-GAP`, `S1-SITEMAP-MISSING`, `S2-ORPHAN`,
  `S2-UNREACHABLE`, `S2-DEEP`, `S3-ASSET-UNUSED`, `S3-IMG-HEAVY`. The crawl records the
  inferred path as `meta.base_path`.
- **Percent-encoded and non-ASCII URLs match the pages they name (#73).** Paths are
  compared in one form, percent-escapes decoded and NFC-normalized, so a sitemap or
  canonical that publishes `/archive/tag/%E7%9B%91%E6%8E%A7/` finds the page built at
  `archive/tag/监控/`, and a decomposed (macOS) file name matches its composed URL.
  Escapes that change a path's meaning (`%2F`, `%23`, `%3F`, `%25`) stay escaped. The
  replay benchmark found 173 findings from this on one site. Affected rules:
  `S1-SITEMAP-ORPHAN`, `S1-SITEMAP-GAP`, `S1-CANONICAL-BROKEN`, `S1-CANONICAL-CROSS`,
  `S1-BROKEN-LINK`, `S1-HREFLANG-BROKEN`, `S2-ORPHAN`, `S2-UNREACHABLE`. Both change which
  findings are emitted, so they ship in a minor release.
- **Large JS bundles no longer stall the crawl (#71).** The scan for media file names in
  CSS, JS and pages was quadratic on a long run of word characters and dots without a
  media extension (a 40,000-character run took 91 s; one site's 45 MB of minified JS took
  about 2.5 hours per commit). It is now linear and finds the same names. Findings are
  unchanged.
- **A preview URL leaked into a site built for localhost is reported (#70).** When
  every URL a site publishes names a dev server (`http://localhost:9876`) and one names a
  preview deploy (`*.vercel.app`), the preview no longer becomes the inferred base URL,
  and the host check counts the loopback host it differs from. Before, the leak raised no
  `S1-HOST-MISMATCH`, and the `https` preview base turned the site's own `http://localhost`
  scripts into `S1-MIXED-CONTENT`. Found by the seeded recall test. Affected rules:
  `S1-HOST-MISMATCH` (now fires), `S1-MIXED-CONTENT` (no longer fires there), and any
  rule that compares against the base URL on such a site.
- **A new duplicate title or description that overlaps an old one fails the gate (#60).**
  `verify` paired a head duplicate group with any base group of the same rule that
  shared a page, so a change that ended one pair and created another on the same page
  (`/apps/` moving from "Electron" to "10 years of Electron") read as the old finding
  changed and passed. The shared text is now part of the finding's identity: a group
  under different text is new, and a group that grows or shrinks under the same text
  is still changed. Found by the seeded recall test. Affected rules (in `verify` only):
  `S3-TITLE-DUPLICATE`, `S3-DESC-DUPLICATE`.
- **The benchmark report: `docs/benchmark-2026-11-replay.md`.** 600 real commits replayed
  through the frozen 1.7.0 gate on a reproducible 15-repository sample. Precision failed
  its pre-registered threshold (76 of 1,442 blocking findings, 5.3%; nearly all false
  positives come from #69 and #73), while frequency (20 of 517 commits, 3.9%) and seeded
  recall (73 of 75, 97.3%) met theirs. As pre-registered: outreach stops, the rules are
  fixed under the stability policy, and each confirmed false positive becomes a test.
- **The full replay on the Addendum 5 sample.** 15 repositories, 615 builds, 600
  comparisons on sitemend 1.7.0 (GitHub Actions run 39183739377): 517 compared, 34 failed
  the gate, 44 skipped for builds that failed and 39 for audits sitemend did not finish.
  `bench/ledger.csv` holds the 1,442 blocking findings, all awaiting B's verdicts; most
  come from two systematic patterns (a base-path site, #69, and percent-encoded non-ASCII
  URLs). layer5io/exoscale-academy took about 2.5 hours per audit (#71), so its 39
  unaudited commits are tool failures (Addendum 8). The 1.7.0 pilot's verdicts move to
  `bench/replay/pilot-1.7.0/ledger.csv`, since that sample was superseded. No behaviour
  changed.
- **Seeded recall and the robustness sweep on the Addendum 5 sample.** Seeded recall on the
  15 (`bench/seeded/addendum-5/`): 73 of 75 critical and high mutations caught (97.3%),
  controls 15 of 15; the rating mutation, reported apart, 10 of 13. The sweep
  (`bench/sweep/`, not pre-registered): 91 repositories drawn after the sample, 37 built,
  sitemend crashed on none, one had no HTML pages; 9 sites flagged, most of them sites
  served from a base path, whose links and canonicals a folder audit reads as broken. The
  benchmark workflows now upload only each job's own result files: the seeded run's
  artifacts had carried the old sample's committed results too. `bench/sweep/report.py`
  reads the page count from `report-data.json` (an antivirus quarantined the `crawl.json`
  of a SQL-injection knowledge base) and labels an output with no pages apart from a crash.
  No behaviour changed.
- **The replay sample, drawn by Addendum 5.** From a code-search frame saved on
  2026-10-18 (each stack at GitHub's 1,000-result cap), the seed-20261017 draw looked at
  2,528 repositories and build-checked 54 candidates at their cutoff commits on Ubuntu. The
  first 3 per stack that built are `bench/replay/repos.json`: Juniors017/docux-blog,
  DevAdmin-Riu/boss-dashboard-guide, jhipster/jhipster.github.io (Docusaurus);
  dergigi/learn-fips, mj3622/mj3622.github.io, GoWorkshopConference/2025 (Astro);
  taoli-tools/taoli-tools-docs, vuejs-translations/docs-zh-cn, fishxcode/fishxcode
  (VitePress); benbjohnson/litestream.io, layer5io/exoscale-academy, layer5io/docs (Hugo);
  rgcsekaraa/brows3, CertisBio-RC/certis_agroute_app, TeoConference/TEOConf-FE (Next.js).
  Two rules were corrected along the way, each in a dated addendum decided by B before any
  measurement: Node from `.nvmrc` or 24, not the `engines` floor (Addendum 6, after it
  failed four Docusaurus builds), and an output with no HTML pages counts as missing
  (Addendum 7). `draw.csv` and `selection.csv` record every repository's outcome.
  No behaviour changed.
- **A reproducible sample for the benchmark (Addendum 5, signed by SurendharVr).** The replay
  repositories were Claude's picks from memory; they are replaced by a procedure anyone can
  rerun: a saved GitHub code-search frame per stack, a shuffle with seed 20261017, recorded
  eligibility checks, a mechanical build-command rule and a build check at the cutoff
  commit, taking the first 3 repositories per stack that build (15 in all, 40 commits each).
  Every repository used in the plan so far is excluded. The full run of the old sample was
  cancelled and its data is not used. No behaviour changed.
- **Sampling and sweep tooling for Addendum 5.** `bench/sample/sample.py` implements the
  reproducible draw: `frame` saves each stack's code-search results once, `draw` walks them
  in the seed-20261017 order through the eligibility rules and the mechanical build-command
  rule (recording every repository in `draw.csv`), and `select` takes the first 3 per
  stack that built. `bench/sweep/report.py` reports the robustness sweep: crashes, slow
  audits and site-wide high findings, flagged for review. The replay workflow gains a
  `config` input so either candidate list can be build-checked at one commit. Nothing is
  drawn until Addendum 5 is signed. No behaviour changed.
- **First verdicts in the evidence ledger.** B judged the 14 blocking findings from the
  1.7.0 pilot (electron/website `273491c35a`, a new page whose language links and hreflang
  alternates point to translations that 404 on the live site) `true_regression`, by a live
  site check. `bench/summary.md` from the pilot now reads frequency 1 of 40 commits and
  precision 14 of 14, still inconclusive under the pre-registered 20 verdicts; all 14 come
  from one commit. No behaviour changed.
- **Seeded recall on 1.7.0, both runs.** `bench/seeded/first-run-1.7.0/` is the first run
  (31 of 33 critical and high mutations caught, 93.9%), `bench/seeded/` the re-run after the
  duplicate-title targeting fix (33 of 33, 100%). The harness changed between them, after the
  first run's data was seen, so both are kept. Controls passed 5 of 5 in each. The rating
  mutation, reported apart, was caught 3 of 5 times in both: "4.7" appears as a version
  number on the two sites where it was missed. The first run's files were committed by
  mistake in #61 at `bench/seeded/`; they move to their own folder here.
- **Replay pilot on 1.7.0, and one ledger row per blocking finding.** The 2-repository
  pilot re-ran on the frozen 1.7.0 (`bench/replay/pilot-1.7.0/`): all 42 commits built and
  were audited, 40 comparisons, one electron/website commit failed the gate with 14 blocking
  findings (7 `S1-BROKEN-LINK`, 7 `S1-HREFLANG-BROKEN`, all language versions of a new page),
  which now await a verdict in `bench/ledger.csv`. `verify_helper.py` keyed ledger rows by
  rule and page, so those 14 became 2; the key now includes the evidence. `bench/summary.md`
  is regenerated from the 1.7.0 pilot. No behaviour changed.
- **Seeded recall: the duplicate-title mutation only adds a duplicate.** The page given a
  copied title must now have a unique title itself. In the 1.7.0 seeded run it twice
  landed on a page already in a duplicate group, so the mutation ended one pair while
  making another, and the gate read that as the old finding changed (#60, logged rather
  than fixed while 1.7.0 is frozen). Changed after that run, so the re-run's recall is
  reported next to the first one. No behaviour changed.
- **The benchmark is re-frozen on 1.7.0 (Addendum 3, signed by SurendharVr).** The replay and
  seeded harnesses and their workflows now require sitemend 1.7.0, and data from 1.6.0 is
  superseded. facebook/relay and typescript-eslint/typescript-eslint replace ionic-docs and
  trpc, whose builds could not be fixed within Addendum 2's rules; unocss keeps its fixed
  build command. Addendum 3 records the pick rule and every candidate's outcome. The seeded
  rating mutation is reported apart from the pooled recall, because its rule was fixed
  after the test showed it missed. No behaviour changed.

## 1.7.0 - 2026-10-17

The example workflows and README pin `@v1.7.0`. A minor release under the stability policy,
because one rule changes which findings it emits: `S5-SCHEMA-UNSUPPORTED-CLAIM` (decimals
in a claim, below). The rest are a crash fix (#51) and benchmark tooling outside the package.

- **An audit no longer crashes on a malformed URL (#51).** A URL whose host starts with
  `[` but is not a valid IPv6 literal (`http://[x`, common in minified CSS and JS) made
  `urlsplit` raise and stopped the whole audit. The replay benchmark hit it on
  electron/website, typescript-eslint and react-navigation. Such a URL is now treated as
  unresolvable: not a page of the site, and an hreflang alternate that names one is
  reported as broken, as any unresolvable alternate is.
- **`S5-SCHEMA-UNSUPPORTED-CLAIM` no longer corroborates a decimal from stray digits.** A
  rating of `"4.7"` was split into `4` and `7`, which every site contains, so a rating the
  site never shows passed. Decimal and grouped numbers now stay whole and must appear as
  that number in the page's visible text. Found by the seeded recall test. This changes
  which findings are emitted, so it ships in a minor release.
- **Seeded recall harness fixes.** A repository whose build fails is now recorded as
  `build_failed` with its own column in `recall.md`, not as a sitemend tool failure, which
  Addendum 1 reserves for audits sitemend cannot complete. Mutations no longer target
  404, error or thank-you pages (sitemend's own `is_utility` test): the first seeded run
  put the rating mutation on `/404.html`. No behaviour changed.
- **Seeded-regression recall for the benchmark.** `bench/seeded/seeded.py` builds each of
  the first 5 pre-registered repositories once, applies 10 known regressions one at a time
  to a copy of the built output (canonical removed, noindex added, canonical and sitemap on
  a preview host, `Disallow: /`, a linked page deleted, title removed, one-way hreflang,
  duplicate title, unsupported rating markup), each declaring the rule it must trigger,
  and checks the gate against the unmutated build. An unmutated control must pass. Writes
  `results.csv` and a recall table by mutation type; the manual `seeded` workflow runs it
  on Ubuntu. No behaviour changed.
- **Evidence ledger and summary for the benchmark.** `bench/verify_helper.py` adds one
  `bench/ledger.csv` row per blocking finding from the replay and prints its evidence (the
  finding, how each page's crawl record changed from base to head, robots.txt and sitemap
  state, and the GitHub compare link); it never writes a verdict. `bench/summarize.py`
  writes `bench/summary.md`: frequency per commit and precision per finding, kept apart,
  precision by rule, tool failures with their reasons, and runtime median and 90th
  percentile. `replay.py` now also writes `builds.csv`, one row per commit with the reason
  for any failure. `bench/summary.md` is generated from the pilot. No behaviour changed.
- **Replay pilot results and a tool-failure rule.** `bench/replay/pilot/` holds the Ubuntu
  pilot (2 repositories x 20 commits): vuejs/docs built and audited all 21 commits and all
  20 comparisons passed; electron/website built all 21 but sitemend 1.6.0 crashed auditing
  each one (#51). The pre-registration gains a dated addendum, decided before the full run:
  1.6.0 stays frozen, #51 waits until the benchmark report is published, and failed audits
  are reported as tool failures. No behaviour changed.
- **Replay harness for the benchmark.** `bench/replay/replay.py` builds each pre-registered
  repository's last N first-parent commits before the cutoff, audits every build with the
  frozen sitemend (it refuses any version but 1.6.0) and runs the gate on each consecutive
  pair, writing `bench/replay/results.csv`. Builds are cached per commit, a failed build is
  recorded as skipped rather than as a pass or a fail, and `--pilot` runs 2 repositories x
  20 commits. `bench/replay/repos.json` holds the 11 repositories from the pre-registration.
  The manual `replay` workflow runs it on Ubuntu, one repository per job, and uploads each
  job's results and audits. Not part of the package. No behaviour changed.
- **Pre-registration for the replay benchmark.** `bench/PREREGISTRATION.md` fixes, before any
  data exists, the frozen version (1.6.0, `badbb38`), the 11 repositories, the commit range
  (last 50 commits before 2026-10-01), the pass/fail thresholds and the decision rules.
  Signed off by SurendharVr and merged as `5899d56` before any replay run. `MANIFEST.in`
  keeps `bench/` out of the sdist. No behaviour changed.

## 1.6.0 - 2026-10-17

The example workflows and README pin `@v1.6.0`. This is the first release under the stability
policy, and a minor one because waivers change which findings fail the gate. No rule,
threshold or severity changed.

- **Per-finding waivers.** A `.sitemend-waivers.json` names deliberate exceptions, each with
  one exact rule ID, a page-path pattern, a required reason and an optional expiry date. A
  finding it covers no longer fails the regression gate or `--fail-on`, but it stays in
  `findings.json` and the report, and the PR comment lists it under "Waived" with its
  reason. Waivers that cover nothing are listed as unused, and expired ones as expired. A
  malformed file, a pattern that matches every page or a missing reason fails the run.
  New: the Action's `waivers` input (default `.sitemend-waivers.json`, read from the PR)
  and `--waivers PATH` on `audit`, `verify` and `check`. This changes which findings fail
  the gate, so under the stability policy it ships in a minor release (1.6.0).
- **A stability policy for the gate.** `RELEASING.md` now says what each kind of release
  may change: patches never change which findings are emitted or their severity, any rule,
  threshold or severity change is a minor release whose entry names the affected rule IDs,
  and the Action inputs, `findings.json` shape and CLI flags change only in a major
  release. The README's Action section summarizes it. No behaviour changed.
- **The README's test count is checked.** It said 189 tests while the suite ran 241. A test
  now compares it with the runner's own count, so adding or removing a test without
  updating the README fails CI. No behaviour changed.

## 1.5.2 - 2026-10-16

The example workflows and README pin `@v1.5.2`. The three crawler fixes came out of scanning 20
open-source docs sites, where they made sitemend report pages as missing that serve 200:

- **A capped http crawl no longer calls hreflang or canonical targets it never reached
  broken.** `--max-pages` already kept uncrawled URLs out of `S1-SITEMAP-ORPHAN` and
  `S1-BROKEN-LINK`, but not `S1-HREFLANG-BROKEN` (high) or `S1-CANONICAL-BROKEN`
  (critical). A 50-page crawl of biomejs.dev reported 241 high hreflang findings for
  language pages that all serve 200. A canonical that names another, uncrawled page is
  still reported, as `S1-CANONICAL-CROSS`, because that much is measured.
- **The http crawl follows hreflang alternates and the canonical**, as search engines do.
  A language version nothing linked to and the sitemap omitted (pnpm.io's `/it`) was
  reported as high `S1-HREFLANG-BROKEN` even on a crawl that finished.
- **The crawler asks for HTML the way browsers and Googlebot do** (`Accept: text/html,…`).
  turborepo.dev answers the generic `*/*` on its home page with `text/markdown`
  (`Vary: Accept`), so the crawl skipped `/` as non-HTML and reported it as a broken link
  and a sitemap orphan.

## 1.5.1 - 2026-10-16

- **The Action can be published to GitHub Marketplace.** Its description was 193
  characters, and Marketplace refuses anything from 125 up, so 1.5.0 could not be listed.
  It is now 107 characters, and a test keeps it under the limit. No behaviour changed;
  the examples pin `@v1.5.1`.

## 1.5.0 - 2026-10-16

- **Judgement calls never fail a pull request.** Findings `audit.py` marks below high
  confidence (`S3-CANNIBALIZATION`, `S3-NEAR-DUPLICATE`) are listed in the PR comment as
  advisory and no longer fail `sitemend verify` or `--fail-on`. Adding a sibling reference
  page (`hx-patch` next to `hx-get`) used to fail the check with three high findings. The
  findings themselves, their severity, the report and the gates are unchanged.
- **Large sites audit in seconds, with the same findings.** The near-duplicate and
  cannibalization checks no longer compare every pair of pages. They compare only pairs
  that could reach the threshold, chosen by filters that can't drop a qualifying pair
  (MinHash banding and prefix filtering). On a generated 10,000-page site the audit went
  from 544 s to 10 s with identical output.
- **A GitHub Action: `uses: SurendharVr/sitemend@v1.5.0`.** It checks out the pull request
  and its base branch, runs your `build-command` in both, audits the built `site-dir`, and
  fails only on what the PR broke, with one updated PR comment. The README has build
  recipes for Next.js (static export), Astro, Docusaurus, SvelteKit, VitePress, Eleventy
  and Hugo. Before this, the example workflow audited the unbuilt checkout, which for a
  framework site meant 0 pages.
- **Preview deploys.** `examples/github-action/preview.yml` runs on a successful Vercel or
  Netlify preview, compares it with production, and comments on the PR the commit belongs
  to: the path for server-rendered sites.
- **`sitemend check HEAD --base BASE`**: the comparison the Action runs, as one command for
  any CI, with folders or URLs.
- **`SITEMEND_HTTP_HEADERS`** sends extra request headers in http mode, such as a Vercel
  protection-bypass secret. It is read from the environment only.
- `release.yml` now runs on `vX.Y.Z` tags only, so the moving `v1` tag publishes nothing.

## 1.4.3 - 2026-10-16

- **`--render` timeout is configurable, and the CI render job no longer flakes.** The
  per-page Chrome timeout (30 seconds) can be raised with `SITEMEND_RENDER_TIMEOUT`; the CI
  render job sets 90. Chrome now starts with `--disable-background-networking
  --disable-component-update`, so a fresh profile does not spend launch time on its own
  update fetches. The render test reports the render error (for example "render timed out
  after 30s") instead of a `KeyError`.
- **The regression gate catches what it missed.** A new finding with the same rule on a
  page that already had one (a different broken link, a different wrong canonical) is new,
  not "changed", and a finding that gets worse (high to critical) fails the gate.
  `sitemend verify` reads `--baseline` before auditing, so the README's own example, which
  keeps the baseline in the default `--out` folder, no longer compares it with itself.
- **No more empty http audits.** A start URL that redirects to another host (apex to `www`,
  `http` to `https`) is crawled where it lands, and a crawl of 0 pages is an error instead
  of a report full of sitemap URLs that "do not exist".
- **Fewer false high and critical findings.**
  - URLs the crawl never reached because of `--max-pages` are no longer reported as sitemap
    orphans or broken links.
  - Absolute links to the site's own origin count as internal links.
  - Auditing a dev server or preview deploy no longer flags every production canonical as
    off-site.
  - `skype:`, `geo:`, `ftp:` and other non-http links are not broken links.
- **Rules applied as documented.**
  - Gate A now withholds schema findings on non-indexable pages.
  - A sitemap listing a blocked page by its clean URL is the critical contradiction.
  - robots.txt groups for the same agent are combined (RFC 9309).
- **Hardening.**
  - The http crawl reads only the headers of linked non-HTML files, and a page whose body breaks off mid-transfer is skipped instead of stopping the crawl.
  - Lighthouse keeps Chrome's sandbox unless running as root or with `SITEMEND_NO_SANDBOX=1`.
  - On Windows, a robots.txt `Sitemap:` path can no longer read files outside the audited folder.

## 1.4.2 - 2026-10-15

- **A preview host in the whole sitemap no longer becomes the base URL.** fs mode infers
  the production origin when `--base-url` is not given, and took the first sitemap URL.
  A deploy that leaks `*.vercel.app` into every sitemap entry while its canonicals still
  name production got the preview as its base, and every correct canonical was reported
  as critical `S1-CANONICAL-OFFSITE`. Inference now skips preview and placeholder hosts
  in favour of the canonical or robots.txt `Sitemap:` origin, falling back to the first
  URL when nothing else is on offer. The leak itself is still the critical
  `S1-HOST-MISMATCH`.

The example GitHub Action now pins `sitemend==1.4.2`. The README links a benchmark write-up
(`docs/benchmark-2026-10.md`) and a live demo PR.

## 1.4.1 - 2026-10-15

**False positives found by a 20-site benchmark, fixed.** sitemend 1.4.0 was run against
20 open-source framework and docs sites and every finding was checked by hand. These
were wrong or overstated:

- **Meta-refresh stubs were judged as pages.** docs.astro.build's home is
  `<meta http-equiv="refresh" content="0;url=/en/getting-started/">`: it got a critical
  missing title and viewport plus H1, description, canonical, lang and OG findings, and
  the http crawl stopped at 1 page. A refresh with a delay of 0 or 1 is now a redirect:
  followed in http mode (alias plus one redirect hop), an alias of its target in fs mode,
  and never judged as a page.
- **Sitemaps declared in robots.txt were reported missing.** Discovery now reads the
  robots.txt `Sitemap:` URLs (path only, on the audited origin), then `/sitemap.xml`,
  then `/sitemap-index.xml`, and follows `<sitemapindex>` children (up to 50 files), in
  fs and http mode. A sitemap that exists but is not declared is `S1-ROBOTS-NO-SITEMAP`,
  not `S1-SITEMAP-MISSING` (astro.build, docs.astro.build, starlight.astro.build,
  biomejs.dev). A file without `<urlset>` or `<sitemapindex>` is not a sitemap.
- **`S2-UNCRAWLABLE-LINK` was wrong on 3 of the 5 sites it flagged.** Elements with
  `aria-hidden="true"` or `tabindex="-1"` are skipped (react.dev); so is a `#` entry in a
  list whose other links are `#fragment`s, a table of contents (react.dev). A bare
  `href="#"` without `onclick` now counts only in prose (`p`, `li`, `td`, `dd` in
  `main`/`article`, or the body when there is neither), not inside `nav`, `figure` or
  `form`, which keeps demo components out (tailwindcss.com, ui.shadcn.com). The two real
  hits stay flagged (pnpm.io, jestjs.io). Evidence is now the opening tag without `class`
  plus the link text, so the triggering attribute is visible.
- **`S1-HOST-MISMATCH` on a deliberate canonical host.** When every published URL agrees
  on one host and only the crawled host differs (tauri.app, whose URLs all name
  v2.tauri.app), it is one medium finding, "served on X, but every URL names Y; check X
  redirects to Y", and the per-page critical `S1-CANONICAL-OFFSITE` findings fold into
  it. It stays critical when that host is a preview host.
- **Severities.** `S1-ROBOTS-MISSING` high → low (Google treats a 404 robots.txt as
  allow-all); `S1-SITEMAP-MISSING` high → medium.

The example GitHub Action now pins `sitemend==1.4.1`, so a copied workflow gets these fixes.

## 1.4.0 - 2026-10-15

Three checks for deploys that break SEO:

- **`S1-HOST-MISMATCH`:** canonicals, `og:url`, sitemap `<loc>`s, the robots `Sitemap:`
  line and the base URL name different hosts. Critical when one is a hosting platform's
  preview host (`*.vercel.app`, `*.netlify.app`, `*.pages.dev`...) that is not the base.
- **`S1-SOFT-404`:** http mode requests one random path that cannot exist and reports a
  200 answer (SPA catch-all, redirect to home).
- **`S2-UNCRAWLABLE-LINK`:** `href="#"`, `javascript:`, an `<a>` with a click handler
  but no href, or an `onclick` that sets `location` on a non-link. Menu toggles, back-to-top
  links and bare `<a>` breadcrumb items are not reported.

**The example GitHub Action is now a ratchet.** It audits the PR's base branch as the
baseline and fails only on critical or high findings the PR adds, so a site with an
existing backlog can adopt it without every PR going red. It posts one PR comment,
updated on each push, listing new and closed findings with their pages and evidence.
`verify` now also writes `verify.md` next to `verify.json` for that comment. The example
pins `sitemend==1.4.0`, the first release with `verify.md`.

`X-Robots-Tag: noindex` on the production homepage was already the critical
`S1-NOT-INDEXABLE`; a test now pins that.

**Positioned as SEO regression tests for repo-based sites.** The README gains a category
line, a Common questions section and a large-site limitation. The PyPI description,
keywords and Testing/QA classifiers, and the plugin and marketplace descriptions, use
the same wording. A stale README claim is fixed: the demo comparison said sitemend did
not check placeholder domains or Open Graph tags, and it does now.

## 1.3.0 - 2026-10-14

**Renamed everywhere to `sitemend`.** 1.2.1 renamed only the PyPI package and command;
this finishes the job. Breaking for anyone on the old names:

- **Skill and plugin:** `/sitemend`, installed as `sitemend@sitemend` from
  `SurendharVr/sitemend`. Remove a `seo-repair` plugin or `~/.claude/skills/seo-repair`
  copy, then install the new one.
- **Script:** `scripts/seo_repair.py` is now `scripts/sitemend.py`.
- **Environment variables:** `SEO_REPAIR_*` are now `SITEMEND_*`
  (`SITEMEND_NO_SANDBOX`, `SITEMEND_RENDER_TEST`, `SITEMEND_LIGHTHOUSE_TEST`).
- **Default output folder:** `./sitemend-out`. An old `seo-repair-out/` is still skipped
  by the crawler and still git-ignored, so a leftover report is never audited or committed.
- Crawler User-Agent is `sitemend-crawler/1.0`; the dashboard and report say sitemend.
- The GitHub Action example installs `sitemend==1.3.0` from PyPI instead of cloning a tag.
- PyPI keywords add `ai-seo` and `ai-agent`.

## 1.2.1 - 2026-10-14

First release on PyPI, as `sitemend`.

- **The PyPI package and command are now `sitemend`.** `pip install sitemend`, then
  `sitemend audit <folder|URL>`; the wheel's import package is `sitemend`. Nothing was
  ever published as `seo-repair`, so no install breaks. The Claude Code skill, plugin,
  scripts and `SEO_REPAIR_*` variables keep their names.

Fixes from reviewing 1.2.0:

- **Chrome keeps its sandbox on.** `--render` added `--no-sandbox` on every non-Windows
  OS. It is now added only when running as root, or with `SEO_REPAIR_NO_SANDBOX=1`.
- **A slash-less hreflang href is not a missing page.** `href="/en"` for the page `/en/`
  was reported "does not exist" in an http crawl (a folder crawl already aliased it).
  Case and file paths stay strict.
- **Reciprocal hreflang alternates are not duplicates.** en-GB and en-US pages with the
  same text were reported as a critical `S3-DUPLICATE-EXACT` and blocked Gate B. Pages
  that do not name each other are still reported.
- **The report says how many pages `--render` rendered**, and how many failed.
- **`pyproject.toml` uses the SPDX `license` form**, ahead of setuptools dropping the old
  one on 2027-02-18.
- **The render test now runs in CI** against Chrome on Ubuntu.
- **A second fixture, `examples/demo-site-intl/`**, plants one defect per 1.2.0 rule and is
  checked by a unit test.
- The 1.2.0 entry said "Fourteen new checks"; it is thirteen.
- 12 new tests (146 total, two opt-in).

## 1.2.0 - 2026-10-14

Closes the three biggest gaps found by comparing seo-repair with other SEO audit tools:
rule coverage, JavaScript rendering outside Claude Code, and distribution.

- **Thirteen new checks, all stage 1.** `S1-REDIRECT-CHAIN`, `S1-REDIRECT-LOOP`,
  `S1-MIXED-CONTENT`, `S1-SECURITY-HEADERS`, `S1-SITEMAP-LASTMOD-INVALID`,
  `S1-SITEMAP-LASTMOD-UNIFORM`, `S1-HREFLANG-INVALID`, `-BROKEN`, `-NO-SELF`, `-NO-RETURN`,
  `S1-JS-SHELL`, `S1-JS-DEPENDENT`, `S1-JS-HEAD-MISMATCH`. Redirects and headers need an
  http crawl and are silent in fs mode; security headers are only judged on an https
  origin, so a local dev server is never nagged. Alternates on another origin are not
  called broken: one crawl cannot see them. `rel=next/prev` is deliberately not checked
  (Google stopped using it). The demo site is unchanged: 24 findings.
- **`--render`: JavaScript rendering without Claude Code.** An http crawl can parse
  Chrome's post-JavaScript DOM (`chrome --headless --dump-dom`, no Playwright or
  Selenium) for up to `--render-limit` pages (default 50, ~5 s each). The raw HTML's word
  count and head are kept so the two can be compared. Verified on Windows against real
  Chrome; the opt-in test is `SEO_REPAIR_RENDER_TEST=1`.
- **A client-rendered shell is no longer reported as missing its H1.** On an unrendered
  page with an empty `#root`, the headings do not exist yet; `S1-JS-SHELL` says so instead.
- **`seo-repair` is installable.** `pyproject.toml` builds a wheel that ships the scripts
  and the dashboard template and installs a `seo-repair` command (`audit`, `verify`).
  CI builds it, installs it into a clean venv and audits the demo site through it.
  `.github/workflows/release.yml` publishes to PyPI on a `v*` tag via trusted publishing
  (one-time setup on pypi.org, see `RELEASING.md`). **Not yet published**; install with
  `pip install git+https://github.com/SurendharVr/seo-repair` until it is.
- **Python 3.9+.** The README said 3.8, which CI never tested and which is end-of-life.
- 38 new tests (134 total, two opt-in), including a threaded server that redirects
  `/a -> /b -> /c`, loops, and sends response headers, and a version-agreement test across
  `pyproject.toml`, `plugin.json` and `SKILL.md`.

## 1.1.0 - 2026-10-14

Two new checks, found by comparing against a plain prompt that noticed both and seo-repair
did not, and one dashboard bug found while regenerating the README screenshot.

- **`S1-PLACEHOLDER-DOMAIN` (high).** Canonicals, `og:url`, sitemap URLs or the robots
  `Sitemap:` line that use example.com/.org/.net, `localhost`, a reserved TLD (`.test`,
  `.invalid`, ...) or a template name like `yourdomain.com`. The base origin is inferred
  from those same URLs, so a site that was uniformly wrong looked consistent to every
  canonical check. Matching is on whole labels: `notexample.com` is not flagged.
- **`S3-OG-MISSING` (low).** An indexable page without `og:title`, `og:description` or
  `og:image`; the evidence names the missing ones. Noindex and 404-style pages are skipped.
- **The dashboard's BLOCKED pill had no styling since 1.0.1.** The class the script
  produced (`pill block`) did not match the stylesheet (`.pill.blocked`), so gates showed
  plain text instead of the red pill. A test now pins the class names. The README
  screenshot is regenerated.
- The demo site now reports 24 findings (1 critical, 7 high, 7 medium, 9 low): the two new
  checks fire on it by design (`demo.example.com`, no Open Graph tags). `EXPECTED.md`, the
  README output and the CI required-id list are updated. 11 new tests (96 total).

## 1.0.5 - 2026-10-14

The last open finding from the 1.0.3 code review: `vitals.py` on Windows.

- **`vitals.py` no longer mis-parses page paths on Windows.** Lighthouse was started
  through `cmd.exe` with an unquoted URL, so `/search?q=a&lang=en` was measured as
  `/search?q=a` and the rest of the command line (including `--output-path`) ran as a
  second command. Arguments that `cmd.exe` would re-parse are now quoted; a double quote,
  or a `%` that could start a `%VAR%` expansion, is refused with a clear error. Reproduced
  and fixed against real Lighthouse and Chrome.
- **A Lighthouse timeout now kills the whole process tree.** Only the shell was killed,
  so node and Chrome kept running. The wait after the kill is bounded, so a survivor
  cannot hang the audit.
- 6 new tests (85 total): five unit tests, and one opt-in test that runs real Lighthouse
  (`SEO_REPAIR_LIGHTHOUSE_TEST=1`; CI has no Chrome, so it is run by hand).

## 1.0.4 - 2026-10-14

Fixes from a code review of 1.0.3. Each has a regression test that failed before the fix.

- **A site that blocks itself no longer reads as clear.** With `Disallow: /` in robots.txt
  and an empty sitemap, the homepage was filed as a deliberate exclusion and Gate A said
  every crawled page was indexable. A robots-blocked homepage is now `S1-NOT-INDEXABLE` at
  critical and Gate A reads BLOCKED.
- **The heading-skip evidence quotes the right heading.** `S2-HEADING-SKIP` showed the
  first H4 after the first H2, which was fine, instead of the heading that skipped.
- **A lookalike domain no longer passes as the site's own canonical.** A canonical on
  `example.community` was accepted for `example.com` because the check was a string
  prefix. It now compares scheme and host.
- **Review authors are matched as whole words, in any script.** "Ann" was found inside
  "channel", short names were skipped, and non-Latin names were never checked. Names under
  two characters are ignored. Crawls gain a `visible_text` field; an older `crawl.json`
  without it skips the check.
- **A clean schema run shows Stage 5 as assessed.** It was reported as not measured when
  the check ran and found nothing (`findings.json` meta now has `schema_checked`). The
  report's re-run block now prints `seo_repair.py` commands instead of ones that passed a
  URL to `crawl.py --root`.
- **A failed regression gate is reported as a gate result.** `verify` printed
  "verify.py failed:" and exited as if the script had crashed when the gate failed. The output
  folder now writes its own `.gitignore`, so `audit .` cannot leave a crawl to commit.
- **An http redirect is no longer a second page.** `/about` redirecting to `/about/` was
  stored twice, which raised `S3-DUPLICATE-EXACT` at critical. The target is stored once
  and the requested path is recorded as an alias.
- 20 new tests (79 total).
- Not changed: `vitals.py` still runs Lighthouse through `shell=True` on Windows, so a page
  path containing `&` is mis-parsed (needs Windows + Chrome to verify).

## 1.0.3 - 2026-10-14

Fixes a bug in 1.0.2's CLI and adds a CI example.

- **A re-run no longer audits its own last report.** With `--out` inside the audited
  folder (the default for `audit .`), the second run crawled the first run's
  `dashboard.html` and the demo site went from 22 findings to 29. `seo-repair-out` is now
  excluded from the crawl and ignored by git.
- **GitHub Action example** in `examples/github-action/seo-repair.yml`: audits on every
  pull request and fails the check on a critical finding. Run end to end on GitHub:
  checkout, install, audit (failed on the demo site's critical finding, as intended)
  and the report uploaded as an artifact even though the audit step failed.
- 1 new test (59 total).

## 1.0.2 - 2026-10-14

The tool now runs without an agent, and two false positives found on the first real-site
run are fixed. Against a real 13-page catering site, findings went from 14 to 3, one of
them real.

- **`scripts/seo_repair.py`: the whole pipeline in one command.** `audit` chains crawl,
  schema check, audit, report and dashboard for a folder or a URL; `verify` diffs a new
  audit against an earlier `findings.json`; `--fail-on` turns open findings into a CI
  exit code. Needs no agent.
- **`S5-SCHEMA-REQUIRED-MISSING` no longer fires on `@id` references.** A nested
  `{"@id": ".../#business", "name": ...}` on a Menu or Service page was reported as a
  FoodEstablishment missing its address, though the full node is defined on another
  page. A property defined for that `@id` anywhere on the site now counts. A business
  with no address anywhere is still flagged.
- **`S3-CANNIBALIZATION` ignores template words.** Terms on at least 35% of pages
  (minimum 4) are dropped before comparing, so five menu pages sharing "catering menu
  set dish" no longer flag each other ten ways. Two pages chasing the same
  distinguishing terms are still reported. Ceiling: a family of 5+ near-identical
  pages on a 13-page site reads as a template.
- README leads with the outcome, says who it is for, and has a "Works with" section.
- 6 new tests (58 total). Demo-site output is unchanged: 22 findings.

## 1.0.1

Two http-mode defects, both found by scoring the tool against its own demo fixture
alongside Lighthouse rather than by reading the code.

- **The http crawl now seeds its frontier from `sitemap.xml`.** It only followed links
  before, so a page that was unlinked *and* listed in the sitemap — the population most
  likely to have an indexing problem — was never fetched. It was then reported as
  `S1-SITEMAP-ORPHAN`, whose message is "listed in sitemap.xml does not exist in the
  crawl", while actually serving a healthy 200. Anyone acting on that went looking for a
  dead URL and found a working page. Seeding from the sitemap is what Screaming Frog and
  Sitebulb do by default, and it makes the frontier match what a search engine discovers.
- **URLs returning 4xx/5xx are no longer recorded as pages.** They are kept in the crawl's
  `skipped` list with their status. Admitting them put them in the alias index, which
  would have silenced `S1-SITEMAP-ORPHAN` for genuinely dead sitemap entries and
  `S1-BROKEN-LINK` for links pointing at them.
- **Gate B has a third state, `NOT ASSESSED`.** It was a pure findings-presence test, so
  in a mode that cannot enumerate pages it turned absence of evidence into a pass —
  printing "no orphan or duplicate pages" on a site with two orphans, and unblocking
  schema work on pages that were merge candidates. fs mode still reports `CLEAR`, since
  walking the filesystem can genuinely prove absence; `BLOCKED` outranks both. Same
  principle as the report's per-stage `assessed` state. The dashboard paints the new state
  neutral — it previously mapped everything that was not `BLOCKED` to the green pill.
- 7 new tests (52 total), including a threaded-HTTP-server fixture pinning the seeding
  behaviour and the dead-sitemap-URL finding it must not silence.

## 1.0.0

First public release.

- Crawler with fs and http modes, handling both clean-URL directories
  (`about/index.html` → `/about/`) and flat files (`services.html`). Build output
  (`dist/`, `node_modules/`, …) is excluded — without that, a `dist/` copy makes every
  real page look like duplicate content.
- Rules engine across five stages, with three ordering gates enforced in code rather
  than only documented.
- Structured-data claim corroboration: checks whether markup asserts content the page
  never shows, including a stricter per-author check for review markup.
- Lighthouse integration for lab Core Web Vitals, tagged as lab and never as field data.
- Regression gate diffing a re-crawl against a baseline.
- Markdown report plus a self-contained HTML dashboard.
- 45 tests and an end-to-end run against a seeded demo site.

Calibration notes, since the thresholds are deliberate rather than arbitrary: titles are
only flagged past 65 characters (50–60 is a target, not a cliff); a `noindex` on a 404 or
a robots-disallowed page is reported as a deliberate exclusion rather than a defect;
findings sharing identical evidence across pages are grouped into one, because a heading
skip in a shared footer is one fix and not five; and cannibalization is suppressed on a
pair already reported as duplicates, since it is the same root cause.
