"""sample.py -- Addendum 5 of bench/PREREGISTRATION.md: draw the replay sample by rule.

  python bench/sample/sample.py frame              # run the code searches once -> frame-<stack>.json
  python bench/sample/sample.py draw --per-stack 8 # draw order, eligibility, build rule
                                                   #   -> candidates.json (to build-check), draw.csv
  python bench/sample/sample.py select --builds builds-*.csv
                                                   # first 3 per stack that built -> bench/replay/repos.json
  python bench/sample/sample.py draw --after-sample --per-stack 20 --out ../sweep/candidates.json
                                                   # the robustness sweep: the next 20 per stack

Every decision is made by the functions below, from data saved on disk: the frame is
saved before anything is filtered, the order comes from a published seed, and every
repository looked at is written to draw.csv with its outcome. GitHub API responses are
cached under cache/ (not committed), so a re-run asks GitHub nothing it already asked.

A candidate is checked by building its cutoff commit with bench/replay/replay.py at
commits 0 (one build, no comparisons), via the replay workflow's `config` input.
"""
import argparse
import base64
import csv
import glob
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.dirname(HERE)
SEED = 20261017
CUTOFF = "2026-10-01T00:00:00Z"
SINCE = "2025-10-01T00:00:00Z"
MIN_COMMITS = 75
TAKE = 3            # per stack, for the sample
N = 40              # commits per repository in the replay

# (stack, code-search queries, config file pattern, output folder under the site folder)
STACKS = [
    ("docusaurus", ["filename:docusaurus.config"],
     r"(^|/)docusaurus\.config\.(js|ts|mjs|mts|cjs)$", "build"),
    ("astro", ["filename:astro.config"], r"(^|/)astro\.config\.(js|ts|mjs|mts|cjs)$", "dist"),
    ("vitepress", ["filename:config path:.vitepress"],
     r"(^|/)\.vitepress/config\.(js|ts|mjs|mts|cjs)$", ".vitepress/dist"),
    ("hugo", ["filename:hugo.toml", "filename:hugo.yaml"], r"(^|/)hugo\.(toml|yaml)$", "public"),
    ("nextjs", ["output export filename:next.config"], r"(^|/)next\.config\.(js|ts|mjs|cjs)$", "out"),
]

TUNING_HOSTS = {
    "astro.build", "biomejs.dev", "docs.astro.build", "docusaurus.io", "gohugo.io", "jestjs.io",
    "nextjs.org", "playwright.dev", "pnpm.io", "prettier.io", "react.dev", "reactnative.dev",
    "redux.js.org", "starlight.astro.build", "svelte.dev", "tailwindcss.com", "tauri.app",
    "turborepo.dev", "ui.shadcn.com", "vite.dev"}
EXCLUDED = {r.lower() for r in """
withastro/astro.build biomejs/website withastro/docs facebook/docusaurus gohugoio/hugoDocs
jestjs/jest vercel/next.js microsoft/playwright pnpm/pnpm.io prettier/prettier reactjs/react.dev
facebook/react-native-website reduxjs/redux withastro/starlight sveltejs/svelte.dev
tailwindlabs/tailwindcss.com tauri-apps/tauri-docs vercel/turborepo shadcn-ui/ui vitejs/vite
electron/website vuejs/docs ionic-team/ionic-docs trpc/trpc unocss/unocss vitest-dev/vitest
cloudflare/cloudflare-docs drizzle-team/drizzle-orm-docs webpro-nl/knip
open-telemetry/opentelemetry.io nodejs/nodejs.org facebook/relay
typescript-eslint/typescript-eslint facebook/flow apache/pulsar-site
react-navigation/react-navigation.github.io ionic-team/capacitor-docs datahub-project/datahub
temporalio/documentation webdriverio/webdriverio""".split()}

# The last release of each pnpm major, for repositories that do not pin one themselves.
PNPM = {"9": "9.15.9", "6": "8.15.9", "5": "7.33.7"}
DRAW_FIELDS = ["stack", "rank", "repo", "outcome", "reason", "sha", "site_dir", "build_command", "node_version"]


