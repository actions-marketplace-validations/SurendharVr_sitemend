"""task9.py -- Task 9 of the evidence plan: the prospective run (bench/PREREGISTRATION-task9.md).

sitemend 1.9.1 gates real pull requests on sites it was never tuned on, as they are opened.
Nothing here posts to, or contacts, a drawn repository (section 2.3).

The draw, once, before the window (section 2.2):
  python bench/task9/task9.py draw --per-stack 12   # eligibility in draw order -> candidates.json, draw.csv
  python bench/task9/task9.py build-check --repo o/n  # the workflow, one job per candidate -> builds-o__n.csv
  python bench/task9/task9.py select --builds b1.csv b2.csv ...  # -> repos.json, window.json
Commit repos.json, draw.csv and window.json the same UTC day; the window opens at 00:00
UTC the next day.

The window (section 3), driven by .github/workflows/task9.yml every 15 minutes:
  poll     folds in every finished check of earlier runs, polls GitHub, writes the next
           state to the data branch and the jobs to run
  check    one job: a PR head in folder or url mode, or a production audit
A poll never waits for this run's checks, so a slow check delays only its own result.

After it (sections 4 and 5):
  python bench/task9/task9.py ledger --data DIR       # pre-fill both ledgers; B gives verdicts
  python bench/task9/task9.py ledger --data DIR --second-look
  python bench/task9/task9.py report --data DIR       # -> summary.md

Every GitHub call goes through api() (live) or sample.gh() (cached, for the draw), so the
tests replace them and never reach GitHub or a drawn site.
"""
import argparse
import csv
import datetime
import glob
import hashlib
import html
import io
import ipaddress
import json
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import zipfile
from urllib.parse import quote, urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.dirname(HERE)
ROOT = os.path.dirname(BENCH)
sys.path[:0] = [os.path.join(BENCH, "replay"), os.path.join(BENCH, "sample"), BENCH]
import replay          # noqa: E402
import sample          # noqa: E402
import verify_helper   # noqa: E402

FROZEN = "1.9.1"                     # Addendum 1
DRAW_DATE = "2026-10-22"             # section 2.2
UNTIL = "2026-10-23T00:00:00Z"       # the end of the draw date
SINCE = "2025-10-23T00:00:00Z"       # 12 months before it
PRS_FROM = "2026-08-27"              # 8 weeks before it, inclusive
MIN_PRS = 8
PER_STACK, MIN_FLAGGED, MAX_TOTAL = 6, 10, 40
B_OWNER = "surendharvr"
PROD_WAIT = 2 * 3600                 # section 3.4
AUDIT_TIMEOUT = 3600                 # section 3.5
BUILD_TIMEOUT = 1800                 # as in the replay
MAX_TRIES = 3                        # a job that never reports back, three times, is a tool failure
IN_FLIGHT = 4 * 3600                 # a scheduled job is waited for this long (its timeout is 200 min)
COLLECT_BACK = 24 * 3600             # runs created this long ago are still looked at for results
WORKFLOW = "task9.yml"
SEED = 20261017
# The hosting platforms' per-deploy hostnames, as audit.py names them.
PREVIEW_HOSTS = (".vercel.app", ".netlify.app", ".pages.dev", ".onrender.com",
                 ".herokuapp.com", ".web.app", ".firebaseapp.com", ".amplifyapp.com",
                 ".fly.dev", ".surge.sh")
RESULT_FIELDS = ["repo", "pr", "head_sha", "base_sha", "mode", "outcome", "blocking",
                 "checked_at", "bot", "reason"]
PROD_FIELDS = ["repo", "audited_at", "previous_at", "branch_sha", "merged_prs", "new_critical_high",
               "outcome", "reason"]
COUNTED = ("pass", "fail")


def now():
    return datetime.datetime.now(datetime.timezone.utc)


def stamp(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(s):
    return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)


def api(path, raw=False, token_env=None):
    """The live GitHub API, parsed (or raw bytes). No cache: the window watches what is
    happening now. token_env names an environment variable whose token to use instead of
    GH_TOKEN (this repository's own Actions API needs the job's token)."""
    env = dict(os.environ, GH_TOKEN=os.environ[token_env]) if token_env and os.environ.get(token_env) else None
    r = subprocess.run(["gh", "api", path], capture_output=True, env=env)
    if r.returncode != 0:
        raise RuntimeError("gh api {0}: {1}".format(path, r.stderr.decode("utf-8", "replace").strip()[-300:]))
    if raw:
        return r.stdout
    return json.loads(r.stdout) if r.stdout.strip() else None


def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path, doc):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True)
        fh.write("\n")


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path, fields, rows):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows({k: r.get(k, "") for k in fields} for r in rows)


def slug(repo):
    return repo.replace("/", "__")


# ---------------------------------------------------------------- previews

def public_https(url):
    """Whether url is https on a public hostname. A preview URL comes from a deployment,
    a status or a comment that strangers control, and the url check crawls it and commits
    what it finds: an internal address (the runner's metadata service, a private range)
    must never be crawled. The hostname is resolved too, so a public name pointing at a
    private address is refused. ponytail: DNS can change between this check and the crawl."""
    parts = urlsplit(url or "")
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        return False
    try:
        ipaddress.ip_address(host)
        return False                        # an address, not a name: no preview is served so
    except ValueError:
        pass
    try:
        addrs = {a[4][0] for a in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)}
    except OSError:
        return False
    return bool(addrs) and all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addrs)


def is_preview(label, url, home=None):
    """Whether a deployment or status names a preview deploy: its environment or context
    says preview, or its URL is on a per-deploy host (PREVIEW_HOSTS), and it is not
    production. REGRESSION from the Task 9 draw: any deployment not called "production"
    counted, so a release deployment to PyPI (https://pypi.org/p/...) flagged a preview,
    and a GitHub Pages deployment ("github-pages", the live site) would have been crawled
    as the PR's preview and compared with itself. A URL on the production site's own host
    is never a preview."""
    host = (urlsplit(url or "").hostname or "").lower()
    home_host = (urlsplit(home if home and "://" in home else "https://" + (home or "")).hostname or "").lower()
    if not host or re.search(r"production|github-pages", label or "", re.I) or (home_host and host == home_host):
        return False
    return bool(re.search(r"preview", label or "", re.I)) or host.endswith(PREVIEW_HOSTS)


def preview_url(get, repo, sha, pr=None, ok=None, home=None):
    """A preview deploy of sha, as the host reported it: a successful deployment, or a
    successful commit status, that is_preview accepts, or (with pr) a bot comment on the
    PR that names the commit and links a per-deploy hostname. None when there is none.
    Only a public https URL counts (public_https, or ok in tests); home is the production
    homepage, never taken for a preview. ponytail: a bot comment that does not name the
    commit is ignored, since it may be about an older head."""
    ok = ok or public_https
    for d in get("repos/{0}/deployments?sha={1}&per_page=20".format(repo, sha)) or []:
        env = d.get("environment") or ""
        for s in get("repos/{0}/deployments/{1}/statuses?per_page=20".format(repo, d["id"])) or []:
            url = s.get("environment_url")
            if s.get("state") == "success" and is_preview(env, url, home) and ok(url):
                return url
    for s in get("repos/{0}/commits/{1}/statuses?per_page=100".format(repo, sha)) or []:
        url = s.get("target_url") or ""
        if (s.get("state") == "success" and re.search(r"deploy|preview", s.get("context") or "", re.I)
                and is_preview(s.get("context"), url, home)
                and "github.com" not in (urlsplit(url).hostname or "") and ok(url)):
            return url
    if pr is not None:
        for c in get("repos/{0}/issues/{1}/comments?per_page=100".format(repo, pr)) or []:
            body = c.get("body") or ""
            if (c.get("user") or {}).get("type") != "Bot" or sha[:7] not in body:
                continue
            for url in re.findall(r"https://[^\s)\"'<>\]|]+", body):
                if (urlsplit(url).hostname or "").endswith(PREVIEW_HOSTS) and is_preview("", url, home) and ok(url):
                    return url
    return None