# ---------------------------------------------------------------- the rules (no network)

def reduce_frame(items, pattern):
    """Unique repositories from search results, each with its shallowest file that matches
    the stack's config pattern (ties: alphabetical)."""
    best = {}
    rx = re.compile(pattern)
    for it in items:
        repo, path = it["repo"], it["path"]
        if not rx.search(path):
            continue
        k = (path.count("/"), path)
        if repo not in best or k < best[repo][0]:
            best[repo] = (k, path)
    return {r: v[1] for r, v in best.items()}


def draw_order(repos):
    """Sorted by name, then shuffled with a fresh generator seeded with SEED."""
    out = sorted(repos)
    random.Random(SEED).shuffle(out)
    return out


def site_dir(stack, cfg_path):
    """The folder holding the site config; for VitePress, the folder holding .vitepress/."""
    d = os.path.dirname(cfg_path)
    if stack == "vitepress":
        d = os.path.dirname(d)
    return d


def node_major(text):
    m = re.search(r"(\d+)", text or "")
    return m.group(1) if m and not (text or "").strip().startswith("lts") else None


def excluded(repo, homepage):
    if repo.lower() in EXCLUDED:
        return "excluded: used in this plan or a tuning site's repository"
    host = (urlsplit(homepage).hostname or "").lower() if homepage else ""
    host = host[4:] if host.startswith("www.") else host
    if host in TUNING_HOSTS:
        return "excluded: homepage is tuning site " + host
    return None


def eligibility(meta, commit_count, repo):
    """Reason the repository is not eligible, or None."""
    if meta.get("private"):
        return "private"
    if meta.get("fork"):
        return "fork"
    if meta.get("archived"):
        return "archived"
    ex = excluded(repo, meta.get("homepage"))
    if ex:
        return ex
    if commit_count < MIN_COMMITS:
        return "{0} commits in the window (needs {1})".format(commit_count, MIN_COMMITS)
    return None


def build_rule(stack, d, root_files, root_pkg, yarnrc, site_pkg, cfg_text, nvmrc, out_dir):
    """Addendum 5, rule 5: (build_command, site_dir, node_version), or (None, reason).
    root_files: names at the repository root; root_pkg / site_pkg: parsed package.json or
    None; yarnrc: .yarnrc.yml text or None; nvmrc: .nvmrc or .node-version text or None."""
    if stack == "nextjs" and not re.search(r"output\s*:\s*['\"]export['\"]", cfg_text or ""):
        return None, "next.config does not set output: 'export'"
    if not site_pkg or not (site_pkg.get("scripts") or {}).get("build"):
        return None, "site folder has no package.json build script"
    pinned = (root_pkg or {}).get("packageManager")
    if "pnpm-lock.yaml" in root_files:
        if pinned:
            pm, install = "pnpm", "pnpm install --frozen-lockfile"
        else:
            ver = PNPM.get((root_files["pnpm-lock.yaml"] or "").split(".")[0])
            if not ver:
                return None, "pnpm lockfileVersion {0} has no rule".format(root_files["pnpm-lock.yaml"])
            pm = "corepack pnpm@" + ver
            install = pm + " install --frozen-lockfile"
    elif "yarn.lock" in root_files:
        if yarnrc is not None:
            m = re.search(r"^yarnPath:\s*(\S+)", yarnrc, re.M)
            if pinned:
                pm = "yarn"
            elif m:
                pm = "node " + m.group(1)
            else:
                return None, "Yarn Berry with neither packageManager nor yarnPath"
            install = pm + " install --immutable"
        else:
            pm = "yarn" if pinned else "corepack yarn@1.22.22"
            install = pm + " install --frozen-lockfile"
    elif "package-lock.json" in root_files:
        pm, install = "npm", "npm ci"
    else:
        return None, "no lockfile at the repository root"
    in_d = "(cd {0} && {1} run build)".format(d, pm) if d else "{0} run build".format(pm)
    build = in_d
    if d and ((root_pkg or {}).get("scripts") or {}).get("build"):
        build = "({0} || ({1} run build && {0}))".format(in_d, pm)
    # Addendum 6: not engines.node, whose minimum is often a floor the project left behind.
    node = node_major(nvmrc) or "24"
    out = "/".join(p for p in (d, out_dir) if p)
    return (install + " && " + build, out, node), None