# ---------------------------------------------------------------- the draw (section 2.2)

def prior_ranks():
    """Per stack, the last draw rank the sample and the sweep looked at."""
    out = {}
    for p in (os.path.join(BENCH, "sample", "draw.csv"), os.path.join(BENCH, "sweep", "draw.csv")):
        for r in read_csv(p):
            out[r["stack"]] = max(out.get(r["stack"], 0), int(r["rank"]))
    return out


def excluded_here():
    """2.1, beyond Addendum 5's list (which sample.excluded applies): the 15 benchmark
    repositories and every repository the sweep built or audited."""
    ex = {e["repo"].lower() for e in read_json(os.path.join(BENCH, "replay", "repos.json"), [])}
    ex |= {r["repo"].lower() for r in read_csv(os.path.join(BENCH, "sweep", "sweep.csv"))}
    return ex


def benchmark_owners():
    """Addendum 2, part 2: the owners of the 15 benchmark repositories."""
    return {e["repo"].split("/")[0].lower() for e in read_json(os.path.join(BENCH, "replay", "repos.json"), [])}


def exclusion(repo, extra, owners):
    """Why 2.1 (with Addendum 2) excludes repo before any lookup, or None."""
    owner = repo.split("/")[0].lower()
    if repo.lower() in extra or owner == B_OWNER:
        return "excluded: the benchmark, the sweep or B's own"
    if owner in owners:
        # A translation of the same docs is, for this run, a site the rules were tuned on.
        return "excluded: its owner also owns a benchmark repository (Addendum 2)"
    return None


def merged_prs(repo, branch):
    """PRs merged into branch in the 8 weeks before the draw date (search API, cached)."""
    q = "repo:{0} is:pr is:merged base:{1} merged:{2}..{3}".format(repo, branch, PRS_FROM, DRAW_DATE)
    doc = sample.gh("search/issues?q={0}&per_page=100".format(quote(q))) or {}
    return doc.get("total_count", 0), [i["number"] for i in doc.get("items", [])]


def preview_flag(repo, numbers, home=None):
    """The first preview found on those merged PRs, or None (recorded, not required)."""
    for n in numbers:
        pull = sample.gh("repos/{0}/pulls/{1}".format(repo, n)) or {}
        sha = (pull.get("head") or {}).get("sha")
        url = sha and preview_url(sample.gh, repo, sha, n, home=home)
        if url:
            return url
    return None


# Task 9 Addendum 5: the size slices a second-frame search starts from, in bytes. GitHub's
# code search indexes files under 384 KB, so the last slice ends there.
SLICES = ((0, 1000), (1001, 3000), (3001, 10000), (10001, 384000))
CAP = 1000                             # the most results GitHub returns for one query


def search_slices(get, query, slices=SLICES):
    """Addendum 4, part 2, with Task 9 Addendum 5: one code search split by file size so
    that no slice reaches the cap. A slice whose total_count is CAP or more is halved at its
    midpoint and searched again; a one-byte slice still at the cap keeps what GitHub returns
    and is marked capped. Returns (items, slices), every slice recorded with its
    total_count and incomplete_results, the split ones included."""
    todo, items, recs = list(slices), [], []
    while todo:
        lo, hi = todo.pop(0)
        q = "{0} size:{1}..{2}".format(query, lo, hi)
        path = lambda page: "search/code?q={0}&per_page=100&page={1}".format(quote(q), page)
        first = get(path(1))
        if first is None:
            raise RuntimeError("code search refused: " + q)
        total = first.get("total_count", 0)
        rec = {"query": query, "lo": lo, "hi": hi, "total_count": total,
               "incomplete_results": first.get("incomplete_results"), "split": False, "capped": False}
        if total >= CAP and lo < hi:
            mid = (lo + hi) // 2
            todo[:0] = [(lo, mid), (mid + 1, hi)]
            recs.append(dict(rec, split=True))
            continue
        got, page, last = list(first.get("items", [])), 2, first.get("items", [])
        while len(last) == 100 and page <= CAP // 100 and len(got) < total:
            last = (get(path(page)) or {}).get("items", [])
            got += last
            page += 1
        recs.append(dict(rec, capped=total >= CAP))
        items += [{"repo": i["repository"]["full_name"], "path": i["path"], "query": query,
                   "slice": "{0}..{1}".format(lo, hi)} for i in got]
    return items, recs


def paced(path):
    """sample.gh for code search, paced under its 10 requests a minute."""
    import time
    time.sleep(7)
    return sample.gh(path)


def cmd_frame2(args):
    """Addendum 4, part 2: the second frame, taken once and saved before any filtering."""
    get = getattr(args, "get", None) or paced
    for stack, queries, _, _ in sample.STACKS:
        path = os.path.join(getattr(args, "out", None) or HERE, "frame2-{0}.json".format(stack))
        if os.path.exists(path):
            print("kept", path, "(the frame is taken once)")
            continue
        items, slices = [], []
        for q in queries:
            got, recs = search_slices(get, q)
            items += got
            slices += recs
        write_json(path, {"taken_at": stamp(now()), "queries": queries, "slices": slices, "items": items})
        print(stack, len(items), "results,", sum(r["capped"] for r in slices), "capped slice(s) ->", path)
    return 0


def first_frame_repos():
    """Every repository in the first frame, any stack (Addendum 4, part 3)."""
    out = set()
    for stack, _, _, _ in sample.STACKS:
        with open(os.path.join(BENCH, "sample", "frame-{0}.json".format(stack)), encoding="utf-8") as fh:
            out |= {i["repo"].lower() for i in json.load(fh)["items"]}
    return out


def frame2_order(frame, first):
    """Addendum 4, part 3: the first frame's repositories left out, then sorted by name and
    shuffled with a fresh random.Random(SEED)."""
    return sample.draw_order([r for r in frame if r.lower() not in first])