# ---------------------------------------------------------------- GitHub, cached

# Answers about the repository itself, the same on any retry: it does not exist (404,
# 410), it is empty (409), it is blocked (451), or the query is invalid (400, 422).
# Anything else (a rate limit, a 5xx, a dropped connection) says nothing about it.
FINAL_STATUSES = {"400", "404", "409", "410", "422", "451"}
GH_WAITS = (60, 120, 240, 480, 900, 900, 900)   # about 1 h of backing off in all
# A 403 is usually a rate limit, but a repository disabled for terms-of-service reasons
# answers 403 "Repository access blocked" for good; retried, the draw could never pass it.
BLOCKED = re.compile(r"access blocked|has been disabled|repository is disabled", re.I)


def gh(path, raw=False):
    """gh api, with every answer cached under cache/ so a re-run is reproducible.

    Only answers are cached: a success, or a final status (FINAL_STATUSES, or a 403 for a
    blocked repository), stored as "HTTP <code>" and read back as no data. A failure that says nothing about the
    repository is retried with GH_WAITS between tries, and if it still fails the draw
    stops with an error. REGRESSION: it used to be cached as an empty answer after six
    tries a minute apart, so a burst of secondary rate limits marked 26 public, readable
    repositories "not readable" in the Task 9 draw, and every re-run read that back."""
    key = hashlib.sha256((("raw:" if raw else "") + path).encode()).hexdigest()
    cache = os.path.join(HERE, "cache", key[:2], key)
    body = None
    if os.path.exists(cache):
        with open(cache, encoding="utf-8") as fh:
            body = fh.read()
    # An empty entry is from before answers were told apart from failures: a 404 and a
    # failed request were both written as "". It is asked again, once.
    if not body:
        for wait in GH_WAITS + (None,):
            r = subprocess.run(["gh", "api"] + (["-i"] if raw else []) + [path],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            status = re.search(r"\(HTTP (\d{3})\)", r.stderr)
            if r.returncode == 0:
                body = r.stdout
                break
            if status and "rate limit" not in r.stderr.lower() and (
                    status.group(1) in FINAL_STATUSES
                    or (status.group(1) == "403" and BLOCKED.search(r.stderr))):
                body = "HTTP " + status.group(1)
                break
            if wait is None:
                raise RuntimeError("gh api {0} failed {1} times; nothing cached: {2}".format(
                    path, len(GH_WAITS) + 1, r.stderr.strip()[-300:]))
            time.sleep(wait)
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache, "w", encoding="utf-8") as fh:
            fh.write(body)
    if re.fullmatch(r"HTTP \d{3}", body):
        return "" if raw else None
    if raw:
        return body
    try:
        return json.loads(body) if body else None
    except ValueError:
        return None


def content(repo, sha, path):
    d = gh("repos/{0}/contents/{1}?ref={2}".format(repo, path, sha)) if path else None
    if not isinstance(d, dict) or "content" not in d:
        return None
    return base64.b64decode(d["content"]).decode("utf-8", "replace")