def cmd_draw(args):
    # Addendum 5's rules with the draw date in place of the cutoff (2.2).
    sample.SINCE, sample.CUTOFF = SINCE, UNTIL
    second = getattr(args, "frame", 1) == 2
    after, extra, owners = ({} if second else prior_ranks()), excluded_here(), benchmark_owners()
    first = first_frame_repos() if second else set()
    rows, cands = [], []
    fields = sample.DRAW_FIELDS + ["merged_prs", "preview", "homepage"]
    for stack, _, pattern, out_dir in sample.STACKS:
        if second:
            with open(os.path.join(HERE, "frame2-{0}.json".format(stack)), encoding="utf-8") as fh:
                frame = sample.reduce_frame(json.load(fh)["items"], pattern)
            order = frame2_order(frame, first)
            write_json(os.path.join(HERE, "order2-{0}.json".format(stack)), order)
        else:
            with open(os.path.join(BENCH, "sample", "frame-{0}.json".format(stack)), encoding="utf-8") as fh:
                frame = sample.reduce_frame(json.load(fh)["items"], pattern)
            with open(os.path.join(BENCH, "sample", "order-{0}.json".format(stack)), encoding="utf-8") as fh:
                order = json.load(fh)
        found = 0
        for rank, repo in enumerate(order, 1):
            if rank <= after.get(stack, 0):
                continue
            if found >= args.per_stack:
                break
            base = {"stack": stack, "rank": rank, "repo": repo}
            why = exclusion(repo, extra, owners)
            if why:
                rows.append(dict(base, outcome="ineligible", reason=why))
                continue
            row = dict(sample.evaluate(stack, repo, frame[repo], out_dir), **base)
            if row["outcome"] == "candidate":
                meta = sample.gh("repos/" + repo) or {}
                n, numbers = merged_prs(repo, meta.get("default_branch"))
                row.update(merged_prs=n, homepage=meta.get("homepage") or "")
                if n < MIN_PRS:
                    row.update(outcome="ineligible", reason="{0} merged PRs in the 8 weeks (needs {1})".format(n, MIN_PRS))
                elif not row["homepage"]:
                    row.update(outcome="ineligible", reason="no GitHub homepage")
                else:
                    row["preview"] = preview_flag(repo, numbers, row["homepage"]) or ""
                    found += 1
                    cands.append(dict({k: row[k] for k in ("repo", "stack", "rank", "build_command", "site_dir",
                                                            "node_version", "homepage", "preview")},
                                      ref_cutoff=UNTIL, commits=0, default_branch=meta.get("default_branch"),
                                      frame=2 if second else 1))
            rows.append(row)
            print(stack, rank, repo, row["outcome"], row.get("reason", ""), flush=True)
    names = ("candidates2.json", "draw2.csv") if second else ("candidates.json", "draw.csv")
    write_json(os.path.join(HERE, names[0]), cands)
    write_csv(os.path.join(HERE, names[1]), fields, rows)
    print("{0} candidates -> {1}; every repository looked at -> {2}".format(len(cands), *names))
    return 0


def page_title(text):
    m = re.search(r"<title[^>]*>(.*?)</title>", text or "", re.I | re.S)
    return " ".join(html.unescape(m.group(1)).split()) if m else None


def https_url(homepage):
    """A GitHub homepage in the https form 2.2 checks it in (Addendum 2, part 4)."""
    url = homepage if "://" in homepage else "https://" + homepage
    return "https://" + url.split("://", 1)[1]


def homepage_check(homepage, site):
    """2.2: the GitHub homepage answers 200 over https with the build's home-page title.
    Returns a reason it fails, or None."""
    import requests

    url = https_url(homepage)
    try:
        r = requests.get(url, timeout=30, headers={"User-Agent": "sitemend-crawler/1.0 (+local audit)"})
    except Exception as e:
        return "homepage unreachable: " + str(e)[:150]
    if r.status_code != 200:
        return "homepage answered {0}".format(r.status_code)
    try:
        with open(os.path.join(site, "index.html"), encoding="utf-8", errors="replace") as fh:
            built = page_title(fh.read())
    except OSError:
        built = None
    live = page_title(r.text)
    if not built or built != live:
        return "homepage title {0!r} is not the build's {1!r}".format(live, built)
    return None


def cmd_build_check(args):
    """One candidate built at the default branch's head on the draw date (2.2)."""
    entry = next(e for e in read_json(args.config, []) if e["repo"] == args.repo)
    work = os.path.abspath(args.work)
    os.makedirs(work, exist_ok=True)
    env = replay.tool_env(work)
    path = replay.clone(entry, work)
    sha = replay.commits(path, UNTIL, 0)[-1]
    logs = os.path.join(work, "logs-" + slug(entry["repo"]))
    os.makedirs(logs, exist_ok=True)
    site, secs = replay.build(entry, path, sha, os.path.join(logs, "build.log"), env, BUILD_TIMEOUT)
    row = {"repo": entry["repo"], "sha": sha, "build_seconds": secs, "status": "ok", "reason": ""}
    if site is None:
        row.update(status="build_failed", reason=replay.failure_reason({"status": "build_failed"}, logs))
    elif not glob.glob(os.path.join(site, "**", "*.html"), recursive=True):
        row.update(status="no_pages", reason="the output holds no HTML pages (Addendum 7)")
    else:
        why = homepage_check(entry["homepage"], site)
        if why:
            row.update(status="homepage_failed", reason=why)
    write_csv(args.out or os.path.join(HERE, "builds-{0}.csv".format(slug(entry["repo"]))),
              ["repo", "sha", "status", "reason", "build_seconds"], [row])
    print(row)
    return 0


SAMPLE = PER_STACK * 5                # 30


def round_robin(per, stacks):
    """The candidates left in per, one stack at a time in the table's order, each stack's
    in draw order."""
    depth = max([len(per[s]) for s in stacks] + [0])
    return [per[s][i] for i in range(depth) for s in stacks if i < len(per[s])]


def select(cands, built):
    """2.2's size rule with Addendum 2, part 1. Per stack, every candidate that built, up
    to PER_STACK, in draw order; the places left, up to SAMPLE, from the stacks that still
    have candidates that built, one stack at a time in the table's order; then, while fewer
    than MIN_FLAGGED have the preview flag, the next flagged ones that built, the same way,
    until MIN_FLAGGED are flagged or MAX_TOTAL are taken. Returns (taken, short): short
    names the stacks with fewer than PER_STACK that built."""
    stacks = [s for s, _, _, _ in sample.STACKS]
    per = {s: sorted((c for c in cands if c["stack"] == s and built.get(c["repo"]) == "ok"),
                     key=lambda c: c["rank"]) for s in stacks}
    taken = [c for s in stacks for c in per[s][:PER_STACK]]
    rest = {s: per[s][PER_STACK:] for s in stacks}
    fill = round_robin(rest, stacks)[:max(0, SAMPLE - len(taken))]
    taken += fill
    rest = {s: [c for c in rest[s] if c not in fill and c.get("preview")] for s in stacks}
    for c in round_robin(rest, stacks):
        if sum(bool(c.get("preview")) for c in taken) >= MIN_FLAGGED or len(taken) >= MAX_TOTAL:
            break
        taken.append(c)
    short = [s for s in stacks if len(per[s]) < PER_STACK]
    return taken, short


def select_widened(keep, cands, built):
    """Addendum 4, part 4. The sites already selected first, all of them, whatever their
    stack; then only new candidates that built, in draw order: each stack up to PER_STACK
    counting those kept, then the places left up to SAMPLE one stack at a time in the
    table's order, then the preview top-up to MIN_FLAGGED, at most MAX_TOTAL. Fewer than
    SAMPLE available means everyone who built (part 5). Every site records its frame."""
    stacks = [s for s, _, _, _ in sample.STACKS]
    taken = [dict(c, frame=c.get("frame", 1)) for c in keep]
    kept = {c["repo"] for c in taken}
    new = {s: sorted((dict(c, frame=c.get("frame", 2)) for c in cands
                      if c["stack"] == s and built.get(c["repo"]) == "ok" and c["repo"] not in kept),
                     key=lambda c: c["rank"]) for s in stacks}
    for s in stacks:
        room = max(0, PER_STACK - sum(c["stack"] == s for c in taken))
        taken += new[s][:room]
        new[s] = new[s][room:]
    fill = round_robin(new, stacks)[:max(0, SAMPLE - len(taken))]
    taken += fill
    rest = {s: [c for c in new[s] if c not in fill and c.get("preview")] for s in stacks}
    for c in round_robin(rest, stacks):
        if sum(bool(c.get("preview")) for c in taken) >= MIN_FLAGGED or len(taken) >= MAX_TOTAL:
            break
        taken.append(c)
    return taken