def evaluate(stack, repo, cfg_path, out_dir):
    """One repository through rules 4 and 5: a draw.csv row."""
    row = {"repo": repo, "outcome": "ineligible", "reason": "", "sha": "", "site_dir": "",
           "build_command": "", "node_version": ""}
    meta = gh("repos/" + repo)
    if not meta:
        row["reason"] = "repository not readable"
        return row
    head = gh("repos/{0}/commits?sha={1}&since={2}&until={3}&per_page=1".format(
        repo, meta["default_branch"], SINCE, CUTOFF), raw=True)
    m = re.search(r'page=(\d+)>; rel="last"', head)
    # With per_page=1 the last page number is the commit count; no Link header means 0 or 1.
    count = int(m.group(1)) if m else (1 if '"sha"' in head else 0)
    why = eligibility(meta, count, repo)
    if why:
        row["reason"] = why
        return row
    sha = (gh("repos/{0}/commits?sha={1}&until={2}&per_page=1".format(repo, meta["default_branch"], CUTOFF))
           or [{}])[0].get("sha")
    row["sha"] = sha or ""
    cfg_text = content(repo, sha, cfg_path)
    if cfg_text is None:
        row["reason"] = "site config not present at the cutoff commit"
        return row
    tree = gh("repos/{0}/git/trees/{1}".format(repo, sha)) or {}
    names = {t["path"] for t in tree.get("tree", [])}
    files = {}
    if "pnpm-lock.yaml" in names:
        m = re.search(r"lockfileVersion:\s*'?([\d.]+)", content(repo, sha, "pnpm-lock.yaml") or "")
        files["pnpm-lock.yaml"] = m.group(1) if m else ""
    for n in ("yarn.lock", "package-lock.json"):
        if n in names:
            files[n] = ""
    load = lambda p: json.loads(content(repo, sha, p) or "null")
    d = site_dir(stack, cfg_path)
    try:
        root_pkg = load("package.json")
        site_pkg = root_pkg if not d else load(d + "/package.json")
    except ValueError:
        row["reason"] = "package.json is not valid JSON"
        return row
    yarnrc = content(repo, sha, ".yarnrc.yml") if ".yarnrc.yml" in names else None
    nvmrc = next((content(repo, sha, n) for n in (".nvmrc", ".node-version") if n in names), None)
    rule, why = build_rule(stack, d, files, root_pkg, yarnrc, site_pkg, cfg_text, nvmrc, out_dir)
    if why:
        row["reason"] = why
        return row
    row.update(outcome="candidate", build_command=rule[0], site_dir=rule[1], node_version=rule[2])
    return row


# ---------------------------------------------------------------- commands

def cmd_frame(args):
    for stack, queries, _, _ in STACKS:
        path = os.path.join(HERE, "frame-{0}.json".format(stack))
        if os.path.exists(path):
            print("kept", path, "(the frame is taken once)")
            continue
        items = []
        for q in queries:
            for page in range(1, 11):
                # A failed page must stop the frame, never shorten it: it is taken once.
                for attempt in range(6):
                    r = subprocess.run(["gh", "api", "-X", "GET", "search/code", "-f", "q=" + q,
                                        "-f", "per_page=100", "-f", "page={0}".format(page)],
                                       capture_output=True, text=True, encoding="utf-8")
                    if r.returncode == 0:
                        break
                    time.sleep(60)
                else:
                    sys.exit("search failed for {0!r} page {1}; no frame written for {2}:\n{3}".format(
                        q, page, stack, r.stderr[-500:]))
                got = json.loads(r.stdout).get("items", [])
                items += [{"repo": i["repository"]["full_name"], "path": i["path"], "query": q} for i in got]
                time.sleep(7)       # code search allows 10 requests a minute
                if len(got) < 100:
                    break
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"taken_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "queries": queries, "items": items}, fh, indent=1)
        print(stack, len(items), "results ->", path)
    return 0


def selected():
    path = os.path.join(BENCH, "replay", "repos.json")
    with open(path, encoding="utf-8") as fh:
        return {e["repo"] for e in json.load(fh) if e.get("stack")}


def cmd_draw(args):
    skip = selected() if args.after_sample else set()
    rows, cands = [], []
    for stack, _, pattern, out_dir in STACKS:
        with open(os.path.join(HERE, "frame-{0}.json".format(stack)), encoding="utf-8") as fh:
            frame = reduce_frame(json.load(fh)["items"], pattern)
        order = draw_order(frame)
        with open(os.path.join(HERE, "order-{0}.json".format(stack)), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(order, fh, indent=0)
        found = 0
        for rank, repo in enumerate(order, 1):
            if found >= args.per_stack:
                break
            if repo in skip:
                rows.append(dict({k: "" for k in DRAW_FIELDS}, stack=stack, rank=rank, repo=repo,
                                 outcome="in sample", reason="taken for the replay sample"))
                continue
            row = dict(evaluate(stack, repo, frame[repo], out_dir), stack=stack, rank=rank)
            rows.append(row)
            print(stack, rank, repo, row["outcome"], row["reason"], flush=True)
            if row["outcome"] == "candidate":
                found += 1
                cands.append({"repo": repo, "stack": stack, "rank": rank, "ref_cutoff": CUTOFF,
                              "commits": 0, "build_command": row["build_command"],
                              "site_dir": row["site_dir"], "node_version": row["node_version"]})
    out = args.out or os.path.join(HERE, "candidates.json")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(cands, fh, indent=2)
    log = os.path.join(os.path.dirname(os.path.abspath(out)), "draw.csv")
    with open(log, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=DRAW_FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows({k: r.get(k, "") for k in DRAW_FIELDS} for r in rows)
    print("{0} candidates -> {1}; every repository looked at -> {2}".format(len(cands), out, log))
    return 0


def built(b):
    """Whether a build-check row counts as built (rule 6). A build whose output holds no
    HTML pages counts as a missing output folder (Addendum 7); sitemend failing on a real
    site still counts as built, and is a tool failure (Addendum 1)."""
    if b["status"] == "ok":
        return True
    return b["status"] == "audit_failed" and "crawled 0 pages" not in (b.get("error") or "")


def cmd_select(args):
    with open(os.path.join(HERE, "candidates.json"), encoding="utf-8") as fh:
        cands = json.load(fh)
    checked = {}
    for p in args.builds:
        with open(p, encoding="utf-8", newline="") as fh:
            for b in csv.DictReader(fh):
                checked[b["repo"]] = ("built" if built(b) else "no pages" if b["status"] == "audit_failed"
                                      else "build failed")
    repos, rows = [], []
    for stack, _, _, _ in STACKS:
        mine = sorted((c for c in cands if c["stack"] == stack), key=lambda c: c["rank"])
        taken = 0
        for c in mine:
            status = checked.get(c["repo"], "not checked")
            if taken < TAKE and status == "built":
                taken += 1
                status = "taken"
                repos.append(dict({k: c[k] for k in ("repo", "stack", "ref_cutoff", "build_command",
                                                     "site_dir", "node_version")}, commits=N))
            elif status == "built":
                status = "built, not needed"
            rows.append((stack, c["rank"], c["repo"], status))
            if taken == TAKE and status == "not checked":
                break
        if taken < TAKE:
            print("{0}: only {1} of {2} built; draw more with a larger --per-stack".format(stack, taken, TAKE))
    with open(os.path.join(BENCH, "replay", "repos.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(repos, fh, indent=2)
        fh.write("\n")
    with open(os.path.join(HERE, "selection.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["stack", "rank", "repo", "build_check"])
        w.writerows(rows)
    print(len(repos), "repositories -> bench/replay/repos.json; outcomes -> selection.csv")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("frame")
    d = sub.add_parser("draw")
    d.add_argument("--per-stack", type=int, default=8, help="eligible candidates to find per stack")
    d.add_argument("--after-sample", action="store_true", help="skip the repositories already taken")
    d.add_argument("--out", help="candidates file (default candidates.json here)")
    s = sub.add_parser("select")
    s.add_argument("--builds", nargs="+", required=True, help="builds CSVs from the build check")
    args = ap.parse_args(argv)
    return {"frame": cmd_frame, "draw": cmd_draw, "select": cmd_select}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