def cmd_select(args):
    out = getattr(args, "out", None) or HERE
    cands = read_json(getattr(args, "candidates", None) or os.path.join(out, "candidates.json"), [])
    built = {}
    for p in args.builds:
        for b in read_csv(p):
            built[b["repo"]] = b["status"]
    if getattr(args, "keep", None):
        # Addendum 4: the sample already selected is kept, and new candidates are added.
        taken, short = select_widened(read_json(args.keep, []), cands, built), []
    else:
        taken, short = select(cands, built)
    for s in short:
        print("{0}: fewer than {1} built; its places are filled from the other stacks (Addendum 2)".format(
            s, PER_STACK))
    if not taken:
        print("no candidate built: nothing written")
        return 1
    if len(taken) < SAMPLE:
        # Addendum 3: with every frame read to its end, the sample is every one that built.
        print("{0} built, fewer than {1}: all {0} are the sample (Addendum 3)".format(len(taken), SAMPLE))
    taken = [dict(c, homepage=https_url(c["homepage"])) for c in taken]
    write_json(os.path.join(out, "repos.json"), taken)
    opens = (now() + datetime.timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
    write_json(os.path.join(out, "window.json"), {"opens": opens, "weeks": 8})
    print("{0} repositories ({1} with a preview{2}) -> repos.json; window opens {3}".format(
        len(taken), sum(bool(c.get("preview")) for c in taken),
        "; {0} from the second frame".format(sum(c.get("frame") == 2 for c in taken)) if getattr(args, "keep", None) else "",
        opens))
    return 0


# ---------------------------------------------------------------- the window (section 3)

def window():
    w = read_json(os.path.join(HERE, "window.json"))
    if not w:
        return None, None
    opens = parse_time(w["opens"])
    return opens, opens + datetime.timedelta(weeks=w["weeks"])


def pulls_in_window(get, repo, branch, opens, ends):
    """PRs against branch opened in [opens, ends), newest first, up to 10 pages."""
    out = []
    for page in range(1, 11):
        got = get("repos/{0}/pulls?state=all&base={1}&sort=created&direction=desc&per_page=100&page={2}"
                  .format(repo, branch, page)) or []
        for p in got:
            t = parse_time(p["created_at"])
            if t < opens:
                return out
            if t < ends:
                out.append(p)
        if len(got) < 100:
            break
    return out


def home_fingerprint(text):
    """What changes when a new build is deployed, and not on every request: the title and
    every src and href, which carry the build's fingerprinted asset names. A nonce, a CSRF
    token or a rendered clock change the page's bytes on every load, and would make a
    merge look deployed before it is."""
    refs = sorted(set(re.findall(r"""\b(?:src|href)\s*=\s*["']([^"']+)["']""", text or "", re.I)))
    return hashlib.sha256("\n".join([page_title(text) or ""] + refs).encode("utf-8")).hexdigest()


def home_hash(url):
    import requests
    try:
        return home_fingerprint(requests.get(url, timeout=30).text)
    except Exception:
        return None


PREVIEW_FAST = 3600        # a head's first hour: its preview is looked for on every poll
PREVIEW_SLOW = 3600        # then once an hour, until it has one or the PR's head is final


def preview_due(h, t):
    """Whether to look for a head's preview on this poll. A preview usually appears within
    minutes of a push; a site that never publishes one would otherwise cost three API
    calls per open PR on every poll for the whole window. The final head is always looked
    at once more, so a late preview is still checked (3.3)."""
    if not h.get("url_looked_at"):
        return True
    age = (t - parse_time(h["seen"])).total_seconds()
    since = (t - parse_time(h["url_looked_at"])).total_seconds()
    return age < PREVIEW_FAST or since >= PREVIEW_SLOW


def plan(state, repos, opens, ends, t, get=None, hash_home=None, cap=200, ok=None):
    """One poll: the next state and the jobs to run. Check outcomes are only ever written
    by collect; plan records what GitHub says about each PR and what it scheduled. At most
    cap jobs (a matrix holds 256); the rest wait for the next poll, their tries untouched."""
    get, hash_home = get or api, hash_home or home_hash
    state = json.loads(json.dumps(state or {}))
    prs, prod = state.setdefault("prs", {}), state.setdefault("production", {})
    jobs = []
    if t < opens:
        return state, jobs
    over = t >= ends
    for e in repos:
        repo, branch = e["repo"], e["default_branch"]
        for p in pulls_in_window(get, repo, branch, opens, ends):
            key = "{0}#{1}".format(repo, p["number"])
            rec = prs.setdefault(key, {"repo": repo, "number": p["number"], "created_at": p["created_at"],
                                       "bot": (p.get("user") or {}).get("type") == "Bot", "heads": {}})
            head = p["head"]["sha"]
            rec.update(state=p["state"], merged_at=p.get("merged_at"), closed_at=p.get("closed_at"))
            if rec.get("final_by") == "end" and parse_time(rec["final_end"]) < ends:
                # The window was extended (3.1) after this head was taken at the old end:
                # the extended close is the window's close, so the PR is followed again.
                for k in ("final_head", "final_by", "final_end"):
                    rec.pop(k, None)
            h = rec["heads"].setdefault(head, {"seen": stamp(t), "base_sha": p["base"]["sha"],
                                               "folder": None, "url": None, "folder_tries": 0, "url_tries": 0})
            h["draft"] = bool(p.get("draft"))
            if rec.get("final_head") is None and (p["state"] == "closed" or over):
                rec["final_head"] = head
                if p["state"] != "closed":
                    rec.update(final_by="end", final_end=stamp(ends))
            final = rec.get("final_head")
            if final and final != head:
                continue                       # after the final head, nothing else counts
            if h["draft"]:
                continue
            base_job = {"repo": repo, "pr": p["number"], "head": head, "base": h["base_sha"],
                        "node_version": e.get("node_version", "24")}
            for mode in ("folder", "url"):
                if h[mode] is not None:
                    continue
                if h.get(mode + "_at") and (t - parse_time(h[mode + "_at"])).total_seconds() < IN_FLIGHT:
                    continue                   # scheduled, and may still be running
                if h[mode + "_tries"] >= MAX_TRIES:
                    h[mode] = "tool_failure"
                    h[mode + "_reason"] = "the job did not report back {0} times".format(MAX_TRIES)
                    continue
                if len(jobs) >= cap:
                    break
                url = None
                if mode == "url":
                    if not final and not preview_due(h, t):
                        continue
                    url = preview_url(get, repo, head, p["number"], ok, e["homepage"])
                    h["url_looked_at"] = stamp(t)
                    if not url:
                        if final:
                            h["url"] = "preview_unavailable"
                            h["url_reason"] = "no preview found for the head"
                        continue
                h[mode + "_tries"] += 1
                h[mode + "_at"] = stamp(t)
                jobs.append(dict(base_job, kind=mode, url=url or ""))
        # 3.4: production at window open, then after each merge, once it changed or 2 h on.
        # After the end, only a change a poll saw before it is still audited.
        seen = state.setdefault("production_seen", {})
        if over and not (repo in seen and parse_time(seen[repo]["at"]) < ends):
            continue
        last = prod.get(repo)
        # The branch head, not commit dates: a fast-forward or rebase merge can keep dates
        # older than the last audit, and would never be seen by date.
        commits = get("repos/{0}/commits?sha={1}&per_page=1".format(repo, branch)) or []
        branch_sha = commits[0]["sha"] if commits else ""
        if last is not None and not branch_sha:
            continue                           # the branch could not be read this poll
        job = {"repo": repo, "kind": "production", "url": e["homepage"], "branch_sha": branch_sha,
               "node_version": e.get("node_version", "24")}
        if len(jobs) >= cap:
            continue
        # A production audit that never succeeds is tried MAX_TRIES times for each state
        # of the branch, not on every poll for the rest of the window.
        tries = state.setdefault("production_tries", {}).setdefault(repo, {"sha": branch_sha, "n": 0})
        if tries["sha"] != branch_sha:
            tries.update(sha=branch_sha, n=0)
        if tries["n"] >= MAX_TRIES:
            continue
        if tries.get("at") and (t - parse_time(tries["at"])).total_seconds() < IN_FLIGHT:
            continue                           # scheduled, and may still be running
        if last is None:
            due = True
        elif branch_sha == last.get("branch_sha"):
            due = False
        else:
            # 3.4's 2 hours run from when a poll first saw a change not yet audited, so at
            # most one poll (15 minutes) after that merge. A later merge does not restart
            # them: the audit then covers every merge since the last one.
            if repo not in seen:
                seen[repo] = {"sha": branch_sha, "at": stamp(t)}
            due = ((t - parse_time(seen[repo]["at"])).total_seconds() >= PROD_WAIT
                   or hash_home(e["homepage"]) != last.get("home_hash"))
        if due:
            tries["n"] += 1
            tries["at"] = stamp(t)
            jobs.append(job)
    return state, jobs


def compact(f):
    return {k: f.get(k) for k in ("id", "severity", "pages", "evidence", "message", "confidence")}


def gate(scripts, env, base_dir, head_dir):
    """verify.py on two audits: (outcome, regressions, advisory)."""
    result, out = replay.compare(sys.executable, scripts, base_dir, head_dir, env)
    if result not in COUNTED or not os.path.exists(out):
        return "tool_failure", [], []
    doc = read_json(out)
    return result, [compact(f) for f in doc["regressions"]], [compact(f) for f in doc.get("advisory", [])]


def run_job(job, data, work, scripts, env, repos=None):
    """One check (3.3) or production audit (3.4); returns the result collect stores."""
    repos = repos if repos is not None else read_json(os.path.join(HERE, "repos.json"), [])
    res = {"job": job, "outcome": "", "reason": "", "regressions": [], "advisory": [],
           "checked_at": stamp(now())}
    out = os.path.join(work, "out")
    shutil.rmtree(out, ignore_errors=True)
    if job["kind"] == "folder":
        entry = next(e for e in repos if e["repo"] == job["repo"])
        path = replay.clone(entry, work)
        replay.git(path, "fetch", "--quiet", "origin", "refs/pull/{0}/head".format(job["pr"]), job["base"])
        dirs = {}
        for side in ("head", "base"):
            site, _ = replay.build(entry, path, job[side], os.path.join(work, side + "-build.log"), env, BUILD_TIMEOUT)
            if site is None:
                res.update(outcome="build_failed", reason="the {0} build failed".format(side))
                return res
            dirs[side] = os.path.join(out, side)
            ok, _ = replay.audit(sys.executable, scripts, site, dirs[side], env, AUDIT_TIMEOUT)
            if not ok:
                res.update(outcome="tool_failure", reason=replay.failure_reason({"status": "audit_failed"}, dirs[side]))
                return res
        res["outcome"], res["regressions"], res["advisory"] = gate(scripts, env, dirs["base"], dirs["head"])
    elif job["kind"] == "url":
        import requests
        try:
            status = requests.get(job["url"], timeout=30).status_code
        except Exception as e:
            status = str(e)[:150]
        if status != 200:
            res.update(outcome="preview_unavailable", reason="preview answered {0}".format(status))
            return res
        entry = next(e for e in repos if e["repo"] == job["repo"])
        dirs = {"head": os.path.join(out, "head"), "base": os.path.join(out, "base")}
        for side, url in (("head", job["url"]), ("base", entry["homepage"])):
            ok, _ = replay.audit(sys.executable, scripts, url, dirs[side], env, AUDIT_TIMEOUT)
            if not ok:
                res.update(outcome="tool_failure", reason=replay.failure_reason({"status": "audit_failed"}, dirs[side]))
                return res
        res["outcome"], res["regressions"], res["advisory"] = gate(scripts, env, dirs["base"], dirs["head"])
    else:
        cur = os.path.join(out, "current")
        res["home_hash"] = home_hash(job["url"])
        ok, _ = replay.audit(sys.executable, scripts, job["url"], cur, env, AUDIT_TIMEOUT)
        if not ok:
            res.update(outcome="tool_failure", reason=replay.failure_reason({"status": "audit_failed"}, cur))
            return res
        res["findings"] = read_json(os.path.join(cur, "findings.json"))["findings"]
        last = (read_json(os.path.join(data, "state.json"), {}).get("production") or {}).get(job["repo"])
        if last is None:
            res["outcome"] = "first"
            return res
        prev = os.path.join(out, "previous")
        write_json(os.path.join(prev, "findings.json"), {"findings": read_json(os.path.join(data, last["findings"]))})
        result, out_path = replay.compare(sys.executable, scripts, prev, cur, env)
        if result not in COUNTED:
            res.update(outcome="tool_failure", reason="verify.py did not finish")
            return res
        doc = read_json(out_path)
        res["outcome"] = "compared"
        res["regressions"] = [compact(f) for f in doc["new"] + doc.get("escalated", [])
                              if f["severity"] in ("critical", "high")]
    return res


def cmd_check(args):
    job = json.loads(args.job)
    scripts = args.scripts or replay.installed_scripts(FROZEN)
    work = os.path.abspath(args.work)
    os.makedirs(work, exist_ok=True)
    res = run_job(job, args.data, work, scripts, replay.tool_env(work))
    write_json(os.path.join(args.out, "result-{0}.json".format(job["id"])), res)
    print(res["outcome"], res["reason"])
    return 0


def collect(state, results, data):
    """Fold job results into state and the data folder's files."""
    rows = read_csv(os.path.join(data, "results.csv"))
    prod_rows = read_csv(os.path.join(data, "production.csv"))
    for res in results:
        job = res["job"]
        if job["kind"] == "production":
            last = state.setdefault("production", {}).get(job["repo"])
            rel = "production/{0}/{1}.json".format(slug(job["repo"]), res["checked_at"].replace(":", ""))
            if res.get("findings") is not None:
                write_json(os.path.join(data, rel), res["findings"])
            merged = sorted(rec["number"] for rec in state.get("prs", {}).values()
                            if rec["repo"] == job["repo"] and rec.get("merged_at")
                            and (last is None or rec["merged_at"] > last["audited_at"])
                            and rec["merged_at"] <= res["checked_at"])
            prod_rows.append({"repo": job["repo"], "audited_at": res["checked_at"],
                              "previous_at": last["audited_at"] if last else "", "branch_sha": job.get("branch_sha", ""),
                              "merged_prs": " ".join("#{0}".format(n) for n in merged),
                              "new_critical_high": len(res["regressions"]), "outcome": res["outcome"],
                              "reason": res["reason"]})
            if res["outcome"] == "compared" and res["regressions"]:
                write_json(os.path.join(data, "production", slug(job["repo"]),
                                        res["checked_at"].replace(":", "") + "-new.json"), res["regressions"])
            if res.get("findings") is not None:
                state["production"][job["repo"]] = {"audited_at": res["checked_at"], "findings": rel,
                                                    "home_hash": res.get("home_hash"),
                                                    "branch_sha": job.get("branch_sha", "")}
                for k in ("production_tries", "production_seen"):
                    state.get(k, {}).pop(job["repo"], None)
            continue
        rec = state.get("prs", {}).get("{0}#{1}".format(job["repo"], job["pr"]))
        h = rec and rec["heads"].get(job["head"])
        if not h:
            continue
        h[job["kind"]] = res["outcome"]
        h[job["kind"] + "_reason"] = res["reason"]
        write_json(os.path.join(data, "findings", slug(job["repo"]), "{0}-{1}-{2}.json".format(
            job["pr"], job["head"][:12], job["kind"])), {"regressions": res["regressions"], "advisory": res["advisory"]})
        rows.append({"repo": job["repo"], "pr": job["pr"], "head_sha": job["head"], "base_sha": job.get("base", ""),
                     "mode": job["kind"], "outcome": res["outcome"], "blocking": len(res["regressions"]),
                     "checked_at": res["checked_at"], "bot": "y" if rec.get("bot") else "n", "reason": res["reason"]})
    write_csv(os.path.join(data, "results.csv"), RESULT_FIELDS, rows)
    write_csv(os.path.join(data, "production.csv"), PROD_FIELDS, prod_rows)
    write_json(os.path.join(data, "state.json"), state)
    return state


OUTCOMES = {"folder": {"pass", "fail", "build_failed", "tool_failure"},
            "url": {"pass", "fail", "tool_failure", "preview_unavailable"},
            "production": {"first", "compared", "tool_failure"}}


def valid(res, job):
    """Whether a check's result may be filed: it describes exactly the job the poll gave
    that id, with an outcome of that mode, and lists where lists belong."""
    return (isinstance(res, dict) and res.get("job") == job
            and res.get("outcome") in OUTCOMES[job["kind"]]
            and isinstance(res.get("regressions"), list) and isinstance(res.get("advisory", []), list)
            and all(isinstance(f, dict) for f in res["regressions"])
            and isinstance(res.get("findings", []), (list, type(None)))
            and isinstance(res.get("reason", ""), str) and isinstance(res.get("checked_at"), str))


def member(blob, name):
    """One named file from an artifact's zip, parsed; None if it is not there. Nothing else
    in the zip is read or extracted, so a path in it can never reach the filesystem."""
    try:
        return json.loads(zipfile.ZipFile(io.BytesIO(blob)).read(name).decode("utf-8"))
    except (KeyError, ValueError, zipfile.BadZipFile):
        return None


def collect_new(state, data, t, get, fetch, repo=None):
    """File every check result of the last COLLECT_BACK of runs not filed yet.

    A check artifact comes from a job that has just run a stranger's build, which can
    write anything into it. So each run's job list is read from its task9-plan artifact,
    which the poll job uploads before any check starts; a check contributes exactly one
    file, result-<id>.json from task9-result-<id>, filed only if it describes the job the
    poll gave that id (valid). An artifact is filed once (its id is remembered), whether
    its run has finished or not. A build can still lie about its own job's result; it
    cannot touch any other job, or the state."""
    repo = repo or os.environ.get("GITHUB_REPOSITORY", "")
    done = set(state.get("collected", []))
    since = stamp(t - datetime.timedelta(seconds=COLLECT_BACK))
    runs = (get("repos/{0}/actions/workflows/{1}/runs?created=%3E%3D{2}&per_page=100".format(repo, WORKFLOW, since))
            or {}).get("workflow_runs", [])
    results, rejected = [], []
    for run in sorted(runs, key=lambda r: r["id"]):
        arts = {a["name"]: a for a in (get("repos/{0}/actions/runs/{1}/artifacts?per_page=100".format(repo, run["id"]))
                                       or {}).get("artifacts", []) if not a.get("expired")}
        plan_art = arts.get("task9-plan")
        jobs = member(fetch(plan_art["id"]), "jobs.json") if plan_art else None
        for job in jobs or []:
            art = arts.get("task9-result-" + job["id"])
            if not art or art["id"] in done:
                continue
            res = member(fetch(art["id"]), "result-{0}.json".format(job["id"]))
            done.add(art["id"])
            if valid(res, job):
                results.append(dict(res, job=job))
            else:
                rejected.append("{0}/{1}".format(run["id"], job["id"]))
    state = collect(state, results, data)
    state["collected"] = sorted(done)[-20000:]
    return state, results, rejected


def cmd_poll(args):
    opens, ends = window()
    repos = read_json(os.path.join(HERE, "repos.json"), [])
    jobs = []
    if repos and opens:
        t = now()
        state = read_json(os.path.join(args.data, "state.json"), {})
        get_actions = lambda path: api(path, token_env="TASK9_ACTIONS_TOKEN")
        fetch = lambda aid: api("repos/{0}/actions/artifacts/{1}/zip".format(
            os.environ.get("GITHUB_REPOSITORY", ""), aid), raw=True, token_env="TASK9_ACTIONS_TOKEN")
        state, results, rejected = collect_new(state, args.data, t, get_actions, fetch)
        print("{0} result(s) filed; rejected: {1}".format(len(results), ", ".join(rejected) or "none"), file=sys.stderr)
        state, jobs = plan(state, repos, opens, ends, t)
        for i, j in enumerate(jobs):
            j["id"] = "{0}-{1}".format(i, slug(j["repo"]))
        write_json(os.path.join(args.data, "state.json"), state)
    write_json(os.path.join(args.out, "jobs.json"), jobs)
    print(json.dumps(jobs))
    return 0


# ---------------------------------------------------------------- verdicts (section 4)

def counted(state):
    """(pr record, final head, mode, outcome) for every comparison that counts (3.2, 3.3):
    the final head's check in each mode, once it has a result. A final head that was a
    draft, or whose check has not reported yet, is not a counted PR."""
    for key, rec in sorted((state.get("prs") or {}).items()):
        h = rec["heads"].get(rec.get("final_head") or "")
        if not h or h.get("draft"):
            continue
        for mode in ("folder", "url"):
            if h.get(mode) is not None:
                yield rec, rec["final_head"], mode, h[mode]


def ledger_row(repo, head, f, note):
    return {"repo": repo, "head_sha": head, "rule_id": f["id"], "severity": f["severity"],
            "url": " ".join(f.get("pages") or []),
            "evidence_excerpt": " ".join(str(f.get("evidence") or "").split())[:200],
            "verdict": "", "verified_by": "", "verification_method": "", "notes": note}


def mode_of(note):
    return note.split(";")[0].replace("mode:", "").strip()


def prefill(ledger, new_rows):
    """Add rows not in the ledger, keeping every verdict already given; a key found in both
    gate modes becomes one row, mode: both (4.1)."""
    by_key = {verify_helper.key(r): r for r in ledger}
    for r in new_rows:
        k = verify_helper.key(r)
        old = by_key.get(k)
        if old is None:
            ledger.append(r)
            by_key[k] = r
        elif {mode_of(old["notes"]), mode_of(r["notes"])} == {"folder", "url"}:
            old["notes"] = "mode: both" + old["notes"][len(old["notes"].split(";")[0]):]
    return ledger


def cmd_ledger(args):
    gate_path = os.path.join(args.data, "ledger-task9.csv")
    prod_path = os.path.join(args.data, "ledger-task9-production.csv")
    if args.second_look:
        judged = [r for r in read_csv(gate_path) + read_csv(prod_path) if r["verdict"]]
        pick = sorted(random.Random(SEED).sample(range(len(judged)), round(0.2 * len(judged))))
        # The first verdict is left out, so it cannot be seen while judging again.
        write_csv(os.path.join(args.data, "second-look.csv"), verify_helper.FIELDS,
                  [dict(judged[i], verdict="", verified_by="", verification_method="", notes="") for i in pick])
        print("{0} of {1} judged findings -> second-look.csv".format(len(pick), len(judged)))
        return 0
    state = read_json(os.path.join(args.data, "state.json"), {})
    new = []
    for rec, head, mode, outcome in counted(state):
        if outcome != "fail":
            continue
        doc = read_json(os.path.join(args.data, "findings", slug(rec["repo"]),
                                     "{0}-{1}-{2}.json".format(rec["number"], head[:12], mode)), {})
        new += [ledger_row(rec["repo"], head, f, "mode: " + mode) for f in doc.get("regressions", [])]
    ledger = prefill(read_csv(gate_path), new)
    write_csv(gate_path, verify_helper.FIELDS, ledger)
    prod = read_csv(prod_path)
    for row in read_csv(os.path.join(args.data, "production.csv")):
        if row["outcome"] != "compared" or not int(row["new_critical_high"] or 0):
            continue
        found = read_json(os.path.join(args.data, "production", slug(row["repo"]),
                                       row["audited_at"].replace(":", "") + "-new.json"), [])
        note = "mode: production; merged since the previous audit: " + (row["merged_prs"] or "none")
        prod = prefill(prod, [ledger_row(row["repo"], row["branch_sha"], f, note) for f in found])
    write_csv(prod_path, verify_helper.FIELDS, prod)
    pending = sum(1 for r in ledger + prod if not r["verdict"])
    print("{0} gate and {1} production row(s); {2} still need a verdict".format(len(ledger), len(prod), pending))
    return 0


# ---------------------------------------------------------------- the report (section 5)

def pct(a, b):
    return "{0} of {1} ({2})".format(a, b, "{0:.1f}%".format(100.0 * a / b) if b else "n/a")


def measures(state, ledger, mode, bots=None, skip=()):
    """Precision, frequency and tool failures for one mode, as section 5 defines them.
    bots: False for PRs by people, True for bot PRs, None for all; it narrows the PRs
    (frequency, tool failures), not the findings, since precision counts every blocking
    finding from any author (Addendum 3, part 4). skip: sites left out."""
    rows = [r for r in ledger if mode_of(r["notes"]) in (mode, "both") and r["repo"] not in skip]
    judged = [r for r in rows if r["verdict"]]
    true = {(r["repo"], r["head_sha"]) for r in judged if r["verdict"] == "true_regression"}
    prs = [(rec, head, out) for rec, head, m, out in counted(state) if m == mode
           and (bots is None or bool(rec.get("bot")) == bots) and rec["repo"] not in skip]
    compared = [(rec, head) for rec, head, out in prs if out in COUNTED]
    return {"findings": len(rows), "judged": len(judged),
            "true": sum(r["verdict"] == "true_regression" for r in judged),
            "compared": len(compared), "hit": sum((rec["repo"], head) in true for rec, head in compared),
            "prs": len(prs), "tool": sum(out == "tool_failure" for _, _, out in prs)}


def decide(f, longest):
    """Section 6, applied to folder mode's measures."""
    met_p = f["judged"] >= 20 and f["true"] >= 0.95 * f["judged"]
    met_f = bool(f["compared"]) and f["hit"] >= 0.01 * f["compared"]
    met_t = bool(f["prs"]) and f["tool"] <= 0.05 * f["prs"]
    if f["findings"] < 20 and not longest:
        return "fewer than 20 blocking findings: extend the window by 4 weeks (3.1)"
    if not met_p:
        return "precision not met: outreach stays stopped, the rules are fixed, and the next run uses a fresh draw"
    if not met_f:
        return "frequency not met: re-position as a pre-launch and redesign audit, not a per-PR gate"
    if not met_t:
        return "tool failures above 5%: outreach stays stopped until they are fixed and re-measured on a fresh draw"
    return "all met: reopen outreach for the release-gate positioning (Phase 4)"


def preview_hosted(repos):
    """Addendum 2, part 3: the sites whose production itself is on a per-deploy host, where
    preview-host leak detection has a known blind spot."""
    return {e["repo"] for e in repos if (urlsplit(https_url(e["homepage"])).hostname or "").endswith(PREVIEW_HOSTS)}


def cmd_report(args):
    state = read_json(os.path.join(args.data, "state.json"), {})
    repos = read_json(getattr(args, "repos", None) or os.path.join(HERE, "repos.json"), [])
    hosted = preview_hosted(repos)
    frames = {e["repo"]: e.get("frame", 1) for e in repos}
    gate_rows = read_csv(os.path.join(args.data, "ledger-task9.csv"))
    prod_rows = read_csv(os.path.join(args.data, "ledger-task9-production.csv"))
    # Addendum 3, part 4: the thresholds count PRs by people; all PRs and bot PRs are given
    # beside them. Precision is the same in each, since it counts every finding.
    f = measures(state, gate_rows, "folder", bots=False)
    u = measures(state, gate_rows, "url", bots=False)
    merged = sum(1 for rec in (state.get("prs") or {}).values() if rec.get("merged_at"))
    url_checked = u["compared"]
    out = ["# Task 9 summary", "",
           "Generated by `bench/task9/task9.py report` from the data branch. Every number is a "
           "count from its files; thresholds apply to folder mode, frequency and tool failures to "
           "PRs by people (section 5, Addendum 3).", "",
           "| Measure | Folder mode | URL mode (apart) | Threshold |", "|---|---|---|---|",
           "| Blocking precision | {0} | {1} | at least 95% with 20 or more blocking findings |".format(
               pct(f["true"], f["judged"]), pct(u["true"], u["judged"])),
           "| Frequency (per PR by people) | {0} | {1} | at least 1 per 100 PRs compared |".format(
               pct(f["hit"], f["compared"]), pct(u["hit"], u["compared"])),
           "| Tool failures (per PR by people) | {0} | {1} | at most 5% |".format(
               pct(f["tool"], f["prs"]), pct(u["tool"], u["prs"]))]
    for label, bots in (("all PRs", None), ("bot PRs", True)):
        m = measures(state, gate_rows, "folder", bots)
        out.append("- Folder mode, {0}: frequency {1}; tool failures {2}".format(
            label, pct(m["hit"], m["compared"]), pct(m["tool"], m["prs"])))
    # Addendum 3, part 6: every measure per site, and again without the busiest site.
    sites = sorted({rec["repo"] for rec in (state.get("prs") or {}).values()})
    per = {s: measures(state, [r for r in gate_rows if r["repo"] == s], "folder", False,
                       skip=tuple(x for x in sites if x != s)) for s in sites}
    if sites:
        out += ["", "Folder mode per site (PRs by people):", "",
                "| Site | PRs compared | With a true_regression | Blocking findings | true_regression | Tool failures |",
                "|---|---|---|---|---|---|"]
        out += ["| {0} | {1} | {2} | {3} | {4} | {5} |".format(
            s, m["compared"], m["hit"], m["findings"], m["true"], m["tool"]) for s, m in sorted(
                per.items(), key=lambda kv: (-kv[1]["compared"], kv[0]))]
        busiest = max(sites, key=lambda s: (per[s]["compared"], s))
        w = measures(state, gate_rows, "folder", False, skip=(busiest,))
        out += ["", "- Without {0}, the site with the most PRs compared: precision {1}; frequency {2}; "
                    "tool failures {3}.".format(busiest, pct(w["true"], w["judged"]), pct(w["hit"], w["compared"]),
                                                pct(w["tool"], w["prs"]))]
    if 2 in frames.values():
        # Addendum 4, part 7: each frame's sites beside the pooled figures.
        for fr in (1, 2):
            m = measures(state, gate_rows, "folder", False, skip=tuple(r for r, x in frames.items() if x != fr))
            out.append("- Frame {0} sites ({1}): precision {2}; frequency {3}".format(
                fr, sum(x == fr for x in frames.values()), pct(m["true"], m["judged"]), pct(m["hit"], m["compared"])))
    pending = sum(1 for r in gate_rows + prod_rows if not r["verdict"])
    if f["findings"] < 20:
        out += ["", "**{0} blocking findings in folder mode: fewer than 20, so the window is extended "
                    "4 weeks, up to 16 in all (3.1).**".format(f["findings"])]
    for rule, sev, label, denom, what in (("S1-HOST-MISMATCH", "critical", "Preview-host leaks", merged, "merged PRs"),
                                          ("S1-SOFT-404", "high", "Soft 404s", url_checked, "PRs checked in url mode")):
        g = [r for r in gate_rows if r["rule_id"] == rule and r["severity"] == sev]
        p = [r for r in prod_rows if r["rule_id"] == rule and r["severity"] == sev]
        true = [r for r in g + p if r["verdict"] == "true_regression"]
        out += ["", "**{0}** ({1} at {2}): {3} gate finding(s), {4} from production audits, {5} "
                    "true_regression.".format(label, rule, sev, len(g), len(p), len(true))]
        if not true:
            out.append("- None verified: rule-of-three upper bound 3 / {0} {1} = {2}.".format(
                denom, what, "{0:.2f}%".format(300.0 / denom) if denom else "n/a"))
        if rule == "S1-HOST-MISMATCH" and hosted:
            # Addendum 2, part 3: the same measure without the sites whose production is on
            # a per-deploy host.
            keep = lambda rows: [r for r in rows if r["repo"] not in hosted]
            m2 = sum(1 for rec in (state.get("prs") or {}).values()
                     if rec.get("merged_at") and rec["repo"] not in hosted)
            t2 = [r for r in keep(g) + keep(p) if r["verdict"] == "true_regression"]
            out.append("- Without the {0} site(s) whose production is on a preview platform's host ({1}): "
                       "{2} gate finding(s), {3} from production audits, {4} true_regression{5}.".format(
                           len(hosted), ", ".join(sorted(hosted)), len(keep(g)), len(keep(p)), len(t2),
                           "" if t2 else "; upper bound 3 / {0} merged PRs = {1}".format(
                               m2, "{0:.2f}%".format(300.0 / m2) if m2 else "n/a")))
    # 3.4: a production true_regression is a miss unless the gate blocked that rule on one of
    # the PRs merged between the two audits (then it confirms the gate, and counts once).
    finals = {(rec["repo"], rec["number"]): rec.get("final_head") for rec in (state.get("prs") or {}).values()}
    blocked = {(r["repo"], r["head_sha"], r["rule_id"]) for r in gate_rows}
    misses = confirmed = 0
    for r in (r for r in prod_rows if r["verdict"] == "true_regression"):
        numbers = [int(n) for n in re.findall(r"#(\d+)", r["notes"])]
        if any((r["repo"], finals.get((r["repo"], n)), r["rule_id"]) in blocked for n in numbers):
            confirmed += 1
        else:
            misses += 1
    out += ["", "**Misses (a floor, not recall):** {0} true_regression finding(s) from production audits "
                "on PRs the gate passed; {1} confirm a gate finding.".format(misses, confirmed)]
    _, ends = window()
    if pending or ends is None or now() < ends:
        out += ["", "{0} finding(s) still have no verdict, or the window is open: no decision rule "
                    "applies yet.".format(pending)]
    else:
        longest = (read_json(os.path.join(HERE, "window.json")) or {}).get("weeks", 8) >= 16
        out[2:2] = ["**Outcome (section 6): {0}.**".format(decide(f, longest)), ""]
    text = "\n".join(out) + "\n"
    with open(os.path.join(args.data, "summary.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print(text)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draw")
    d.add_argument("--per-stack", type=int, default=12, help="eligible candidates to find per stack")
    d.add_argument("--frame", type=int, choices=(1, 2), default=1, help="2: the second frame (Addendum 4)")
    sub.add_parser("frame2", help="take the second frame once (Addendum 4, Task 9 Addendum 5)")
    b = sub.add_parser("build-check")
    b.add_argument("--repo", required=True)
    b.add_argument("--config", default=os.path.join(HERE, "candidates.json"))
    b.add_argument("--work", default=os.path.join(HERE, "work"))
    b.add_argument("--out")
    s = sub.add_parser("select")
    s.add_argument("--builds", nargs="+", required=True)
    s.add_argument("--candidates", help="candidates file (default candidates.json)")
    s.add_argument("--keep", help="the sample already selected, kept whole (Addendum 4), e.g. repos.json")
    for name in ("poll", "check", "ledger", "report"):
        p = sub.add_parser(name)
        p.add_argument("--data", default=os.path.join(HERE, "data"), help="a checkout of the data branch")
    sub.choices["poll"].add_argument("--out", default=os.path.join(HERE, "plan"))
    sub.choices["check"].add_argument("--job", required=True, help="one job from plan, as JSON")
    sub.choices["check"].add_argument("--work", default=os.path.join(HERE, "work"))
    sub.choices["check"].add_argument("--out", default=os.path.join(HERE, "result"))
    sub.choices["check"].add_argument("--scripts", help="sitemend's scripts folder (default: the installed 1.9.1)")
    sub.choices["ledger"].add_argument("--second-look", action="store_true")
    args = ap.parse_args(argv)
    return {"draw": cmd_draw, "frame2": cmd_frame2, "build-check": cmd_build_check, "select": cmd_select,
            "poll": cmd_poll,
            "check": cmd_check, "ledger": cmd_ledger, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
