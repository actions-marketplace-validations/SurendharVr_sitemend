"""Regression tests for the sitemend skill.

These exist because this tool's only value is that its findings can be trusted. Every
test below pins down a calibration decision that was made deliberately after a real
false positive or false negative -- the kind of thing a well-meaning "improvement"
silently undoes. If a test fails, the question is not "how do I make it pass" but
"was this behaviour meant to change".

Fixtures are generated into a temp directory, so there are no fixture files to drift.

Run:  python tests/test_skill.py            (from the skill root)
      python -m unittest discover -s tests  (equivalent)
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import audit          # noqa: E402
import crawl          # noqa: E402
import report         # noqa: E402
import schema_check   # noqa: E402
import sitemend     # noqa: E402
import seolib as S    # noqa: E402
import verify as V    # noqa: E402
import vitals          # noqa: E402


def page_html(title="A Perfectly Reasonable Page Title Here",
              desc=("A meta description of entirely unremarkable length that sits "
                    "comfortably inside the seventy to one hundred sixty character band."),
              body="<h1>Heading</h1><p>" + ("word " * 300) + "</p>",
              head_extra="", lang="en", viewport=True):
    vp = '<meta name="viewport" content="width=device-width, initial-scale=1">' if viewport else ""
    return (
        '<!doctype html><html lang="{lang}"><head><meta charset="utf-8">{vp}'
        "<title>{title}</title>"
        '<meta name="description" content="{desc}">{head_extra}</head>'
        "<body><main>{body}</main></body></html>"
    ).format(lang=lang, vp=vp, title=title, desc=desc, head_extra=head_extra, body=body)


class Fixture:
    """A throwaway site on disk."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="sitemend-test-")

    def write(self, relpath, content):
        full = os.path.join(self.root, relpath.replace("/", os.sep))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
        return full

    def write_bytes(self, relpath, nbytes):
        full = os.path.join(self.root, relpath.replace("/", os.sep))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(b"\0" * nbytes)
        return full

    def crawl(self):
        (pages, assets, robots, sitemap, extras, excluded,
         skipped, refs, names, base_path) = crawl.crawl_fs(self.root)
        rb = S.Robots(robots)
        for p in pages:
            allowed, rule = rb.check(p["url"])
            p["robots_allowed"] = allowed
            p["robots_rule"] = rule
        sm_urls, _ = S.parse_sitemap(sitemap)
        return {
            "meta": {"source": self.root, "mode": "fs", "page_count": len(pages),
                     "base_url": None, "excluded_dirs_present": excluded, "base_path": base_path},
            "robots": {"found": bool(robots), "sitemaps": rb.sitemaps, "groups": [], "raw": robots},
            "sitemap": {"found": bool(sitemap), "urls": sm_urls, "notes": [],
                        "lastmods": S.parse_sitemap_lastmods(sitemap)},
            "assets": assets, "pages": pages, "extras": {},
            "referenced_assets": refs, "referenced_basenames": names,
        }

    def audit(self):
        return audit.audit(self.crawl())

    def ids(self):
        return [f["id"] for f in self.audit()["findings"]]

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


class Base(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.cleanup)


# --------------------------------------------------------------- URL handling

class TestUrlMapping(Base):
    def test_both_conventions(self):
        """Clean-URL directories and flat .html files must both map correctly.
        Real sites in use here do it both ways."""
        self.assertEqual(S.file_to_urls("index.html")[0], "/")
        self.assertEqual(S.file_to_urls("about/index.html")[0], "/about/")
        self.assertEqual(S.file_to_urls("services.html")[0], "/services.html")

    def test_aliases_let_clean_links_resolve_to_flat_files(self):
        """A link written href="/services" must not report as broken on a site
        whose file is services.html."""
        _, aliases = S.file_to_urls("services.html")
        self.assertIn("/services", aliases)

    def test_index_collapsing(self):
        """REGRESSION: http mode fetched / and /index.html as two pages and called
        them a critical duplicate. Relative href="index.html" links are ordinary."""
        self.assertEqual(S.canonical_http_path("/index.html"), "/")
        self.assertEqual(S.canonical_http_path("/foo/index.html"), "/foo/")
        self.assertEqual(S.canonical_http_path("/services.html"), "/services.html")
        self.assertEqual(S.canonical_http_path("/"), "/")

    def test_no_broken_link_for_clean_url_to_flat_file(self):
        self.fx.write("index.html", page_html(
            body='<h1>H</h1><p><a href="/services">Services</a></p>' + "word " * 300))
        self.fx.write("services.html", page_html(title="Services Page With A Fine Title Here"))
        self.assertNotIn("S1-BROKEN-LINK", self.fx.ids())

    def test_any_non_http_scheme_is_not_a_page_link(self):
        """REGRESSION found by the 2026-10-16 audit: skype:, viber:, geo: and ftp: links
        resolved to /skype:echo123 and were reported as high S1-BROKEN-LINK."""
        for href in ("skype:echo123?call", "viber://chat?number=1", "geo:37.7,-122.4",
                     "ftp://files.x.org/a.zip", "mailto:a@b.c", "tel:+1"):
            with self.subTest(href=href):
                self.assertEqual(S.link_kind(href), "nonhttp")
        for href in ("https://x.org/", "http://x.org/", "/a", "page.html", "./a:b"):
            with self.subTest(href=href):
                self.assertEqual(S.link_kind(href), "link")

    def test_no_broken_link_for_app_scheme_links(self):
        self.fx.write("index.html", page_html(
            body='<h1>H</h1><p><a href="skype:echo123?call">Skype</a> ' + "word " * 300 + "</p>"))
        self.assertNotIn("S1-BROKEN-LINK", self.fx.ids())


class TestAbsoluteInternalLinks(Base):
    """REGRESSION found by the 2026-10-16 audit: links written as absolute URLs on the
    site's own origin were ignored, so every page of a Hugo/Jekyll-style site was a high
    S2-ORPHAN and S2-UNREACHABLE, and its real broken links went unreported."""

    def _findings(self, other=False):
        host = "https://other.org" if other else "https://site.org"
        self.fx.write("index.html", page_html(
            body='<h1>H</h1><p><a href="https://site.org/about/">About</a> ' + "word " * 300 + "</p>"))
        self.fx.write("about/index.html", page_html(
            title="About Page With A Fine Long Title",
            body='<h1>A</h1><p><a href="https://site.org/">Home</a> <a href="{0}/gone/">x</a> '
                 .format(host) + "more " * 300 + "</p>"))
        doc = self.fx.crawl()
        doc["meta"]["base_url"] = "https://site.org"
        return audit.audit(doc)["findings"]

    def test_same_origin_absolute_links_are_inlinks(self):
        ids = [f["id"] for f in self._findings()]
        self.assertNotIn("S2-ORPHAN", ids)
        self.assertNotIn("S2-UNREACHABLE", ids)

    def test_same_origin_absolute_link_to_a_missing_page_is_broken(self):
        broken = [f for f in self._findings() if f["id"] == "S1-BROKEN-LINK"]
        self.assertEqual([f["detail"]["target"] for f in broken], ["/gone/"])

    def test_another_origin_is_still_external(self):
        self.assertNotIn("S1-BROKEN-LINK", [f["id"] for f in self._findings(other=True)])


# --------------------------------------------------------------- exclusions

class TestExclusions(Base):
    def test_build_output_excluded(self):
        """REGRESSION: a dist/ copy of the site made every real page look like a
        duplicate. This is the single highest-volume false positive available."""
        self.fx.write("index.html", page_html())
        self.fx.write("dist/index.html", page_html())
        self.fx.write("node_modules/pkg/readme.html", page_html())
        doc = self.fx.crawl()
        self.assertEqual([p["url"] for p in doc["pages"]], ["/"])
        self.assertNotIn("S3-DUPLICATE-EXACT", self.fx.ids())

    def test_noindex_404_is_not_a_defect(self):
        """A noindex 404 is correct. Reporting it as a finding trains the user to
        ignore the report."""
        self.fx.write("index.html", page_html())
        self.fx.write("404.html", page_html(title="Not Found Page Title Goes Right Here",
                                            head_extra='<meta name="robots" content="noindex">'))
        res = self.fx.audit()
        self.assertIn("/404.html", [i["url"] for i in res["intentional"]])
        self.assertNotIn("S1-NOT-INDEXABLE", [f["id"] for f in res["findings"]])

    def test_robots_disallowed_noindex_is_deliberate(self):
        self.fx.write("index.html", page_html())
        self.fx.write("studio/index.html", page_html(
            title="Internal Studio Tool Page Title", head_extra='<meta name="robots" content="noindex">'))
        self.fx.write("robots.txt", "User-agent: *\nAllow: /\nDisallow: /studio/\n")
        res = self.fx.audit()
        self.assertIn("/studio/", [i["url"] for i in res["intentional"]])

    def test_sitemap_plus_blocked_is_critical(self):
        """The one case that IS always a defect: the site contradicting itself."""
        self.fx.write("index.html", page_html())
        self.fx.write("secret.html", page_html(title="Secret Page Title That Is Long Enough",
                                               head_extra='<meta name="robots" content="noindex">'))
        self.fx.write("sitemap.xml",
                      "<urlset><url><loc>https://e.com/</loc></url>"
                      "<url><loc>https://e.com/secret.html</loc></url></urlset>")
        f = self.fx.audit()["findings"]
        crit = [x for x in f if x["id"] == "S1-INDEX-CONTRADICTION"]
        self.assertTrue(crit, "sitemap-listed blocked page must be critical")
        self.assertEqual(crit[0]["severity"], "critical")

    def test_robots_blocking_the_homepage_is_not_deliberate(self):
        """REGRESSION found by the v1.0.3 review: `Disallow: /` with a sitemap that
        lists nothing filed every page as a deliberate exclusion, so Gate A read
        CLEAR 'every crawled page is indexable'."""
        self.fx.write("index.html", page_html())
        self.fx.write("about.html", page_html(title="About Us Page Title That Is Long Enough"))
        self.fx.write("robots.txt", "User-agent: *\nDisallow: /\n")
        self.fx.write("sitemap.xml", "<urlset></urlset>")
        res = self.fx.audit()
        gate_a = [g for g in res["gates"] if g["gate"] == "A"][0]
        self.assertEqual(gate_a["status"], "BLOCKED")
        self.assertIn("/", gate_a["pages"])
        crit = [f for f in res["findings"]
                if f["id"] == "S1-NOT-INDEXABLE" and f["severity"] == "critical"]
        self.assertTrue(crit, "a robots-blocked homepage is never a deliberate exclusion")


class TestRobotsGroups(unittest.TestCase):
    """REGRESSION found by the 2026-10-16 audit: only the first User-agent: * group was
    read. RFC 9309 combines every group that matches the same agent."""

    TXT = ("User-agent: *\nDisallow: /admin/\n\nUser-agent: Googlebot\nDisallow: /tmp/\n\n"
           "User-agent: *\nDisallow: /private/\n")

    def test_groups_for_the_same_agent_are_merged(self):
        r = S.Robots(self.TXT)
        self.assertEqual(r.check("/private/x"), (False, "Disallow: /private/"))
        self.assertEqual(r.check("/admin/x"), (False, "Disallow: /admin/"))
        self.assertEqual(r.check("/tmp/x"), (True, None))

    def test_a_named_agent_still_ignores_the_star_groups(self):
        r = S.Robots(self.TXT)
        self.assertEqual(r.check("/admin/x", agent="Googlebot"), (True, None))
        self.assertEqual(r.check("/tmp/x", agent="Googlebot"), (False, "Disallow: /tmp/"))


# --------------------------------------------------------------- Gate A

class TestGateA(Base):
    def test_no_stage3_findings_on_nonindexable_page(self):
        """Gate A in code: optimising a title Google will never read is waste, and
        raising it buries the indexability problem that actually matters."""
        self.fx.write("index.html", page_html())
        self.fx.write("hidden.html",
                      '<!doctype html><html><head><meta name="robots" content="noindex">'
                      "<title>x</title></head><body><p>thin</p></body></html>")
        for f in self.fx.audit()["findings"]:
            if "/hidden.html" in f["pages"]:
                self.assertLessEqual(f["stage"], 1,
                                     "stage {0} finding raised on a non-indexable page: {1}"
                                     .format(f["stage"], f["id"]))


class TestIndexContradictionAliases(Base):
    """REGRESSION found by the 2026-10-16 audit: a noindex services.html listed in the
    sitemap as /services was medium S1-NOT-INDEXABLE, not the critical contradiction."""

    def test_clean_url_in_sitemap_for_a_noindex_flat_file(self):
        self.fx.write("index.html", page_html(
            body='<h1>H</h1><p><a href="/services">s</a> ' + "word " * 300 + "</p>"))
        self.fx.write("services.html", page_html(
            title="Services Page With A Fine Title Here",
            head_extra='<meta name="robots" content="noindex">'))
        self.fx.write("sitemap.xml", "<urlset><url><loc>https://x.org/</loc></url>"
                                     "<url><loc>https://x.org/services</loc></url></urlset>")
        hit = [f for f in self.fx.audit()["findings"] if f["id"] == "S1-INDEX-CONTRADICTION"]
        self.assertEqual([f["pages"] for f in hit], [["/services.html"]])


# --------------------------------------------------------------- grouping

class TestGrouping(Base):
    def test_shared_component_grouped_once(self):
        """REGRESSION: one heading skip in a shared footer was counted five times,
        making a single fix look like five."""
        body = "<h1>T</h1><h2>S</h2><h5>Shared Footer Heading</h5><p>" + "word " * 300 + "</p>"
        for name in ("index.html", "a.html", "b.html"):
            self.fx.write(name, page_html(title="Distinct Title For " + name + " Here Ok",
                                          body=body))
        skips = [f for f in self.fx.audit()["findings"] if f["id"] == "S2-HEADING-SKIP"]
        self.assertEqual(len(skips), 1, "identical evidence must group into one finding")
        self.assertGreaterEqual(skips[0].get("affects", 1), 3)


    def test_distinct_pairs_are_not_merged(self):
        """REGRESSION: near-duplicate findings are pairwise. Grouping them by evidence
        merged two unrelated pairs that scored the same similarity into one finding
        claiming all four pages duplicated each other."""
        a = {"id": "S3-NEAR-DUPLICATE", "pages": ["/a", "/b"], "evidence": "estimated Jaccard 0.88",
             "severity": "high", "stage": 3, "message": "m"}
        b = {"id": "S3-NEAR-DUPLICATE", "pages": ["/c", "/d"], "evidence": "estimated Jaccard 0.88",
             "severity": "high", "stage": 3, "message": "m"}
        grouped = audit.group_findings([a, b])
        self.assertEqual(len(grouped), 2, "distinct page pairs must stay separate")
        self.assertEqual([sorted(g["pages"]) for g in grouped], [["/a", "/b"], ["/c", "/d"]])

    def test_cannibalization_suppressed_when_duplicate(self):
        """Duplicate content and cannibalization on the same pair are one root
        cause; reporting both doubles the noise."""
        html = page_html(title="Exactly The Same Title On Both Of These Pages")
        self.fx.write("index.html", html)
        self.fx.write("copy.html", html)
        ids = self.fx.ids()
        self.assertIn("S3-DUPLICATE-EXACT", ids)
        self.assertNotIn("S3-CANNIBALIZATION", ids)

    def test_heading_skip_evidence_names_the_skipping_heading(self):
        """REGRESSION found by the v1.0.3 review: the evidence quoted the first H4
        after the first H2, which was a legitimate heading, not the one that skipped."""
        body = ("<h1>Top</h1><h2>Two A</h2><h3>Three</h3><h4>Four fine</h4>"
                "<h2>Two B</h2><h4>Skipped to four</h4><p>" + "word " * 300 + "</p>")
        self.fx.write("index.html", page_html(body=body))
        hits = [f for f in self.fx.audit()["findings"] if f["id"] == "S2-HEADING-SKIP"]
        self.assertEqual(len(hits), 1)
        self.assertIn("Skipped to four", hits[0]["evidence"])

    def _canonical_ids(self, canonical):
        self.fx.write("index.html", page_html(
            head_extra='<link rel="canonical" href="{0}">'.format(canonical)))
        doc = self.fx.crawl()
        doc["meta"]["base_url"] = "https://example.com"
        return [f["id"] for f in audit.audit(doc)["findings"]]

    def test_canonical_on_a_lookalike_domain_is_offsite(self):
        """REGRESSION found by the v1.0.3 review: a string-prefix test let
        https://example.community pass as https://example.com."""
        self.assertIn("S1-CANONICAL-OFFSITE", self._canonical_ids("https://example.community/"))

    def test_canonical_on_the_same_origin_is_not_offsite(self):
        self.assertNotIn("S1-CANONICAL-OFFSITE", self._canonical_ids("https://example.com/"))

    def _cannibal_pairs(self):
        pairs = set()
        for f in self.fx.audit()["findings"]:
            if f["id"] == "S3-CANNIBALIZATION":
                pairs.add(frozenset(f["pages"]))
        return pairs

    def _write(self, path, title, desc, tag):
        body = "<h1>{0}</h1><p>{1}</p>".format(tag, (tag + " ") * 300)
        self.fx.write(path, page_html(title=title, desc=desc, body=body))

    def test_templated_siblings_do_not_cannibalize(self):
        """REGRESSION from the first real-site run (a catering site): five menu pages
        sharing 'catering menu set dish' template words each flagged against the other
        four, ten high findings for pages that target five different occasions. Terms
        on a large share of the site are template words, not intent."""
        for occ in ("lunch", "dinner", "tiffin", "housewarming", "seemantham"):
            self._write("menu/%s/index.html" % occ,
                        "%s Catering Menu Pure Veg Sets Kitchen" % occ.title(),
                        "Every %s set menu dish listed for Pure Veg Catering in Kitchen "
                        "menus and sets across the city." % occ, occ)
        for n, t in enumerate(("Alpha Gallery Photos", "Bravo Contact Form", "Charlie Hiring")):
            self._write("p%d/index.html" % n, t, "Distinct %s page content here." % t, t.split()[0])
        self.assertEqual(self._cannibal_pairs(), set())

    def test_real_cannibal_pair_still_flagged_among_templated_siblings(self):
        """The template-word filter must not blind the check: two pages chasing the
        same distinguishing terms are still reported."""
        for occ in ("lunch", "dinner", "tiffin", "housewarming", "seemantham"):
            self._write("menu/%s/index.html" % occ,
                        "%s Catering Menu Pure Veg Sets Kitchen" % occ.title(),
                        "Every %s set menu dish listed for Pure Veg Catering in Kitchen "
                        "menus and sets across the city." % occ, occ)
        for p, tag in (("wedding-a", "alpha"), ("wedding-b", "bravo")):
            self._write(p + "/index.html", "Chennai Wedding Reception Hall Booking",
                        "Book a Chennai wedding reception hall with parking.", tag)
        self.assertEqual(self._cannibal_pairs(),
                         {frozenset(("/wedding-a/", "/wedding-b/"))})

    def test_grouping_a_site_wide_finding_is_linear(self):
        """A finding with the same evidence on every page (no breadcrumbs, no Open Graph
        tags) groups into one. Checking membership in the page list made that quadratic:
        17 s for 40,000 pages, and 9 s of a 10,000-page audit."""
        fs = [{"id": "S2-BREADCRUMB-MISSING", "pages": ["/p%d" % i],
               "evidence": "jsonld types: none", "severity": "low", "stage": 2,
               "message": "m"} for i in range(40000)]
        fs.append(dict(fs[0]))                     # the same page twice counts once
        t = time.perf_counter()
        grouped = audit.group_findings(fs)
        self.assertLess(time.perf_counter() - t, 3.0)
        self.assertEqual(len(grouped), 1)
        self.assertEqual(grouped[0]["affects"], 40000)
        self.assertEqual(len(grouped[0]["pages"]), 40000)


class TestPairwiseCandidates(unittest.TestCase):
    """The near-duplicate and cannibalization checks compare only candidate pairs. The
    filters must be lossless at the current thresholds: a pair the exhaustive loop would
    report and the filter drops is a silent false negative, the worst kind for a tool
    whose findings have to be trusted."""

    def _sig_pages(self, seed=11):
        import random
        rnd = random.Random(seed)
        pages = []
        for _ in range(12):                       # 12 clusters of 25 around a base
            base = [rnd.getrandbits(61) for _ in range(S.MINHASH_N)]
            for _ in range(25):
                sig = list(base)
                for pos in rnd.sample(range(S.MINHASH_N), rnd.randint(0, 30)):
                    sig[pos] = rnd.getrandbits(61)
                pages.append({"minhash": sig, "word_count": 400})
        return pages

    def test_near_duplicate_candidates_include_every_pair_at_the_threshold(self):
        pages = self._sig_pages()
        cand = set(audit.near_dup_candidates(pages))
        hits = 0
        for i in range(len(pages)):
            for j in range(i + 1, len(pages)):
                sim = S.minhash_similarity(pages[i]["minhash"], pages[j]["minhash"])
                if sim >= audit.NEAR_DUP:
                    hits += 1
                    self.assertIn((i, j), cand, "pair at {0:.3f} not compared".format(sim))
        self.assertGreater(hits, 100, "fixture must put pairs on both sides of 0.80")

    def test_worst_case_near_duplicate_is_a_candidate(self):
        """12 differing values, one in each of the first 12 bands: the most a pair at
        0.80 can differ. Only the last four bands still match."""
        a = list(range(S.MINHASH_N))
        b = list(a)
        r = S.MINHASH_N // audit.BANDS
        for band in range(12):
            b[band * r] = -1
        self.assertGreaterEqual(S.minhash_similarity(a, b), audit.NEAR_DUP)
        pages = [{"minhash": a, "word_count": 400}, {"minhash": b, "word_count": 400}]
        self.assertEqual(audit.near_dup_candidates(pages), [(0, 1)])

    def test_unrelated_pages_are_not_candidates(self):
        """The point of the filter: 300 unrelated pages give no candidates."""
        import random
        rnd = random.Random(5)
        pages = [{"minhash": [rnd.getrandbits(61) for _ in range(S.MINHASH_N)],
                  "word_count": 400} for _ in range(300)]
        self.assertEqual(audit.near_dup_candidates(pages), [])

    def test_short_pages_are_not_candidates(self):
        sig = list(range(S.MINHASH_N))
        pages = [{"minhash": sig, "word_count": 400}, {"minhash": sig, "word_count": 49}]
        self.assertEqual(audit.near_dup_candidates(pages), [])

    def _jaccard(self, a, b):
        return len(a & b) / len(a | b)

    def _term_sets(self, seed=3, n=600):
        """Template words on a quarter of the pages each (under the 35% boiler cut),
        clusters sharing 6 to 11 of 12 terms, Zipf filler."""
        import random
        rnd = random.Random(seed)
        vocab = ["t%d" % i for i in range(800)]
        weights = [1 / (i + 1) for i in range(800)]
        sigs, urls = {}, []
        for i in range(n):
            s = {"section%d" % (i % 4)}
            if i < 240:
                core = random.Random(i // 12).sample(vocab[100:], 12)
                s |= set(core[:rnd.randint(6, 11)])
            while len(s) < 12:
                s.add(rnd.choices(vocab, weights)[0])
            urls.append("/%d" % i)
            sigs[urls[-1]] = s
        return urls, sigs

    def test_cannibal_candidates_include_every_pair_at_the_threshold(self):
        urls, sigs = self._term_sets()
        cand = set(audit.cannibal_candidates(urls, sigs))
        hits = 0
        for i in range(len(urls)):
            for j in range(i + 1, len(urls)):
                if self._jaccard(sigs[urls[i]], sigs[urls[j]]) >= audit.CANNIBAL_TERMS:
                    hits += 1
                    self.assertIn((i, j), cand)
        self.assertGreater(hits, 100, "fixture must put pairs on both sides of 0.60")

    def test_cannibal_candidates_handle_short_and_empty_sets(self):
        """After template words are removed a page can keep 1 or 0 terms. One shared
        term out of one is Jaccard 1.0 and must be compared; an empty set never is."""
        urls = ["/a", "/b", "/c"]
        sigs = {"/a": {"widget"}, "/b": {"widget"}, "/c": set()}
        self.assertEqual(audit.cannibal_candidates(urls, sigs), [(0, 1)])

    def test_templated_terms_do_not_make_every_pair_a_candidate(self):
        """Guard against the rejected design: indexing every term makes 71% of these
        pairs candidates (prefix filtering: 4%), and on a 4,000-page templated set it
        ran slower than comparing every pair."""
        urls, sigs = self._term_sets()
        total = len(urls) * (len(urls) - 1) // 2
        self.assertLess(len(audit.cannibal_candidates(urls, sigs)), total // 10)


# --------------------------------------------------------------- thresholds

class TestThresholds(Base):
    def _title_ids(self, title):
        self.fx.write("index.html", page_html(title=title))
        return self.fx.ids()

    def test_62_char_title_not_flagged(self):
        """50-60 is a target, not a cliff -- the real constraint is pixel width.
        Flagging 62 chars trains the user to ignore low findings."""
        t = "A" * 62
        self.assertNotIn("S3-TITLE-LONG", self._title_ids(t))

    def test_70_char_title_flagged(self):
        self.assertIn("S3-TITLE-LONG", self._title_ids("A" * 70))


# --------------------------------------------------------------- headings

class TestHeadingOrder(Base):
    def test_document_order_preserved(self):
        """REGRESSION: headings were collected level-by-level, silently sorting them.
        That turned 'H2 then H5' into 'the page uses h3 and h5'."""
        self.fx.write("index.html", page_html(
            body="<h1>Alpha</h1><h2>Bravo</h2><h3>Charlie</h3><h2>Delta</h2><h5>Echo</h5>"
                 "<p>" + "word " * 300 + "</p>"))
        heads = self.fx.crawl()["pages"][0]["headings"]
        self.assertEqual([h["text"] for h in heads],
                         ["Alpha", "Bravo", "Charlie", "Delta", "Echo"])
        self.assertEqual([h["level"] for h in heads], [1, 2, 3, 2, 5])

    def test_skip_names_the_real_pair(self):
        """The reported jump must be the actual adjacent pair (H2->H5), not an
        artefact of sorted levels (H3->H5)."""
        self.fx.write("index.html", page_html(
            body="<h1>Alpha</h1><h2>Bravo</h2><h3>Charlie</h3><h2>Delta</h2><h5>Echo</h5>"
                 "<p>" + "word " * 300 + "</p>"))
        skips = [f for f in self.fx.audit()["findings"] if f["id"] == "S2-HEADING-SKIP"]
        self.assertTrue(skips)
        self.assertIn("H2 -> H5", skips[0]["evidence"])
        self.assertIn("Echo", skips[0]["evidence"])

    def test_well_formed_headings_not_flagged(self):
        self.fx.write("index.html", page_html(
            body="<h1>A</h1><h2>B</h2><h3>C</h3><h2>D</h2><p>" + "word " * 300 + "</p>"))
        self.assertNotIn("S2-HEADING-SKIP", self.fx.ids())


# --------------------------------------------------------------- images

class TestImages(Base):
    def test_relative_image_size_is_checked(self):
        """REGRESSION: the size lookup only fired for root-relative src, so a site
        using assets/x.png was never checked -- and said nothing rather than
        admitting it could not check."""
        self.fx.write_bytes("assets/big.jpg", 300 * 1024)
        self.fx.write("services.html", page_html(
            title="Services Page With Heavy Imagery Here",
            body='<h1>S</h1><img src="assets/big.jpg" alt="big" width="10" height="10">'
                 "<p>" + "word " * 300 + "</p>"))
        heavy = [f for f in self.fx.audit()["findings"] if f["id"] == "S3-IMG-HEAVY"]
        self.assertTrue(heavy, "relative image src must be resolved and size-checked")
        self.assertIn("assets/big.jpg", heavy[0]["evidence"])

    def test_small_image_not_flagged(self):
        self.fx.write_bytes("assets/small.jpg", 10 * 1024)
        self.fx.write("index.html", page_html(
            body='<h1>S</h1><img src="assets/small.jpg" alt="s" width="10" height="10">'
                 "<p>" + "word " * 300 + "</p>"))
        self.assertNotIn("S3-IMG-HEAVY", self.fx.ids())

    def test_empty_alt_is_not_missing_alt(self):
        """alt="" on a decorative image is correct, and is not the same as no alt."""
        self.fx.write("index.html", page_html(
            body='<h1>S</h1><img src="/d.png" alt="" width="1" height="1">'
                 "<p>" + "word " * 300 + "</p>"))
        self.assertNotIn("S3-IMG-ALT-MISSING", self.fx.ids())


# --------------------------------------------------------------- gates

class TestGates(Base):
    def test_gates_are_emitted_by_audit(self):
        self.fx.write("index.html", page_html())
        gates = self.fx.audit()["gates"]
        self.assertEqual([g["gate"] for g in gates], ["A", "B", "C"])

    def test_gate_a_clear_when_every_page_indexable(self):
        """REGRESSION: the report re-derived Gate A from stage-1 severity, so a site
        with no robots.txt (stage-1 high) but every page indexable printed
        'Gate A: BLOCKED' beside a rule about non-indexable pages."""
        self.fx.write("index.html", page_html())   # no robots.txt, no sitemap
        res = self.fx.audit()
        ids = [f["id"] for f in res["findings"]]
        self.assertIn("S1-ROBOTS-MISSING", ids)
        gate_a = [g for g in res["gates"] if g["gate"] == "A"][0]
        self.assertEqual(gate_a["status"], "CLEAR",
                         "Gate A is about non-indexable pages, not stage-1 severity")

    def test_gate_a_blocked_names_the_pages(self):
        self.fx.write("index.html", page_html())
        self.fx.write("blocked.html", page_html(
            title="A Blocked Page Title Long Enough Here",
            head_extra='<meta name="robots" content="noindex">'))
        self.fx.write("robots.txt", "User-agent: *\nAllow: /\n")   # not deliberate
        gate_a = [g for g in self.fx.audit()["gates"] if g["gate"] == "A"][0]
        self.assertEqual(gate_a["status"], "BLOCKED")
        self.assertIn("/blocked.html", gate_a["pages"])

    def test_gate_c_blocks_on_open_critical(self):
        html = page_html(title="Identical Title Across Two Different Pages")
        self.fx.write("index.html", html)
        self.fx.write("dupe.html", html)
        gate_c = [g for g in self.fx.audit()["gates"] if g["gate"] == "C"][0]
        self.assertEqual(gate_c["status"], "BLOCKED")


class TestReport(Base):
    GATES = {"gates": [{"gate": "A", "name": "n", "rule": "r", "status": "CLEAR", "detail": "d"}]}

    def test_report_states_how_many_pages_were_rendered(self):
        """A rendered crawl that silently rendered 50 of 200 pages is a coverage claim the
        reader cannot check; the honesty contract says to state it."""
        meta = {"source": "https://x.test/", "page_count": 5, "mode": "http",
                "render": True, "rendered_pages": 2, "render_limit": 2}
        md = report.build_markdown({"meta": meta, "pages": []}, self.GATES, [], None, "x.test")
        self.assertIn("2 of 5 pages", md)
        self.assertIn("limit 2", md)

    def test_plain_report_says_nothing_about_rendering(self):
        meta = {"source": "https://x.test/", "page_count": 5, "mode": "http"}
        md = report.build_markdown({"meta": meta, "pages": []}, self.GATES, [], None, "x.test")
        self.assertNotIn("JavaScript rendering", md)

    def test_audit_records_whether_schema_was_checked(self):
        self.fx.write("index.html", page_html())
        doc = self.fx.crawl()
        self.assertIs(audit.audit(doc, None, [])["schema_checked"], True)
        self.assertIs(audit.audit(doc)["schema_checked"], False)

    def test_clean_schema_run_counts_as_stage_5_assessed(self):
        """REGRESSION found by the v1.0.3 review: a schema check that ran and found
        nothing was reported 'not-measured'."""
        self.assertTrue(report.stage5_ran({"meta": {"schema_checked": True}}, []))
        self.assertFalse(report.stage5_ran({"meta": {}}, []))
        self.assertTrue(report.stage5_ran({"meta": {}}, [{"stage": 5}]))

    def test_rerun_block_uses_the_cli_for_both_modes(self):
        """REGRESSION found by the v1.0.3 review: the block omitted schema_check and
        passed a URL to crawl.py --root."""
        crawl_doc = {"meta": {"source": "https://x.test/", "page_count": 0, "mode": "http"},
                     "pages": []}
        fdoc = {"gates": [{"gate": "A", "name": "n", "rule": "r", "status": "CLEAR",
                           "detail": "d"}]}
        md = report.build_markdown(crawl_doc, fdoc, [], None, "x.test")
        self.assertIn('sitemend.py audit "https://x.test/"', md)
        self.assertNotIn("--root", md)


# --------------------------------------------------------------- cli

class TestCli(Base):
    def test_audit_writes_every_artifact_and_edits_nothing(self):
        self.fx.write("index.html", page_html())
        before = sorted(os.listdir(self.fx.root))
        out = os.path.join(tempfile.mkdtemp(prefix="sitemend-out-"), "o")
        self.addCleanup(shutil.rmtree, os.path.dirname(out), True)
        findings = sitemend.audit(self.fx.root, out, 200, None)
        names = os.listdir(out)
        for want in ("crawl.json", "schema.json", "findings.json", "report-data.json",
                     "dashboard.html"):
            self.assertIn(want, names)
        self.assertTrue(any(n.startswith("SEO-REPORT-") for n in names))
        self.assertEqual(sorted(os.listdir(self.fx.root)), before, "audit must not touch the site")
        self.assertGreaterEqual(sitemend.worst_open(findings), -1)

    def test_verify_with_the_baseline_inside_out_still_compares(self):
        """REGRESSION found by the 2026-10-16 audit: README's `verify --baseline
        sitemend-out/findings.json` uses the default --out sitemend-out, so the audit
        overwrote the baseline before verify.py read it, and the gate always passed."""
        self.fx.write("index.html", page_html())
        out = os.path.join(tempfile.mkdtemp(prefix="sitemend-out-"), "o")
        self.addCleanup(shutil.rmtree, os.path.dirname(out), True)
        sitemend.audit(self.fx.root, out, 200, None)
        self.fx.write("index.html", page_html(
            body='<h1>H</h1><p><a href="/gone/">x</a> ' + "word " * 300 + "</p>"))
        r = subprocess.run(
            [sys.executable, os.path.join(sitemend.HERE, "sitemend.py"), "verify", self.fx.root,
             "--baseline", os.path.join(out, "findings.json"), "--out", out],
            capture_output=True, text=True, encoding="utf-8",
            env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        self.assertIn("REGRESSION GATE: FAIL", r.stdout)
        self.assertNotEqual(r.returncode, 0)

    def test_rerun_does_not_audit_its_own_report(self):
        """REGRESSION: with --out inside the audited folder (the default when run as
        `audit .`), the second run crawled the first run's dashboard.html and reported
        7 extra findings on the demo site."""
        self.fx.write("index.html", page_html())
        out = os.path.join(self.fx.root, "sitemend-out")
        counts = []
        for _ in range(2):
            findings = sitemend.audit(self.fx.root, out, 200, None)
            counts.append(len(json.load(open(findings, encoding="utf-8"))["findings"]))
        self.assertEqual(counts[0], counts[1])

    def test_worst_open_ranks_severity(self):
        path = os.path.join(self.fx.root, "f.json")
        with open(path, "w") as f:
            json.dump({"findings": [{"severity": "low"}, {"severity": "high"}]}, f)
        self.assertEqual(sitemend.SEVERITY[sitemend.worst_open(path)], "high")

    def test_output_folder_ignores_itself(self):
        """REGRESSION found by the v1.0.3 review: `audit .` left a full-text crawl.json
        in the audited repo with nothing stopping `git add -A`."""
        self.fx.write("index.html", page_html())
        out = os.path.join(tempfile.mkdtemp(prefix="sitemend-out-"), "o")
        self.addCleanup(shutil.rmtree, os.path.dirname(out), True)
        sitemend.audit(self.fx.root, out, 200, None)
        with open(os.path.join(out, ".gitignore")) as f:
            self.assertEqual(f.read(), "*\n")

    def _verify_args(self):
        d = tempfile.mkdtemp(prefix="sitemend-verify-")
        self.addCleanup(shutil.rmtree, d, True)
        base, cur = os.path.join(d, "b.json"), os.path.join(d, "c.json")
        with open(base, "w") as f:
            json.dump({"findings": []}, f)
        with open(cur, "w") as f:
            json.dump({"findings": [{"id": "X", "severity": "high", "pages": ["/"],
                                     "evidence": "e", "message": "m"}]}, f)
        return ["--baseline", base, "--current", cur, "--out", os.path.join(d, "v.json")]

    def test_failed_regression_gate_is_a_result_not_a_crash(self):
        """REGRESSION found by the v1.0.3 review: verify.py exits 1 on a FAILED gate and
        run() reported that as 'verify.py failed:'."""
        r = sitemend.run("verify.py", *self._verify_args(), ok=(0, 1))
        self.assertEqual(r.returncode, 1)
        self.assertIn("REGRESSION GATE: FAIL", r.stdout)

    def test_unexpected_exit_codes_still_abort(self):
        with self.assertRaises(SystemExit):
            sitemend.run("verify.py", *self._verify_args())

    def test_fail_on_ignores_judgement_calls(self):
        path = os.path.join(self.fx.root, "f.json")
        with open(path, "w") as f:
            json.dump({"findings": [{"severity": "high", "confidence": "medium"},
                                    {"severity": "low"}]}, f)
        self.assertEqual(sitemend.SEVERITY[sitemend.worst_open(path)], "low")

    def test_adding_a_sibling_reference_page_passes_the_gate(self):
        """The 2026-10-16 review's reproduction, end to end: a docs site with hx-get,
        hx-post and hx-put reference pages gains hx-patch. The new cannibalization
        findings are advisory and the gate passes."""
        import random
        rnd = random.Random(3)
        words = ["w%d" % i for i in range(4000)]
        topics = ["install", "config", "routing", "caching", "testing", "deploy", "plugins",
                  "themes", "cli", "faq", "security", "migration"]
        verbs = ["get", "post", "put"]

        def nav():
            return " ".join('<a href="/{0}/">{0}</a>'.format(t)
                            for t in topics + ["hx-" + v for v in verbs])

        def write(slug, title, desc):
            body = "<h1>{0}</h1><p>{1}</p><nav>{2}</nav>".format(
                title, " ".join(rnd.choice(words) for _ in range(400)), nav())
            self.fx.write((slug + "/" if slug else "") + "index.html",
                          page_html(title=title, desc=desc, body=body))

        def verb(v):
            write("hx-" + v, "hx-%s attribute reference for x" % v,
                  "The hx-%s attribute issues a %s request to the specified url and swaps "
                  "the returned element." % (v, v.upper()))

        write("", "X framework documentation home",
              "Documentation for the x framework: guides, reference and every attribute it supports.")
        for t in topics:
            write(t, "%s guide for the x framework docs" % t.title(),
                  "How %s works in the x framework, with examples and every option explained "
                  "in one place." % t)
        for v in verbs:
            verb(v)
        out = os.path.join(tempfile.mkdtemp(prefix="sitemend-out-"), "o")
        self.addCleanup(shutil.rmtree, os.path.dirname(out), True)
        sitemend.audit(self.fx.root, out, 200, None)
        verbs.append("patch")
        verb("patch")
        write("", "X framework documentation home",
              "Documentation for the x framework: guides, reference and every attribute it supports.")
        r = subprocess.run(
            [sys.executable, os.path.join(sitemend.HERE, "sitemend.py"), "verify", self.fx.root,
             "--baseline", os.path.join(out, "findings.json"), "--out", out + "2"],
            capture_output=True, text=True, encoding="utf-8",
            env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        self.addCleanup(shutil.rmtree, out + "2", True)
        self.assertIn("REGRESSION GATE: PASS", r.stdout)
        self.assertEqual(r.returncode, 0)
        with open(os.path.join(out + "2", "verify.json"), encoding="utf-8") as fh:
            new = [f["id"] for f in json.load(fh)["new"]]
        self.assertIn("S3-CANNIBALIZATION", new)


# --------------------------------------------------------------- schema

class TestSchemaReferences(unittest.TestCase):
    """REGRESSION from the first real-site run: a nested {"@id": ".../#business", "name"}
    on eight Menu/Service pages was reported as a FoodEstablishment missing its address,
    though the full node lives on another page. A reference is not a definition."""

    FULL = {"@type": "FoodEstablishment", "@id": "https://x.test/#b", "name": "X",
            "address": "1 Some Street"}
    STUB = {"@type": "Menu", "name": "Lunch",
            "provider": {"@type": "FoodEstablishment", "@id": "https://x.test/#b", "name": "X"}}

    def _required(self, known):
        page = {"url": "/menu/", "jsonld": [self.STUB], "jsonld_errors": []}
        f, _ = schema_check.check_page(page, "", known)
        return [x for x in f if x["id"] == "S5-SCHEMA-REQUIRED-MISSING"]

    def test_stub_resolved_to_a_full_definition_elsewhere_is_not_flagged(self):
        known = schema_check.known_props([{"jsonld": [self.FULL]}, {"jsonld": [self.STUB]}])
        self.assertEqual(self._required(known), [])

    def test_stub_with_no_definition_anywhere_is_still_flagged(self):
        known = schema_check.known_props([{"jsonld": [self.STUB]}])
        self.assertTrue(self._required(known))


class TestReferencedBasenamesIsLinear(unittest.TestCase):
    """REGRESSION #71, a permanent test from the replay benchmark: the media-name regex
    restarted at every position of a long run of word characters and dots, so a 40,000
    character run took 91 s and one site's 45 MB of minified JS took 2.5 h per commit."""

    OLD = __import__("re").compile(
        r"[\w\-.]+\.(?:png|jpe?g|webp|avif|gif|svg|ico|mp4|webm|pdf|woff2?)", __import__("re").I)

    def test_same_names_as_the_old_pattern(self):
        for text in ("logo.png", "a.b.c.PNG x", "x.png-y.webp", "img/hero.jpeg?v=1", ".png",
                     ".png.png", "a.pngx b.svg", "font.woff2", "font.woff", "-a_b.gif",
                     '"https://site.dev/img/og-card.jpg"', "no media here", "a..pdf", "x.ico.ico"):
            with self.subTest(text=text):
                self.assertEqual(crawl.referenced_basenames(text),
                                 {m.lower() for m in self.OLD.findall(text)})

    def test_a_long_run_without_an_extension_is_fast(self):
        start = time.time()
        self.assertEqual(crawl.referenced_basenames("a.b" * 200000 + " logo.png"), {"logo.png"})
        self.assertLess(time.time() - start, 2)


class TestBasePath(Base):
    """REGRESSION #69, a permanent test from the replay benchmark: a site served from a
    base path (a GitHub Pages project site at /<repo>/, Docusaurus baseUrl) writes every
    link, canonical and sitemap URL under that path. A folder audit treated the build
    folder as /, so 1,193 findings on one site read as broken, all false positives."""

    HOST = "https://octo-labs.github.io"

    def _site(self, extra_links=""):
        nav = '<a href="/handbook/intro/">Intro</a> <a href="/handbook/">Home</a> ' + extra_links
        canon = lambda path: '<link rel="canonical" href="{0}/handbook{1}">'.format(self.HOST, path)
        self.fx.write("index.html", page_html(
            title="Handbook Home For The Octo Labs Team",
            head_extra=canon("/") + '<link rel="stylesheet" href="/handbook/assets/site.css">',
            body="<h1>Handbook</h1><p>" + nav + "word " * 300 +
                 '</p><img src="/handbook/img/logo.png" alt="logo" width="1" height="1">'))
        self.fx.write("intro/index.html", page_html(
            title="Introduction To The Octo Labs Handbook", head_extra=canon("/intro/"),
            body="<h1>Intro</h1><p>" + nav + "word " * 300 + "</p>"))
        self.fx.write("assets/site.css", "body{background:url(../img/logo.png)}")
        self.fx.write_bytes("img/logo.png", 100)
        self.fx.write("sitemap.xml",
                      '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                      "<url><loc>{0}/handbook/</loc></url><url><loc>{0}/handbook/intro/</loc></url>"
                      "</urlset>".format(self.HOST))
        self.fx.write("robots.txt", "User-agent: *\nAllow: /\nSitemap: {0}/handbook/sitemap.xml\n".format(self.HOST))

    def test_a_base_path_site_reads_as_served(self):
        self._site()
        doc = self.fx.crawl()
        self.assertEqual(doc["meta"]["base_path"], "/handbook")
        self.assertEqual(sorted(p["url"] for p in doc["pages"]), ["/handbook/", "/handbook/intro/"])
        ids = set(self.fx.ids())
        for rule in ("S1-BROKEN-LINK", "S1-CANONICAL-BROKEN", "S1-SITEMAP-ORPHAN", "S1-SITEMAP-MISSING",
                     "S1-SITEMAP-GAP", "S2-ORPHAN", "S2-UNREACHABLE", "S3-ASSET-UNUSED"):
            with self.subTest(rule=rule):
                self.assertNotIn(rule, ids)

    def test_a_link_that_forgets_the_base_path_is_still_broken(self):
        """On the deployed site /intro/ is outside the base path and 404s."""
        self._site(extra_links='<a href="/intro/">Broken</a>')
        broken = [f for f in self.fx.audit()["findings"] if f["id"] == "S1-BROKEN-LINK"]
        self.assertEqual([f["detail"]["target"] for f in broken], ["/intro/"])

    def test_a_real_top_level_folder_is_never_taken_for_a_base_path(self):
        """A home page whose canonical names /docs/, on a site that has a docs/ folder."""
        self.fx.write("index.html", page_html(
            head_extra='<link rel="canonical" href="https://site.dev/docs/">',
            body='<h1>H</h1><p><a href="/docs/">Docs</a> ' + "word " * 300 + "</p>"))
        self.fx.write("docs/index.html", page_html(title="Documentation For The Whole Site Here"))
        self.assertEqual(self.fx.crawl()["meta"]["base_path"], "")

    def test_a_canonical_its_own_links_do_not_follow_is_not_a_base_path(self):
        """A misplaced canonical alone must not re-root a normal site."""
        self.fx.write("index.html", page_html(
            head_extra='<link rel="canonical" href="https://site.dev/welcome/">',
            body='<h1>H</h1><p><a href="/about/">About</a> ' + "word " * 300 + "</p>"))
        self.fx.write("about/index.html", page_html(title="About This Site And The People Behind It"))
        self.assertEqual(self.fx.crawl()["meta"]["base_path"], "")
        self.assertNotIn("S1-BROKEN-LINK", self.fx.ids())


class TestPageFoldersWithToolingNames(Base):
    """REGRESSION #82, a permanent test from the 1.8.0 replay: a built Docusaurus site had
    content pages under folders named vendor (b2b/stats/purchases/vendor/index.html). The
    crawl skipped every folder named vendor, out, build or tmp at any depth, so links and
    sitemap entries for real pages read as broken: 13 false positives on one site."""

    def _site(self):
        self.fx.write("index.html", page_html(
            body='<h1>Guide</h1><p><a href="/b2b/stats/purchases/vendor">Monthly purchases</a> '
                 '<a href="/b2b/">B2B</a> ' + "word " * 300 + "</p>"))
        self.fx.write("b2b/index.html", page_html(title="B2B Section Of The Admin Guide Here"))
        self.fx.write("b2b/stats/purchases/vendor/index.html",
                      page_html(title="B2B Monthly Purchases By Vendor In The Guide"))
        self.fx.write("refund-question/vendor/all/index.html",
                      page_html(title="Refund Questions From Every Vendor In One List"))
        self.fx.write("sitemap.xml",
                      '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                      "<url><loc>https://guide.dev/</loc></url><url><loc>https://guide.dev/b2b/</loc></url>"
                      "<url><loc>https://guide.dev/b2b/stats/purchases/vendor</loc></url>"
                      "<url><loc>https://guide.dev/refund-question/vendor/all/</loc></url></urlset>")

    def test_linked_and_sitemapped_pages_in_a_vendor_folder_are_crawled(self):
        self._site()
        urls = {p["url"] for p in self.fx.crawl()["pages"]}
        self.assertIn("/b2b/stats/purchases/vendor/", urls)          # linked
        self.assertIn("/refund-question/vendor/all/", urls)          # only in the sitemap
        ids = set(self.fx.ids())
        for rule in ("S1-BROKEN-LINK", "S1-SITEMAP-ORPHAN"):
            with self.subTest(rule=rule):
                self.assertNotIn(rule, ids)

    def test_unreferenced_html_in_a_vendor_folder_is_still_skipped(self):
        """A library's bundled docs (vendor/lib/docs/) are not the site's pages; crawling
        them would turn every one into an orphan."""
        self._site()
        self.fx.write("vendor/lib/docs/index.html", page_html(title="Library Documentation Bundled Here"))
        self.fx.write("node_modules/pkg/index.html", page_html(title="A Package Readme Rendered As HTML"))
        urls = {p["url"] for p in self.fx.crawl()["pages"]}
        self.assertFalse({u for u in urls if u.startswith(("/vendor/", "/node_modules/"))})
        orphans = {u for f in self.fx.audit()["findings"] if f["id"] == "S2-ORPHAN" for u in f["pages"]}
        self.assertFalse({u for u in orphans if u.startswith(("/vendor/", "/node_modules/"))})

    def test_a_page_reached_only_through_another_vendor_page_is_crawled(self):
        self._site()
        self.fx.write("b2b/stats/purchases/vendor/index.html", page_html(
            title="B2B Monthly Purchases By Vendor In The Guide",
            body='<h1>V</h1><a href="/b2b/stats/purchases/vendor/detail/">Detail</a>'))
        self.fx.write("b2b/stats/purchases/vendor/detail/index.html",
                      page_html(title="Vendor Purchase Detail For One Month Here"))
        self.assertIn("/b2b/stats/purchases/vendor/detail/", {p["url"] for p in self.fx.crawl()["pages"]})
        self.assertNotIn("S1-BROKEN-LINK", self.fx.ids())


class TestNonAsciiUrls(Base):
    """REGRESSION #73, a permanent test from the replay benchmark: a page whose path is
    not ASCII is named from its file (/archive/tag/监控/), while the sitemap and canonical
    publish it percent-encoded (/archive/tag/%E7%9B%91%E6%8E%A7/). They were compared
    without decoding, so existing pages read as missing (173 findings on one site)."""

    HOST = "https://notes-blog.dev"

    def test_norm_path_decodes_to_one_form(self):
        self.assertEqual(S.norm_path("/archive/tag/%E7%9B%91%E6%8E%A7/"), "/archive/tag/监控/")
        self.assertEqual(S.norm_path("/archive/tag/%e7%9b%91%e6%8e%a7/"), "/archive/tag/监控/")
        self.assertEqual(S.norm_path("/caf%C3%A9/"), S.norm_path("/café/"))      # NFC
        self.assertEqual(S.norm_path("/a%20b/"), "/a b/")
        # Escapes that change a path's meaning stay escaped.
        for kept in ("/a%2Fb/", "/c%23-guide/", "/q%3Fx/", "/100%25/"):
            with self.subTest(path=kept):
                self.assertEqual(S.norm_path(kept), kept)

    def test_an_encoded_sitemap_canonical_and_link_find_the_page(self):
        tag = "/archive/tag/%E7%9B%91%E6%8E%A7/"
        self.fx.write("index.html", page_html(
            head_extra='<link rel="canonical" href="{0}/">'.format(self.HOST),
            body='<h1>H</h1><p><a href="{0}">Monitoring</a> <a href="/archive/tag/监控/">Raw</a> '.format(tag)
                 + "word " * 300 + "</p>"))
        self.fx.write("archive/tag/监控/index.html", page_html(
            title="Monitoring Posts On The Notes Blog Archive",
            head_extra='<link rel="canonical" href="{0}{1}">'.format(self.HOST, tag)))
        self.fx.write("sitemap.xml",
                      '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                      "<url><loc>{0}/</loc></url><url><loc>{0}{1}</loc></url></urlset>".format(self.HOST, tag))
        ids = set(self.fx.ids())
        for rule in ("S1-SITEMAP-ORPHAN", "S1-CANONICAL-BROKEN", "S1-BROKEN-LINK", "S1-SITEMAP-GAP"):
            with self.subTest(rule=rule):
                self.assertNotIn(rule, ids)

    def test_an_accented_path_saved_decomposed_still_matches(self):
        """macOS writes file names decomposed (NFD); generators encode the composed form."""
        self.fx.write("index.html", page_html(
            body='<h1>H</h1><p><a href="/caf%C3%A9/">Cafe</a> ' + "word " * 300 + "</p>"))
        self.fx.write("café/index.html", page_html(title="The Cafe Page Of This Small Example Site"))
        self.assertNotIn("S1-BROKEN-LINK", self.fx.ids())

    def test_an_encoded_url_that_does_not_exist_is_still_reported(self):
        self.fx.write("index.html", page_html())
        self.fx.write("sitemap.xml",
                      '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                      "<url><loc>{0}/</loc></url><url><loc>{0}/archive/tag/%E7%BC%BA/</loc></url>"
                      "</urlset>".format(self.HOST))
        orphan = [f for f in self.fx.audit()["findings"] if f["id"] == "S1-SITEMAP-ORPHAN"]
        self.assertEqual([f["pages"] for f in orphan], [["/archive/tag/缺/"]])


class TestBracketHosts(Base):
    """REGRESSION #51: a URL whose host starts with "[" but is not a valid IPv6 literal
    made urlsplit raise, and the whole audit stopped. The replay benchmark hit it on
    electron/website, typescript-eslint and react-navigation, all in minified JS/CSS."""

    def test_resolve_href_does_not_raise(self):
        for href in ("http://[", "https://[::1", "//[x", "http://[x/page"):
            with self.subTest(href=href):
                self.assertEqual(S.resolve_href("/", href), ("invalid", href))

    def test_audit_survives_a_bracket_host_anywhere(self):
        bad = "https://[x/page"
        for name, head, body, files in (
                ("css", '<link rel="stylesheet" href="/style.css">', "", {"style.css": "a{background:url(http://[x)}"}),
                ("link", "", '<a href="{0}">x</a>'.format(bad), {}),
                ("hreflang", '<link rel="alternate" hreflang="de" href="{0}">'.format(bad), "", {}),
                ("canonical", '<link rel="canonical" href="{0}">'.format(bad), "", {}),
                ("sitemap", "", "", {"sitemap.xml": '<urlset><url><loc>{0}</loc></url></urlset>'.format(bad),
                                     "robots.txt": "User-agent: *\nSitemap: https://[x/sitemap.xml\n"})):
            with self.subTest(source=name):
                fx = Fixture()
                self.addCleanup(fx.cleanup)
                fx.write("index.html", page_html(head_extra=head, body="<h1>H</h1><p>" + body + "word " * 300 + "</p>"))
                for rel, text in files.items():
                    fx.write(rel, text)
                self.assertIsInstance(fx.ids(), list)


class TestSchemaClaims(unittest.TestCase):
    REVIEW = {"@type": "LocalBusiness", "name": "X", "address": "Some Street",
              "review": [{"@type": "Review",
                          "author": {"@type": "Person", "name": "Jane Doe"},
                          "reviewBody": "Great service."}]}

    def _check(self, claim_text):
        page = {"url": "/", "jsonld": [self.REVIEW], "jsonld_errors": []}
        if claim_text is not None:
            page["claim_text"] = S.claim_norm(claim_text)
            page["visible_text"] = claim_text.casefold()
        f, _ = schema_check.check_page(page, page.get("claim_text", ""))
        return [x for x in f if x["id"] == "S5-SCHEMA-UNSUPPORTED-CLAIM"]

    def _review_by(self, author, page_text):
        biz = dict(self.REVIEW, review=[{"@type": "Review", "reviewBody": "ok",
                                         "author": {"@type": "Person", "name": author}}])
        page = {"url": "/", "jsonld": [biz], "jsonld_errors": [],
                "claim_text": S.claim_norm(page_text), "visible_text": page_text.casefold()}
        f, _ = schema_check.check_page(page, page["claim_text"])
        return [x for x in f if x["id"] == "S5-SCHEMA-UNSUPPORTED-CLAIM"]

    def test_name_inside_a_longer_word_is_not_a_match(self):
        """REGRESSION found by the v1.0.3 review: 'ann' matched inside 'channel'."""
        self.assertTrue(self._review_by("Ann Lee", "Our channel partners. Some Street"))

    def test_short_names_are_checked(self):
        self.assertTrue(self._review_by("Li Wu", "Nothing about them here. Some Street"))
        self.assertFalse(self._review_by("Li Wu", "Li Wu said it was great. Some Street"))

    def test_non_latin_names_are_checked(self):
        tamil = "ராஜேஷ்"
        self.assertTrue(self._review_by(tamil, "Nothing about them here. Some Street"))
        self.assertFalse(self._review_by(tamil, "Review by " + tamil + ". Some Street"))

    def test_initial_only_tokens_are_ignored(self):
        self.assertFalse(self._review_by("Varsha B.", "Varsha said it was lovely. Some Street"))

    def _rating(self, page_text, elsewhere=""):
        product = {"@type": "Product", "name": "Widget",
                   "aggregateRating": {"@type": "AggregateRating", "ratingValue": "4.7",
                                       "reviewCount": "86413"}}
        page = {"url": "/", "jsonld": [product], "jsonld_errors": [],
                "claim_text": S.claim_norm(page_text), "visible_text": page_text.casefold()}
        site = page_text + " " + elsewhere
        f, _ = schema_check.check_page(page, S.claim_norm(site),
                                       site_numbers=schema_check.numbers(site.casefold()))
        return [x for x in f if x["id"] == "S5-SCHEMA-UNSUPPORTED-CLAIM"]

    def test_a_rating_on_a_page_with_only_non_latin_text_is_checked(self):
        """REGRESSION #81, a permanent test from the 1.8.0 seeded run (boss-dashboard-guide):
        a fabricated 4.7-star rating on a page whose only text is Korean raised nothing,
        because claim text kept only [a-z0-9] and an empty page skips the check."""
        self.assertTrue(self._rating("이용 가이드"))
        self.assertTrue(self._rating("监控 系统 文章"))

    def test_a_non_latin_rating_shown_on_the_page_is_supported(self):
        self.assertFalse(self._rating("평점 4.7 · 리뷰 86413개"))
        self.assertFalse(self._rating("评分 4.7，86413 条评价"))

    def test_a_non_latin_address_shown_on_the_page_is_supported(self):
        biz = {"@type": "LocalBusiness", "name": "포장보스",
               "address": {"@type": "PostalAddress", "streetAddress": "테헤란로 152",
                           "addressLocality": "서울특별시 강남구"}}
        for text, fires in (("본사: 서울특별시 강남구 테헤란로 152", False),
                            ("포장보스 이용 가이드", True)):
            with self.subTest(text=text):
                page = {"url": "/", "jsonld": [biz], "jsonld_errors": [],
                        "claim_text": S.claim_norm(text), "visible_text": text.casefold()}
                f, _ = schema_check.check_page(page, page["claim_text"])
                self.assertEqual(bool([x for x in f if x["id"] == "S5-SCHEMA-UNSUPPORTED-CLAIM"]), fires)

    def test_an_accented_name_matches_either_way(self):
        self.assertEqual(S.claim_norm("Café Zürich"), S.claim_norm("Cafe Zurich"))
        self.assertEqual(S.claim_norm("서울특별시 강남구"), S.claim_norm("서울특별시강남구"))

    def test_a_rating_is_not_corroborated_by_stray_digits(self):
        """REGRESSION found by the seeded recall run (2026-10-17): ratingValue "4.7" was
        split into "4" and "7", which every site contains, so a rating the site never
        shows passed as corroborated."""
        self.assertTrue(self._rating("Widget docs.", "Version 4 ships in 7 days. Step 47."))

    def test_a_rating_the_site_shows_is_corroborated(self):
        self.assertEqual(self._rating("Rated 4.7 by 86413 customers."), [])
        self.assertEqual(self._rating("Widget docs.", "Our widget is rated 4.7 from 86413 reviews."), [])

    def test_visible_review_not_flagged(self):
        self.assertEqual(self._check("Jane Doe said: Great service. Some Street"), [])

    def test_absent_review_flagged(self):
        hits = self._check("This page never mentions any reviewer at all. Some Street")
        self.assertTrue(hits)
        self.assertIn("Jane Doe", hits[0]["evidence"])

    def test_no_page_text_means_skip_not_accuse(self):
        """REGRESSION and the worst bug this tool had: with no text to compare
        against, every author read as absent, fabricating the exact policy-violation
        accusation the tool exists to make honestly. Silence is the only honest
        output when corroboration is impossible."""
        self.assertEqual(self._check(None), [])
        self.assertEqual(self._check(""), [])

    def test_nested_reference_not_flagged_for_recommended(self):
        """REGRESSION: every Service inside makesOffer[] was flagged for a missing
        provider, producing 128 findings on a 5-page site."""
        page = {"url": "/", "jsonld_errors": [], "claim_text": "",
                "jsonld": [{"@type": "Organization", "name": "N", "url": "u", "logo": "l",
                            "makesOffer": [{"@type": "Offer",
                                            "itemOffered": {"@type": "Service", "name": "S"}}]}]}
        f, _ = schema_check.check_page(page, "")
        self.assertEqual([x for x in f if x["id"] == "S5-SCHEMA-RECOMMENDED-MISSING"], [])

    def test_top_level_missing_required_is_flagged(self):
        page = {"url": "/", "jsonld_errors": [], "claim_text": "",
                "jsonld": [{"@type": "LocalBusiness", "name": "N"}]}   # no address
        f, _ = schema_check.check_page(page, "")
        self.assertTrue([x for x in f if x["id"] == "S5-SCHEMA-REQUIRED-MISSING"])


# --------------------------------------------------------------- verify

class TestVerify(unittest.TestCase):
    @staticmethod
    def f(fid, pages, evidence="e", severity="high", stage=2):
        return {"id": fid, "pages": pages, "evidence": evidence,
                "severity": severity, "stage": stage, "message": fid}

    def test_a_judgement_call_is_advisory_and_never_fails_the_gate(self):
        """REGRESSION found by the 2026-10-16 review: adding an hx-patch reference page
        next to hx-get/hx-post/hx-put failed the PR with three high S3-CANNIBALIZATION
        findings. Cannibalization is a judgement (confidence medium); it is reported
        as advisory and only measured findings fail the gate."""
        d = tempfile.mkdtemp(prefix="sitemend-verify-")
        self.addCleanup(shutil.rmtree, d, True)
        guess = dict(self.f("S3-CANNIBALIZATION", ["/hx-get/", "/hx-patch/"]), confidence="medium")
        paths = {}
        for name, items in (("b", []), ("c", [guess])):
            paths[name] = os.path.join(d, name + ".json")
            with open(paths[name], "w") as fh:
                json.dump({"findings": items}, fh)
        r = sitemend.run("verify.py", "--baseline", paths["b"], "--current", paths["c"],
                         "--out", os.path.join(d, "v.json"), ok=(0, 1))
        self.assertEqual(r.returncode, 0)
        self.assertIn("REGRESSION GATE: PASS", r.stdout)
        with open(os.path.join(d, "v.md"), encoding="utf-8") as fh:
            self.assertIn("| high (advisory) | S3-CANNIBALIZATION", fh.read())

    def test_a_measured_high_finding_still_fails_the_gate(self):
        self.assertTrue(V.blocks(self.f("S1-BROKEN-LINK", ["/"])))
        self.assertTrue(V.blocks(dict(self.f("S1-BROKEN-LINK", ["/"]), confidence="high")))
        self.assertFalse(V.blocks(dict(self.f("S3-NEAR-DUPLICATE", ["/a", "/b"]), confidence="medium")))
        self.assertFalse(V.blocks(self.f("S3-THIN", ["/a"], severity="medium")))

    def test_shrinking_page_list_is_changed_not_new(self):
        """REGRESSION: when a grouped finding's page list shrank after a partial fix,
        it read as one finding closed plus one brand-new finding -- wrong and
        alarming on every re-run."""
        base = [self.f("S2-HEADING-SKIP", ["/a", "/b", "/c"])]
        cur = [self.f("S2-HEADING-SKIP", ["/a", "/b"])]
        self.assertTrue(V.related(base[0], cur[0]))

    def test_new_broken_target_on_the_same_page_is_new(self):
        """REGRESSION found by the 2026-10-16 audit: fixing href="/a" while adding a
        broken href="/b" on the same page read as one 'changed' finding and passed."""
        a = dict(self.f("S1-BROKEN-LINK", ["/"], evidence='href="/a" -> /a'), detail={"target": "/a"})
        b = dict(self.f("S1-BROKEN-LINK", ["/"], evidence='href="/b" -> /b'), detail={"target": "/b"})
        self.assertFalse(V.related(a, b))

    def test_same_broken_target_spelled_differently_is_still_changed(self):
        a = dict(self.f("S1-BROKEN-LINK", ["/"], evidence='href="/a" -> /a'), detail={"target": "/a"})
        b = dict(self.f("S1-BROKEN-LINK", ["/", "/x"], evidence='href="a" -> /a'), detail={"target": "/a"})
        self.assertTrue(V.related(a, b))

    def test_a_new_duplicate_title_sharing_a_page_with_an_old_one_fails_the_gate(self):
        """REGRESSION #60, a permanent test from the seeded recall run (electron/website):
        /apps/ shared "Electron" with /governance/; a change gave /apps/ the title of
        /blog/10-years-of-electron/. The new pair overlapped the old one on /apps/, so it
        read as that finding 'changed' and the gate passed."""
        d = tempfile.mkdtemp(prefix="sitemend-verify-")
        self.addCleanup(shutil.rmtree, d, True)
        paths = {}
        for name, pages, title in (("b", ["/apps/", "/governance/"], "Electron"),
                                   ("c", ["/apps/", "/blog/10-years-of-electron/"], "10 years of Electron")):
            paths[name] = os.path.join(d, name + ".json")
            with open(paths[name], "w") as fh:
                json.dump({"findings": [self.f("S3-TITLE-DUPLICATE", pages, evidence=title)]}, fh)
        r = sitemend.run("verify.py", "--baseline", paths["b"], "--current", paths["c"],
                         "--out", os.path.join(d, "v.json"), ok=(0, 1))
        self.assertEqual(r.returncode, 1)
        with open(os.path.join(d, "v.json"), encoding="utf-8") as fh:
            self.assertEqual([f["id"] for f in json.load(fh)["new"]], ["S3-TITLE-DUPLICATE"])

    def test_a_duplicate_group_renamed_on_the_same_pages_is_changed_not_new(self):
        """REGRESSION #82, a permanent test from the 1.8.0 replay (mj3622.github.io): 108
        archive pages already shared "Archive - Minjer"; a commit translated it to
        "文章 - Minjer". Keyed by text alone (#60), the same duplicate read as new and
        blocked."""
        d = tempfile.mkdtemp(prefix="sitemend-verify-")
        self.addCleanup(shutil.rmtree, d, True)
        pages = ["/archive/"] + ["/archive/tag/t{0}/".format(i) for i in range(107)]
        paths = {}
        for name, title in (("b", "Archive - Minjer"), ("c", "文章 - Minjer")):
            paths[name] = os.path.join(d, name + ".json")
            with open(paths[name], "w", encoding="utf-8") as fh:
                json.dump({"findings": [self.f("S3-TITLE-DUPLICATE", pages, evidence=title)]}, fh)
        r = sitemend.run("verify.py", "--baseline", paths["b"], "--current", paths["c"],
                         "--out", os.path.join(d, "v.json"), ok=(0, 1))
        self.assertEqual(r.returncode, 0, r.stdout[-2000:])
        with open(os.path.join(d, "v.json"), encoding="utf-8") as fh:
            v = json.load(fh)
        self.assertEqual(v["new"], [])

    def test_a_duplicate_group_that_grows_under_the_same_text_is_changed(self):
        for rule in ("S3-TITLE-DUPLICATE", "S3-DESC-DUPLICATE"):
            with self.subTest(rule=rule):
                self.assertTrue(V.related(self.f(rule, ["/a", "/b"], evidence="Same"),
                                          self.f(rule, ["/a", "/b", "/c"], evidence="Same")))
                self.assertFalse(V.related(self.f(rule, ["/a", "/b"], evidence="Same"),
                                           self.f(rule, ["/a", "/c"], evidence="Other")))

    def test_finding_that_gets_worse_fails_the_gate(self):
        """REGRESSION found by the 2026-10-16 audit: S1-HOST-MISMATCH going high ->
        critical (a preview host appeared) paired as 'changed' and passed."""
        d = tempfile.mkdtemp(prefix="sitemend-verify-")
        self.addCleanup(shutil.rmtree, d, True)
        paths = {}
        for name, sev, ev in (("b", "high", "canonical: www.x.org (3)"),
                              ("c", "critical", "canonical: x-git-a.vercel.app (3)")):
            paths[name] = os.path.join(d, name + ".json")
            with open(paths[name], "w") as fh:
                json.dump({"findings": [self.f("S1-HOST-MISMATCH", ["/"], evidence=ev, severity=sev)]}, fh)
        r = sitemend.run("verify.py", "--baseline", paths["b"], "--current", paths["c"],
                         "--out", os.path.join(d, "v.json"), ok=(0, 1))
        self.assertEqual(r.returncode, 1)
        self.assertIn("REGRESSION GATE: FAIL", r.stdout)
        with open(os.path.join(d, "v.json"), encoding="utf-8") as fh:
            self.assertEqual([f["id"] for f in json.load(fh)["escalated"]], ["S1-HOST-MISMATCH"])

    def test_unrelated_finding_is_new(self):
        self.assertFalse(V.related(self.f("S2-ORPHAN", ["/a"]), self.f("S2-ORPHAN", ["/z"])))
        self.assertFalse(V.related(self.f("S2-ORPHAN", ["/a"]), self.f("S3-THIN", ["/a"])))

    def test_markdown_quotes_evidence_and_counts_only(self):
        """The PR comment quotes each finding's evidence verbatim (bar the pipe that
        would break the table) and its only numbers are counts from verify.json."""
        new = self.f("S1-NOT-INDEXABLE", ["/"], evidence="<meta> noindex | nofollow",
                     severity="critical")
        doc = {"gate": "FAIL", "counts": {"closed": 1, "new": 1, "changed": 0, "persisting": 7},
               "new": [new], "closed": [self.f("S3-THIN", ["/about"], severity="low")],
               "changed": [], "regressions": [new]}
        md = V.markdown(doc)
        self.assertTrue(md.startswith(V.MARKER))
        self.assertIn("regression gate FAIL", md)
        self.assertIn("1 new, 1 closed, 0 changed, 7 unchanged", md)
        self.assertIn("| critical | S1-NOT-INDEXABLE: S1-NOT-INDEXABLE | `/` | "
                      "`<meta> noindex \\| nofollow` |", md)
        self.assertIn("### Closed", md)
        self.assertNotIn("### New (critical", V.markdown(dict(doc, regressions=[])))

    def test_markdown_lets_no_site_text_act_as_markup(self):
        """SECURITY: the comment quotes text the audited site wrote, and in the preview
        workflow that site is the PR's own deploy. Posted with the workflow's token, an
        @mention would notify whoever it names and a link or image would render as the
        bot's own. Evidence and pages are literal code spans; prose is escaped."""
        evil = "@octocat ![x](https://evil.test/p.png) [click](https://evil.test) <img src=x>"
        self.assertEqual(V.cell(evil),
                         "@⁠octocat \\!\\[x\\](https://evil.test/p.png) "
                         "\\[click\\](https://evil.test) &lt;img src=x>")
        # Code spans: a fence longer than any backtick run inside, padded when the text
        # starts or ends with one, and the pipe still escaped for the table.
        self.assertEqual(V.code_cell("a ``b`` | c"), "```a ``b`` \\| c```")
        self.assertEqual(V.code_cell("`x"), "`` `x ``")
        self.assertEqual(V.code_cell(""), "")
        new = self.f("S1-BROKEN-LINK", ["/a"], evidence=evil, severity="high")
        new["message"] = "Title is " + evil
        md = V.markdown({"gate": "FAIL", "counts": {"closed": 0, "new": 1, "changed": 0, "persisting": 0},
                         "new": [new], "closed": [], "changed": [], "regressions": [new]})
        # The only bare "@octocat" left is inside the evidence's code span, where it is text.
        self.assertIn("| high | S1-BROKEN-LINK: Title is " + V.cell(evil) + " | `/a` | `" + evil + "` |", md)
        self.assertEqual(md.count("@octocat"), 1)


# --------------------------------------------------------------- determinism

class TestDeterminism(unittest.TestCase):
    def test_minhash_is_stable_across_processes(self):
        """verify diffs a later crawl against a baseline, so hashing must not depend
        on Python's per-process hash salt."""
        text = "the quick brown fox jumps over the lazy dog and keeps on running"
        code = ("import sys; sys.path.insert(0, r'{0}'); import seolib;"
                "print(seolib.minhash({1!r})[:4])").format(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"), text)
        import subprocess
        outs = {subprocess.run([sys.executable, "-c", code], capture_output=True,
                               text=True).stdout.strip() for _ in range(2)}
        self.assertEqual(len(outs), 1, "minhash differed between processes: " + str(outs))
        self.assertEqual(S.minhash(text), S.minhash(text))

    def test_identical_text_is_perfectly_similar(self):
        a = S.minhash("alpha beta gamma delta epsilon zeta eta theta iota kappa")
        b = S.minhash("alpha beta gamma delta epsilon zeta eta theta iota kappa")
        self.assertEqual(S.minhash_similarity(a, b), 1.0)


# --------------------------------------------------------------- robustness

class TestRobustness(Base):
    def test_empty_site_does_not_crash(self):
        res = self.fx.audit()
        self.assertIsInstance(res["findings"], list)

    def test_single_page_no_robots_no_sitemap(self):
        self.fx.write("index.html", page_html())
        ids = self.fx.ids()
        self.assertIn("S1-ROBOTS-MISSING", ids)
        self.assertIn("S1-SITEMAP-MISSING", ids)

    def test_malformed_jsonld_reported_not_fatal(self):
        """The crawl records the parse error and keeps going; schema_check.py is what
        turns it into a finding, since it owns stage 5."""
        self.fx.write("index.html", page_html(
            head_extra='<script type="application/ld+json">{not json}</script>'))
        doc = self.fx.crawl()
        self.assertTrue(doc["pages"][0]["jsonld_errors"])
        f, _ = schema_check.check_page(doc["pages"][0], "")
        self.assertIn("S5-SCHEMA-INVALID-JSON", [x["id"] for x in f])


# --------------------------------------------------- srcset & unused assets

class TestSrcsetAndAssets(Base):
    def test_source_srcset_is_size_checked(self):
        """REGRESSION: only <img src> was size-checked, so a heavy .webp behind a
        <picture> was invisible -- yet it is exactly what the browser downloads."""
        self.fx.write_bytes("assets/hero.webp", 300 * 1024)
        self.fx.write_bytes("assets/hero.jpg", 10 * 1024)
        self.fx.write("index.html", page_html(
            body='<h1>H</h1><picture><source srcset="assets/hero.webp" type="image/webp">'
                 '<img src="assets/hero.jpg" alt="hero" width="9" height="9"></picture>'
                 "<p>" + "word " * 300 + "</p>"))
        heavy = [f for f in self.fx.audit()["findings"] if f["id"] == "S3-IMG-HEAVY"]
        self.assertTrue(heavy, "<source srcset> must be size-checked")
        self.assertIn("hero.webp", heavy[0]["evidence"])

    def test_source_does_not_trigger_alt_or_dims(self):
        """A <source> has no alt and inherits layout from its <img>; flagging it for
        either is a false positive."""
        self.fx.write_bytes("assets/a.webp", 1024)
        self.fx.write("index.html", page_html(
            body='<h1>H</h1><picture><source srcset="assets/a.webp">'
                 '<img src="assets/a.jpg" alt="x" width="9" height="9"></picture>'
                 "<p>" + "word " * 300 + "</p>"))
        ids = self.fx.ids()
        self.assertNotIn("S3-IMG-ALT-MISSING", ids)
        self.assertNotIn("S3-IMG-DIMS-MISSING", ids)

    def test_unused_media_is_flagged(self):
        self.fx.write_bytes("assets/orphan.jpg", 50 * 1024)
        self.fx.write("index.html", page_html())
        found = [f for f in self.fx.audit()["findings"] if f["id"] == "S3-ASSET-UNUSED"]
        self.assertTrue(found)
        self.assertIn("orphan.jpg", found[0]["evidence"])

    def test_absolute_url_reference_suppresses_unused(self):
        """REGRESSION: og:image and JSON-LD logo use absolute URLs on the production
        origin, which the path resolver does not treat as internal. They were flagged
        for deletion. Recommending removal of a file that IS used is the worst
        failure this check can have, so basename matching backstops it."""
        self.fx.write_bytes("assets/og-card.png", 50 * 1024)
        self.fx.write("index.html", page_html(
            head_extra='<meta property="og:image" content="https://example.com/assets/og-card.png">'))
        found = [f for f in self.fx.audit()["findings"] if f["id"] == "S3-ASSET-UNUSED"]
        self.assertEqual(found, [], "absolute-URL reference must suppress the finding")

    def test_jsonld_reference_suppresses_unused(self):
        self.fx.write_bytes("assets/logo-square.png", 50 * 1024)
        self.fx.write("index.html", page_html(
            head_extra='<script type="application/ld+json">'
                       '{"@type":"Organization","name":"N",'
                       '"logo":"https://example.com/assets/logo-square.png"}</script>'))
        found = [f for f in self.fx.audit()["findings"] if f["id"] == "S3-ASSET-UNUSED"]
        self.assertEqual(found, [])

    def test_css_reference_suppresses_unused(self):
        self.fx.write_bytes("assets/bg.jpg", 50 * 1024)
        self.fx.write("styles.css", ".hero{background-image:url('assets/bg.jpg')}")
        self.fx.write("index.html", page_html(head_extra='<link rel="stylesheet" href="/styles.css">'))
        found = [f for f in self.fx.audit()["findings"] if f["id"] == "S3-ASSET-UNUSED"]
        self.assertEqual(found, [])

    def test_favicon_never_flagged(self):
        """Hosts and crawlers fetch these by convention, never by an in-page link."""
        self.fx.write_bytes("favicon.ico", 50 * 1024)
        self.fx.write("index.html", page_html())
        found = [f for f in self.fx.audit()["findings"] if f["id"] == "S3-ASSET-UNUSED"]
        self.assertEqual(found, [])


# --------------------------------------------------- stage 5 ownership

class TestStageFiveOwnership(Base):
    def test_audit_merges_schema_findings(self):
        """Schema findings must be merged by audit.py so the GATES see them. Merging
        only in report.py left Gate C blind to stage-5 problems."""
        self.fx.write("index.html", page_html())
        doc = self.fx.crawl()
        schema = [{"id": "S5-SCHEMA-UNSUPPORTED-CLAIM", "severity": "high", "page": "/",
                   "message": "made up claim", "evidence": "e"}]
        res = audit.audit(doc, None, schema)
        self.assertIn("S5-SCHEMA-UNSUPPORTED-CLAIM", [f["id"] for f in res["findings"]])
        gate_c = [g for g in res["gates"] if g["gate"] == "C"][0]
        self.assertEqual(gate_c["status"], "BLOCKED",
                         "a high stage-5 finding must block gate C")

    def test_audit_emits_no_schema_findings_of_its_own(self):
        """audit.py's inline schema check could not corroborate anything and
        double-reported through the merge. schema_check.py owns stage 5."""
        self.fx.write("index.html", page_html(
            head_extra='<script type="application/ld+json">'
                       '{"@type":"LocalBusiness","name":"N","aggregateRating":'
                       '{"ratingValue":"5","reviewCount":"9"}}</script>'))
        stage5 = [f for f in self.fx.audit()["findings"] if f["stage"] == 5]
        self.assertEqual(stage5, [], "stage 5 must come only from schema_check.py")


class TestSchemaRespectsGateA(Base):
    """REGRESSION found by the 2026-10-16 audit: a noindex page's broken JSON-LD was a
    high S5 finding and blocked Gate C. Gate A covers stage 5 like every stage after 1."""

    def _s5(self, robots_meta):
        self.fx.write("index.html", page_html(
            body='<h1>H</h1><p><a href="/draft.html">d</a> ' + "word " * 300 + "</p>"))
        self.fx.write("draft.html", page_html(
            title="Draft Page With A Long Enough Title",
            head_extra=robots_meta + '<script type="application/ld+json">{"@type": bad}</script>'))
        doc = self.fx.crawl()
        schema = [f for p in doc["pages"] for f in schema_check.check_page(p)[0]]
        return [f["id"] for f in audit.audit(doc, None, schema)["findings"] if f["stage"] == 5]

    def test_noindex_page_gets_no_schema_findings(self):
        self.assertEqual(self._s5('<meta name="robots" content="noindex">'), [])

    def test_indexable_page_still_does(self):
        self.assertEqual(self._s5(""), ["S5-SCHEMA-INVALID-JSON"])


# ------------------------------------------------------- http mode: discovery

class TestGateBIsModeAware(Base):
    """A gate may only be CLEARED by a check that could actually run.

    http mode discovers pages via links and the sitemap, so it can never prove a site
    has no orphans -- a page neither linked nor listed is invisible to it. It once
    printed 'CLEAR -- no orphan or duplicate pages' on a site with two orphans, which
    also unblocked schema work on pages that were merge candidates.
    """

    def _gate_b(self, mode):
        self.fx.write("index.html", page_html(
            body='<h1>H</h1><p><a href="/about.html">About</a> ' + ("word " * 300) + "</p>"))
        self.fx.write("about.html", page_html(title="An About Page With A Fine Title"))
        doc = self.fx.crawl()
        doc["meta"]["mode"] = mode
        return [g for g in audit.audit(doc)["gates"] if g["gate"] == "B"][0]

    def test_fs_mode_can_clear_gate_b(self):
        self.assertEqual(self._gate_b("fs")["status"], "CLEAR")

    def test_http_mode_cannot_clear_gate_b(self):
        gate_b = self._gate_b("http")
        self.assertEqual(gate_b["status"], "NOT ASSESSED",
                         "silence from a check that could not run is not a pass")
        self.assertIn("fs mode", gate_b["detail"], "say what would clear it")

    def test_positive_findings_still_block_in_http_mode(self):
        """BLOCKED outranks NOT ASSESSED -- an orphan the http walk *did* see is real."""
        self.fx.write("index.html", page_html())
        self.fx.write("stray.html", page_html(title="A Stray Page Nothing Links To"))
        doc = self.fx.crawl()
        doc["meta"]["mode"] = "http"
        gate_b = [g for g in audit.audit(doc)["gates"] if g["gate"] == "B"][0]
        self.assertEqual(gate_b["status"], "BLOCKED")
        self.assertIn("/stray.html", gate_b["pages"])


class TestHttpSitemapSeeding(unittest.TestCase):
    """REGRESSION: crawl_http only followed links, so a page that was unlinked but
    listed in sitemap.xml was never fetched -- and was then reported as
    S1-SITEMAP-ORPHAN ('does not exist in the crawl') despite serving a 200."""

    @classmethod
    def setUpClass(cls):
        try:
            import requests  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("requests not installed (http mode is optional)")

        import functools
        import http.server
        import threading

        cls.root = tempfile.mkdtemp(prefix="sitemend-http-test-")
        body = "<h1>H</h1><p>" + ("word " * 300) + "</p>"

        def w(name, html):
            with open(os.path.join(cls.root, name), "w", encoding="utf-8") as f:
                f.write(html)

        w("index.html", page_html(body='<h1>H</h1><p><a href="/linked.html">L</a> ' +
                                       ("word " * 300) + "</p>"))
        w("linked.html", page_html(title="A Linked Page With An Adequate Title", body=body))
        # Listed in the sitemap, linked from nowhere. The whole point of the fixture.
        w("stray.html", page_html(title="A Stray Page With An Adequate Title", body=body))
        w("sitemap.xml",
          '<?xml version="1.0" encoding="UTF-8"?>\n'
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
          "<url><loc>https://example.com/</loc></url>"
          "<url><loc>https://example.com/linked.html</loc></url>"
          "<url><loc>https://example.com/stray.html</loc></url>"
          "<url><loc>https://example.com/gone.html</loc></url>"
          "</urlset>")

        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=cls.root)
        cls.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.httpd.RequestHandlerClass.log_message = lambda *a, **k: None
        cls.base = "http://127.0.0.1:{0}/".format(cls.httpd.server_address[1])
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

        pages, _, robots, sitemap, _, _, cls.skipped, _, _ = crawl.crawl_http(cls.base)
        cls.paths = sorted(p["url"] for p in pages)
        for p in pages:
            p["robots_allowed"], p["robots_rule"] = True, None
        sm_urls, _ = S.parse_sitemap(sitemap)
        doc = {
            "meta": {"source": cls.base, "mode": "http", "page_count": len(pages),
                     "base_url": None, "excluded_dirs_present": []},
            "robots": {"found": bool(robots), "sitemaps": [], "groups": [], "raw": robots},
            "sitemap": {"found": bool(sitemap), "urls": sm_urls, "notes": []},
            "assets": [], "pages": pages, "extras": {},
            "referenced_assets": [], "referenced_basenames": [],
        }
        cls.found = [(f["id"], tuple(f["pages"])) for f in audit.audit(doc)["findings"]]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.root, ignore_errors=True)

    def ids_for(self, path):
        return [i for i, pgs in self.found if pgs == (path,)]

    def test_unlinked_sitemap_page_is_crawled(self):
        self.assertIn("/stray.html", self.paths,
                      "a sitemap entry must seed the crawl frontier")

    def test_live_unlinked_page_is_not_called_a_dead_sitemap_url(self):
        self.assertNotIn("S1-SITEMAP-ORPHAN", self.ids_for("/stray.html"),
                         "/stray.html returns 200; it is an orphan, not a dead sitemap URL")

    def test_live_unlinked_page_is_reported_as_an_orphan(self):
        self.assertIn("S2-ORPHAN", self.ids_for("/stray.html"))

    def test_genuinely_missing_sitemap_url_still_reported(self):
        """The fix must not silence the finding it was confused with: /gone.html is a
        404, so it must stay out of `pages` and keep firing S1-SITEMAP-ORPHAN."""
        self.assertNotIn("/gone.html", self.paths)
        self.assertIn("S1-SITEMAP-ORPHAN", self.ids_for("/gone.html"))


class TestHttpRedirects(unittest.TestCase):
    """REGRESSION found by the v1.0.3 review: /about 301s to /about/, the crawl stored
    the same content under both paths, S3-DUPLICATE-EXACT fired (critical) and the
    redirect itself was never visible."""

    # Home links to the redirecting path first, so the redirect target is NOT yet crawled.
    HOME_LINKS = '<a href="/about">About</a>'
    CONTACT_LINKS = ""

    @classmethod
    def setUpClass(cls):
        try:
            import requests  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("requests not installed (http mode is optional)")
        import functools
        import http.server
        import threading

        cls.root = tempfile.mkdtemp(prefix="sitemend-redirect-test-")
        os.makedirs(os.path.join(cls.root, "about"))
        os.makedirs(os.path.join(cls.root, "contact"))
        with open(os.path.join(cls.root, "index.html"), "w", encoding="utf-8") as f:
            f.write(page_html(body="<h1>Home</h1><p>" + cls.HOME_LINKS + " " +
                                   ("home " * 300) + "</p>"))
        with open(os.path.join(cls.root, "about", "index.html"), "w", encoding="utf-8") as f:
            f.write(page_html(title="About This Site And Its Maker Title",
                              body="<h1>About</h1><p>" + ("about " * 300) + "</p>"))
        with open(os.path.join(cls.root, "contact", "index.html"), "w", encoding="utf-8") as f:
            f.write(page_html(title="Contact The Team Behind This Site Title",
                              body="<h1>Contact</h1><p>" + cls.CONTACT_LINKS + " " +
                                   ("contact " * 300) + "</p>"))
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=cls.root)
        cls.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.httpd.RequestHandlerClass.log_message = lambda *a, **k: None
        base = "http://127.0.0.1:{0}/".format(cls.httpd.server_address[1])
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

        cls.pages, _, robots, sitemap, _, _, cls.skipped, _, _ = crawl.crawl_http(base)
        for p in cls.pages:
            p["robots_allowed"], p["robots_rule"] = True, None
        doc = {"meta": {"source": base, "mode": "http", "page_count": len(cls.pages),
                        "base_url": None, "excluded_dirs_present": []},
               "robots": {"found": False, "sitemaps": [], "groups": [], "raw": ""},
               "sitemap": {"found": False, "urls": [], "notes": []},
               "assets": [], "pages": cls.pages, "extras": {},
               "referenced_assets": [], "referenced_basenames": []}
        cls.ids = [f["id"] for f in audit.audit(doc)["findings"]]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.root, ignore_errors=True)

    def test_redirect_target_is_stored_once_under_its_final_path(self):
        self.assertEqual(sorted(p["url"] for p in self.pages),
                         ["/", "/about/"] + (["/contact/"] if self.CONTACT_LINKS else []))

    def test_requested_path_becomes_an_alias(self):
        about = [p for p in self.pages if p["url"] == "/about/"][0]
        self.assertIn("/about", about["aliases"])

    def test_no_false_duplicate_or_broken_link(self):
        self.assertNotIn("S3-DUPLICATE-EXACT", self.ids)
        self.assertNotIn("S1-BROKEN-LINK", self.ids)


class TestHttpRedirectToCrawledTarget(TestHttpRedirects):
    """The redirect target is crawled BEFORE the redirecting URL is fetched: home links
    /about/ directly, then /contact/ links the redirecting /about. The second fetch must
    not create a page, yet /about must still resolve (no S1-BROKEN-LINK)."""

    HOME_LINKS = '<a href="/about/">About</a> <a href="/contact/">Contact</a>'
    CONTACT_LINKS = '<a href="/about">About</a>'


class TestDashboardTemplate(unittest.TestCase):
    """REGRESSION found while regenerating the README screenshot: gateClass() returned
    'gate-block', the pill class was derived from it as 'block', and the stylesheet
    defined '.pill.blocked', so the BLOCKED pill had no styling from v1.0.1 on."""

    def test_every_gate_state_has_matching_pill_and_mark_styles(self):
        import re
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets",
                            "dashboard.html")
        with open(path, encoding="utf-8") as f:
            html = f.read()
        body = re.search(r"const gateClass.*?;", html, re.S).group(0)
        classes = re.findall(r'"(gate-[a-z]+)"', body)
        self.assertEqual(len(set(classes)), 3, "expected blocked, clear and unassessed")
        for cls in set(classes):
            pill = cls.replace("gate-", "")        # how render() derives the pill class
            self.assertIn(".pill." + pill + "{", html, "no pill style for " + cls)
            self.assertIn("." + cls + " span{", html, "no mark style for " + cls)


class TestPlaceholderDomain(Base):
    """A site whose canonicals or sitemap point at example.com, localhost or similar tells
    search engines to index a domain that is not its own. It was missed because the base
    origin is inferred from those same URLs, so a uniformly wrong site looked consistent.
    Found when a plain prompt noticed it and sitemend did not."""

    def _ids(self, canonical=None, sitemap_host=None, robots_sitemap=None):
        extra = '<link rel="canonical" href="{0}">'.format(canonical) if canonical else ""
        self.fx.write("index.html", page_html(head_extra=extra))
        if sitemap_host:
            self.fx.write("sitemap.xml",
                          "<urlset><url><loc>https://{0}/</loc></url></urlset>".format(sitemap_host))
        if robots_sitemap:
            self.fx.write("robots.txt", "User-agent: *\nAllow: /\nSitemap: {0}\n".format(robots_sitemap))
        return self.fx.audit()["findings"]

    def _hit(self, findings):
        return [f for f in findings if f["id"] == "S1-PLACEHOLDER-DOMAIN"]

    def test_canonical_on_example_com_is_flagged(self):
        hit = self._hit(self._ids(canonical="https://example.com/"))
        self.assertEqual(len(hit), 1)
        self.assertEqual(hit[0]["severity"], "high")
        self.assertIn("canonical", hit[0]["evidence"])

    def test_subdomain_of_a_reserved_name_is_flagged(self):
        self.assertTrue(self._hit(self._ids(sitemap_host="demo.example.org")))

    def test_localhost_in_robots_sitemap_line_is_flagged(self):
        self.assertTrue(self._hit(self._ids(robots_sitemap="http://localhost:3000/sitemap.xml")))

    def test_reserved_tld_is_flagged(self):
        self.assertTrue(self._hit(self._ids(canonical="https://shop.test/")))

    def test_a_real_domain_is_not_flagged(self):
        self.assertEqual(self._hit(self._ids(canonical="https://www.vaavkitchenandcaterers.com/",
                                             sitemap_host="www.vaavkitchenandcaterers.com")), [])

    def test_lookalike_names_are_not_flagged(self):
        """Suffix matching must be on whole labels: notexample.com and example.community
        are not example.com."""
        self.assertEqual(self._hit(self._ids(canonical="https://notexample.com/")), [])
        self.assertEqual(self._hit(self._ids(sitemap_host="example.community")), [])


class TestOpenGraph(Base):
    def _og(self, head_extra="", **kw):
        self.fx.write("index.html", page_html(head_extra=head_extra, **kw))
        return [f for f in self.fx.audit()["findings"] if f["id"] == "S3-OG-MISSING"]

    def test_page_with_no_open_graph_tags_is_flagged_low(self):
        hit = self._og()
        self.assertEqual(len(hit), 1)
        self.assertEqual(hit[0]["severity"], "low")
        for tag in ("og:title", "og:description", "og:image"):
            self.assertIn(tag, hit[0]["evidence"])

    def test_complete_open_graph_is_not_flagged(self):
        og = ('<meta property="og:title" content="T"><meta property="og:description" content="D">'
              '<meta property="og:image" content="https://x.test/i.png">')
        self.assertEqual(self._og(head_extra=og), [])

    def test_partial_open_graph_names_only_what_is_missing(self):
        hit = self._og(head_extra='<meta property="og:title" content="T">')
        self.assertEqual(len(hit), 1)
        self.assertNotIn("og:title", hit[0]["evidence"])
        self.assertIn("og:image", hit[0]["evidence"])

    def test_noindex_and_utility_pages_are_not_flagged(self):
        self.fx.write("index.html", page_html(
            head_extra='<meta property="og:title" content="T"><meta property="og:description" '
                       'content="D"><meta property="og:image" content="https://x.test/i.png">'))
        self.fx.write("hidden.html", page_html(head_extra='<meta name="robots" content="noindex">'))
        self.fx.write("404.html", page_html())
        hits = [f for f in self.fx.audit()["findings"] if f["id"] == "S3-OG-MISSING"]
        self.assertEqual(hits, [], "noindex and 404 pages are never shared or indexed")


def alt(*pairs):
    return "".join('<link rel="alternate" hreflang="{0}" href="{1}">'.format(*p) for p in pairs)


class TestHreflang(Base):
    def _ids(self, en, fr, home=""):
        self.fx.write("index.html", page_html(title="Home Page With An Adequate Title", head_extra=home))
        self.fx.write("en/index.html", page_html(title="English Page With An Adequate Title", head_extra=en))
        self.fx.write("fr/index.html", page_html(title="French Page With An Adequate Title", head_extra=fr))
        return [(f["id"], tuple(f["pages"]), f["evidence"]) for f in self.fx.audit()["findings"]
                if f["id"].startswith("S1-HREFLANG")]

    def test_reciprocal_set_with_self_references_is_clean(self):
        both = alt(("en", "/en/"), ("fr", "/fr/"), ("x-default", "/en/"))
        self.assertEqual(self._ids(both, both), [])

    def test_missing_return_tag_names_the_silent_page(self):
        hits = self._ids(alt(("en", "/en/"), ("fr", "/fr/")), "")
        self.assertEqual([h[:2] for h in hits], [("S1-HREFLANG-NO-RETURN", ("/en/",))])
        self.assertIn("/fr/", hits[0][2])

    def test_page_missing_from_its_own_set_is_flagged(self):
        hits = self._ids(alt(("fr", "/fr/")), alt(("en", "/en/"), ("fr", "/fr/")))
        self.assertIn(("S1-HREFLANG-NO-SELF", ("/en/",)), [h[:2] for h in hits])

    def test_alternate_that_does_not_exist_is_broken(self):
        hits = self._ids(alt(("en", "/en/"), ("de", "/de/")), "")
        self.assertIn(("S1-HREFLANG-BROKEN", ("/en/",)), [h[:2] for h in hits])

    def test_invalid_codes_flagged_valid_codes_are_not(self):
        bad = self._ids(alt(("en_GB", "/en/")), "")
        self.assertIn("S1-HREFLANG-INVALID", [h[0] for h in bad])
        for code in ("en-GB", "x-default", "zh-Hant-TW", "es-419", "fil"):
            self.assertTrue(audit.HREFLANG_RE.match(code), code)

    def test_other_origin_alternates_are_not_checked(self):
        """A cross-domain alternate cannot be verified from this crawl, so it is not 'broken'."""
        self.fx.write("index.html", page_html(head_extra=alt(
            ("en", "https://acme-widgets.com/"), ("fr", "https://acme-widgets.fr/"))))
        doc = self.fx.crawl()
        doc["meta"]["base_url"] = "https://acme-widgets.com"
        ids = [f["id"] for f in audit.audit(doc)["findings"]]
        self.assertNotIn("S1-HREFLANG-BROKEN", ids)

    def test_slashless_href_resolves_against_an_http_mode_alias_set(self):
        """An http crawl records a directory page as {/en/, /en/index.html}, with no
        slash-less alias, so /en used to be reported as a page that does not exist.
        (fs crawls already alias /en, which is why this is not a Fixture test.)"""
        alias = {"/en/": "/en/", "/en/index.html": "/en/"}
        self.assertEqual(audit.hreflang_target("/en", "/", alias, None), ("internal", "/en/"))
        self.assertEqual(audit.hreflang_target("https://acme-widgets.com/en", "/", alias, None),
                         ("internal", "/en/"))
        self.assertEqual(audit.hreflang_target("/en/", "/", {"/en": "/en"}, None), ("internal", "/en"))

    def test_wrong_case_and_file_paths_stay_broken(self):
        """Guard: the tolerance is for directory slashes only. Paths are case-sensitive
        and /about.html is not /about.html/."""
        hits = self._ids(alt(("en", "/en/"), ("fr", "/FR/")), alt(("fr", "/fr/"), ("en", "/en/")))
        self.assertIn(("S1-HREFLANG-BROKEN", ("/en/",)), [h[:2] for h in hits])
        self.assertIsNone(audit.hreflang_target("/about.html/", "/", {"/about.html": "/about.html"}, None)[1])

    def _variants(self, en_head, us_head):
        home = "<h1>Home</h1><p>" + "other " * 300 + "</p>"
        # A distinct description keeps the home page out of the cannibalization check,
        # so the assertions below are about the two alternates only.
        self.fx.write("index.html", page_html(
            title="Home Page With An Adequate Title", body=home,
            desc="Welcome to the company front page, where you can find our latest news and contact details."))
        self.fx.write("en/index.html", page_html(title="British English Page Title Here Ok", head_extra=en_head))
        self.fx.write("us/index.html", page_html(title="American English Page Title Here Ok", head_extra=us_head))
        return [f["id"] for f in self.fx.audit()["findings"]]

    def test_reciprocal_regional_variants_are_not_duplicates(self):
        """en-GB and en-US pages are meant to be near-identical; hreflang is how the site
        says so, and reporting them as duplicates would tell the owner to merge them."""
        both = alt(("en-GB", "/en/"), ("en-US", "/us/"))
        ids = self._variants(both, both)
        for dup in ("S3-DUPLICATE-EXACT", "S3-NEAR-DUPLICATE", "S3-CANNIBALIZATION"):
            self.assertNotIn(dup, ids)

    def test_identical_pages_without_a_return_tag_are_still_duplicates(self):
        ids = self._variants(alt(("en-GB", "/en/"), ("en-US", "/us/")), "")
        self.assertIn("S3-DUPLICATE-EXACT", ids)


class TestMixedContent(Base):
    def _hit(self, body_extra="", canonical="https://acme-widgets.com/"):
        head = '<link rel="canonical" href="{0}">'.format(canonical) if canonical else ""
        self.fx.write("index.html", page_html(head_extra=head,
                                              body="<h1>H</h1><p>" + "word " * 300 + "</p>" + body_extra))
        return [f for f in self.fx.audit()["findings"] if f["id"] == "S1-MIXED-CONTENT"]

    def test_http_image_on_https_page_is_medium(self):
        hit = self._hit('<img src="http://cdn.test/a.png" alt="a" width="1" height="1">')
        self.assertEqual([f["severity"] for f in hit], ["medium"])
        self.assertIn("http://cdn.test/a.png", hit[0]["evidence"])

    def test_http_script_is_high_because_browsers_block_it(self):
        hit = self._hit('<script src="http://cdn.test/a.js"></script>')
        self.assertEqual([f["severity"] for f in hit], ["high"])

    def test_https_resources_are_fine(self):
        self.assertEqual(self._hit('<script src="https://cdn.test/a.js"></script>'), [])

    def test_an_http_page_cannot_have_mixed_content(self):
        self.assertEqual(self._hit('<script src="http://cdn.test/a.js"></script>', canonical=None), [])


class TestSitemapLastmod(Base):
    def _ids(self, dates):
        urls = "".join("<url><loc>https://acme-widgets.com/p{0}</loc>{1}</url>".format(
            i, "<lastmod>{0}</lastmod>".format(d) if d else "") for i, d in enumerate(dates))
        self.fx.write("index.html", page_html())
        self.fx.write("sitemap.xml", '<?xml version="1.0"?><urlset xmlns='
                      '"http://www.sitemaps.org/schemas/sitemap/0.9">' + urls + "</urlset>")
        return [f["id"] for f in self.fx.audit()["findings"] if "LASTMOD" in f["id"]]

    def test_identical_dates_on_many_urls_are_flagged(self):
        self.assertEqual(self._ids(["2026-01-01"] * 5), ["S1-SITEMAP-LASTMOD-UNIFORM"])

    def test_few_urls_may_honestly_share_a_date(self):
        self.assertEqual(self._ids(["2026-01-01"] * 4), [])

    def test_distinct_valid_dates_are_clean(self):
        self.assertEqual(self._ids(["2026-01-0%d" % i for i in range(1, 6)]), [])
        self.assertEqual(self._ids(["2026-05-01T10:00:00Z", "2026-05-02T10:00:00+05:30"]), [])

    def test_missing_lastmod_is_not_an_error(self):
        self.assertEqual(self._ids([None] * 6), [])

    def test_invalid_dates_are_flagged(self):
        for bad in ("2026-13-45", "2026-05-01 10:00", "yesterday", "01/05/2026"):
            self.assertEqual(self._ids(["2026-01-01", bad]), ["S1-SITEMAP-LASTMOD-INVALID"], bad)

    def test_sitemap_parsing_is_linear_on_unclosed_tags(self):
        """SECURITY: "<loc>(.*?)</loc>" let every unclosed <loc> scan to the end of the
        file, so a crafted 48 KB sitemap took 10 s and 1 MB would hold a CI job for hours.
        The audited site controls the file; in the preview workflow it is a PR's deploy."""
        start = time.time()
        S.parse_sitemap("<urlset>" + "<loc>a" * 80000)
        S.parse_sitemap_lastmods("<urlset>" + "<url><loc>a<lastmod>b" * 80000)
        self.assertLess(time.time() - start, 2.0)
        # Well-formed sitemaps read as before: whitespace around a value, a CDATA value
        # kept as written, a lastmod per <url>.
        xml = ("<urlset><url><loc> https://a.test/p </loc><lastmod>2026-01-01</lastmod></url>"
               "<url><loc><![CDATA[https://a.test/q]]></loc></url>\n<url>\n<LOC>\nhttps://a.test/r\n</LOC>\n</url></urlset>")
        self.assertEqual(S.parse_sitemap(xml),
                         (["https://a.test/p", "<![CDATA[https://a.test/q]]>", "https://a.test/r"], []))
        self.assertEqual(S.parse_sitemap_lastmods(xml),
                         [("https://a.test/p", "2026-01-01"), ("<![CDATA[https://a.test/q]]>", None),
                          ("https://a.test/r", None)])


class TestSecurityHeaders(Base):
    def _ids(self, base, headers, mode="http", source=None):
        self.fx.write("index.html", page_html())
        doc = self.fx.crawl()
        doc["meta"].update(mode=mode, base_url=base, source=base if source is None else source)
        for p in doc["pages"]:
            p["status"] = 200
            if headers is not None:
                p["security_headers"] = headers
        return [f for f in audit.audit(doc)["findings"] if f["id"] == "S1-SECURITY-HEADERS"]

    def test_missing_headers_on_https_are_low(self):
        hit = self._ids("https://acme-widgets.com", {})
        self.assertEqual([f["severity"] for f in hit], ["low"])
        self.assertIn("Strict-Transport-Security", hit[0]["evidence"])
        self.assertIn("X-Content-Type-Options", hit[0]["evidence"])

    def test_present_headers_are_clean(self):
        self.assertEqual(self._ids("https://acme-widgets.com", {
            "strict-transport-security": "max-age=1", "x-content-type-options": "nosniff"}), [])

    def test_https_canonicals_on_a_plain_http_crawl_are_never_nagged(self):
        """REGRESSION found by the PR #12 review: base_url is inferred from the canonicals,
        so crawling a local http dev server of an https site reported 'HSTS missing' --
        a header that cannot be sent over http, so the finding could never be fixed."""
        self.assertEqual(self._ids("https://acme-widgets.com", {}, source="http://127.0.0.1:8000/"), [])

    def test_plain_http_dev_server_is_never_nagged(self):
        self.assertEqual(self._ids("http://127.0.0.1:8000", {}), [])

    def test_fs_mode_and_old_crawls_say_nothing(self):
        self.assertEqual(self._ids("https://acme-widgets.com", {}, mode="fs"), [])
        self.assertEqual(self._ids("https://acme-widgets.com", None), [])


class TestJsShellAndRenderedDiff(Base):
    SHELL = '<div id="root"></div>'

    def _ids(self, body, mutate=None):
        self.fx.write("index.html", page_html(body=body))
        doc = self.fx.crawl()
        if mutate:
            mutate(doc["pages"][0])
        return {f["id"]: f for f in audit.audit(doc)["findings"] if f["id"].startswith("S1-JS")}

    def test_empty_mount_point_is_flagged_as_a_shell(self):
        self.assertIn("S1-JS-SHELL", self._ids(self.SHELL))

    def test_a_shell_is_not_also_called_h1_less(self):
        """Its headings only exist after JS runs; the shell finding is the honest one."""
        self.fx.write("index.html", page_html(body=self.SHELL))
        ids = [f["id"] for f in self.fx.audit()["findings"]]
        self.assertIn("S1-JS-SHELL", ids)
        self.assertNotIn("S2-H1-MISSING", ids)

    def test_mount_point_with_server_rendered_text_is_not(self):
        self.assertEqual(self._ids('<div id="root"><h1>Hi</h1><p>' + "word " * 80 + "</p></div>"), {})

    def test_a_normal_page_is_not_a_shell(self):
        self.assertEqual(self._ids("<h1>H</h1><p>" + "word " * 300 + "</p>"), {})

    def _rendered(self, raw_words=5, canonical=None, robots=None, **page):
        def m(p):
            p.update(rendered=True, **page)
            p["raw"] = {"words": raw_words, "title": p["title"], "canonical": canonical,
                        "robots_meta": robots, "h1": 0}
        return m

    def test_text_that_only_exists_after_js_is_flagged(self):
        ids = self._ids("<h1>H</h1><p>" + "word " * 300 + "</p>", self._rendered(raw_words=5))
        self.assertIn("S1-JS-DEPENDENT", ids)
        self.assertIn("raw HTML 5 words", ids["S1-JS-DEPENDENT"]["evidence"])

    def test_server_rendered_text_is_not_js_dependent(self):
        ids = self._ids("<h1>H</h1><p>" + "word " * 300 + "</p>", self._rendered(raw_words=300))
        self.assertNotIn("S1-JS-DEPENDENT", ids)
        self.assertNotIn("S1-JS-SHELL", ids)

    def test_js_that_injects_noindex_or_a_canonical_is_high(self):
        body = "<h1>H</h1><p>" + "word " * 300 + "</p>"
        ids = self._ids(body, self._rendered(raw_words=300, noindex=True, robots_meta="noindex"))
        self.assertEqual(ids["S1-JS-HEAD-MISMATCH"]["severity"], "high")
        ids = self._ids(body, self._rendered(raw_words=300, canonical="https://acme-widgets.com/old"))
        self.assertIn("canonical", ids["S1-JS-HEAD-MISMATCH"]["evidence"])


class _JsServer:
    """A site whose only page is an empty shell that JavaScript fills in."""

    @classmethod
    def start(cls):
        import http.server
        import threading
        html = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width"><title>Shell</title></head>'
                '<body><div id="root"></div><script>document.getElementById("root").innerHTML='
                '"<h1>Rendered by JS</h1><p>" + "word ".repeat(150) + "</p>";</script></body></html>'
                ).encode()

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                ok = self.path == "/"
                body = html if ok else b"nope"
                self.send_response(200 if ok else 404)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv, "http://127.0.0.1:%d/" % srv.server_address[1]


class TestRenderCrawl(unittest.TestCase):
    """The plain crawl cannot see JS-built content and says so; --render shows it.
    The Chrome half is opt-in (SITEMEND_RENDER_TEST=1), like the Lighthouse test: CI
    cannot be assumed to have a usable headless Chrome, and a skipped test is honest."""

    @classmethod
    def setUpClass(cls):
        try:
            import requests  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("requests not installed (http mode is optional)")
        cls.srv, cls.base = _JsServer.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def test_plain_crawl_sees_an_empty_shell(self):
        page = crawl.crawl_http(self.base)[0][0]
        self.assertTrue(page["js_shell"])
        self.assertLess(page["full_word_count"], 5)     # just the <title>
        self.assertNotIn("rendered", page)

    @unittest.skipUnless(os.environ.get("SITEMEND_RENDER_TEST") == "1" and S.find_chrome(),
                         "set SITEMEND_RENDER_TEST=1 (needs Chrome, Chromium or Edge)")
    def test_render_crawl_sees_the_javascript_content(self):
        page = crawl.crawl_http(self.base, render=True, render_limit=3)[0][0]
        self.assertIsNone(page.get("render_error"), page.get("render_error"))
        self.assertTrue(page["rendered"])
        self.assertEqual(page["h1"], ["Rendered by JS"])
        self.assertLess(page["raw"]["words"], 5)
        self.assertGreaterEqual(page["full_word_count"], 150)
        self.assertFalse(page["js_shell"])

    def test_render_without_chrome_stops_with_a_clear_message(self):
        real, S.find_chrome = S.find_chrome, lambda: None
        self.addCleanup(setattr, S, "find_chrome", real)
        with self.assertRaises(SystemExit) as cm:
            crawl.crawl_http(self.base, render=True)
        self.assertIn("Chrome", str(cm.exception))


class TestHttpRedirectChains(unittest.TestCase):
    """/a -> /b -> /c is two hops; /x -> /d is one and is fine; /loop1 <-> /loop2 never ends."""

    @classmethod
    def setUpClass(cls):
        try:
            import requests  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("requests not installed (http mode is optional)")
        import http.server
        import threading
        redirects = {"/a": "/b", "/b": "/c", "/x": "/d", "/loop1": "/loop2", "/loop2": "/loop1"}
        home = page_html(title="Home Page With An Adequate Title", body=(
            '<h1>H</h1><p><a href="/a">a</a> <a href="/x">x</a> <a href="/loop1">l</a> '
            + "word " * 300 + "</p>"))
        pages = {"/": home,
                 "/c": page_html(title="Chain Target Page With A Fine Title"),
                 "/d": page_html(title="Single Hop Target With A Fine Title")}

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path in redirects:
                    self.send_response(301)
                    self.send_header("Location", redirects[self.path])
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                body = pages.get(self.path, "nope").encode()
                self.send_response(200 if self.path in pages else 404)
                self.send_header("Content-Type", "text/html")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d/" % cls.srv.server_address[1]
        cls.pages, _, _, _, _, _, skipped, _, _ = crawl.crawl_http(base)
        for p in cls.pages:
            p["robots_allowed"], p["robots_rule"] = True, None
        doc = {"meta": {"source": base, "mode": "http", "page_count": len(cls.pages),
                        "base_url": None, "excluded_dirs_present": [], "skipped": skipped},
               "robots": {"found": False, "sitemaps": [], "groups": [], "raw": ""},
               "sitemap": {"found": False, "urls": [], "notes": []},
               "assets": [], "pages": cls.pages, "extras": {},
               "referenced_assets": [], "referenced_basenames": []}
        cls.findings = audit.audit(doc)["findings"]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def of(self, fid):
        return [f for f in self.findings if f["id"] == fid]

    def test_two_hop_chain_is_flagged_with_every_hop_in_the_evidence(self):
        hit = self.of("S1-REDIRECT-CHAIN")
        self.assertEqual([f["pages"] for f in hit], [["/c"]])
        for hop in ("/a", "/b", "/c"):
            self.assertIn(hop, hit[0]["evidence"])

    def test_a_single_redirect_is_not_a_chain(self):
        self.assertNotIn(["/d"], [f["pages"] for f in self.of("S1-REDIRECT-CHAIN")])

    def test_redirect_loop_is_flagged_high(self):
        hit = self.of("S1-REDIRECT-LOOP")
        self.assertEqual([f["pages"] for f in hit], [["/loop1"]])
        self.assertEqual(hit[0]["severity"], "high")

    def test_response_security_headers_are_recorded(self):
        home = next(p for p in self.pages if p["url"] == "/")
        self.assertEqual(home["security_headers"], {"x-content-type-options": "nosniff"})


class TestChromeCommand(unittest.TestCase):
    """--no-sandbox runs a site's JavaScript with Chrome's sandbox off, so it is only
    added when Chrome would not start otherwise (root) or the user asks for it."""

    def cmd(self, **kw):
        return S.chrome_cmd("chrome", "http://x.test/", "/tmp/p", **kw)

    def test_sandbox_stays_on_for_a_normal_posix_user(self):
        self.assertNotIn("--no-sandbox", self.cmd(nt=False, root=False, env={}))

    def test_root_needs_the_sandbox_off(self):
        self.assertIn("--no-sandbox", self.cmd(nt=False, root=True, env={}))

    def test_env_var_opts_in_explicitly(self):
        self.assertIn("--no-sandbox",
                      self.cmd(nt=False, root=False, env={"SITEMEND_NO_SANDBOX": "1"}))

    def test_windows_never_gets_the_flag(self):
        self.assertNotIn("--no-sandbox",
                         self.cmd(nt=True, root=True, env={"SITEMEND_NO_SANDBOX": "1"}))


class TestIntlDemoSite(unittest.TestCase):
    """End-to-end guard for the v1.2.0 rules: crawl the fixture on disk through the real
    CLI path and require exactly the planted findings, so a rule that stops firing, or
    starts firing on clean pages, fails here."""

    ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "examples", "demo-site-intl")

    def test_planted_defects_are_found_and_nothing_else_leaks(self):
        out = os.path.join(tempfile.mkdtemp(prefix="sitemend-intl-"), "o")
        self.addCleanup(shutil.rmtree, os.path.dirname(out), True)
        findings = sitemend.audit(self.ROOT, out, 200, None)
        with open(findings, encoding="utf-8") as f:
            ids = sorted(x["id"] for x in json.load(f)["findings"])
        self.assertEqual(ids, sorted([
            "S1-HREFLANG-BROKEN", "S1-HREFLANG-INVALID", "S1-HREFLANG-NO-RETURN",
            "S1-JS-SHELL", "S1-MIXED-CONTENT", "S1-SITEMAP-LASTMOD-INVALID",
            "S2-BREADCRUMB-MISSING", "S3-THIN", "S3-THIN", "S3-THIN", "S3-THIN"]))


class TestPackaging(unittest.TestCase):
    ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

    def _read(self, *parts):
        with open(os.path.join(self.ROOT, *parts), encoding="utf-8") as f:
            return f.read()

    def test_every_manifest_carries_the_same_version(self):
        """Three places name the version; releasing with one stale is how a PyPI upload
        and a plugin tag end up disagreeing."""
        import re
        py = re.search(r'^version = "([^"]+)"', self._read("pyproject.toml"), re.M).group(1)
        plugin = json.loads(self._read(".claude-plugin", "plugin.json"))["version"]
        skill = re.search(r"^version: (\S+)", self._read("SKILL.md"), re.M).group(1)
        self.assertEqual((py, plugin), (skill, skill))

    def test_the_example_workflows_pin_this_version(self):
        """The examples pin @vX.Y.Z so a release never changes a user's gate unasked;
        they must name the version being released, not the last one."""
        import re
        py = re.search(r'^version = "([^"]+)"', self._read("pyproject.toml"), re.M).group(1)
        for parts in (("examples", "github-action", "sitemend.yml"),
                      ("examples", "github-action", "preview.yml"), ("README.md",)):
            pins = re.findall(r"SurendharVr/sitemend@v([0-9.]+)", self._read(*parts))
            self.assertEqual(set(pins), {py}, "/".join(parts))

    def test_the_readme_states_the_real_test_count(self):
        """The README said 189 tests when the suite ran 241. A tool sold on not inventing
        numbers cannot carry a stale one; this is the runner's own count, skips included."""
        import re
        real = unittest.defaultTestLoader.loadTestsFromModule(
            sys.modules[type(self).__module__]).countTestCases()
        stated = re.findall(r"\b(\d+) tests\b", self._read("README.md"))
        self.assertTrue(stated)
        self.assertEqual(set(stated), {str(real)})

    def test_the_wheel_ships_every_script_and_the_dashboard_template(self):
        """pyproject maps scripts/ and assets/ into the wheel by directory, so a new script
        is picked up automatically -- but only if it is a module in scripts/."""
        scripts = {f for f in os.listdir(os.path.join(self.ROOT, "scripts")) if f.endswith(".py")}
        self.assertLessEqual({"sitemend.py", "crawl.py", "audit.py", "report.py", "verify.py",
                              "schema_check.py", "build_dashboard.py", "seolib.py", "__init__.py"},
                             scripts)
        self.assertTrue(os.path.isfile(os.path.join(self.ROOT, "assets", "dashboard.html")))

    def test_dashboard_template_resolves_in_the_source_tree(self):
        import build_dashboard
        self.assertTrue(os.path.isfile(build_dashboard.TEMPLATE))

    def test_license_metadata_is_not_the_deprecated_form(self):
        """setuptools drops the table form of `license` and license classifiers on
        2027-02-18. SPDX string + setuptools>=77 is the supported spelling."""
        text = self._read("pyproject.toml")
        self.assertIn('license = "MIT"', text)
        self.assertNotIn("license = {", text)
        self.assertNotIn("License ::", text)
        self.assertIn("setuptools>=77", text)


class TestHttpRedirectChainOrder(unittest.TestCase):
    """REGRESSION found by the PR #12 review: when the redirect target had already been
    crawled directly, the chain leading to it was discarded and S1-REDIRECT-CHAIN never
    fired. Home links to /c first, then to /a, and /a -> /b -> /c."""

    @classmethod
    def setUpClass(cls):
        try:
            import requests  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("requests not installed (http mode is optional)")
        import http.server
        import threading
        redirects = {"/a": "/b", "/b": "/c"}
        pages = {"/": page_html(title="Home Page With An Adequate Title", body=(
                     '<h1>H</h1><p><a href="/c">c</a> <a href="/a">a</a> ' + "word " * 300 + "</p>")),
                 "/c": page_html(title="Chain Target Page With A Fine Title")}

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path in redirects:
                    self.send_response(301)
                    self.send_header("Location", redirects[self.path])
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                body = pages.get(self.path, "nope").encode()
                self.send_response(200 if self.path in pages else 404)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d/" % cls.srv.server_address[1]
        cls.pages, _, _, _, _, _, skipped, _, _ = crawl.crawl_http(base)
        for p in cls.pages:
            p["robots_allowed"], p["robots_rule"] = True, None
        doc = {"meta": {"source": base, "mode": "http", "page_count": len(cls.pages),
                        "base_url": None, "excluded_dirs_present": [], "skipped": skipped},
               "robots": {"found": False, "sitemaps": [], "groups": [], "raw": ""},
               "sitemap": {"found": False, "urls": [], "notes": []},
               "assets": [], "pages": cls.pages, "extras": {},
               "referenced_assets": [], "referenced_basenames": []}
        cls.chains = [f for f in audit.audit(doc)["findings"] if f["id"] == "S1-REDIRECT-CHAIN"]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def test_chain_is_reported_even_though_the_target_was_crawled_first(self):
        self.assertEqual([f["pages"] for f in self.chains], [["/c"]])
        for hop in ("/a", "/b", "/c"):
            self.assertIn(hop, self.chains[0]["evidence"])


class TestVitalsCommand(unittest.TestCase):
    """REGRESSION found by the v1.0.3 review: on Windows the Lighthouse command ran
    with shell=True from a list, so cmd.exe saw an unquoted '&' in a page path and cut
    the command there (`/?q=a&lang=en` was measured as `/?q=a`, and the rest, including
    --output-path, was run as a separate command)."""

    def test_url_with_cmd_metacharacters_is_quoted(self):
        line = vitals._nt_cmdline(["npx", "lighthouse", "http://h/?q=a&lang=en", "--quiet"])
        self.assertEqual(line, 'npx lighthouse "http://h/?q=a&lang=en" --quiet')

    def test_arguments_with_spaces_are_quoted(self):
        line = vitals._nt_cmdline(["x", "--chrome-flags=--headless=new --no-sandbox"])
        self.assertEqual(line, 'x "--chrome-flags=--headless=new --no-sandbox"')

    def test_percent_encoding_is_allowed_and_quoted(self):
        self.assertEqual(vitals._nt_cmdline(["x", "http://h/a%20b"]), 'x "http://h/a%20b"')

    def test_quote_and_variable_expansion_are_refused(self):
        for bad in ('http://h/"&calc', "http://h/%PATH%", "http://h/%USERNAME%x"):
            with self.assertRaises(ValueError):
                vitals._nt_cmdline(["x", bad])

    def test_timeout_kills_grandchildren_too(self):
        """REGRESSION: the timeout used to kill only the shell, leaving node/Chrome
        running. Here the child spawns a grandchild that ticks into a file; after the
        timeout the ticking must stop."""
        d = tempfile.mkdtemp(prefix="sitemend-kill-")
        self.addCleanup(shutil.rmtree, d, True)
        tick = os.path.join(d, "tick.txt")
        grand = os.path.join(d, "grand.py")
        child = os.path.join(d, "child.py")
        with open(grand, "w") as f:
            f.write("import time\n"
                    "while True:\n"
                    "    open(%r, 'a').write('x')\n"
                    "    time.sleep(0.2)\n" % tick)
        with open(child, "w") as f:
            f.write("import subprocess, sys, time\n"
                    "subprocess.Popen([sys.executable, %r])\n"
                    "time.sleep(60)\n" % grand)
        import time
        with self.assertRaises(subprocess.TimeoutExpired):
            vitals.run_command([sys.executable, child], timeout=3)
        before = os.path.getsize(tick)
        time.sleep(1.2)
        self.assertEqual(os.path.getsize(tick), before, "the grandchild is still running")


class TestLighthouseSandbox(unittest.TestCase):
    """REGRESSION found by the 2026-10-16 audit: Lighthouse's Chrome always ran with
    --no-sandbox; the render path drops the sandbox only as root or on opt-out."""

    def flags(self, **kw):
        cmd = vitals.lighthouse_cmd("http://h/", "o.json", "mobile", **kw)
        return next(a for a in cmd if a.startswith("--chrome-flags="))

    def test_sandbox_is_kept_by_default(self):
        self.assertNotIn("--no-sandbox", self.flags(nt=False, root=False, env={}))
        self.assertNotIn("--no-sandbox", self.flags(nt=True, root=False, env={}))

    def test_root_or_the_opt_out_drops_it(self):
        self.assertIn("--no-sandbox", self.flags(nt=False, root=True, env={}))
        self.assertIn("--no-sandbox", self.flags(nt=False, root=False,
                                                 env={"SITEMEND_NO_SANDBOX": "1"}))


@unittest.skipUnless(os.environ.get("SITEMEND_LIGHTHOUSE_TEST") == "1",
                     "set SITEMEND_LIGHTHOUSE_TEST=1 (needs npx, Lighthouse and Chrome)")
class TestVitalsLive(unittest.TestCase):
    """Opt-in: runs real Lighthouse against a local server and checks the URL Chrome
    actually requested. CI has no Chrome, so this is run by hand before touching vitals.py."""

    def test_ampersand_in_page_path_reaches_the_server_intact(self):
        import http.server
        import threading
        seen = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.path)
                body = (b"<!doctype html><html lang=en><head><meta charset=utf-8><title>t</title>"
                        b"<meta name=viewport content='width=device-width'></head>"
                        b"<body><h1>hi</h1></body></html>")
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        wd = tempfile.mkdtemp(prefix="sitemend-lh-test-")
        self.addCleanup(shutil.rmtree, wd, True)
        base = "http://127.0.0.1:%d" % srv.server_address[1]
        res, err = vitals.run_one(base + "/?q=a&lang=en", "desktop", wd, timeout=150)
        self.assertIsNone(err)
        self.assertIn("/?q=a&lang=en", seen)


class TestHostMismatch(Base):
    """A preview deploy's host (*.vercel.app) baked into a production build was invisible:
    the base origin is inferred from the same URLs, and only canonicals were compared."""

    def _hit(self, canonical=None, og_url=None, sitemap_host=None, robots_sitemap=None,
             base="https://acme-widgets.com"):
        extra = ""
        if canonical:
            extra += '<link rel="canonical" href="{0}">'.format(canonical)
        if og_url:
            extra += '<meta property="og:url" content="{0}">'.format(og_url)
        self.fx.write("index.html", page_html(head_extra=extra))
        if sitemap_host:
            self.fx.write("sitemap.xml",
                          "<urlset><url><loc>https://{0}/</loc></url></urlset>".format(sitemap_host))
        if robots_sitemap:
            self.fx.write("robots.txt", "User-agent: *\nAllow: /\nSitemap: {0}\n".format(robots_sitemap))
        doc = self.fx.crawl()
        doc["meta"]["base_url"] = base
        return [f for f in audit.audit(doc)["findings"] if f["id"] == "S1-HOST-MISMATCH"]

    def test_preview_host_in_sitemap_is_critical(self):
        hit = self._hit(canonical="https://acme-widgets.com/", sitemap_host="acme-git-main.vercel.app")
        self.assertEqual(len(hit), 1)
        self.assertEqual(hit[0]["severity"], "critical")
        self.assertIn("acme-git-main.vercel.app", hit[0]["evidence"])
        self.assertIn("base URL acme-widgets.com", hit[0]["evidence"])

    def test_preview_host_in_og_url_is_flagged_on_the_page(self):
        hit = self._hit(canonical="https://acme-widgets.com/", og_url="https://acme.netlify.app/")
        self.assertEqual(hit[0]["pages"], ["/"])
        self.assertEqual(hit[0]["severity"], "critical")

    def test_www_against_apex_is_high(self):
        hit = self._hit(canonical="https://acme-widgets.com/", sitemap_host="www.acme-widgets.com",
                        robots_sitemap="https://acme-widgets.com/sitemap.xml")
        self.assertEqual([f["severity"] for f in hit], ["high"])

    def test_inconsistent_sources_without_a_base_url(self):
        self.assertTrue(self._hit(canonical="https://acme-widgets.com/",
                                  sitemap_host="acme.pages.dev", base=None))

    def test_consistent_site_is_clean(self):
        self.assertEqual(self._hit(canonical="https://acme-widgets.com/",
                                   og_url="https://acme-widgets.com/",
                                   sitemap_host="acme-widgets.com",
                                   robots_sitemap="https://acme-widgets.com/sitemap.xml"), [])

    def test_production_on_a_platform_host_is_clean(self):
        """A site whose real home IS acme.netlify.app is not a leak."""
        self.assertEqual(self._hit(canonical="https://acme.netlify.app/",
                                   sitemap_host="acme.netlify.app",
                                   base="https://acme.netlify.app"), [])

    def test_crawling_localhost_or_a_preview_is_not_a_mismatch(self):
        """`sitemend audit <url>` makes the crawled origin the base URL. A dev server or a
        preview deploy whose URLs all correctly name production must stay clean."""
        for base in ("http://127.0.0.1:8000", "https://acme-git-feat.vercel.app"):
            with self.subTest(base=base):
                self.assertEqual(self._hit(canonical="https://acme-widgets.com/",
                                           sitemap_host="acme-widgets.com", base=base), [])

    def test_preview_crawl_still_catches_a_preview_host_in_its_sitemap(self):
        """VERCEL_URL is the per-deploy host even in production, so a sitemap built from
        it is a real bug wherever it is crawled."""
        hit = self._hit(canonical="https://acme-widgets.com/", sitemap_host="acme-abc123.vercel.app",
                        base="https://acme-abc123.vercel.app")
        self.assertEqual([f["severity"] for f in hit], ["critical"])

    def test_relative_urls_and_schemes_are_not_hosts(self):
        self.assertEqual(self._hit(canonical="/", sitemap_host="acme-widgets.com",
                                   robots_sitemap="http://acme-widgets.com/sitemap.xml"), [])

    def test_canonical_alone_offsite_is_left_to_canonical_offsite(self):
        """Not reported twice: S1-CANONICAL-OFFSITE already names the page."""
        self.assertEqual(self._hit(canonical="https://acme.vercel.app/",
                                   sitemap_host="acme-widgets.com"), [])

    def test_placeholder_host_is_left_to_placeholder_domain(self):
        self.assertEqual(self._hit(canonical="https://acme-widgets.com/",
                                   sitemap_host="demo.example.com"), [])

    def test_preview_host_in_whole_sitemap_does_not_become_the_base(self):
        """fs mode infers the base URL. A sitemap that names only the preview host must
        not win over production canonicals, or every correct canonical is OFFSITE."""
        prod, preview = "https://sitemend-demo.dev", "https://x-git-y.vercel.app"
        for path in ("", "about/", "blog/"):
            self.fx.write(path + "index.html", page_html(
                head_extra='<link rel="canonical" href="{0}/{1}">'.format(prod, path)))
        self.fx.write("sitemap.xml", "<urlset>{0}</urlset>".format("".join(
            "<url><loc>{0}/{1}</loc></url>".format(preview, p) for p in ("", "about/", "blog/"))))
        doc = self.fx.crawl()
        doc["meta"]["base_url"] = crawl.infer_base_url(
            doc["sitemap"]["urls"], doc["pages"], doc["robots"]["sitemaps"])
        self.assertEqual(doc["meta"]["base_url"], prod)
        hits = [(f["id"], f["severity"]) for f in audit.audit(doc)["findings"]
                if f["id"] in ("S1-HOST-MISMATCH", "S1-CANONICAL-OFFSITE")]
        self.assertEqual(hits, [("S1-HOST-MISMATCH", "critical")])

    def test_one_preview_url_on_a_localhost_site_is_reported(self):
        """REGRESSION #70, a permanent test from the seeded recall run (exoscale-academy):
        every URL the site publishes names http://localhost:9876, and one sitemap <loc>
        leaked onto a preview host. The preview became the inferred base, the host check
        then saw a single host, and the only new finding was an unrelated MIXED-CONTENT."""
        local, preview = "http://localhost:9876", "https://seeded-git-preview.vercel.app"
        for path in ("", "about/"):
            self.fx.write(path + "index.html", page_html(
                head_extra='<link rel="canonical" href="{0}/{1}">'
                           '<script src="{0}/js/app.js"></script>'.format(local, path)))
        self.fx.write("sitemap.xml", "<urlset><url><loc>{0}/</loc></url>"
                                     "<url><loc>{1}/about/</loc></url></urlset>".format(preview, local))
        doc = self.fx.crawl()
        doc["meta"]["base_url"] = crawl.infer_base_url(
            doc["sitemap"]["urls"], doc["pages"], doc["robots"]["sitemaps"])
        self.assertEqual(doc["meta"]["base_url"], local)
        found = audit.audit(doc)["findings"]
        self.assertEqual([f["severity"] for f in found if f["id"] == "S1-HOST-MISMATCH"], ["critical"])
        self.assertNotIn("S1-MIXED-CONTENT", [f["id"] for f in found])

    def test_a_localhost_site_without_a_preview_url_has_no_mismatch(self):
        local = "http://localhost:9876"
        self.fx.write("index.html", page_html(head_extra='<link rel="canonical" href="{0}/">'.format(local)))
        self.fx.write("sitemap.xml", "<urlset><url><loc>{0}/</loc></url></urlset>".format(local))
        doc = self.fx.crawl()
        doc["meta"]["base_url"] = crawl.infer_base_url(
            doc["sitemap"]["urls"], doc["pages"], doc["robots"]["sitemaps"])
        self.assertNotIn("S1-HOST-MISMATCH", [f["id"] for f in audit.audit(doc)["findings"]])

    def test_an_example_com_leftover_on_a_platform_host_is_left_to_placeholder_domain(self):
        self.assertEqual(self._hit(canonical="https://acme.netlify.app/", og_url="https://example.com/",
                                   sitemap_host="acme.netlify.app", base="https://acme.netlify.app"), [])

    def test_preview_only_site_still_infers_its_own_host(self):
        """With no production host on offer, inference falls back to the first URL."""
        self.assertEqual(crawl.infer_base_url(["https://acme.netlify.app/"], [], []),
                         "https://acme.netlify.app")

    def _offsite(self, base):
        self.fx.write("index.html", page_html(
            head_extra='<link rel="canonical" href="https://acme-widgets.com/">'))
        doc = self.fx.crawl()
        doc["meta"]["base_url"] = base
        return [f for f in audit.audit(doc)["findings"] if f["id"] == "S1-CANONICAL-OFFSITE"]

    def test_dev_server_or_preview_crawl_does_not_flag_production_canonicals(self):
        """REGRESSION found by the 2026-10-16 audit: `sitemend audit http://127.0.0.1:8000/`
        reported every correct production canonical as critical S1-CANONICAL-OFFSITE."""
        for base in ("http://127.0.0.1:8000", "http://localhost:3000", "http://app.localhost:5173",
                     "https://acme-git-feat.vercel.app"):
            with self.subTest(base=base):
                self.assertEqual(self._offsite(base), [])

    def test_a_production_base_still_flags_an_offsite_canonical(self):
        self.assertEqual(len(self._offsite("https://acme-widgets.org")), 1)


class TestXRobotsTagNoindex(Base):
    """X-Robots-Tag: noindex on the production homepage (a preview-deploy header that
    shipped) is already the critical S1-NOT-INDEXABLE. Pinned so it stays that way."""

    def test_header_noindex_on_home_is_critical(self):
        self.fx.write("index.html", page_html())
        doc = self.fx.crawl()
        doc["meta"].update(mode="http", base_url="https://acme-widgets.com")
        doc["pages"][0]["x_robots_tag"] = "noindex"
        hit = [f for f in audit.audit(doc)["findings"] if f["id"] == "S1-NOT-INDEXABLE"]
        self.assertEqual([(f["severity"], f["evidence"]) for f in hit],
                         [("critical", "X-Robots-Tag noindex")])


class TestSoft404(unittest.TestCase):
    """The probe requests one random path at the origin root. A real server answering
    it 404 is clean; a catch-all answering 200 (SPA rewrite, redirect to home) is not."""

    def _serve(self, catch_all):
        try:
            import requests  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("requests not installed (http mode is optional)")
        import http.server
        import threading

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != "/" and catch_all == "redirect":
                    self.send_response(302)
                    self.send_header("Location", "/")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                code = 200 if self.path == "/" or catch_all == "spa" else 404
                body = b"<html><body>hi</body></html>"
                self.send_response(code)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return crawl.probe_soft404("http://127.0.0.1:%d/" % srv.server_address[1])

    def _hit(self, probe, mode="http"):
        doc = {"meta": {"mode": mode, "base_url": None, "soft404_probe": probe},
               "robots": {"found": True, "sitemaps": [], "groups": [], "raw": ""},
               "sitemap": {"found": True, "urls": [], "notes": [], "lastmods": []},
               "pages": [], "assets": []}
        return [f for f in audit.audit(doc)["findings"] if f["id"] == "S1-SOFT-404"]

    def test_proper_404_is_clean(self):
        probe = self._serve(None)
        self.assertEqual(probe["status"], 404)
        self.assertTrue(probe["path"].startswith("/sitemend-404-probe-"))
        self.assertEqual(self._hit(probe), [])

    def test_spa_catch_all_is_flagged(self):
        hit = self._hit(self._serve("spa"))
        self.assertEqual([f["severity"] for f in hit], ["high"])
        self.assertIn("-> 200", hit[0]["evidence"])
        self.assertNotIn("redirect", hit[0]["evidence"])

    def test_redirect_to_home_is_flagged_and_says_so(self):
        hit = self._hit(self._serve("redirect"))
        self.assertIn("after redirect", hit[0]["evidence"])

    def test_probe_is_random(self):
        self.assertNotEqual(self._serve(None)["path"], self._serve(None)["path"])

    def test_unreachable_probe_and_fs_mode_say_nothing(self):
        self.assertEqual(self._hit({"path": "/x", "status": None, "error": "refused"}), [])
        self.assertEqual(self._hit({"path": "/x", "status": 200}, mode="fs"), [])
        self.assertEqual(self._hit(None), [])


class TestUncrawlableLinks(Base):
    def _hit(self, body):
        self.fx.write("index.html", page_html(body="<h1>H</h1><p>" + "word " * 300 + "</p>" + body))
        return [f for f in self.fx.audit()["findings"] if f["id"] == "S2-UNCRAWLABLE-LINK"]

    def test_js_navigation_is_flagged(self):
        for body in ('<p>See <a href="#">Pricing</a></p>',
                     '<a href="javascript:void(0)" onclick="go()">Pricing</a>',
                     '<a onclick="go(\'/pricing\')">Pricing</a>',
                     '<a tabindex="0">Pricing</a>',
                     '<div onclick="location.href=\'/pricing\'">Pricing</div>',
                     '<button onclick="window.location = \'/pricing\'">Pricing</button>',
                     '<span onclick="window.open(\'/pricing\')">Pricing</span>'):
            with self.subTest(body=body):
                hit = self._hit(body)
                self.assertEqual(len(hit), 1, body)
                self.assertEqual(hit[0]["severity"], "medium")
                self.assertIn("Pricing", hit[0]["evidence"])

    def test_things_that_are_not_navigation_are_clean(self):
        for body in ('<a href="/pricing" onclick="track()">Pricing</a>',
                     '<a>Current crumb</a>',
                     '<a name="section"></a>',
                     '<a href="#">Back to top</a>',
                     '<a href="#features">Features</a>',
                     '<a href="#" role="button">Menu</a>',
                     '<a href="#" aria-expanded="false">Menu</a>',
                     '<a href="#" data-bs-toggle="dropdown">Menu</a>',
                     '<button onclick="openMenu()">Menu</button>',
                     '<div onclick="toggle()">Show more</div>'):
            with self.subTest(body=body):
                self.assertEqual(self._hit(body), [], body)

    def test_shared_nav_is_one_finding(self):
        nav = '<ul><li><a href="#">Pricing</a></li></ul>'
        self.fx.write("index.html", page_html(body='<h1>H</h1><a href="/b.html">b</a>' + nav))
        self.fx.write("b.html", page_html(title="Another Perfectly Reasonable Title",
                                          body='<h1>B</h1><a href="/">h</a>' + nav))
        hit = [f for f in self.fx.audit()["findings"] if f["id"] == "S2-UNCRAWLABLE-LINK"]
        self.assertEqual(len(hit), 1)
        self.assertEqual(hit[0]["pages"], ["/", "/b.html"])


# ------------------------------------------- false positives from the 20-site benchmark

def serve(test, routes):
    """A throwaway http server for one test: routes maps path -> (status, content type,
    body, extra headers). Returns its base URL."""
    try:
        import requests  # noqa: F401
    except ImportError:
        raise unittest.SkipTest("requests not installed (http mode is optional)")
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            status, ctype, body, headers = routes.get(self.path, (404, "text/html", "nope", {}))
            body = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    test.addCleanup(srv.server_close)
    test.addCleanup(srv.shutdown)
    return "http://127.0.0.1:%d/" % srv.server_address[1]


def http_doc(base, max_pages=300):
    """crawl_http plus the robots/sitemap blocks crawl.main() would build."""
    (pages, _, robots, sitemap, _, _, skipped, _, _) = crawl.crawl_http(base, max_pages)
    rb = S.Robots(robots)
    for p in pages:
        p["robots_allowed"], p["robots_rule"] = rb.check(p["url"])
    sm_urls, _ = S.parse_sitemap(sitemap)
    return {"meta": {"source": base, "mode": "http", "page_count": len(pages),
                     "base_url": None, "excluded_dirs_present": [], "skipped": skipped},
            "robots": {"found": bool(robots), "sitemaps": rb.sitemaps, "groups": [], "raw": robots},
            "sitemap": {"found": bool(sitemap), "urls": sm_urls, "notes": []},
            "assets": [], "pages": pages, "extras": {},
            "referenced_assets": [], "referenced_basenames": []}


class TestHttpStartRedirect(unittest.TestCase):
    """REGRESSION found by the 2026-10-16 audit: a start URL redirecting to another host
    (apex -> www, http -> https) skipped every page as off-site, crawl.py exited 0 with 0
    pages, and every sitemap URL was reported as not existing."""

    def _sites(self):
        target = serve(self, {
            "/": (200, "text/html", page_html(
                body='<h1>H</h1><p><a href="/about/">a</a> ' + "word " * 300 + "</p>"), {}),
            "/about/": (200, "text/html", page_html(title="About Page With A Fine Long Title"), {}),
        })
        apex = serve(self, {"/": (301, "text/html", "", {"Location": target})})
        return apex, target

    def test_crawl_follows_the_start_redirect(self):
        apex, _ = self._sites()
        pages = crawl.crawl_http(apex)[0]
        self.assertEqual(sorted(p["url"] for p in pages), ["/", "/about/"])

    def test_base_url_repeating_the_typed_origin_follows_it(self):
        apex, target = self._sites()
        d = tempfile.mkdtemp(prefix="sitemend-redir-")
        self.addCleanup(shutil.rmtree, d, True)
        out = os.path.join(d, "crawl.json")
        subprocess.run([sys.executable, os.path.join(sitemend.HERE, "crawl.py"), "--mode", "http",
                        "--start", apex, "--base-url", apex.rstrip("/"), "--out", out],
                       capture_output=True, check=True)
        with open(out, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["meta"]["base_url"], target.rstrip("/"))

    def test_zero_pages_is_an_error_not_an_empty_audit(self):
        dead = serve(self, {})
        d = tempfile.mkdtemp(prefix="sitemend-dead-")
        self.addCleanup(shutil.rmtree, d, True)
        r = subprocess.run([sys.executable, os.path.join(sitemend.HERE, "crawl.py"), "--mode", "http",
                            "--start", dead, "--out", os.path.join(d, "crawl.json")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("crawled 0 pages", r.stderr)

    def test_http_crawl_follows_absolute_links_on_its_own_origin(self):
        routes = {"/": (200, "text/html", None, {}),
                  "/about/": (200, "text/html", page_html(title="About Page With A Fine Long Title"), {})}
        base = serve(self, routes)
        routes["/"] = (200, "text/html", page_html(
            body='<h1>H</h1><p><a href="{0}about/">a</a> '.format(base) + "word " * 300 + "</p>"), {})
        self.assertEqual(sorted(p["url"] for p in crawl.crawl_http(base)[0]), ["/", "/about/"])


STUB = ('<!doctype html><html><head><meta http-equiv="refresh" content="{0}">'
        '</head><body></body></html>')
ON_PAGE = {"S3-TITLE-MISSING", "S3-VIEWPORT-MISSING", "S2-H1-MISSING", "S3-DESC-MISSING",
           "S1-CANONICAL-MISSING", "S3-LANG-MISSING", "S3-OG-MISSING", "S3-THIN"}


class TestHttpMaxPagesTruncation(unittest.TestCase):
    """REGRESSION found by the 2026-10-16 audit: with --max-pages 5 on a 13-page site,
    the 8 pages never fetched were reported as high S1-SITEMAP-ORPHAN ("does not
    exist") and high S1-BROKEN-LINK. Not crawled is unknown, not missing."""

    def test_uncrawled_urls_are_not_reported_missing(self):
        links = "".join('<a href="/p{0}/">p{0}</a> '.format(i) for i in range(8))
        routes = {"/": (200, "text/html", page_html(
            body="<h1>H</h1><p>" + links + "word " * 300 + "</p>"), {})}
        for i in range(8):
            routes["/p%d/" % i] = (200, "text/html", page_html(
                title="Page %d With A Long Enough Title Here" % i,
                body='<h1>P</h1><p><a href="/">home</a> ' + ("w%d " % i) * 300 + "</p>"), {})
        routes["/sitemap.xml"] = (200, "application/xml", "<urlset>" + "".join(
            "<url><loc>https://x.org/p%d/</loc></url>" % i for i in range(8)) + "</urlset>", {})
        doc = http_doc(serve(self, routes), max_pages=3)
        self.assertTrue(any(s.get("not_crawled") for s in doc["meta"]["skipped"]))
        ids = [f["id"] for f in audit.audit(doc)["findings"]]
        for fid in ("S1-SITEMAP-ORPHAN", "S1-BROKEN-LINK", "S2-ORPHAN", "S2-UNREACHABLE"):
            self.assertNotIn(fid, ids)

    def _i18n(self, max_pages, missing=()):
        alt = ('<link rel="alternate" hreflang="en" href="/">'
               '<link rel="alternate" hreflang="fr" href="/fr/">'
               '<link rel="alternate" hreflang="de" href="/de/">')
        routes = {"/": (200, "text/html", page_html(
            head_extra=alt + '<link rel="canonical" href="/">',
            body='<h1>H</h1><p><a href="/p0/">p0</a> <a href="/fr/">fr</a> <a href="/de/">de</a> '
                 + "word " * 300 + "</p>"), {})}
        for lang in ("fr", "de"):
            if lang not in missing:
                routes["/%s/" % lang] = (200, "text/html", page_html(
                    title="%s home page with a long enough title" % lang,
                    head_extra=alt + '<link rel="canonical" href="/%s/">' % lang,
                    body="<h1>%s</h1><p>" % lang + ("%s " % lang) * 300 + "</p>"), {})
        for i in range(8):
            routes["/p%d/" % i] = (200, "text/html", page_html(
                title="Page %d With A Long Enough Title Here" % i,
                head_extra='<link rel="canonical" href="/p7/">' if i == 0 else "",
                body='<h1>P</h1><p><a href="/">home</a> ' + ("w%d " % i) * 300 + "</p>"), {})
        routes["/sitemap.xml"] = (200, "application/xml", "<urlset>" + "".join(
            "<url><loc>https://x.org/p%d/</loc></url>" % i for i in range(8)) + "</urlset>", {})
        return audit.audit(http_doc(serve(self, routes), max_pages=max_pages))["findings"]

    def test_hreflang_and_canonical_targets_it_never_reached_are_not_broken(self):
        """REGRESSION found on biomejs.dev: a 50-page crawl reported 241 high
        S1-HREFLANG-BROKEN for language pages that serve 200 but were never fetched.
        A canonical to an unfetched page is still a measured cross-canonical."""
        found = self._i18n(max_pages=3)
        ids = [f["id"] for f in found]
        self.assertNotIn("S1-HREFLANG-BROKEN", ids)
        self.assertNotIn("S1-CANONICAL-BROKEN", ids)
        cross = [f for f in found if f["id"] == "S1-CANONICAL-CROSS"]
        self.assertEqual([(f["pages"], f["detail"]["points_to"]) for f in cross], [(["/p0/"], "/p7/")])

    def test_hreflang_alternates_nothing_links_to_are_crawled(self):
        """REGRESSION found on pnpm.io: /it serves 200 but no crawled page links to it and
        the sitemap omits it, so a finished crawl still called it missing. Search engines
        discover pages through hreflang and the canonical; the crawl now does too."""
        alt = ('<link rel="alternate" hreflang="en" href="/">'
               '<link rel="alternate" hreflang="it" href="/it">')
        routes = {"/": (200, "text/html", page_html(head_extra=alt), {}),
                  "/it": (200, "text/html", page_html(
                      title="Pagina italiana con un titolo abbastanza lungo", head_extra=alt,
                      body="<h1>Ciao</h1><p>" + "parola " * 300 + "</p>"), {})}
        doc = http_doc(serve(self, routes))
        self.assertIn("/it", [p["url"] for p in doc["pages"]])
        self.assertNotIn("S1-HREFLANG-BROKEN", [f["id"] for f in audit.audit(doc)["findings"]])

    def test_a_site_that_negotiates_on_accept_is_crawled_as_html(self):
        """REGRESSION found on turborepo.dev: its home page answers the generic */* with
        text/markdown (Vary: Accept), so the crawl skipped it as non-HTML and reported
        "/" as a broken link and a sitemap orphan. Ask for HTML the way browsers do."""
        try:
            import requests  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("requests not installed (http mode is optional)")
        import http.server
        import threading
        home = page_html().encode()

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                html = "text/html" in (self.headers.get("Accept") or "") and self.path == "/"
                body = home if html else b"# Home\n"
                self.send_response(200 if self.path == "/" else 404)
                self.send_header("Content-Type", "text/html" if html else "text/markdown")
                self.send_header("Vary", "Accept")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        pages = crawl.crawl_http("http://127.0.0.1:%d/" % srv.server_address[1])[0]
        self.assertEqual([p["url"] for p in pages], ["/"])

    def test_a_missing_hreflang_page_is_still_broken_when_the_crawl_finished(self):
        broken = [f for f in self._i18n(max_pages=300, missing=("de",))
                  if f["id"] == "S1-HREFLANG-BROKEN"]
        self.assertTrue(broken)
        self.assertTrue(all('hreflang="de"' in f["evidence"] for f in broken))


class TestHttpSkipsNonHtmlBodies(unittest.TestCase):
    """REGRESSION found by the 2026-10-16 audit: a link to a 60 MB file downloaded all of
    it just to learn it was not HTML."""

    def test_linked_binary_is_not_downloaded(self):
        try:
            import requests  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("requests not installed (http mode is optional)")
        import http.server
        import threading

        sent = [0]
        home = page_html(body='<h1>H</h1><p><a href="/big.bin">get</a> ' + "word " * 300 + "</p>").encode()

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != "/big.bin":
                    body = home if self.path == "/" else b"nope"
                    self.send_response(200 if self.path == "/" else 404)
                    self.send_header("Content-Type", "text/html")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                size, chunk = 64 * 1024 * 1024, b"\0" * 65536
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(size))
                self.end_headers()
                try:
                    for _ in range(size // len(chunk)):
                        self.wfile.write(chunk)
                        sent[0] += len(chunk)
                except OSError:
                    pass

            def log_message(self, *a):
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        pages = crawl.crawl_http("http://127.0.0.1:%d/" % srv.server_address[1])[0]
        self.assertEqual([p["url"] for p in pages], ["/"])
        self.assertLess(sent[0], 16 * 1024 * 1024)
    def test_a_body_that_breaks_mid_read_is_skipped_not_fatal(self):
        try:
            import requests  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("requests not installed (http mode is optional)")
        import http.server
        import threading

        home = page_html(body='<h1>H</h1><p><a href="/broken/">b</a> ' + "word " * 300 + "</p>").encode()

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/broken/":
                    # Promise 100000 bytes, send 10, then hang up.
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.send_header("Content-Length", "100000")
                    self.end_headers()
                    self.wfile.write(b"<html><bo")
                    self.wfile.flush()
                    self.close_connection = True
                    return
                body = home if self.path == "/" else b"nope"
                self.send_response(200 if self.path == "/" else 404)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        pages, _, _, _, _, _, skipped, _, _ = crawl.crawl_http("http://127.0.0.1:%d/" % srv.server_address[1])
        self.assertEqual([p["url"] for p in pages], ["/"])
        self.assertIn("/broken/", [s["url"] for s in skipped])


class TestMetaRefresh(Base):
    """REGRESSION from the benchmark: docs.astro.build's home page is
    <meta http-equiv="refresh" content="0;url=/en/getting-started/">. It was judged as a
    page (critical missing title and viewport, plus H1, description, canonical, lang and
    OG) and the http crawl stopped there, at 1 page."""

    def test_fs_stub_is_an_alias_of_its_target(self):
        self.fx.write("index.html", STUB.format("0;url=/en/getting-started/"))
        self.fx.write("en/getting-started/index.html", page_html())
        doc = self.fx.crawl()
        self.assertEqual([p["url"] for p in doc["pages"]], ["/en/getting-started/"])
        self.assertIn("/", doc["pages"][0]["aliases"])
        f = audit.audit(doc)["findings"]
        self.assertEqual([x["id"] for x in f if x["id"] in ON_PAGE and "/" in x["pages"]], [])

    def test_quoted_url_and_one_second_delay_are_redirects_too(self):
        self.fx.write("old.html", STUB.format("1; URL='/new.html'"))
        self.fx.write("new.html", page_html())
        doc = self.fx.crawl()
        self.assertEqual([p["url"] for p in doc["pages"]], ["/new.html"])
        self.assertIn("/old.html", doc["pages"][0]["aliases"])

    def test_slow_refresh_is_a_page(self):
        """A 5-second refresh shows the visitor the page first. It is a page."""
        self.fx.write("index.html", page_html(
            head_extra='<meta http-equiv="refresh" content="5;url=/next.html">'))
        self.assertEqual([p["url"] for p in self.fx.crawl()["pages"]], ["/"])

    def test_offsite_stub_is_skipped_not_judged(self):
        self.fx.write("index.html", page_html())
        self.fx.write("away.html", STUB.format("0;url=https://elsewhere.org/"))
        self.assertEqual([p["url"] for p in self.fx.crawl()["pages"]], ["/"])

    def test_http_stub_is_followed_like_a_redirect(self):
        base = serve(self, {
            "/": (200, "text/html", STUB.format("0;url=/en/getting-started/"), {}),
            "/en/getting-started/": (200, "text/html", page_html(), {}),
        })
        doc = http_doc(base)
        self.assertEqual([p["url"] for p in doc["pages"]], ["/en/getting-started/"])
        page = doc["pages"][0]
        self.assertIn("/", page["aliases"])
        self.assertEqual(page["redirect_hops"], [base, base + "en/getting-started/"])
        f = audit.audit(doc)["findings"]
        self.assertEqual([x["id"] for x in f if x["id"] in ON_PAGE and "/" in x["pages"]], [])


class TestSitemapDiscovery(Base):
    """REGRESSION from the benchmark: only /sitemap.xml was read. astro.build declares
    `Sitemap: https://astro.build/sitemap-index.xml` in robots.txt and was told its sitemap
    was missing; docs.astro.build, starlight.astro.build and biomejs.dev publish
    /sitemap-index.xml without declaring it, which is S1-ROBOTS-NO-SITEMAP, not missing."""

    INDEX = ('<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
             '<sitemap><loc>https://acme-widgets.com/sitemap-0.xml</loc></sitemap></sitemapindex>')
    URLSET = ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
              '<url><loc>https://acme-widgets.com/</loc></url></urlset>')

    def _site(self, robots):
        self.fx.write("index.html", page_html(
            head_extra='<link rel="canonical" href="https://acme-widgets.com/">'))
        self.fx.write("robots.txt", robots)
        self.fx.write("sitemap-index.xml", self.INDEX)
        self.fx.write("sitemap-0.xml", self.URLSET)
        doc = self.fx.crawl()
        return doc, {f["id"] for f in audit.audit(doc)["findings"]}

    def test_declared_index_is_followed_to_its_urls(self):
        doc, ids = self._site("User-agent: *\nAllow: /\n"
                              "Sitemap: https://acme-widgets.com/sitemap-index.xml\n")
        self.assertEqual(doc["sitemap"]["urls"], ["https://acme-widgets.com/"])
        self.assertFalse(ids & {"S1-SITEMAP-MISSING", "S1-ROBOTS-NO-SITEMAP", "S1-SITEMAP-ORPHAN"})

    def test_undeclared_index_is_robots_no_sitemap(self):
        doc, ids = self._site("User-agent: *\nAllow: /\n")
        self.assertTrue(doc["sitemap"]["found"])
        self.assertIn("S1-ROBOTS-NO-SITEMAP", ids)
        self.assertNotIn("S1-SITEMAP-MISSING", ids)

    def test_http_mode_reads_the_declared_path_on_the_crawled_origin(self):
        """tauri.app's robots.txt names v2.tauri.app's sitemap-index.xml; only the path
        transfers, as for sitemap <loc>s."""
        xml, txt = "application/xml", "text/plain"
        base = serve(self, {
            "/": (200, "text/html", page_html(), {}),
            "/robots.txt": (200, txt, "User-agent: *\nSitemap: https://v2.acme.dev/sitemap-index.xml\n", {}),
            "/sitemap-index.xml": (200, xml, self.INDEX, {}),
            "/sitemap-0.xml": (200, xml, self.URLSET, {}),
        })
        doc = http_doc(base)
        self.assertEqual(doc["sitemap"]["urls"], ["https://acme-widgets.com/"])
        ids = {f["id"] for f in audit.audit(doc)["findings"]}
        self.assertFalse(ids & {"S1-SITEMAP-MISSING", "S1-ROBOTS-NO-SITEMAP"})

    def test_index_children_are_capped(self):
        reads = []
        index = "<sitemapindex>" + "".join(
            "<sitemap><loc>https://a.com/s{0}.xml</loc></sitemap>".format(i)
            for i in range(200)) + "</sitemapindex>"

        def read(path):
            reads.append(path)
            return index if path == "/sitemap.xml" else self.URLSET
        crawl.discover_sitemap("", read)
        self.assertEqual(len(reads), crawl.SITEMAP_FILES_MAX)

    def test_html_at_the_sitemap_path_is_not_a_sitemap(self):
        """A catch-all route answering /sitemap.xml with the app shell is no sitemap."""
        self.assertEqual(crawl.discover_sitemap("", lambda p: "<html><body>app</body></html>"), "")

    def test_missing_files_are_calibrated(self):
        """Google treats a 404 robots.txt as allow-all, so its absence is low; a missing
        sitemap only slows discovery on a linked site, so medium."""
        self.fx.write("index.html", page_html())
        sev = {f["id"]: f["severity"] for f in self.fx.audit()["findings"]}
        self.assertEqual(sev["S1-ROBOTS-MISSING"], "low")
        self.assertEqual(sev["S1-SITEMAP-MISSING"], "medium")


class TestSitemapStaysInsideRoot(Base):
    """REGRESSION found by the 2026-10-16 audit: on Windows a robots.txt Sitemap: path
    such as /C:/... or /..\\x was read from outside the audited folder."""

    def test_robots_sitemap_path_cannot_leave_the_folder(self):
        outside = tempfile.mkdtemp(prefix="sitemend-outside-")
        self.addCleanup(shutil.rmtree, outside, True)
        sm = os.path.join(outside, "sm.xml")
        with open(sm, "w") as fh:
            fh.write("<urlset><url><loc>https://x.org/LEAKED/</loc></url></urlset>")
        self.fx.write("index.html", page_html())
        for path in (sm.replace("\\", "/").lstrip("/"), os.path.relpath(sm, self.fx.root)):
            with self.subTest(path=path):
                self.fx.write("robots.txt", "User-agent: *\nSitemap: https://x.org/" + path + "\n")
                self.assertEqual(self.fx.crawl()["sitemap"]["urls"], [])


class TestUncrawlableBenchmark(Base):
    """REGRESSION from the benchmark: S2-UNCRAWLABLE-LINK fired on 5 sites and 3 were
    wrong. The 2 right ones must stay flagged."""

    def _hit(self, html):
        self.fx.write("index.html", html)
        return [f for f in self.fx.audit()["findings"] if f["id"] == "S2-UNCRAWLABLE-LINK"]

    def _main(self, body):
        return page_html(body="<h1>H</h1><p>" + "word " * 300 + "</p>" + body)

    def test_react_dev_hidden_thumbnail_is_clean(self):
        self.assertEqual(self._hit(self._main(
            '<article><a aria-hidden="true" tabindex="-1" target="_blank"><img src="t.jpg" alt=""></a>'
            '<div aria-hidden="true"><p><a href="#">x</a></p></div></article>')), [])

    def test_react_dev_toc_overview_is_clean(self):
        self.assertEqual(self._hit(self._main(
            '<ul><li><a href="#">Overview</a></li><li><a href="#install">Install</a></li></ul>')), [])

    def test_tailwind_demo_in_a_figure_without_main_is_clean(self):
        """tailwindcss.com has no <main>; its live examples sit in <figure>."""
        html = page_html().replace("<main>", "<div>").replace("</main>", "</div>")
        html = html.replace("</body>", '<figure><p>by <a href="#">planeteria.tech</a></p>'
                                       '<ul><li><a href="#">Call</a></li></ul></figure></body>')
        self.assertEqual(self._hit(html), [])

    def test_shadcn_components_are_clean(self):
        """ui.shadcn.com: pagination in a nav, a login form's "Forgot?", item cards."""
        self.assertEqual(self._hit(self._main(
            '<nav><ul><li><a href="#">Previous</a></li><li><a href="#">1</a></li></ul></nav>'
            '<div><div><a href="#">Forgot?</a></div></div>'
            '<form><p><a href="#">Forgot?</a></p></form>'
            '<a href="#" data-slot="item">Danger Zone</a>')), [])

    def test_placeholder_links_in_docs_text_stay_flagged(self):
        """pnpm.io: "ignored by the [pnpm audit](#) command"; jestjs.io: "your Jest
        [config file](#)". Both are <a href="#"> in a docs paragraph or list item."""
        for body in ('<article><p>ignored by the <a href="#"><code>pnpm audit</code></a> command</p></article>',
                     '<article><ul><li>your Jest <a href="#">config file</a></li></ul></article>'):
            with self.subTest(body=body):
                self.assertEqual(len(self._hit(self._main(body))), 1)

    def test_no_main_body_prose_is_still_checked(self):
        html = page_html(body='<h1>H</h1><p>see <a href="#">the guide</a></p>')
        html = html.replace("<main>", "<div>").replace("</main>", "</div>")
        self.assertEqual(len(self._hit(html)), 1)

    def test_evidence_shows_the_triggering_attribute(self):
        """The 120-character cut used to end inside a utility-class list, before href."""
        hit = self._hit(self._main('<p><a class="{0}" data-x="1" href="#">config file</a></p>'
                                   .format("text-link " * 30)))
        self.assertEqual(hit[0]["evidence"], '<a data-x="1" href="#">config file</a>')


class TestHostAgreement(Base):
    """REGRESSION from the benchmark: tauri.app serves the site, and every URL it
    publishes (canonical, og:url, sitemap, robots) names v2.tauri.app, which also serves
    it. That is a deliberate canonical host, not a leak: one medium finding asking for a
    redirect, instead of a high mismatch plus a critical CANONICAL-OFFSITE per page."""

    def _audit(self, host):
        url = "https://{0}/".format(host)
        self.fx.write("index.html", page_html(head_extra=(
            '<link rel="canonical" href="{0}"><meta property="og:url" content="{0}">').format(url)))
        self.fx.write("sitemap.xml", "<urlset><url><loc>{0}</loc></url></urlset>".format(url))
        self.fx.write("robots.txt", "User-agent: *\nSitemap: {0}sitemap.xml\n".format(url))
        doc = self.fx.crawl()
        doc["meta"]["base_url"] = "https://acme-widgets.com"
        return audit.audit(doc)["findings"]

    def test_every_url_naming_one_other_host_is_medium(self):
        f = self._audit("v2.acme-widgets.com")
        hit = [x for x in f if x["id"] == "S1-HOST-MISMATCH"]
        self.assertEqual([x["severity"] for x in hit], ["medium"])
        self.assertEqual(hit[0]["message"],
                         "Served on acme-widgets.com, but every URL names v2.acme-widgets.com; "
                         "check acme-widgets.com redirects to v2.acme-widgets.com.")
        self.assertNotIn("S1-CANONICAL-OFFSITE", [x["id"] for x in f])

    def test_agreeing_on_a_preview_host_stays_critical(self):
        f = self._audit("acme-git-main.vercel.app")
        self.assertEqual([x["severity"] for x in f if x["id"] == "S1-HOST-MISMATCH"], ["critical"])

class TestCheckCommand(unittest.TestCase):
    """`sitemend check` is what the GitHub Action runs: compare a change with its base and
    fail only on what the change broke. Folders for a static build, URLs for a preview."""

    def _site(self, broken=False):
        fx = Fixture()
        self.addCleanup(fx.cleanup)
        link = '<a href="/gone/">x</a> ' if broken else ""
        fx.write("index.html", page_html(body="<h1>H</h1><p>" + link + "word " * 300 + "</p>"))
        return fx.root

    def _out(self):
        d = tempfile.mkdtemp(prefix="sitemend-check-")
        self.addCleanup(shutil.rmtree, d, True)
        return os.path.join(d, "out")

    def test_a_change_that_breaks_a_link_fails_and_leaves_a_comment(self):
        out = self._out()
        code = sitemend.check(self._site(broken=True), self._site(), out, 200)
        self.assertEqual(code, 1)
        with open(os.path.join(out, "verify.md"), encoding="utf-8") as fh:
            self.assertIn("S1-BROKEN-LINK", fh.read())

    def test_an_unchanged_site_passes(self):
        self.assertEqual(sitemend.check(self._site(), self._site(), self._out(), 200), 0)

    def test_without_a_base_it_fails_only_on_fail_on(self):
        broken = self._site(broken=True)          # one high finding, no critical
        self.assertEqual(sitemend.check(broken, None, self._out(), 200), 0)
        self.assertEqual(sitemend.check(broken, None, self._out(), 200, "high"), 1)

    def test_a_preview_url_compared_with_production_passes_when_nothing_changed(self):
        """The same site on two origins (production and a preview) is not a regression:
        no finding's evidence may depend on the origin it was crawled from."""
        routes = {"/": (200, "text/html", page_html(
                      body='<h1>H</h1><p><a href="/about/">a</a> ' + "word " * 300 + "</p>"), {}),
                  "/about/": (200, "text/html", page_html(title="About Page With A Fine Long Title"), {})}
        prod, preview = serve(self, routes), serve(self, routes)
        out = self._out()
        self.assertEqual(sitemend.check(preview, prod, out, 50), 0)


def host_site(test, host):
    """Three pages whose canonicals, og:url, sitemap and robots Sitemap line all name host."""
    fx = Fixture()
    test.addCleanup(fx.cleanup)
    for f, body in host_routes(host).values():
        fx.write(f, body)
    return fx.root


def host_routes(host):
    """{url path: (file, body)} for host_site, also served over http by the url-mode test."""
    h = "https://" + host
    nav = '<nav><a href="/">Home</a> <a href="/about.html">About</a> <a href="/pricing.html">Pricing</a></nav>'
    routes = {}
    for name, path in (("index", "/"), ("about", "/about.html"), ("pricing", "/pricing.html")):
        url = h + path
        routes[path] = (name + ".html", page_html(
            title="Acme {0} page with a fine long title".format(name),
            head_extra='<link rel="canonical" href="{0}"><meta property="og:url" content="{0}">'.format(url),
            body="<h1>{0}</h1>{1}<p>{2}</p>".format(name, nav, ("unique {0} text ".format(name)) * 150)))
    routes["/robots.txt"] = ("robots.txt", "User-agent: *\nAllow: /\nSitemap: {0}/sitemap.xml\n".format(h))
    routes["/sitemap.xml"] = ("sitemap.xml", '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                              + "".join("<url><loc>{0}{1}</loc></url>".format(h, p)
                                        for p in ("/", "/about.html", "/pricing.html")) + "</urlset>")
    return routes


class TestPublishedHostDrift(unittest.TestCase):
    """REGRESSION (#115): a build whose site-URL env var fell back to the preview URL puts
    every canonical, og:url, sitemap and robots URL on *.vercel.app. One build alone agrees
    with itself, so S1-HOST-MISMATCH stays quiet; only the base build says where production
    is. S1-HOST-DRIFT compares the hosts the two builds publish."""

    _out = TestCheckCommand._out

    def _verify(self, out):
        with open(os.path.join(out, "verify.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def _drift(self, doc):
        return [f for f in doc["new"] if f["id"] == "S1-HOST-DRIFT"]

    def test_moving_every_url_to_a_preview_host_fails_critical(self):
        out = self._out()
        code = sitemend.check(host_site(self, "acme-git-feat-x.vercel.app"),
                              host_site(self, "www.acmedocs.io"), out, 200)
        self.assertEqual(code, 1)
        doc = self._verify(out)
        [f] = self._drift(doc)
        self.assertEqual(f["severity"], "critical")
        self.assertIn(f, doc["regressions"])
        for text in ("www.acmedocs.io", "acme-git-feat-x.vercel.app"):
            self.assertIn(text, f["message"])
        for where in ("base: canonical www.acmedocs.io (3)", "og:url www.acmedocs.io (3)",
                      "sitemap.xml www.acmedocs.io (3)", "robots.txt Sitemap line www.acmedocs.io (1)",
                      "head: canonical acme-git-feat-x.vercel.app (3)"):
            self.assertIn(where, f["evidence"])

    def test_the_same_production_host_passes(self):
        out = self._out()
        self.assertEqual(sitemend.check(host_site(self, "www.acmedocs.io"),
                                        host_site(self, "www.acmedocs.io"), out, 200), 0)
        self.assertEqual(self._drift(self._verify(out)), [])

    def test_a_move_to_another_real_domain_is_reported_but_advisory(self):
        """A domain move is usually deliberate, so it never fails the gate, but it is in
        the PR comment as an advisory finding in case it was not."""
        out = self._out()
        self.assertEqual(sitemend.check(host_site(self, "new-prod.com"),
                                        host_site(self, "old-prod.com"), out, 200), 0)
        doc = self._verify(out)
        [f] = self._drift(doc)
        self.assertEqual((f["severity"], f["confidence"]), ("high", "medium"))
        self.assertIn(f, doc["advisory"])
        with open(os.path.join(out, "verify.md"), encoding="utf-8") as fh:
            self.assertIn("S1-HOST-DRIFT", fh.read())

    def test_a_site_that_lives_on_a_preview_style_host_passes(self):
        """Production on a per-deploy host (Addendum 2, part 3 of the Task 9 plan)."""
        out = self._out()
        self.assertEqual(sitemend.check(host_site(self, "sywyke.vercel.app"),
                                        host_site(self, "sywyke.vercel.app"), out, 200), 0)
        self.assertEqual(self._drift(self._verify(out)), [])

    def test_a_preview_url_with_production_canonicals_passes(self):
        """preview.yml: the head is crawled on its preview URL, and its correct production
        URLs must not read as a move away from production."""
        routes = {path: (200, "application/xml" if f.endswith(".xml") else
                         "text/plain" if f.endswith(".txt") else "text/html", body, {})
                  for path, (f, body) in host_routes("www.acmedocs.io").items()}
        prod, preview = serve(self, routes), serve(self, routes)
        out = self._out()
        self.assertEqual(sitemend.check(preview, prod, out, 50), 0)
        self.assertEqual(self._drift(self._verify(out)), [])


class TestWaivers(unittest.TestCase):
    """.sitemend-waivers.json is the gate's escape hatch for a deliberate exception, such as
    a draft page that is noindex on purpose. Without one, the only way past an unwanted
    failure is to switch the check off. Waivers change whether the gate fails, never what
    was found."""

    f = staticmethod(TestVerify.f)

    def _dir(self):
        d = tempfile.mkdtemp(prefix="sitemend-waivers-")
        self.addCleanup(shutil.rmtree, d, True)
        return d

    def _file(self, doc, raw=None):
        path = os.path.join(self._dir(), ".sitemend-waivers.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(raw if raw is not None else json.dumps(doc))
        return path

    def _load(self, *waivers, **kw):
        return V.load_waivers(self._file({"waivers": list(waivers)}), **kw)

    @staticmethod
    def w(rule="S1-NOT-INDEXABLE", url="/drafts/*", reason="Drafts are noindex on purpose", **kw):
        return dict(kw, rule=rule, url=url, reason=reason)

    def _verify(self, base, cur, *waivers):
        """Run verify.py on findings lists; return (exit code, verify.json, verify.md)."""
        d = self._dir()
        paths = {}
        for name, items in (("b", base), ("c", cur)):
            paths[name] = os.path.join(d, name + ".json")
            with open(paths[name], "w") as fh:
                json.dump({"findings": items}, fh)
        args = ["--baseline", paths["b"], "--current", paths["c"], "--out", os.path.join(d, "v.json")]
        if waivers:
            args += ["--waivers", self._file({"waivers": list(waivers)})]
        r = sitemend.run("verify.py", *args, ok=(0, 1))
        with open(os.path.join(d, "v.json"), encoding="utf-8") as fh, \
                open(os.path.join(d, "v.md"), encoding="utf-8") as md:
            return r.returncode, json.load(fh), md.read()

    def test_exact_page_match(self):
        ws = self._load(self.w(url="/drafts/a/"))
        self.assertTrue(V.waiver_for(self.f("S1-NOT-INDEXABLE", ["/drafts/a/"]), ws))
        self.assertIsNone(V.waiver_for(self.f("S1-NOT-INDEXABLE", ["/drafts/b/"]), ws))

    def test_glob_match(self):
        ws = self._load(self.w())
        self.assertTrue(V.waiver_for(self.f("S1-NOT-INDEXABLE", ["/drafts/a/", "/drafts/b/"]), ws))

    def test_no_match_on_another_rule_or_page(self):
        ws = self._load(self.w())
        self.assertIsNone(V.waiver_for(self.f("S3-TITLE-MISSING", ["/drafts/a/"]), ws))
        self.assertIsNone(V.waiver_for(self.f("S1-NOT-INDEXABLE", ["/pricing/"]), ws))

    def test_every_page_of_a_finding_must_be_covered(self):
        """A duplicate between a draft and /pricing is not a draft problem."""
        ws = self._load(self.w(rule="S3-TITLE-DUPLICATE"))
        self.assertIsNone(V.waiver_for(self.f("S3-TITLE-DUPLICATE", ["/drafts/a/", "/pricing/"]), ws))

    def test_site_wide_finding_is_waived_by_root(self):
        ws = self._load(self.w(rule="S1-ROBOTS-MISSING", url="/"))
        self.assertTrue(V.waiver_for(self.f("S1-ROBOTS-MISSING", ["/"]), ws))

    def test_a_pattern_that_covers_every_page_is_rejected(self):
        for url in ("*", "/*", "/**", "**"):
            with self.subTest(url=url):
                with self.assertRaisesRegex(ValueError, "every page"):
                    self._load(self.w(url=url))

    def test_a_wildcard_rule_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "exact rule ID"):
            self._load(self.w(rule="S1-*"))

    def test_missing_or_blank_reason_is_rejected(self):
        for w in ({"rule": "S1-NOT-INDEXABLE", "url": "/drafts/*"}, self.w(reason="  ")):
            with self.subTest(w=w):
                with self.assertRaisesRegex(ValueError, 'waiver 1 needs a non-empty "reason"'):
                    self._load(w)

    def test_unknown_field_and_bad_date_are_rejected(self):
        """A misspelled "expiry" would otherwise make a temporary waiver permanent."""
        with self.assertRaisesRegex(ValueError, "unknown field.*expiry"):
            self._load(self.w(expiry="2027-01-31"))
        with self.assertRaisesRegex(ValueError, "expires"):
            self._load(self.w(expires="next month"))

    def test_malformed_json_fails_the_run_loudly(self):
        path = self._file(None, raw='{"waivers": [')
        with self.assertRaisesRegex(ValueError, "not valid JSON"):
            V.load_waivers(path)
        d = self._dir()
        empty = os.path.join(d, "f.json")
        with open(empty, "w") as fh:
            json.dump({"findings": []}, fh)
        r = subprocess.run([sys.executable, os.path.join(sitemend.HERE, "verify.py"),
                            "--baseline", empty, "--current", empty, "--waivers", path,
                            "--out", os.path.join(d, "v.json")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("not valid JSON", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(d, "v.json")))

    def test_an_expired_waiver_stops_applying_and_says_so(self):
        import datetime
        ws = self._load(self.w(expires="2027-01-31"), today=datetime.date(2027, 2, 1))
        self.assertIsNone(V.waiver_for(self.f("S1-NOT-INDEXABLE", ["/drafts/a/"]), ws))
        self.assertTrue(V.waiver_for(self.f("S1-NOT-INDEXABLE", ["/drafts/a/"]),
                                     self._load(self.w(expires="2027-01-31"),
                                                today=datetime.date(2027, 1, 31))))
        code, doc, md = self._verify([], [self.f("S1-NOT-INDEXABLE", ["/drafts/a/"])],
                                     self.w(expires="2000-01-01"))
        self.assertEqual(code, 1)
        self.assertEqual([w["url"] for w in doc["expired_waivers"]], ["/drafts/*"])
        self.assertIn("### Expired waivers", md)

    def test_a_waived_regression_passes_and_is_still_reported(self):
        new = self.f("S1-NOT-INDEXABLE", ["/drafts/a/"], severity="critical")
        code, doc, md = self._verify([], [new], self.w())
        self.assertEqual(code, 0)
        self.assertEqual(doc["gate"], "PASS")
        self.assertEqual([f["id"] for f in doc["new"]], ["S1-NOT-INDEXABLE"])
        self.assertEqual([f["waiver"]["reason"] for f in doc["waived"]], ["Drafts are noindex on purpose"])
        self.assertIn("| critical (waived) | S1-NOT-INDEXABLE", md)
        self.assertIn("### Waived", md)
        self.assertIn("Drafts are noindex on purpose", md)

    def test_the_gate_passes_only_when_every_failing_finding_is_waived(self):
        cur = [self.f("S1-NOT-INDEXABLE", ["/drafts/a/"]),
               dict(self.f("S1-BROKEN-LINK", ["/"]), detail={"target": "/gone/"})]
        self.assertEqual(self._verify([], cur, self.w())[0], 1)
        self.assertEqual(self._verify([], cur, self.w(),
                                      self.w(rule="S1-BROKEN-LINK", url="/", reason="Removed next week"))[0], 0)

    def test_an_unused_waiver_is_listed(self):
        """Unused means it covers nothing in this audit. A waiver for a finding the base
        branch already had covers no new finding, but it is not unused."""
        old = self.f("S1-NOT-INDEXABLE", ["/drafts/a/"])
        code, doc, md = self._verify([old], [old], self.w(), self.w(rule="S3-TITLE-MISSING", url="/old/*"))
        self.assertEqual(code, 0)
        self.assertEqual([w["rule"] for w in doc["unused_waivers"]], ["S3-TITLE-MISSING"])
        self.assertIn("### Unused waivers", md)

    def test_fail_on_respects_waivers(self):
        path = os.path.join(self._dir(), "f.json")
        with open(path, "w") as fh:
            json.dump({"findings": [self.f("S1-NOT-INDEXABLE", ["/drafts/a/"], severity="critical"),
                                    self.f("S3-THIN", ["/a"], severity="low")]}, fh)
        self.assertEqual(sitemend.SEVERITY[sitemend.worst_open(path)], "critical")
        self.assertEqual(sitemend.SEVERITY[sitemend.worst_open(path, self._load(self.w()))], "low")

    def test_check_end_to_end_keeps_the_finding_in_findings_json(self):
        site = TestCheckCommand._site
        broken, clean = site(self, broken=True), site(self)
        out = os.path.join(self._dir(), "out")
        waivers = self._file({"waivers": [self.w(rule="S1-BROKEN-LINK", url="/", reason="Page lands Monday")]})
        self.assertEqual(sitemend.check(broken, clean, out, 200, waivers_path=waivers), 0)
        with open(os.path.join(out, "head", "findings.json"), encoding="utf-8") as fh:
            self.assertIn("S1-BROKEN-LINK", [f["id"] for f in json.load(fh)["findings"]])
        with open(os.path.join(out, "verify.md"), encoding="utf-8") as fh:
            self.assertIn("Page lands Monday", fh.read())
        self.assertEqual(sitemend.check(broken, None, os.path.join(out, "2"), 200, "high",
                                        waivers_path=waivers), 0)
        with open(os.path.join(out, "verify.json"), encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual([f["id"] for f in doc["new"]], ["S1-BROKEN-LINK"])
        self.assertEqual([f["id"] for f in doc["waived"]], ["S1-BROKEN-LINK"])


class TestExtraHeaders(unittest.TestCase):
    """A Vercel preview behind Deployment Protection answers 401 until the request carries
    its bypass header. The header comes from SITEMEND_HTTP_HEADERS, never the command line."""

    def test_parses_name_value_lines(self):
        env = {"SITEMEND_HTTP_HEADERS": "x-vercel-protection-bypass: s3cret\n\nbad line\nX-A:b:c\n"}
        self.assertEqual(crawl.extra_headers(env), {"x-vercel-protection-bypass": "s3cret", "X-A": "b:c"})
        self.assertEqual(crawl.extra_headers({}), {})

    def test_a_protected_preview_is_crawled_with_the_header(self):
        try:
            import requests  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("requests not installed (http mode is optional)")
        import http.server
        import threading
        home = page_html().encode()

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                ok = self.headers.get("x-vercel-protection-bypass") == "s3cret" and self.path == "/"
                body = home if ok else b"nope"
                self.send_response(200 if ok else 401)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        base = "http://127.0.0.1:%d/" % srv.server_address[1]
        self.assertEqual(crawl.crawl_http(base)[0], [])
        self._with_header(lambda: self.assertEqual([p["url"] for p in crawl.crawl_http(base)[0]], ["/"]))

    def _with_header(self, fn):
        old = os.environ.get("SITEMEND_HTTP_HEADERS")
        os.environ["SITEMEND_HTTP_HEADERS"] = "x-vercel-protection-bypass: s3cret"
        try:
            fn()
        finally:
            if old is None:
                os.environ.pop("SITEMEND_HTTP_HEADERS")
            else:
                os.environ["SITEMEND_HTTP_HEADERS"] = old

    def _requests(self):
        try:
            import requests
        except ImportError:
            raise unittest.SkipTest("requests not installed (http mode is optional)")
        return requests

    def _server(self, seen, name, handle):
        """A local server whose every request records the bypass header it carried."""
        import http.server
        import threading

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen.setdefault(name, []).append(self.headers.get("x-vercel-protection-bypass"))
                handle(self)

            def log_message(self, *a):
                pass
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return "http://127.0.0.1:%d" % srv.server_address[1]

    @staticmethod
    def _send(h, status, body=b"", headers=()):
        h.send_response(status)
        for k, v in headers:
            h.send_header(k, v)
        h.send_header("Content-Length", str(len(body)))
        h.end_headers()
        h.wfile.write(body)

    def test_the_header_never_follows_a_redirect_to_another_host(self):
        """SECURITY: requests keeps custom headers on a redirect to another host, so a
        preview page that redirected off-site (a fork PR's _redirects rule, say) handed the
        bypass token to that host. Here every path but / on the crawled origin redirects to
        a second server, which must never see the header: not from the walk, not from the
        sitemap or robots.txt fetch, not from the soft-404 probe."""
        self._requests()
        seen, send, html = {}, self._send, [("Content-Type", "text/html")]
        other = self._server(seen, "other", lambda h: send(h, 200, page_html().encode(), html))
        home_page = page_html(body='<h1>H</h1><p><a href="/away/">away</a> ' + "word " * 300 + "</p>").encode()
        home = self._server(seen, "home", lambda h: send(h, 200, home_page, html)
                            if h.path == "/" else send(h, 302, headers=[("Location", other + h.path)]))

        def run():
            crawl.crawl_http(home + "/")
            crawl.probe_soft404(home + "/")
        self._with_header(run)
        self.assertIn("s3cret", seen["home"], "the crawled origin must still get the header")
        self.assertTrue(seen.get("other"), "the fixture's redirects were never followed")
        self.assertEqual(set(seen["other"]), {None}, "the bypass header reached another host")

    def test_a_redirect_within_the_site_keeps_the_header(self):
        """The other half: a protected preview redirects /docs to /docs/ (Vercel and
        Netlify both add the slash), and the page behind it answers only with the header.
        Stripping it on that hop would leave every such page out of the crawl."""
        self._requests()
        seen, send, html = {}, self._send, [("Content-Type", "text/html")]
        home_page = page_html(body='<h1>H</h1><p><a href="/docs">docs</a> ' + "word " * 300 + "</p>").encode()
        docs = page_html(title="The Documentation Page Of This Site").encode()

        def handle(h):
            ok = h.headers.get("x-vercel-protection-bypass") == "s3cret"
            if h.path == "/docs":
                send(h, 302, headers=[("Location", "/docs/")])
            elif not ok:
                send(h, 401, b"nope", html)
            else:
                send(h, 200, {"/": home_page, "/docs/": docs}.get(h.path, b"missing"), html)
        home = self._server(seen, "home", handle)
        pages = []
        self._with_header(lambda: pages.extend(p["url"] for p in crawl.crawl_http(home + "/")[0]))
        self.assertIn("/docs/", pages)

    def test_the_site_is_requests_own_rule_for_authorization(self):
        """http -> https on the same host (a start URL that lands on https) and an explicit
        default port are the same site and keep the header; another host or port does not,
        and a redirect chain that leaves and comes back gets it again on the way back."""
        requests = self._requests()

        def sent(trusted, url):
            sess = crawl.http_session(trusted)
            return sess.prepare_request(requests.Request("GET", url)).headers.get(
                "x-vercel-protection-bypass")
        cases = [("http://site.test/", "https://site.test/docs/", "s3cret"),
                 ("https://site.test/", "https://site.test:443/docs/", "s3cret"),
                 ("http://site.test/", "http://site.test:80/", "s3cret"),
                 ("https://site.test/", "https://www.site.test/", None),
                 ("https://site.test/", "https://site.test:8443/", None),
                 ("https://site.test/", "https://evil.test/", None)]
        got = []
        self._with_header(lambda: got.extend(sent(t, u) for t, u, _ in cases))
        self.assertEqual(got, [want for _, _, want in cases])

        def hops():
            sess = crawl.http_session("https://site.test/")
            prep = sess.prepare_request(requests.Request("GET", "https://site.test/a"))
            out = []
            for url in ("https://evil.test/b", "https://site.test/c"):
                resp = requests.Response()
                resp.request = prep.copy()
                prep.url = url
                sess.rebuild_auth(prep, resp)
                out.append(prep.headers.get("x-vercel-protection-bypass"))
            return out
        chain = []
        self._with_header(lambda: chain.extend(hops()))
        self.assertEqual(chain, [None, "s3cret"])

class TestGithubAction(unittest.TestCase):
    """action.yml is the product's front door. CI's `action` job runs it for real on every
    pull request; these tests catch the cheap mistakes first, on every platform."""

    ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

    def _action(self):
        try:
            import yaml
        except ImportError:
            raise unittest.SkipTest("pyyaml not installed")
        with open(os.path.join(self.ROOT, "action.yml"), encoding="utf-8") as fh:
            return yaml.safe_load(fh)

    def test_the_marketplace_accepts_the_metadata(self):
        """REGRESSION: GitHub Marketplace refused to publish 1.5.0 because the action's
        description was over its limit ("Description must be less than 125 characters")."""
        a = self._action()
        self.assertLess(len(a["description"]), 125)
        self.assertTrue(a["name"] and a["branding"]["icon"] and a["branding"]["color"])

    def test_the_metadata_parses_and_every_used_input_is_declared(self):
        import re
        a = self._action()
        self.assertEqual(a["runs"]["using"], "composite")
        with open(os.path.join(self.ROOT, "action.yml"), encoding="utf-8") as fh:
            used = set(re.findall(r"inputs\.([a-z-]+)", fh.read()))
        self.assertLessEqual(used, set(a["inputs"]))

    def test_no_checkout_leaves_the_token_on_disk(self):
        """SECURITY: actions/checkout writes the job's token into .git/config unless told
        not to, and the build that follows runs the PR's code and its install scripts,
        which could read it and act with the workflow's pull-requests: write."""
        steps = [s for s in self._action()["runs"]["steps"] if "actions/checkout" in s.get("uses", "")]
        self.assertTrue(steps)
        for s in steps:
            self.assertIs((s.get("with") or {}).get("persist-credentials"), False, s["name"])

    @staticmethod
    def _bash():
        """A bash that runs this filesystem's scripts. On Windows a bare "bash" resolves to
        System32's bash.exe, the WSL launcher, before anything on PATH (GitHub's Windows
        runners have it, so the step failed there), so use the Git Bash beside git.exe."""
        if os.name != "nt":
            return shutil.which("bash")
        git = shutil.which("git")
        for rel in (("..", "bin", "bash.exe"), ("..", "..", "bin", "bash.exe")):
            cand = os.path.normpath(os.path.join(os.path.dirname(git or ""), *rel))
            if git and os.path.isfile(cand):
                return cand
        return None

    def _run_step(self, waivers=None):
        """Run the action's own shell step with bash against two prepared folders, the
        way the runner would after checkout and build; return its GITHUB_OUTPUT words."""
        bash = self._bash()
        if not bash:
            raise unittest.SkipTest("bash not available")
        step = next(s for s in self._action()["runs"]["steps"] if s.get("id") == "check")
        work = tempfile.mkdtemp(prefix="sitemend-action-")
        self.addCleanup(shutil.rmtree, work, True)
        for side, broken in (("head", True), ("base", False)):
            link = '<a href="/gone/">x</a> ' if broken else ""
            full = os.path.join(work, "_sitemend", side, "out", "index.html")
            os.makedirs(os.path.dirname(full))
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(page_html(body="<h1>H</h1><p>" + link + "word " * 300 + "</p>"))
        shim = os.path.join(work, "bin")
        os.makedirs(shim)
        with open(os.path.join(shim, "sitemend"), "w", newline="\n") as fh:
            fh.write('#!/bin/sh\nexec "{0}" "{1}" "$@"\n'.format(
                sys.executable.replace("\\", "/"),
                os.path.join(sitemend.HERE, "sitemend.py").replace("\\", "/")))
        os.chmod(os.path.join(shim, "sitemend"), 0o755)
        gh_out = os.path.join(work, "gh_output")
        if waivers is not None:
            with open(os.path.join(work, "_sitemend", "head", ".sitemend-waivers.json"), "w") as fh:
                json.dump({"waivers": waivers}, fh)
        env = dict(os.environ, SITE_DIR="out", URL="", BASELINE_URL="", FAIL_ON="",
                   MAX_PAGES="200", SITEMEND_HTTP_HEADERS="", GITHUB_OUTPUT=gh_out,
                   WAIVERS=".sitemend-waivers.json",
                   PATH=shim + os.pathsep + os.environ.get("PATH", ""), PYTHONIOENCODING="utf-8")
        script = os.path.join(work, "step.sh")
        with open(script, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(step["run"])
        r = subprocess.run([bash, script], cwd=work, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        self.assertEqual(r.returncode, 0, "bash {0} failed:\n{1}{2}".format(
            bash, r.stdout[-2000:], r.stderr[-2000:]))
        self.assertTrue(os.path.isfile(os.path.join(work, "_sitemend", "out", "verify.md")))
        with open(gh_out, encoding="utf-8") as fh:
            return fh.read().split()

    def test_the_audit_step_runs_check_on_the_folders_it_checked_out(self):
        """No waivers file at the default path is not an error: the PR still fails."""
        self.assertEqual(self._run_step(), ["code=1", "result=fail"])

    def test_the_audit_step_reads_the_pull_requests_waivers(self):
        self.assertEqual(self._run_step([{"rule": "S1-BROKEN-LINK", "url": "/",
                                          "reason": "Page lands Monday"}]),
                         ["code=0", "result=pass"])


class TestReplay(unittest.TestCase):
    """bench/replay/replay.py builds a repository's real commits and runs the gate on each
    consecutive pair. Two throwaway git repositories stand in for real sites, so no
    network is needed. A failed build must never read as a pass or a fail."""

    ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    SCRIPT = os.path.join(ROOT, "bench", "replay", "replay.py")
    BUILD = ("import os, shutil, sys\n"
             "if os.path.exists('src/FAIL'):\n    sys.exit('build failed')\n"
             "shutil.copytree('src', 'out')\n")

    @classmethod
    def setUpClass(cls):
        if not os.path.isfile(cls.SCRIPT):
            raise unittest.SkipTest("bench/ is not shipped in the sdist")
        if not shutil.which("git"):
            raise unittest.SkipTest("git not available")
        cls.tmp = tempfile.mkdtemp(prefix="sitemend-replay-")
        page = lambda link="", words=300: page_html(body="<h1>H</h1><p>" + link + "word " * words + "</p>")
        # Cutoff 2026-02-01: the last commit of each is after it and must never be built.
        cls.a = cls._repo("a", [
            ("2026-01-01", {"build.py": cls.BUILD, "src/index.html": page()}),
            ("2026-01-02", {"src/index.html": page(words=310)}),
            ("2026-01-03", {"src/index.html": page('<a href="/gone/">x</a> ')}),
            ("2026-01-04", {"src/FAIL": "x"}),
            ("2026-01-05", {"src/FAIL": None}),
            ("2026-03-01", {"src/index.html": page(words=320)}),
        ])
        cls.b = cls._repo("b", [
            ("2026-01-01", {"build.py": cls.BUILD, "src/index.html": page()}),
            ("2026-01-02", {"src/index.html": page(words=310)}),
            ("2026-03-01", {"src/index.html": page(words=320)}),
        ])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    @classmethod
    def _repo(cls, name, steps):
        path = os.path.join(cls.tmp, "src-" + name)
        os.makedirs(path)

        def git(*args, date="2026-01-01"):
            stamp = date + "T12:00:00+00:00"
            subprocess.run(["git"] + list(args), cwd=path, check=True, capture_output=True,
                           env=dict(os.environ, GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp,
                                    GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.test",
                                    GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.test"))
        git("init", "-q", "-b", "main")
        git("config", "commit.gpgsign", "false")
        shas = []
        for date, files in steps:
            for rel, content in files.items():
                full = os.path.join(path, rel)
                if content is None:
                    os.remove(full)
                    continue
                os.makedirs(os.path.dirname(full) or path, exist_ok=True)
                with open(full, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(content)
            git("add", "-A")
            git("commit", "-q", "-m", date, date=date)
            shas.append(subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, check=True,
                                       capture_output=True, text=True).stdout.strip())
        return path, shas

    def _run(self, entries, *flags):
        """Run the harness on a fresh config; return (results rows, out dir, run dir)."""
        d = tempfile.mkdtemp(prefix="run-", dir=self.tmp)
        cfg = os.path.join(d, "repos.json")
        with open(cfg, "w", encoding="utf-8") as fh:
            json.dump([dict(e, ref_cutoff="2026-02-01T00:00:00Z", site_dir="out", node_version="24",
                            build_command='"{0}" build.py'.format(sys.executable)) for e in entries], fh)
        return self._again(d, *flags)

    def _again(self, d, *flags):
        out, results = os.path.join(d, "out"), os.path.join(d, "results.csv")
        r = subprocess.run([sys.executable, self.SCRIPT, "--config", os.path.join(d, "repos.json"),
                            "--work", os.path.join(d, "work"), "--out", out, "--results", results,
                            "--scripts", sitemend.HERE] + list(flags),
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-2000:])
        import csv
        with open(results, encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh)), out, d

    def test_consecutive_commits_are_compared_and_failed_builds_skipped(self):
        a, sa = self.a
        rows, out, d = self._run([{"repo": "t/a", "url": a, "commits": 4}])
        ra = rows
        self.assertEqual([(r["base_sha"], r["head_sha"]) for r in ra],
                         list(zip(sa[:4], sa[1:5])))
        self.assertEqual([r["gate_result"] for r in ra],
                         ["pass", "fail", "skipped_build_failed", "skipped_build_failed"])
        self.assertNotIn(sa[5], {r["head_sha"] for r in rows}, "a commit after the cutoff was built")
        with open(os.path.join(d, ra[1]["new_findings_json_path"]), encoding="utf-8") as fh:
            self.assertEqual([f["id"] for f in json.load(fh)["regressions"]], ["S1-BROKEN-LINK"])
        self.assertEqual(ra[2]["new_findings_json_path"], "")
        self.assertTrue(float(ra[0]["build_seconds"]) >= 0 and float(ra[0]["audit_seconds"]) > 0)
        import csv
        with open(os.path.join(d, "builds.csv"), encoding="utf-8", newline="") as fh:
            builds = list(csv.DictReader(fh))
        self.assertEqual([(b["sha"], b["status"]) for b in builds],
                         list(zip(sa[:5], ["ok", "ok", "ok", "build_failed", "ok"])))
        self.assertEqual(builds[3]["error"], "build failed")
        self.assertEqual(builds[0]["error"], "")

        # A re-run reuses every build and audit and writes the same results.
        marker = os.path.join(out, "t__a", sa[0], "build.json")
        before = os.path.getmtime(marker)
        again, _, _ = self._again(d)
        self.assertEqual(os.path.getmtime(marker), before)
        self.assertEqual(again, rows)

        # Another sitemend never reuses those audits: every commit is audited again.
        other = os.path.join(d, "other", "scripts")
        shutil.copytree(sitemend.HERE, other, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(os.path.join(sitemend.HERE, "..", "assets"), os.path.join(d, "other", "assets"))
        with open(os.path.join(other, "audit.py"), "a", encoding="utf-8") as fh:
            fh.write("\n# another version\n")
        with open(marker, encoding="utf-8") as fh:
            old = json.load(fh)["sitemend"]
        third, _, _ = self._again(d, "--scripts", other)
        with open(marker, encoding="utf-8") as fh:
            self.assertNotEqual(json.load(fh)["sitemend"], old)
        self.assertEqual([r["gate_result"] for r in third], [r["gate_result"] for r in rows])

    def test_pilot_runs_two_repositories_at_twenty_commits(self):
        """commits: 0 would compare nothing. The pilot asks for 20, and b has only two
        commits before the cutoff, so each repository gets exactly one comparison."""
        b, sb = self.b
        rows, _, _ = self._run([{"repo": "t/x", "url": b, "commits": 0},
                                {"repo": "t/y", "url": b, "commits": 0},
                                {"repo": "t/z", "url": b, "commits": 0}], "--pilot")
        self.assertEqual([(r["repo"], r["head_sha"], r["gate_result"]) for r in rows],
                         [("t/x", sb[1], "pass"), ("t/y", sb[1], "pass")])

    def test_list_prints_the_selection_for_a_ci_matrix(self):
        """The replay workflow runs one job per repository from this list."""
        cfg = os.path.join(tempfile.mkdtemp(prefix="run-", dir=self.tmp), "repos.json")
        with open(cfg, "w", encoding="utf-8") as fh:
            json.dump([{"repo": n, "node_version": 24} for n in ("o/a", "o/b", "o/c")], fh)

        def listed(*flags):
            r = subprocess.run([sys.executable, self.SCRIPT, "--config", cfg, "--list"] + list(flags),
                               capture_output=True, text=True, check=True)
            return json.loads(r.stdout)
        self.assertEqual(listed("--pilot"), [{"repo": "o/a", "slug": "o__a", "node_version": "24"},
                                             {"repo": "o/b", "slug": "o__b", "node_version": "24"}])
        self.assertEqual([e["repo"] for e in listed("--pilot", "--only", "o/c")], ["o/c"])
        self.assertEqual(len(listed()), 3)


class TestEvidenceLedger(unittest.TestCase):
    """bench/verify_helper.py pre-fills one ledger row per blocking finding and shows the
    evidence; a person writes every verdict. bench/summarize.py turns the ledger and the
    replay's results into bench/summary.md, keeping per-commit frequency and per-finding
    precision apart."""

    BENCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bench")
    HEAD, BASE, OTHER = "h" * 40, "b" * 40, "c" * 40

    def setUp(self):
        if not os.path.isfile(os.path.join(self.BENCH, "summarize.py")):
            raise unittest.SkipTest("bench/ is not shipped in the sdist")
        self.d = tempfile.mkdtemp(prefix="sitemend-ledger-")
        self.addCleanup(shutil.rmtree, self.d, True)

    def _write(self, rel, text):
        full = os.path.join(self.d, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="") as fh:
            fh.write(text if isinstance(text, str) else json.dumps(text))
        return full

    def _csv(self, rel, header, rows):
        return self._write(rel, "\n".join([",".join(header)] + [",".join(r) for r in rows]) + "\n")

    def _run(self, script, *args):
        r = subprocess.run([sys.executable, os.path.join(self.BENCH, script)] + list(args),
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-2000:])
        return r.stdout

    def _ledger(self, path):
        import csv
        with open(path, encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    RESULTS = ["repo", "base_sha", "head_sha", "build_seconds", "audit_seconds", "gate_result",
               "new_findings_json_path"]

    def _replay(self):
        """One failing comparison whose head made /drafts/a/ noindex, one passing one."""
        page = lambda noindex: {"url": "/drafts/a/", "title": "Draft", "noindex": noindex,
                                "robots_meta": "noindex" if noindex else None, "canonical": "/drafts/a/"}
        for sha, noindex in ((self.BASE, False), (self.HEAD, True)):
            self._write("out/o__r/{0}/crawl.json".format(sha),
                        {"pages": [page(noindex)], "robots": {"found": True}, "sitemap": {"found": True}})
        self._write("out/o__r/{0}/verify.json".format(self.HEAD), {"regressions": [
            {"id": "S1-NOT-INDEXABLE", "severity": "critical", "pages": ["/drafts/a/"],
             "evidence": '<meta name="robots" content="noindex">', "message": "Page is noindex"}]})
        return self._csv("results.csv", self.RESULTS, [
            ["o/r", self.BASE, self.HEAD, "10", "5", "fail", "out/o__r/{0}/verify.json".format(self.HEAD)],
            ["o/r", self.OTHER, self.BASE, "10", "5", "pass", "out/o__r/{0}/verify.json".format(self.BASE)]])

    def test_helper_prefills_rows_and_shows_evidence_but_never_a_verdict(self):
        results, ledger = self._replay(), os.path.join(self.d, "ledger.csv")
        out = self._run("verify_helper.py", "--results", results, "--ledger", ledger)
        rows = self._ledger(ledger)
        self.assertEqual([(r["repo"], r["head_sha"], r["rule_id"], r["severity"], r["url"], r["verdict"])
                          for r in rows], [("o/r", self.HEAD, "S1-NOT-INDEXABLE", "critical", "/drafts/a/", "")])
        self.assertIn('content="noindex"', rows[0]["evidence_excerpt"])
        self.assertIn("noindex: False -> True", out)
        self.assertIn("https://github.com/o/r/compare/{0}...{1}".format(self.BASE, self.HEAD), out)

        # A second run adds nothing, and keeps a verdict a person wrote.
        import csv
        rows[0].update(verdict="true_regression", verified_by="B", verification_method="curl")
        with open(ledger, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
        out = self._run("verify_helper.py", "--results", results, "--ledger", ledger)
        self.assertEqual([r["verdict"] for r in self._ledger(ledger)], ["true_regression"])
        self.assertNotIn("noindex: False -> True", out)

    def test_one_row_per_blocking_finding_not_per_rule_and_page(self):
        """REGRESSION found by the 1.7.0 pilot: seven broken language links on one new
        electron/website page became one ledger row, so precision, counted per finding,
        would have counted one finding where the gate blocked on seven."""
        results, ledger = self._replay(), os.path.join(self.d, "ledger.csv")
        self._write("out/o__r/{0}/verify.json".format(self.HEAD), {"regressions": [
            {"id": "S1-BROKEN-LINK", "severity": "high", "pages": ["/drafts/a/"],
             "evidence": 'href="/de/x" -> /de/x', "message": "broken"},
            {"id": "S1-BROKEN-LINK", "severity": "high", "pages": ["/drafts/a/"],
             "evidence": 'href="/fr/x" -> /fr/x', "message": "broken"}]})
        self._run("verify_helper.py", "--results", results, "--ledger", ledger)
        self._run("verify_helper.py", "--results", results, "--ledger", ledger)
        self.assertEqual(sorted(r["evidence_excerpt"] for r in self._ledger(ledger)),
                         ['href="/de/x" -> /de/x', 'href="/fr/x" -> /fr/x'])

    def test_summary_keeps_frequency_per_commit_and_precision_per_finding(self):
        c1, c2, c3, c4 = ("1" * 40, "2" * 40, "3" * 40, "4" * 40)
        results = self._csv("results.csv", self.RESULTS, [
            ["o/r", self.BASE, c1, "10", "4", "fail", "x"],
            ["o/r", c1, c2, "20", "6", "fail", "x"],
            ["o/r", c2, c3, "30", "8", "pass", "x"],
            ["o/r", c3, c4, "40", "", "skipped_audit_failed", ""]])
        builds = self._csv("builds.csv", ["repo", "sha", "status", "build_seconds", "audit_seconds",
                                          "node", "error"], [
            ["o/r", self.BASE, "ok", "10", "4", "v24", ""], ["o/r", c1, "ok", "10", "4", "v24", ""],
            ["o/r", c2, "ok", "20", "6", "v24", ""], ["o/r", c3, "ok", "30", "8", "v24", ""],
            ["o/r", c4, "audit_failed", "40", "1", "v24", "ValueError: Invalid IPv6 URL"]])
        ledger = self._csv("ledger.csv", ["repo", "head_sha", "rule_id", "severity", "url",
                                          "evidence_excerpt", "verdict", "verified_by",
                                          "verification_method", "notes"], [
            ["o/r", c1, "S1-NOT-INDEXABLE", "critical", "/a/", "e", "true_regression", "B", "curl", ""],
            ["o/r", c1, "S1-BROKEN-LINK", "high", "/a/", "e", "unclear", "B", "curl", ""],
            ["o/r", c2, "S1-BROKEN-LINK", "high", "/b/", "e", "false_positive", "B", "curl", ""]])
        out = os.path.join(self.d, "summary.md")
        self._run("summarize.py", "--results", results, "--builds", builds, "--ledger", ledger, "--out", out)
        with open(out, encoding="utf-8") as fh:
            md = fh.read()
        # Two commits failed the gate, but only one introduced a verified regression.
        self.assertIn("| o/r | 3 | 2 | 1 | 1 |", md)
        self.assertIn("**Frequency: 1 of 3 commits compared (33.3%)**", md)
        # Unclear counts against precision, as pre-registered.
        self.assertIn("**Precision: 1 of 3 blocking findings with a verdict (33.3%)**", md)
        self.assertIn("| S1-BROKEN-LINK | 2 | 0 | 1 | 0 | 1 | 0 | 0.0% |", md)
        self.assertIn("| S1-NOT-INDEXABLE | 1 | 1 | 0 | 0 | 0 | 0 | 100.0% |", md)
        self.assertIn("inconclusive: 3 verdicts, 20 needed", md)
        self.assertIn("| o/r | 1 | 0 | ValueError: Invalid IPv6 URL |", md)
        self.assertIn("| Build | 4 | 15.0 | 30.0 |", md)
        self.assertIn("| Audit | 4 | 5.0 | 8.0 |", md)


class TestSeededRecall(unittest.TestCase):
    """bench/seeded/seeded.py builds a repository once, applies each known regression to a
    copy of the built output and checks the gate catches it: recall needs ground truth,
    which replay cannot give. An unmutated copy must pass, or the harness is the problem."""

    SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bench", "seeded", "seeded.py")
    HOST = "https://docs.acme-widgets.com"

    def setUp(self):
        if not os.path.isfile(self.SCRIPT):
            raise unittest.SkipTest("bench/ is not shipped in the sdist")
        if not shutil.which("git"):
            raise unittest.SkipTest("git not available")
        self.d = tempfile.mkdtemp(prefix="sitemend-seeded-")
        self.addCleanup(shutil.rmtree, self.d, True)

    def _site_repo(self):
        """A clean four-page site every mutation applies to: absolute canonicals, a sitemap
        robots.txt names, unique titles, and every page linking to every other."""
        src = os.path.join(self.d, "src-site")
        pages = {"/": "index.html", "/a.html": "a.html", "/b.html": "b.html", "/c.html": "c.html"}
        nav = " ".join('<a href="{0}">{1}</a>'.format(u, f) for u, f in pages.items())
        files = {"build.py": TestReplay.BUILD,
                 "src/robots.txt": "User-agent: *\nAllow: /\nSitemap: {0}/sitemap.xml\n".format(self.HOST),
                 "src/sitemap.xml": '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                                    + "".join("<url><loc>{0}{1}</loc></url>".format(self.HOST, u) for u in pages)
                                    + "</urlset>",
                 # An error page that sorts before every content page: never a target.
                 "src/404.html": page_html(title="Page Not Found On The Widget Handbook Site",
                                           body="<h1>Not found</h1><p>" + "gone " * 300 + "</p>"),
                 # Two pages that already share a title, sorting before the content pages:
                 # the page given a copied title must not be one of them, or the mutation
                 # swaps one duplicate pair for another instead of adding one (#60).
                 "src/0a.html": page_html(title="An Older Widget Page With A Shared Title",
                                          body="<h1>Old A</h1><p>" + "older " * 300 + "</p>"),
                 "src/0b.html": page_html(title="An Older Widget Page With A Shared Title",
                                          body="<h1>Old B</h1><p>" + "elder " * 300 + "</p>")}
        for i, (u, f) in enumerate(pages.items()):
            files["src/" + f] = page_html(
                title="Widget Handbook Chapter Number {0} Overview".format(i),
                desc="Chapter {0} of the widget handbook, covering setup, tuning and the care of "
                     "widgets in production.".format(i),
                head_extra='<link rel="canonical" href="{0}{1}">'.format(self.HOST, u),
                body="<h1>Chapter {0}</h1><p>{1} ".format(i, nav) + "widget " * 300 + "</p>")
        os.makedirs(src)
        env = dict(os.environ, GIT_AUTHOR_DATE="2026-01-01T12:00:00+00:00",
                   GIT_COMMITTER_DATE="2026-01-01T12:00:00+00:00", GIT_AUTHOR_NAME="t",
                   GIT_AUTHOR_EMAIL="t@example.test", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.test")
        for rel, text in files.items():
            full = os.path.join(src, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
        for args in (["init", "-q", "-b", "main"], ["config", "commit.gpgsign", "false"],
                     ["add", "-A"], ["commit", "-q", "-m", "site"]):
            subprocess.run(["git"] + args, cwd=src, check=True, capture_output=True, env=env)
        return src

    def test_every_mutation_is_caught_and_the_unmutated_control_passes(self):
        import csv
        cfg = os.path.join(self.d, "repos.json")
        with open(cfg, "w", encoding="utf-8") as fh:
            site = {"url": self._site_repo(), "ref_cutoff": "2026-02-01T00:00:00Z", "commits": 50,
                    "site_dir": "out", "node_version": "24"}
            json.dump([dict(site, repo="t/site", build_command='"{0}" build.py'.format(sys.executable)),
                       dict(site, repo="t/broken",
                            build_command='"{0}" -c "import sys; sys.exit(1)"'.format(sys.executable))], fh)
        results = os.path.join(self.d, "results.csv")
        r = subprocess.run([sys.executable, self.SCRIPT, "--config", cfg, "--work", os.path.join(self.d, "work"),
                            "--out", os.path.join(self.d, "out"), "--results", results,
                            "--scripts", sitemend.HERE], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-3000:])
        with open(results, encoding="utf-8", newline="") as fh:
            all_rows = list(csv.DictReader(fh))
        # A build that fails is a build failure, never a sitemend tool failure.
        self.assertEqual({x["fired"] for x in all_rows if x["repo"] == "t/broken" and x["mutation"] != "control"},
                         {"build_failed"})
        rows = {x["mutation"]: x for x in all_rows if x["repo"] == "t/site"}
        self.assertNotIn("/404.html", {x["target"] for x in rows.values()})
        self.assertEqual(rows.pop("control")["gate_failed"], "n")
        self.assertEqual(len(rows), 10)
        missed = {m: (x["expected_rule"], x["fired"], x["target"]) for m, x in rows.items() if x["fired"] != "y"}
        self.assertEqual(missed, {})
        # The medium one fires but, by design, does not fail the gate.
        self.assertEqual({m for m, x in rows.items() if x["gate_failed"] == "n"}, {"canonical-removed"})
        with open(os.path.join(self.d, "recall.md"), encoding="utf-8") as fh:
            md = fh.read()
        # Two of the nine critical/high types are reported apart (Addenda 3, 9 and 10), not pooled.
        self.assertIn("**Recall, critical and high mutation types: 7 of 7 (100.0%)**", md)
        for name in ("rating-unsupported", "sitemap-preview-host"):
            self.assertIn("| {0} (apart) |".format(name), md)
        self.assertIn("| title-duplicated |", md)
        self.assertIn("Build failures, not counted in recall: t/broken.", md)
        self.assertNotIn("Tool failures (sitemend", md)
        self.assertIn("it failed the check on 7 of 7 (100.0%); it failed it and the expected "
                      "rule fired on 7 of 7 (100.0%).", md)

    def test_recall_also_counts_what_the_gate_did(self):
        """The 1.9.0 run's one pooled miss (learn-fips, canonical-preview-host): the expected
        rule did not fire, but another one failed the gate. Fired alone hid that; a rule
        firing while the gate passes must not read as caught by the gate either."""
        seeded = _bench_module("seeded", "seeded.py")
        if seeded is None:
            raise unittest.SkipTest("bench/ is not shipped in the sdist")
        row = lambda m, fired, gate: dict(repo="t/a", mutation=m, fired=fired, gate_failed=gate)
        md = seeded.recall_md([row("canonical-preview-host", "n", "y"), row("noindex-added", "y", "y"),
                               row("title-removed", "y", "n"), row("canonical-removed", "y", "n")], ["x"])
        self.assertIn("**Recall, critical and high mutation types: 2 of 3 (66.7%)**", md)
        self.assertIn("it failed the check on 2 of 3 (66.7%); it failed it and the expected "
                      "rule fired on 1 of 3 (33.3%).", md)

    def test_the_duplicate_title_mutation_skips_a_title_shared_with_the_404_page(self):
        """REGRESSION from the 1.8.0 seeded run (#81): the home page shared its title with
        404.html, which is not indexable, so the harness took it for unique and the
        mutation only grew an existing duplicate group (Addendum 10)."""
        seeded = _bench_module("seeded", "seeded.py")
        if seeded is None:
            self.skipTest("bench/ is not shipped in the sdist")
        seeded.is_utility = audit.is_utility
        page = lambda url, title, f: {"url": url, "title": title, "file": f, "noindex": False,
                                      "robots_allowed": True}
        # A base-path site: its home is /hb/, not /, so it sorts first and was the pick.
        crawl = {"pages": [page("/hb/", "Guide", "index.html"), page("/hb/404.html", "Guide", "404.html"),
                           page("/hb/a/", "Alpha", "a/index.html"), page("/hb/b/", "Beta", "b/index.html")]}
        for d, title in (("a", "Alpha"), ("b", "Beta")):
            os.makedirs(os.path.join(self.d, d), exist_ok=True)
            with open(os.path.join(self.d, d, "index.html"), "w", encoding="utf-8") as fh:
                fh.write("<html><head><title>{0}</title></head><body></body></html>".format(title))
        seeded.title_duplicated(self.d, crawl)
        with open(os.path.join(self.d, "b", "index.html"), encoding="utf-8") as fh:
            self.assertIn("<title>Alpha</title>", fh.read())     # a new pair, Alpha + Alpha


class TestTask9(unittest.TestCase):
    """bench/task9/task9.py, the prospective run (bench/PREREGISTRATION-task9.md). Every test
    runs on fixtures: a fake GitHub API, throwaway git repositories and local servers. No
    test reaches GitHub or a drawn site."""

    T0 = "2026-10-24T00:00:00Z"

    def setUp(self):
        self.t9 = _bench_module("task9", "task9.py")
        if self.t9 is None:
            raise unittest.SkipTest("bench/ is not shipped in the sdist")
        # No test resolves a hostname: the real check is tested on its own.
        self.real_public_https = self.t9.public_https
        self.t9.public_https = lambda u: (u or "").startswith("https://")
        self.d = tempfile.mkdtemp(prefix="sitemend-task9-")
        self.addCleanup(shutil.rmtree, self.d, True)

    def at(self, minutes=0, days=0):
        import datetime
        return self.t9.parse_time(self.T0) + datetime.timedelta(minutes=minutes, days=days)

    # ------------------------------------------------------------ the draw

    def test_select_takes_six_per_stack_then_tops_up_previews(self):
        """2.2: the first 6 per stack that built; with fewer than 10 flagged, the next
        flagged ones that built, one stack at a time, until 10 are flagged or 40 taken."""
        stacks = [s for s, _, _, _ in self.t9.sample.STACKS]
        cands, built = [], {}
        for s in stacks:
            for rank in range(1, 11):
                repo = "{0}/r{1}".format(s, rank)
                flagged = (s == "astro" and rank == 2) or rank in (8, 9, 10)
                cands.append({"repo": repo, "stack": s, "rank": rank, "preview": "https://p" if flagged else ""})
                built[repo] = "build_failed" if rank == 1 else "ok"
        taken, short = self.t9.select(cands, built)
        first = [c["repo"] for c in taken[:30]]
        self.assertEqual(first[:6], ["docusaurus/r{0}".format(i) for i in range(2, 8)])
        self.assertEqual(short, [])
        # 1 flagged among the first 30 (astro/r2); 9 more come from rank 8 on, round-robin.
        self.assertEqual([c["repo"] for c in taken[30:]],
                         ["docusaurus/r8", "astro/r8", "vitepress/r8", "hugo/r8", "nextjs/r8",
                          "docusaurus/r9", "astro/r9", "vitepress/r9", "hugo/r9"])
        self.assertEqual(sum(bool(c["preview"]) for c in taken), 10)

    def test_a_preview_is_found_by_deployment_status_or_bot_comment(self):
        repo, sha = "o/r", "a" * 40
        api = {"repos/o/r/deployments?sha={0}&per_page=20".format(sha): [
                   {"id": 1, "environment": "Production"}, {"id": 2, "environment": "Preview"}],
               "repos/o/r/deployments/1/statuses?per_page=20": [{"state": "success", "environment_url": "https://prod"}],
               "repos/o/r/deployments/2/statuses?per_page=20": [{"state": "success", "environment_url": "https://pr-2.vercel.app"}]}
        self.assertEqual(self.t9.preview_url(api.get, repo, sha), "https://pr-2.vercel.app")
        comment = {"user": {"type": "Bot"}, "body": "Deploy preview for aaaaaaa ready: https://deploy-preview-7--x.netlify.app)"}
        api2 = {"repos/o/r/issues/7/comments?per_page=100": [comment]}
        self.assertEqual(self.t9.preview_url(api2.get, repo, sha, 7), "https://deploy-preview-7--x.netlify.app")
        # A bot comment about another commit, or from a person, does not count.
        self.assertIsNone(self.t9.preview_url(api2.get, repo, "b" * 40, 7))
        api2["repos/o/r/issues/7/comments?per_page=100"] = [dict(comment, user={"type": "User"})]
        self.assertIsNone(self.t9.preview_url(api2.get, repo, sha, 7))

    # ------------------------------------------------------------ the window

    def _pr(self, n, head, created, state="open", draft=False, merged_at=None, bot=False):
        return {"number": n, "created_at": created, "state": state, "draft": draft, "merged_at": merged_at,
                "closed_at": merged_at, "user": {"type": "Bot" if bot else "User"},
                "head": {"sha": head}, "base": {"sha": "b" * 40}}

    def _api(self, pulls, commits=(), previews=()):
        def get(path):
            if path.startswith("repos/o/r/pulls?"):
                return pulls if "page=1" in path else []
            if path.startswith("repos/o/r/commits?"):
                return list(commits)
            if "/statuses?" in path and "/commits/" in path:
                sha = path.split("/commits/")[1].split("/")[0]
                return [{"state": "success", "context": "netlify/x/deploy-preview",
                         "target_url": "https://deploy-preview--x.netlify.app"}] if sha in previews else []
            return []
        return get

    def test_plan_checks_each_new_head_and_counts_only_the_last(self):
        t9 = self.t9
        repos = [{"repo": "o/r", "default_branch": "main", "homepage": "https://o.test", "node_version": "24"}]
        opens, ends = self.at(), self.at(days=56)
        h1, h2 = "1" * 40, "2" * 40
        pulls = [self._pr(5, h1, "2026-10-25T10:00:00Z"),
                 self._pr(6, "6" * 40, "2026-10-25T11:00:00Z", draft=True),
                 self._pr(4, "4" * 40, "2026-10-20T00:00:00Z")]       # opened before the window
        commits = [{"sha": "c" * 40, "commit": {"committer": {"date": "2026-10-25T09:00:00Z"}}}]
        state, jobs = t9.plan({}, repos, opens, ends, self.at(days=1, minutes=600),
                              get=self._api(pulls, commits), hash_home=lambda u: "h")
        self.assertEqual(sorted((j["kind"], j.get("pr")) for j in jobs), [("folder", 5), ("production", None)])
        self.assertNotIn("o/r#4", state["prs"])
        self.assertNotIn("folder", [j["kind"] for j in jobs if j.get("pr") == 6], "a draft is not checked")
        # collect records the folder result; a new head arrives with a preview; then the PR closes.
        state["prs"]["o/r#5"]["heads"][h1]["folder"] = "pass"
        state["production"]["o/r"] = {"audited_at": "2026-10-25T10:00:00Z", "home_hash": "h", "findings": "x"}
        state["production_tries"].pop("o/r")          # as collect does when an audit succeeds
        # The first poll's jobs are in flight: the next poll does not schedule them again.
        _, again = t9.plan(state, repos, opens, ends, self.at(days=1, minutes=605),
                           get=self._api(pulls, commits), hash_home=lambda u: "h")
        self.assertEqual(again, [])
        pulls[0] = self._pr(5, h2, "2026-10-25T10:00:00Z")
        state, jobs = t9.plan(state, repos, opens, ends, self.at(days=1, minutes=615),
                              get=self._api(pulls, previews=(h2,)), hash_home=lambda u: "h")
        self.assertEqual(sorted(j["kind"] for j in jobs if j.get("pr") == 5), ["folder", "url"])
        pulls[0] = self._pr(5, h2, "2026-10-25T10:00:00Z", state="closed", merged_at="2026-10-25T12:00:00Z")
        merge = [{"sha": "d" * 40, "commit": {"committer": {"date": "2026-10-25T12:00:00Z"}}}]
        state, jobs = t9.plan(state, repos, opens, ends, self.at(days=1, minutes=630),
                              get=self._api(pulls, merge, previews=(h2,)), hash_home=lambda u: "h")
        self.assertEqual(state["prs"]["o/r#5"]["final_head"], h2)
        # The merge is 30 minutes old and the home page has not changed: no production audit yet.
        self.assertNotIn("production", [j["kind"] for j in jobs])
        _, jobs = t9.plan(state, repos, opens, ends, self.at(days=1, minutes=630),
                          get=self._api(pulls, merge, previews=(h2,)), hash_home=lambda u: "changed")
        self.assertIn("production", [j["kind"] for j in jobs])
        # A job that never reports back is tried 3 times, then counts as a tool failure.
        for i in range(3):
            state, _ = t9.plan(state, repos, opens, ends, self.at(days=1, minutes=900 + 300 * i),
                               get=self._api(pulls, previews=(h2,)), hash_home=lambda u: "h")
        self.assertEqual(state["prs"]["o/r#5"]["heads"][h2]["folder"], "tool_failure")

    def test_a_final_head_with_no_preview_is_preview_unavailable(self):
        t9 = self.t9
        repos = [{"repo": "o/r", "default_branch": "main", "homepage": "https://o.test"}]
        pulls = [self._pr(9, "9" * 40, "2026-10-25T10:00:00Z", state="closed", merged_at="2026-10-25T11:00:00Z")]
        state, jobs = t9.plan({}, repos, self.at(), self.at(days=56), self.at(days=2),
                              get=self._api(pulls), hash_home=lambda u: "h")
        self.assertEqual(state["prs"]["o/r#9"]["heads"]["9" * 40]["url"], "preview_unavailable")
        self.assertEqual([j["kind"] for j in jobs if j.get("pr") == 9], ["folder"])

    # ------------------------------------------------------------ results, ledger, report

    def test_collect_ledger_and_report(self):
        t9, data = self.t9, os.path.join(self.d, "data")
        h = "f" * 40
        state = {"prs": {"o/r#1": {"repo": "o/r", "number": 1, "bot": False, "merged_at": "2026-10-25T12:00:00Z",
                                   "final_head": h, "heads": {h: {"folder": None, "url": None}}}},
                 "production": {}}
        broken = {"id": "S1-BROKEN-LINK", "severity": "high", "pages": ["/"], "evidence": "href=/gone",
                  "message": "m", "confidence": "high"}
        leak = {"id": "S1-HOST-MISMATCH", "severity": "critical", "pages": ["/"], "evidence": "x.vercel.app",
                "message": "m", "confidence": "high"}
        job = {"repo": "o/r", "pr": 1, "head": h, "base": "b" * 40}
        results = [{"job": dict(job, kind="folder"), "outcome": "fail", "reason": "", "regressions": [broken],
                    "advisory": [], "checked_at": "2026-10-25T12:01:00Z"},
                   {"job": dict(job, kind="url"), "outcome": "fail", "reason": "", "regressions": [broken],
                    "advisory": [], "checked_at": "2026-10-25T12:02:00Z"},
                   {"job": {"repo": "o/r", "kind": "production", "url": "https://o.test", "branch_sha": "c" * 40},
                    "outcome": "first", "reason": "", "regressions": [], "findings": [], "home_hash": "h",
                    "checked_at": "2026-10-25T11:00:00Z"},
                   {"job": {"repo": "o/r", "kind": "production", "url": "https://o.test", "branch_sha": "d" * 40},
                    "outcome": "compared", "reason": "", "regressions": [leak], "findings": [leak], "home_hash": "h2",
                    "checked_at": "2026-10-25T14:00:00Z"}]
        state = t9.collect(state, results[:3], data)
        state = t9.collect(state, results[3:], data)
        rows = t9.read_csv(os.path.join(data, "results.csv"))
        self.assertEqual([(r["mode"], r["outcome"], r["blocking"]) for r in rows], [("folder", "fail", "1"), ("url", "fail", "1")])
        prod = t9.read_csv(os.path.join(data, "production.csv"))
        self.assertEqual([(p["outcome"], p["merged_prs"]) for p in prod], [("first", ""), ("compared", "#1")])

        self.assertEqual(t9.cmd_ledger(argparse.Namespace(data=data, second_look=False)), 0)
        gate = t9.read_csv(os.path.join(data, "ledger-task9.csv"))
        self.assertEqual([(r["rule_id"], r["notes"]) for r in gate], [("S1-BROKEN-LINK", "mode: both")])
        prod_ledger = t9.read_csv(os.path.join(data, "ledger-task9-production.csv"))
        self.assertEqual([(r["rule_id"], r["head_sha"]) for r in prod_ledger], [("S1-HOST-MISMATCH", "d" * 40)])
        self.assertIn("#1", prod_ledger[0]["notes"])
        # B's verdicts survive a second pre-fill.
        gate[0].update(verdict="true_regression", verified_by="SurendharVr")
        prod_ledger[0].update(verdict="true_regression", verified_by="SurendharVr")
        t9.write_csv(os.path.join(data, "ledger-task9.csv"), t9.verify_helper.FIELDS, gate)
        t9.write_csv(os.path.join(data, "ledger-task9-production.csv"), t9.verify_helper.FIELDS, prod_ledger)
        t9.cmd_ledger(argparse.Namespace(data=data, second_look=False))
        self.assertEqual(t9.read_csv(os.path.join(data, "ledger-task9.csv"))[0]["verdict"], "true_regression")

        t9.cmd_report(argparse.Namespace(data=data, repos=os.path.join(self.d, "no-repos.json")))
        with open(os.path.join(data, "summary.md"), encoding="utf-8") as fh:
            md = fh.read()
        self.assertIn("| Blocking precision | 1 of 1 (100.0%) | 1 of 1 (100.0%) |", md)
        self.assertIn("| Frequency (per PR by people) | 1 of 1 (100.0%) |", md)
        self.assertIn("| o/r | 1 | 1 | 1 | 1 | 0 |", md)
        self.assertIn("- Without o/r, the site with the most PRs compared:", md)
        self.assertIn("fewer than 20, so the window is extended", md)
        self.assertIn("1 from production audits, 1 true_regression", md)
        self.assertIn("Soft 404s** (S1-SOFT-404 at high): 0 gate finding(s)", md)
        self.assertIn("rule-of-three upper bound 3 / 1 PRs checked in url mode", md)
        # The leak was not blocked on PR #1 by the gate: a miss.
        self.assertIn("1 true_regression finding(s) from production audits on PRs the gate passed", md)

        # Addendum 2, part 3: the preview-host measure again without the sites whose
        # production is on a per-deploy host.
        repos = os.path.join(self.d, "repos.json")
        t9.write_json(repos, [{"repo": "o/r", "homepage": "https://o-r.vercel.app"}])
        t9.cmd_report(argparse.Namespace(data=data, repos=repos))
        with open(os.path.join(data, "summary.md"), encoding="utf-8") as fh:
            md = fh.read()
        self.assertIn("- Without the 1 site(s) whose production is on a preview platform's host (o/r): "
                      "0 gate finding(s), 0 from production audits, 0 true_regression; "
                      "upper bound 3 / 0 merged PRs = n/a.", md)

        # Addendum 4, part 7: each frame's sites beside the pooled figures.
        t9.write_json(repos, [{"repo": "o/r", "homepage": "https://o.test", "frame": 2},
                              {"repo": "q/s", "homepage": "https://q.test", "frame": 1}])
        t9.cmd_report(argparse.Namespace(data=data, repos=repos))
        with open(os.path.join(data, "summary.md"), encoding="utf-8") as fh:
            md = fh.read()
        self.assertIn("- Frame 1 sites (1): precision 0 of 0 (n/a); frequency 0 of 0 (n/a)", md)
        self.assertIn("- Frame 2 sites (1): precision 1 of 1 (100.0%); frequency 1 of 1 (100.0%)", md)

        t9.cmd_ledger(argparse.Namespace(data=data, second_look=True))
        look = t9.read_csv(os.path.join(data, "second-look.csv"))
        self.assertEqual(len(look), round(0.2 * 2))
        self.assertTrue(all(not r["verdict"] for r in look), "the first verdict must not be shown")

    def _zip(self, files):
        import io
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for name, doc in files.items():
                z.writestr(name, json.dumps(doc))
        return buf.getvalue()

    def test_collect_reads_only_each_jobs_own_artifact(self):
        """SECURITY: a check artifact is a zip a stranger's build could fill. Only the
        job's own result-<id>.json in task9-result-<id> is read, and only if it describes
        the job the poll gave that id; nothing in a zip is extracted. A result is filed
        once, even if its run is still going."""
        t9, data = self.t9, os.path.join(self.d, "data")
        h = "1" * 40
        jobs = [{"id": "0-o__r", "kind": "folder", "repo": "o/r", "pr": 1, "head": h, "base": "b" * 40, "url": ""},
                {"id": "1-o__r", "kind": "folder", "repo": "o/r", "pr": 2, "head": "2" * 40, "base": "b" * 40, "url": ""}]
        state = {"prs": {"o/r#1": {"repo": "o/r", "number": 1, "heads": {h: {"folder": None}}},
                         "o/r#2": {"repo": "o/r", "number": 2, "heads": {"2" * 40: {"folder": None}}}}}
        good = {"job": jobs[0], "outcome": "fail", "reason": "", "regressions": [], "advisory": [],
                "checked_at": "2026-10-25T00:00:00Z"}
        blobs = {1: self._zip({"jobs.json": jobs}),
                 # Job 0's own result, plus a planted result for job 1 and a path outside.
                 2: self._zip({"result-0-o__r.json": good,
                               "result-1-o__r.json": dict(good, job=jobs[1], outcome="pass"),
                               "../../state.json": {"prs": {}}}),
                 # Job 1's artifact claims to be about another PR.
                 3: self._zip({"result-1-o__r.json": dict(good, job=dict(jobs[1], pr=7))})}
        api = {"repos/me/t/actions/workflows/task9.yml/runs": {"workflow_runs": [{"id": 9}]},
               "repos/me/t/actions/runs/9/artifacts?per_page=100": {"artifacts": [
                   {"id": 1, "name": "task9-plan"}, {"id": 2, "name": "task9-result-0-o__r"},
                   {"id": 3, "name": "task9-result-1-o__r"}]}}
        get = lambda path: api.get(path.split("?created")[0], api.get(path))
        state, results, rejected = t9.collect_new(state, data, self.at(days=1), get, blobs.get, repo="me/t")
        self.assertEqual([r["job"]["id"] for r in results], ["0-o__r"])
        self.assertEqual(rejected, ["9/1-o__r"])
        self.assertEqual(state["prs"]["o/r#1"]["heads"][h]["folder"], "fail")
        self.assertIsNone(state["prs"]["o/r#2"]["heads"]["2" * 40]["folder"])
        self.assertFalse(os.path.exists(os.path.join(self.d, "state.json")))
        _, again, _ = t9.collect_new(state, data, self.at(days=1), get, blobs.get, repo="me/t")
        self.assertEqual(again, [], "an artifact is filed once")

    def test_only_a_preview_deployment_counts_as_a_preview(self):
        """REGRESSION from the Task 9 draw: rtl-buddy was flagged with a preview at
        https://pypi.org/p/rtl_buddy, a release deployment. A GitHub Pages deployment (the
        live site) would have been crawled as the PR's preview and compared with itself."""
        t9, sha = self.t9, "a" * 40

        def found(env, url, home="https://site.example"):
            api = {"repos/o/r/deployments?sha={0}&per_page=20".format(sha): [{"id": 1, "environment": env}],
                   "repos/o/r/deployments/1/statuses?per_page=20": [{"state": "success", "environment_url": url}]}
            return t9.preview_url(api.get, "o/r", sha, home=home)
        self.assertIsNone(found("pypi", "https://pypi.org/p/rtl_buddy"))
        self.assertIsNone(found("github-pages", "https://o.github.io/r/"))
        self.assertIsNone(found("Production – sywyke", "https://sywyke.vercel.app"))
        self.assertIsNone(found("staging", "https://site.example/"), "the production host is never a preview")
        self.assertIsNone(found("Preview", "https://sywyke.vercel.app", home="https://sywyke.vercel.app"))
        self.assertEqual(found("Preview – sywyke", "https://sywyke-abc123.vercel.app"), "https://sywyke-abc123.vercel.app")
        self.assertEqual(found("deploy", "https://deploy-preview-7--x.netlify.app"), "https://deploy-preview-7--x.netlify.app")
        # Commit statuses follow the same rule.
        api = {"repos/o/r/commits/{0}/statuses?per_page=100".format(sha): [
            {"state": "success", "context": "release/deploy", "target_url": "https://pypi.org/p/x"},
            {"state": "success", "context": "netlify/x/deploy-preview", "target_url": "https://deploy-preview-7--x.netlify.app"}]}
        self.assertEqual(t9.preview_url(api.get, "o/r", sha), "https://deploy-preview-7--x.netlify.app")

    def test_a_preview_url_must_be_public_https(self):
        """SECURITY: preview URLs come from deployments, statuses and comments strangers
        control; an internal address must never be crawled and committed."""
        ok = self.real_public_https
        for url in ("http://x.vercel.app/", "https://169.254.169.254/latest/", "https://10.0.0.5/",
                    "https://[::1]/", "https://localhost/", "https://db.internal/", "", None):
            self.assertFalse(ok(url), url)
        api = {"repos/o/r/deployments?sha={0}&per_page=20".format("a" * 40): [{"id": 1, "environment": "Preview"}],
               "repos/o/r/deployments/1/statuses?per_page=20": [{"state": "success",
                                                                 "environment_url": "http://169.254.169.254/"}]}
        self.assertIsNone(self.t9.preview_url(api.get, "o/r", "a" * 40, ok=ok))

    def test_a_failing_production_audit_is_tried_three_times_per_branch_state(self):
        t9 = self.t9
        repos = [{"repo": "o/r", "default_branch": "main", "homepage": "https://o.test"}]
        commits = [{"sha": "c" * 40, "commit": {"committer": {"date": "2026-10-25T09:00:00Z"}}}]
        state, scheduled = {}, 0
        for i in range(5):        # no result ever comes back: collect never records an audit
            state, jobs = t9.plan(state, repos, self.at(), self.at(days=56), self.at(days=1, minutes=300 * i),
                                  get=self._api([], commits), hash_home=lambda u: "h")
            scheduled += sum(j["kind"] == "production" for j in jobs)
        self.assertEqual(scheduled, 3)
        commits = [{"sha": "d" * 40, "commit": {"committer": {"date": "2026-10-26T09:00:00Z"}}}] + commits
        _, jobs = t9.plan(state, repos, self.at(), self.at(days=56), self.at(days=3),
                          get=self._api([], commits), hash_home=lambda u: "h")
        self.assertEqual([j["kind"] for j in jobs], ["production"], "a new branch state is tried again")

    def test_only_checked_non_draft_final_heads_are_counted(self):
        """3.2: a PR counts when its final head was not a draft and was checked. One closed
        as a draft, or whose check has not reported yet, is not in any denominator."""
        t9 = self.t9
        heads = lambda **h: {"f" * 40: dict({"folder": None, "url": None, "draft": False}, **h)}
        state = {"prs": {"o/r#1": {"repo": "o/r", "number": 1, "final_head": "f" * 40, "heads": heads(folder="pass")},
                         "o/r#2": {"repo": "o/r", "number": 2, "final_head": "f" * 40, "heads": heads(draft=True)},
                         "o/r#3": {"repo": "o/r", "number": 3, "final_head": "f" * 40, "heads": heads()},
                         "o/r#4": {"repo": "o/r", "number": 4, "final_head": "f" * 40,
                                   "heads": heads(folder="tool_failure", url="preview_unavailable")}}}
        self.assertEqual([(r["number"], m, o) for r, _, m, o in t9.counted(state)],
                         [(1, "folder", "pass"), (4, "folder", "tool_failure"), (4, "url", "preview_unavailable")])
        m = t9.measures(state, [], "folder")
        self.assertEqual((m["prs"], m["compared"], m["tool"]), (2, 1, 1))

    def test_an_extended_window_follows_prs_the_old_end_froze(self):
        """3.1: the extended close is the window's close. A PR still open at the first end
        had its head taken then; once the window is extended it is followed again, and the
        head it has at the new close is the one that counts."""
        t9 = self.t9
        repos = [{"repo": "o/r", "default_branch": "main", "homepage": "https://o.test"}]
        h1, h2 = "1" * 40, "2" * 40
        pulls = [self._pr(5, h1, "2026-10-25T10:00:00Z")]
        old_end, new_end = self.at(days=56), self.at(days=84)
        state, _ = t9.plan({}, repos, self.at(), old_end, self.at(days=57),
                           get=self._api(pulls), hash_home=lambda u: "h")
        self.assertEqual(state["prs"]["o/r#5"]["final_head"], h1)
        pulls = [self._pr(5, h2, "2026-10-25T10:00:00Z")]
        state, jobs = t9.plan(state, repos, self.at(), new_end, self.at(days=58),
                              get=self._api(pulls), hash_home=lambda u: "h")
        self.assertIsNone(state["prs"]["o/r#5"].get("final_head"))
        self.assertIn(("folder", h2), [(j["kind"], j.get("head")) for j in jobs])
        # A PR that closed stays final: an extension only reopens the ones the end froze.
        pulls = [self._pr(5, h2, "2026-10-25T10:00:00Z", state="closed", merged_at="2026-12-01T00:00:00Z")]
        state, _ = t9.plan(state, repos, self.at(), new_end, self.at(days=59), get=self._api(pulls), hash_home=lambda u: "h")
        self.assertEqual((state["prs"]["o/r#5"]["final_head"], state["prs"]["o/r#5"].get("final_by")), (h2, None))

    def test_a_check_job_outlasts_a_folder_checks_worst_case(self):
        try:
            import yaml
        except ImportError:
            raise unittest.SkipTest("pyyaml not installed")
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".github", "workflows", "task9.yml")
        with open(path, encoding="utf-8") as fh:
            job = yaml.safe_load(fh)["jobs"]["check"]
        worst = (2 * self.t9.BUILD_TIMEOUT + 2 * self.t9.AUDIT_TIMEOUT) / 60
        self.assertGreater(job["timeout-minutes"], worst)
        self.assertNotIn("merge-multiple", open(path, encoding="utf-8").read())
        # A poll never waits for checks: only the poll job is in the concurrency group.
        with open(path, encoding="utf-8") as fh:
            doc = yaml.safe_load(fh)
        self.assertNotIn("concurrency", doc)
        self.assertNotIn("concurrency", job)
        self.assertEqual(doc["jobs"]["poll"]["concurrency"]["group"], "task9-poll")

    def test_a_head_without_a_preview_is_looked_at_less_often(self):
        """A preview appears within minutes of a push. On a head that has none, plan looks
        on every poll for its first hour, then once an hour, and once more when it is final."""
        t9 = self.t9
        repos = [{"repo": "o/r", "default_branch": "main", "homepage": "https://o.test"}]
        h = "1" * 40
        looks = []
        base = self._api([self._pr(5, h, "2026-10-25T10:00:00Z")])

        def get(path):
            if "/commits/{0}/statuses".format(h) in path:
                looks.append(path)
            return base(path)
        state = {}
        for i in range(12):                       # 3 hours of 15-minute polls
            state, _ = t9.plan(state, repos, self.at(), self.at(days=56), self.at(days=1, minutes=15 * i),
                               get=get, hash_home=lambda u: "h")
            state["prs"]["o/r#5"]["heads"][h]["folder"] = "pass"
        self.assertEqual(len(looks), 4 + 2)          # every poll of the first hour, then hourly
        closed = self._api([self._pr(5, h, "2026-10-25T10:00:00Z", state="closed", merged_at="2026-10-25T14:00:00Z")])

        def get_closed(path):
            if "/commits/{0}/statuses".format(h) in path:
                looks.append(path)
            return closed(path)
        state, _ = t9.plan(state, repos, self.at(), self.at(days=56), self.at(days=1, minutes=185),
                           get=get_closed, hash_home=lambda u: "h")
        self.assertEqual(len(looks), 7, "the final head is looked at once more")
        self.assertEqual(state["prs"]["o/r#5"]["heads"][h]["url"], "preview_unavailable")

    def test_production_changes_are_the_branch_head_moving(self):
        """A fast-forward merge can keep commit dates older than the last audit. Production
        is audited again when the branch head moves, 2 hours after a poll first saw it."""
        t9 = self.t9
        repos = [{"repo": "o/r", "default_branch": "main", "homepage": "https://o.test"}]
        old = {"sha": "a" * 40, "commit": {"committer": {"date": "2026-01-01T00:00:00Z"}}}
        state = {"production": {"o/r": {"audited_at": "2026-10-25T00:00:00Z", "home_hash": "h",
                                        "branch_sha": "a" * 40, "findings": "x"}}}
        _, jobs = t9.plan(state, repos, self.at(), self.at(days=56), self.at(days=2),
                          get=self._api([], [old]), hash_home=lambda u: "h")
        self.assertEqual(jobs, [], "the head has not moved")
        moved = dict(old, sha="b" * 40)            # dated long before the last audit
        state, jobs = t9.plan(state, repos, self.at(), self.at(days=56), self.at(days=2),
                              get=self._api([], [moved]), hash_home=lambda u: "h")
        self.assertEqual(jobs, [])
        _, jobs = t9.plan(state, repos, self.at(), self.at(days=56), self.at(days=2, minutes=120),
                          get=self._api([], [moved]), hash_home=lambda u: "h")
        self.assertEqual([(j["kind"], j["branch_sha"]) for j in jobs], [("production", "b" * 40)])

    def test_a_production_audit_with_nothing_new_writes_no_new_file(self):
        t9, data = self.t9, os.path.join(self.d, "data")
        job = {"repo": "o/r", "kind": "production", "url": "https://o.test", "branch_sha": "c" * 40}
        res = lambda outcome, regressions, at: {"job": job, "outcome": outcome, "reason": "", "regressions": regressions,
                                                "findings": [], "home_hash": "h", "checked_at": at}
        state = t9.collect({"prs": {}, "production": {}}, [res("first", [], "2026-10-25T00:00:00Z"),
                                                          res("compared", [], "2026-10-25T03:00:00Z")], data)
        self.assertEqual(glob.glob(os.path.join(data, "production", "o__r", "*-new.json")), [])
        self.assertEqual(state["production"]["o/r"]["branch_sha"], "c" * 40)
        f = {"id": "S1-HOST-MISMATCH", "severity": "critical", "pages": ["/"], "evidence": "e"}
        t9.collect(state, [res("compared", [f], "2026-10-25T06:00:00Z")], data)
        self.assertEqual(len(glob.glob(os.path.join(data, "production", "o__r", "*-new.json"))), 1)

    def test_a_later_merge_does_not_restart_productions_wait(self):
        t9 = self.t9
        repos = [{"repo": "o/r", "default_branch": "main", "homepage": "https://o.test"}]
        c = lambda sha: [{"sha": sha * 40, "commit": {"committer": {"date": "2026-10-25T00:00:00Z"}}}]
        state = {"production": {"o/r": {"audited_at": "2026-10-25T00:00:00Z", "home_hash": "h",
                                        "branch_sha": "a" * 40, "findings": "x"}}}
        state, _ = t9.plan(state, repos, self.at(), self.at(days=56), self.at(days=2),
                           get=self._api([], c("b")), hash_home=lambda u: "h")
        state, jobs = t9.plan(state, repos, self.at(), self.at(days=56), self.at(days=2, minutes=90),
                              get=self._api([], c("d")), hash_home=lambda u: "h")
        self.assertEqual(jobs, [])
        _, jobs = t9.plan(state, repos, self.at(), self.at(days=56), self.at(days=2, minutes=120),
                          get=self._api([], c("e")), hash_home=lambda u: "h")
        self.assertEqual([j["branch_sha"] for j in jobs], ["e" * 40], "2 hours from the first merge seen")

    def test_the_home_page_fingerprint_ignores_per_request_tokens(self):
        f = self.t9.home_fingerprint
        page = '<title>T</title><script nonce="{0}">t={1}</script><link href="/app.{2}.css"><p>{1}</p>'
        self.assertEqual(f(page.format("n1", "10:01", "a1")), f(page.format("n2", "10:02", "a1")))
        self.assertNotEqual(f(page.format("n1", "10:01", "a1")), f(page.format("n1", "10:01", "b2")))

    def test_a_merge_just_before_the_end_is_still_audited(self):
        """3.4 covers every merge in the window: one seen before the end is audited after
        it, once its 2 hours are up; one first seen after the end is not."""
        t9 = self.t9
        repos = [{"repo": "o/r", "default_branch": "main", "homepage": "https://o.test"}]
        ends = self.at(days=56)
        c = lambda sha: [{"sha": sha * 40, "commit": {"committer": {"date": "2026-10-25T00:00:00Z"}}}]
        base = {"production": {"o/r": {"audited_at": "2026-10-25T00:00:00Z", "home_hash": "h",
                                       "branch_sha": "a" * 40, "findings": "x"}}}
        state, _ = t9.plan(base, repos, self.at(), ends, self.at(days=56, minutes=-30),
                           get=self._api([], c("b")), hash_home=lambda u: "h")
        _, jobs = t9.plan(state, repos, self.at(), ends, self.at(days=56, minutes=90),
                          get=self._api([], c("b")), hash_home=lambda u: "h")
        self.assertEqual([j["kind"] for j in jobs], ["production"])
        _, jobs = t9.plan(base, repos, self.at(), ends, self.at(days=56, minutes=200),
                          get=self._api([], c("b")), hash_home=lambda u: "h")
        self.assertEqual(jobs, [], "a change first seen after the end is not audited")

    def test_select_takes_every_one_that_built_when_fewer_than_30_did(self):
        t9, out = self.t9, os.path.join(self.d, "draw")
        cands = [{"repo": "{0}/r{1}".format(s, i), "stack": s, "rank": i, "preview": "",
                  "homepage": "http://{0}{1}.example".format(s, i)}
                 for s, _, _, _ in t9.sample.STACKS for i in range(1, 7)]
        t9.write_json(os.path.join(out, "candidates.json"), cands)
        builds = os.path.join(out, "builds.csv")
        t9.write_csv(builds, ["repo", "status"], [{"repo": c["repo"], "status": "build_failed" if c["repo"] == "hugo/r3" else "ok"}
                                                  for c in cands])
        # Addendum 3: with every frame read to its end, the sample is every one that built.
        self.assertEqual(t9.cmd_select(argparse.Namespace(builds=[builds], out=out)), 0)
        self.assertEqual(len(t9.read_json(os.path.join(out, "repos.json"))), 29)
        os.remove(os.path.join(out, "repos.json"))
        t9.write_csv(builds, ["repo", "status"], [{"repo": c["repo"], "status": "build_failed"} for c in cands])
        self.assertEqual(t9.cmd_select(argparse.Namespace(builds=[builds], out=out)), 1)
        self.assertFalse(os.path.exists(os.path.join(out, "repos.json")), "nothing built: nothing written")
        t9.write_csv(builds, ["repo", "status"], [{"repo": c["repo"], "status": "ok"} for c in cands])
        self.assertEqual(t9.cmd_select(argparse.Namespace(builds=[builds], out=out)), 0)
        taken = t9.read_json(os.path.join(out, "repos.json"))
        self.assertEqual(len(taken), 30)
        # Addendum 2, part 4: the production URL is the https form the build check read.
        self.assertTrue(all(e["homepage"].startswith("https://") for e in taken))

    def test_short_stacks_are_filled_from_the_others_in_draw_order(self):
        """Addendum 2, part 1, on the draw's own shape: Hugo has none, VitePress and
        Next.js 4 each. Every one that built is taken, the places left up to 30 come from
        Docusaurus and Astro one at a time in draw order, then the preview top-up."""
        t9 = self.t9
        sizes = {"docusaurus": 12, "astro": 12, "vitepress": 4, "hugo": 0, "nextjs": 4}
        cands = [{"repo": "{0}/r{1}".format(s, i), "stack": s, "rank": i,
                  "preview": "https://p" if (s, i) in {("astro", 12), ("docusaurus", 12)} else ""}
                 for s, n in sizes.items() for i in range(1, n + 1)]
        built = {c["repo"]: "build_failed" if c["repo"] == "vitepress/r2" else "ok" for c in cands}
        taken, short = t9.select(cands, built)
        self.assertEqual(sorted(short), ["hugo", "nextjs", "vitepress"])
        repos = [c["repo"] for c in taken]
        self.assertEqual(len([r for r in repos if r.startswith(("vitepress", "nextjs"))]), 3 + 4)
        # 6 + 6 + 3 + 0 + 4 = 19; 11 more alternate from rank 7: D7, A7, D8, A8, ..., D12.
        self.assertEqual(repos[19:30], ["docusaurus/r7", "astro/r7", "docusaurus/r8", "astro/r8",
                                        "docusaurus/r9", "astro/r9", "docusaurus/r10", "astro/r10",
                                        "docusaurus/r11", "astro/r11", "docusaurus/r12"])
        # Only 1 flagged among the 30: the top-up takes the next flagged one, astro/r12.
        self.assertEqual(repos[30:], ["astro/r12"])

    def test_a_repository_sharing_an_owner_with_the_benchmark_is_excluded(self):
        """Addendum 2, part 2: vuejs-translations/docs-ja is the twin of docs-zh-cn, one of
        the 15 benchmark repositories."""
        why = self.t9.exclusion
        owners = self.t9.benchmark_owners()
        self.assertIn("vuejs-translations", owners)
        self.assertIn("benchmark repository", why("vuejs-translations/docs-ja", set(), owners))
        self.assertIn("B's own", why("SurendharVr/x", set(), owners))
        self.assertIn("the sweep", why("o/swept", {"o/swept"}, owners))
        self.assertIsNone(why("honojs/website", set(), owners))

    def test_the_second_frame_splits_each_search_below_the_cap(self):
        """Addendum 4, part 2, with Task 9 Addendum 5: slices start at 0..1000, 1001..3000,
        3001..10000 and 10001..384000; one with a total_count of 1,000 or more is halved; a
        one-byte slice still at the cap keeps what GitHub returns and is marked capped."""
        from urllib.parse import unquote
        # 3,000 untouched starter configs of exactly 500 bytes, 1,500 spread over 1001..3000,
        # 200 in 3001..10000 and 50 large ones.
        files = ([500] * 3000 + [1001 + i % 2000 for i in range(1500)] + [5000] * 200 + [50000] * 50)
        files = [(size, "o/r{0}".format(n)) for n, size in enumerate(files)]
        calls = []

        def get(path):
            q = unquote(path.split("q=")[1].split("&")[0])
            lo, hi = (int(x) for x in q.rsplit("size:", 1)[1].split(".."))
            page = int(path.rsplit("page=", 1)[1])
            calls.append((lo, hi, page))
            hits = [r for size, r in files if lo <= size <= hi]
            got = hits[(page - 1) * 100:page * 100] if page <= 10 else []
            return {"total_count": len(hits), "incomplete_results": False,
                    "items": [{"repository": {"full_name": r}, "path": "docusaurus.config.js"} for r in got]}
        items, slices = self.t9.search_slices(get, "filename:docusaurus.config")
        self.assertEqual(max(r["hi"] for r in slices), 384000, "the open range has an upper end")
        capped = [(r["lo"], r["hi"]) for r in slices if r["capped"]]
        self.assertEqual(capped, [(500, 500)])
        self.assertTrue(all(r["split"] for r in slices if r["total_count"] >= 1000 and r["lo"] < r["hi"]))
        self.assertTrue(all(r["total_count"] < 1000 for r in slices if not r["split"] and not r["capped"]))
        self.assertEqual(len(items), 1000 + 1500 + 200 + 50, "every uncapped slice is read whole")
        self.assertEqual(len({i["repo"] for i in items if i["slice"] == "500..500"}), 1000)
        self.assertTrue(all(page <= 10 for _, _, page in calls))

    def test_the_second_draw_leaves_out_the_first_frame(self):
        t9 = self.t9
        frame = {"a/one": "x", "B/Two": "x", "c/three": "x", "d/four": "x"}
        order = t9.frame2_order(frame, {"b/two", "z/other"})
        self.assertNotIn("B/Two", order)
        self.assertEqual(order, t9.sample.draw_order(["a/one", "c/three", "d/four"]))

    def test_a_widened_sample_keeps_the_16_and_adds_new_sites_by_stack(self):
        """Addendum 4, part 4: all 16 stay (Astro has 8); new candidates fill each stack up
        to 6 counting the 16, then 30, then the preview top-up from new ones only."""
        t9 = self.t9
        keep = ([{"repo": "d/k{0}".format(i), "stack": "docusaurus", "rank": i, "preview": ""} for i in range(6)]
                + [{"repo": "a/k{0}".format(i), "stack": "astro", "rank": i, "preview": "https://p" if i < 3 else ""}
                   for i in range(8)]
                + [{"repo": "v/k0", "stack": "vitepress", "rank": 0, "preview": ""},
                   {"repo": "n/k0", "stack": "nextjs", "rank": 0, "preview": "https://p"}])
        sizes = {"docusaurus": 5, "astro": 5, "vitepress": 4, "hugo": 3, "nextjs": 6}
        cands = [{"repo": "{0}/n{1}".format(s[0], i), "stack": s, "rank": i,
                  "preview": "https://p" if (s, i) in {("docusaurus", 2), ("astro", 1), ("nextjs", 5)} else ""}
                 for s, n in sizes.items() for i in range(1, n + 1)]
        built = {c["repo"]: "ok" for c in cands}
        taken = t9.select_widened(keep, cands, built)
        repos = [c["repo"] for c in taken]
        self.assertEqual(repos[:16], [c["repo"] for c in keep], "the 16 come first and stay")
        self.assertTrue(all(c["frame"] == 1 for c in taken[:16]) and all(c["frame"] == 2 for c in taken[16:]))
        # Room: VitePress 5 (4 there), Hugo 6 (3 there), Next.js 5 of 6: 12 new, 28 in all.
        self.assertEqual(repos[16:28], ["v/n1", "v/n2", "v/n3", "v/n4", "h/n1", "h/n2", "h/n3",
                                        "n/n1", "n/n2", "n/n3", "n/n4", "n/n5"])
        self.assertEqual(repos[28:30], ["d/n1", "a/n1"], "the fill takes the next new ones, one stack at a time")
        # Flagged so far: 3 kept Astro, 1 kept Next.js, n/n5 (per stack) and a/n1 (fill): 6.
        # The top-up takes the one flagged new candidate left, d/n2, and stops there.
        self.assertEqual(repos[30:], ["d/n2"])
        self.assertEqual(len(set(repos)), len(repos))

    def test_the_workflow_keeps_strangers_code_away_from_tokens(self):
        """SECURITY: check builds drawn repositories' PRs and crawls their previews, code
        and content strangers wrote. It must get no secret, no write permission and no saved
        credentials; only collect, which runs this repository's code, may write."""
        try:
            import yaml
        except ImportError:
            raise unittest.SkipTest("pyyaml not installed")
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".github", "workflows", "task9.yml")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        jobs = yaml.safe_load(text)["jobs"]
        self.assertEqual(yaml.safe_load(text)["permissions"], {"contents": "read"})
        writers = [n for n, j in jobs.items() if (j.get("permissions") or {}).get("contents") == "write"]
        self.assertEqual(writers, ["poll"])
        for name in ("check", "build-check"):
            job = jobs[name]
            self.assertNotIn("secrets.", json.dumps(job), name)
            self.assertNotIn("github.token", json.dumps(job), name)
            for step in job["steps"]:
                if "actions/checkout" in step.get("uses", ""):
                    self.assertIs(step["with"]["persist-credentials"], False, name)

    def test_thresholds_count_prs_by_people_and_precision_every_finding(self):
        """Addendum 3, part 4: frequency and tool failures count PRs by people; all PRs and
        bot PRs are given beside them. Precision counts every blocking finding, a bot PR's
        included."""
        t9 = self.t9
        head = lambda c: c * 40
        pr = lambda n, bot, out: {"repo": "o/r", "number": n, "bot": bot, "final_head": head(str(n)),
                                  "heads": {head(str(n)): {"folder": out, "url": None, "draft": False}}}
        state = {"prs": {"o/r#1": pr(1, False, "fail"), "o/r#2": pr(2, False, "pass"),
                         "o/r#3": pr(3, True, "fail"), "o/r#4": pr(4, True, "tool_failure")}}
        row = lambda n, verdict: {"repo": "o/r", "head_sha": head(str(n)), "rule_id": "S1-BROKEN-LINK",
                                  "verdict": verdict, "notes": "mode: folder"}
        ledger = [row(1, "true_regression"), row(3, "false_positive")]
        people, everyone, bots = (t9.measures(state, ledger, "folder", b) for b in (False, None, True))
        self.assertEqual((people["hit"], people["compared"], people["tool"], people["prs"]), (1, 2, 0, 2))
        self.assertEqual((everyone["hit"], everyone["compared"], everyone["tool"], everyone["prs"]), (1, 3, 1, 4))
        self.assertEqual((bots["hit"], bots["compared"], bots["tool"], bots["prs"]), (0, 1, 1, 2))
        self.assertEqual((people["true"], people["judged"]), (1, 2), "precision counts the bot PR's finding too")
        self.assertEqual(t9.measures(state, ledger, "folder", False, skip=("o/r",))["prs"], 0)

    def test_decision_rules_follow_section_6(self):
        d = self.t9.decide
        base = {"findings": 40, "judged": 40, "true": 39, "compared": 500, "hit": 10, "prs": 520, "tool": 10}
        self.assertIn("all met", d(base, False))
        self.assertIn("precision not met", d(dict(base, true=37), False))
        self.assertIn("frequency not met", d(dict(base, hit=4), False))
        self.assertIn("tool failures", d(dict(base, tool=30), False))
        self.assertIn("extend", d(dict(base, findings=12, judged=12, true=12), False))
        self.assertIn("precision not met", d(dict(base, findings=12, judged=12, true=12), True))

    # ------------------------------------------------------------ one check, end to end

    def test_a_folder_check_builds_the_pr_and_its_base(self):
        """3.3, folder mode, on a throwaway repository: the PR head adds a broken link, its
        base does not, so the gate fails with that one regression. The PR head is fetched
        as refs/pull/N/head, as GitHub serves it."""
        if not shutil.which("git"):
            raise unittest.SkipTest("git not available")
        src = os.path.join(self.d, "src")
        os.makedirs(os.path.join(src, "src"))

        def git(*args):
            return subprocess.run(["git"] + list(args), cwd=src, check=True, capture_output=True, text=True,
                                  env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.test",
                                           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.test")).stdout.strip()
        git("init", "-q", "-b", "main")
        git("config", "commit.gpgsign", "false")
        git("config", "uploadpack.allowAnySHA1InWant", "true")
        page = lambda link="": page_html(body="<h1>H</h1><p>" + link + "word " * 300 + "</p>")
        with open(os.path.join(src, "build.py"), "w", encoding="utf-8") as fh:
            fh.write("import shutil\nshutil.copytree('src', 'out')\n")
        with open(os.path.join(src, "src", "index.html"), "w", encoding="utf-8") as fh:
            fh.write(page())
        git("add", "-A")
        git("commit", "-q", "-m", "base")
        base = git("rev-parse", "HEAD")
        git("checkout", "-q", "-b", "pr")
        with open(os.path.join(src, "src", "index.html"), "w", encoding="utf-8") as fh:
            fh.write(page('<a href="/gone/">x</a> '))
        git("commit", "-q", "-am", "head")
        head = git("rev-parse", "HEAD")
        git("update-ref", "refs/pull/3/head", head)
        git("checkout", "-q", "main")
        git("branch", "-D", "pr")
        entry = {"repo": "t/site", "url": src, "site_dir": "out",
                 "build_command": '"{0}" build.py'.format(sys.executable), "homepage": "https://t.test"}
        work = os.path.join(self.d, "work")
        os.makedirs(work)
        job = {"kind": "folder", "repo": "t/site", "pr": 3, "head": head, "base": base, "url": ""}
        res = self.t9.run_job(job, self.d, work, sitemend.HERE, dict(os.environ, PYTHONIOENCODING="utf-8"), [entry])
        self.assertEqual(res["outcome"], "fail", res["reason"])
        self.assertEqual([f["id"] for f in res["regressions"]], ["S1-BROKEN-LINK"])

    def test_a_url_check_compares_the_preview_with_production(self):
        """3.3, url mode, with two local servers standing in for a preview and production.
        A preview that does not answer 200 is preview_unavailable, never a pass or a fail."""
        try:
            import requests  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("requests not installed (http mode is optional)")
        import functools
        import http.server
        import threading

        def serve(files):
            root = tempfile.mkdtemp(dir=self.d)
            for name, text in files.items():
                with open(os.path.join(root, name), "w", encoding="utf-8") as fh:
                    fh.write(text)
            srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(
                http.server.SimpleHTTPRequestHandler, directory=root))
            srv.RequestHandlerClass.log_message = lambda *a, **k: None
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            self.addCleanup(srv.server_close)
            self.addCleanup(srv.shutdown)
            return "http://127.0.0.1:%d/" % srv.server_address[1]
        body = "<h1>H</h1><p>" + "word " * 300 + "</p>"
        prod = serve({"index.html": page_html(body=body)})
        preview = serve({"index.html": page_html(body='<h1>H</h1><p><a href="/gone/">x</a> ' + "word " * 300 + "</p>")})
        entry = {"repo": "t/site", "homepage": prod}
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        job = {"kind": "url", "repo": "t/site", "pr": 3, "head": "h" * 40, "base": "b" * 40, "url": preview}
        res = self.t9.run_job(job, self.d, os.path.join(self.d, "w1"), sitemend.HERE, env, [entry])
        self.assertEqual(res["outcome"], "fail", res["reason"])
        self.assertIn("S1-BROKEN-LINK", [f["id"] for f in res["regressions"]])
        res = self.t9.run_job(dict(job, url=preview + "missing/"), self.d, os.path.join(self.d, "w2"),
                              sitemend.HERE, env, [entry])
        self.assertEqual(res["outcome"], "preview_unavailable")


def _bench_module(*parts):
    """Load a bench/ script as a module; None when bench/ is absent (the sdist)."""
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bench", *parts)
    if not os.path.isfile(path):
        return None
    spec = importlib.util.spec_from_file_location(parts[-1][:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestSampling(unittest.TestCase):
    """bench/sample/sample.py draws the replay sample by Addendum 5's rules, so that anyone
    can rerun it from the saved frame and get the same repositories."""

    def setUp(self):
        self.S = _bench_module("sample", "sample.py")
        if self.S is None:
            raise unittest.SkipTest("bench/ is not shipped in the sdist")

    def test_frame_keeps_each_repositorys_shallowest_matching_config(self):
        items = [{"repo": "o/a", "path": "docs/docusaurus.config.js"},
                 {"repo": "o/a", "path": "docusaurus.config.ts"},
                 {"repo": "o/b", "path": "x/docusaurus.config.backup.js"},
                 {"repo": "o/c", "path": "site/docusaurus.config.mts"}]
        pattern = self.S.STACKS[0][2]
        self.assertEqual(self.S.reduce_frame(items, pattern),
                         {"o/a": "docusaurus.config.ts", "o/c": "site/docusaurus.config.mts"})

    def _fake_gh(self, answers):
        """sample.gh against scripted gh answers, a throwaway cache and no sleeping.
        answers: (returncode, stdout, stderr) per call, in order."""
        S, calls, waits = self.S, [], []
        d = tempfile.mkdtemp(prefix="sitemend-gh-")
        self.addCleanup(shutil.rmtree, d, True)
        S.HERE = d

        def run(cmd, **kw):
            calls.append(cmd)
            code, out, err = answers[min(len(calls), len(answers)) - 1]
            return subprocess.CompletedProcess(cmd, code, out, err)
        S.subprocess = type("P", (), {"run": staticmethod(run)})
        S.time = type("T", (), {"sleep": staticmethod(waits.append)})
        return calls, waits

    def test_a_failed_request_is_retried_and_never_cached(self):
        """REGRESSION from the Task 9 draw: a burst of secondary rate limits was cached as
        an empty answer, marking 26 public repositories "not readable" for good."""
        S = self.S
        limited = (1, "", "gh: You have exceeded a secondary rate limit (HTTP 403)")
        calls, waits = self._fake_gh([limited, limited, (0, '{"full_name": "o/r"}', "")])
        self.assertEqual(S.gh("repos/o/r"), {"full_name": "o/r"})
        self.assertEqual(waits, [60, 120])
        self.assertEqual(S.gh("repos/o/r"), {"full_name": "o/r"})
        self.assertEqual(len(calls), 3, "the success is cached")
        # Failing on every try stops the draw, and leaves nothing behind to read back.
        calls, waits = self._fake_gh([limited])
        with self.assertRaises(RuntimeError):
            S.gh("repos/o/s")
        self.assertEqual(waits, list(S.GH_WAITS))
        calls, _ = self._fake_gh([(0, '{"full_name": "o/s"}', "")])
        self.assertEqual(S.gh("repos/o/s"), {"full_name": "o/s"})
        self.assertEqual(len(calls), 1, "nothing was cached for the failure")

    def test_a_final_status_is_cached_as_such(self):
        """A 404 (gone) or a 409 (empty repository) is an answer about the repository: it
        is cached, read back as no data, and not asked again."""
        S = self.S
        calls, waits = self._fake_gh([(1, "", "gh: Not Found (HTTP 404)")])
        self.assertIsNone(S.gh("repos/o/gone"))
        self.assertIsNone(S.gh("repos/o/gone"))
        self.assertEqual((len(calls), waits), (1, []))
        calls, _ = self._fake_gh([(1, "", "gh: Git Repository is empty. (HTTP 409)")])
        self.assertEqual(S.gh("repos/o/e/commits?per_page=1", raw=True), "")
        # A repository disabled for terms-of-service reasons answers 403 for good: final,
        # or the draw could never get past it.
        calls, waits = self._fake_gh([(1, "", "gh: Repository access blocked (HTTP 403)")])
        self.assertIsNone(S.gh("repos/o/blocked"))
        self.assertEqual(waits, [])
        # An empty entry from an older cache (a 404 and a failure were both written as "")
        # is asked again once, and the real answer replaces it.
        calls, _ = self._fake_gh([(0, '{"full_name": "o/old"}', "")])
        key = __import__("hashlib").sha256(b"repos/o/old").hexdigest()
        os.makedirs(os.path.join(S.HERE, "cache", key[:2]))
        open(os.path.join(S.HERE, "cache", key[:2], key), "w").close()
        self.assertEqual(S.gh("repos/o/old"), {"full_name": "o/old"})
        self.assertEqual(S.gh("repos/o/old"), {"full_name": "o/old"})
        self.assertEqual(len(calls), 1)
        # Unchanged: a rate limit reported with a 404-looking code is still a rate limit.
        calls, waits = self._fake_gh([(1, "", "API rate limit exceeded (HTTP 403)"), (0, "[]", "")])
        self.assertEqual(S.gh("repos/o/x/commits"), [])
        self.assertEqual(waits, [60])

    def test_draw_order_is_the_published_seed(self):
        import random
        repos = ["c/z", "a/x", "b/y", "d/w"]
        expected = sorted(repos)
        random.Random(20261017).shuffle(expected)
        self.assertEqual(self.S.SEED, 20261017)
        self.assertEqual(self.S.draw_order(repos), expected)
        self.assertEqual(self.S.draw_order(list(reversed(repos))), expected)

    def test_vitepress_site_folder_holds_dot_vitepress(self):
        self.assertEqual(self.S.site_dir("vitepress", "docs/.vitepress/config.ts"), "docs")
        self.assertEqual(self.S.site_dir("vitepress", ".vitepress/config.ts"), "")
        self.assertEqual(self.S.site_dir("astro", "site/astro.config.mjs"), "site")

    def test_eligibility_reasons(self):
        ok = {"private": False, "fork": False, "archived": False, "homepage": "https://example.org"}
        self.assertIsNone(self.S.eligibility(ok, 75, "o/r"))
        self.assertIn("commits", self.S.eligibility(ok, 74, "o/r"))
        self.assertEqual(self.S.eligibility(dict(ok, fork=True), 99, "o/r"), "fork")
        self.assertEqual(self.S.eligibility(dict(ok, archived=True), 99, "o/r"), "archived")
        self.assertIn("used in this plan", self.S.eligibility(ok, 99, "Electron/Website"))
        self.assertIn("docusaurus.io", self.S.eligibility(dict(ok, homepage="https://www.docusaurus.io/"), 99, "o/r"))

    def _rule(self, files, root_pkg=None, site_pkg=None, d="", yarnrc=None, cfg="", nvmrc=None, stack="docusaurus"):
        site_pkg = {"scripts": {"build": "x"}} if site_pkg is None else site_pkg
        return self.S.build_rule(stack, d, files, root_pkg, yarnrc, site_pkg, cfg, nvmrc, "build")

    def test_build_rule_pins_pnpm_by_lockfile_unless_the_repo_pins_it(self):
        (cmd, out, node), _ = self._rule({"pnpm-lock.yaml": "9.0"}, d="site", nvmrc="v22.3.0")
        self.assertEqual(cmd, "corepack pnpm@9.15.9 install --frozen-lockfile && "
                              "(cd site && corepack pnpm@9.15.9 run build)")
        self.assertEqual((out, node), ("site/build", "22"))
        (cmd, _, node), _ = self._rule({"pnpm-lock.yaml": "9.0"},
                                       root_pkg={"packageManager": "pnpm@10.1.0", "engines": {"node": ">=20"}})
        # Addendum 6: an engines floor (">=20") is not the Node version used.
        self.assertEqual((cmd, node), ("pnpm install --frozen-lockfile && pnpm run build", "24"))

    def test_build_rule_for_yarn_and_npm(self):
        self.assertTrue(self._rule({"yarn.lock": ""})[0][0].startswith("corepack yarn@1.22.22 install --frozen-lockfile"))
        rule, _ = self._rule({"yarn.lock": ""}, yarnrc="yarnPath: .yarn/releases/yarn-4.1.0.cjs\n")
        self.assertTrue(rule[0].startswith("node .yarn/releases/yarn-4.1.0.cjs install --immutable"))
        self.assertIn("neither packageManager nor yarnPath", self._rule({"yarn.lock": ""}, yarnrc="nodeLinker: pnp\n")[1])
        (cmd, _, node), _ = self._rule({"package-lock.json": ""}, d="docs",
                                       root_pkg={"scripts": {"build": "turbo build"}}, nvmrc="lts/*")
        self.assertEqual(cmd, "npm ci && ((cd docs && npm run build) || (npm run build && (cd docs && npm run build)))")
        self.assertEqual(node, "24")

    def test_an_output_with_no_pages_is_not_built(self):
        """Addendum 7: first10forward/f10f-spa built, but its output held no HTML pages."""
        self.assertTrue(self.S.built({"status": "ok", "error": ""}))
        self.assertTrue(self.S.built({"status": "audit_failed", "error": "ValueError: Invalid IPv6 URL"}))
        self.assertFalse(self.S.built({"status": "audit_failed", "error": "ERROR: crawled 0 pages from /x/public"}))
        self.assertFalse(self.S.built({"status": "build_failed", "error": "exit 1"}))

    def test_build_rule_refuses_what_it_cannot_build_mechanically(self):
        self.assertIn("no lockfile", self._rule({})[1])
        self.assertIn("no package.json build script", self._rule({"package-lock.json": ""}, site_pkg={})[1])
        self.assertIn("output: 'export'", self._rule({"package-lock.json": ""}, stack="nextjs", cfg="module.exports = {}")[1])
        rule, why = self._rule({"package-lock.json": ""}, stack="nextjs", cfg='export default { output: "export" }')
        self.assertIsNone(why)


class TestSweepReport(unittest.TestCase):
    """bench/sweep/report.py flags crashes, slow audits and site-wide high findings for a
    person to review; it decides nothing."""

    def test_flags(self):
        report = _bench_module("sweep", "report.py")
        if report is None:
            raise unittest.SkipTest("bench/ is not shipped in the sdist")
        d = tempfile.mkdtemp(prefix="sitemend-sweep-")
        self.addCleanup(shutil.rmtree, d, True)
        site = os.path.join(d, "out", "o__a", "s1")
        os.makedirs(site)
        pages = ["/p{0}".format(i) for i in range(10)]
        with open(os.path.join(site, "findings.json"), "w") as fh:
            json.dump({"findings": [{"id": "S1-X", "severity": "high", "pages": pages},
                                    {"id": "S3-Y", "severity": "medium", "pages": pages}]}, fh)
        with open(os.path.join(site, "crawl.json"), "w") as fh:
            json.dump({"meta": {"page_count": 10}}, fh)
        builds = os.path.join(d, "builds.csv")
        with open(builds, "w", encoding="utf-8", newline="") as fh:
            fh.write("repo,sha,status,build_seconds,audit_seconds,node,error\n"
                     "o/a,s1,ok,10,700,v24,\n"
                     "o/b,s2,audit_failed,10,5,v24,ValueError: Invalid IPv6 URL\n"
                     "o/c,s3,build_failed,10,,v24,exit 1\n")
        r = subprocess.run([sys.executable, os.path.join(os.path.dirname(report.__file__), "report.py"),
                            "--builds", builds, "--audits", d, "--out", d], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(d, "sweep.md"), encoding="utf-8") as fh:
            md = fh.read()
        self.assertIn("**3 repositories: 2 built, 1 did not; of those built, 0 had no HTML pages and "
                      "sitemend could not audit 1.**", md)
        self.assertIn("| o/a | slow (700 s); site-wide S1-X (10 of 10 pages) |", md)
        self.assertIn("| o/b | crash | ValueError: Invalid IPv6 URL |", md)
        self.assertNotIn("S3-Y", md)


class TestBlocksColumn(unittest.TestCase):
    """docs/blocks.py generates the README's Blocks? column. It once read S4-CWV-POOR's
    severity, which comes from a loop tuple, as nothing and reported "no", though LCP and
    CLS are high and block. A value it cannot read must stop it, not become "no"."""

    def setUp(self):
        import importlib.util
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "blocks.py")
        if not os.path.isfile(path):
            self.skipTest("docs/ is not in the sdist")
        spec = importlib.util.spec_from_file_location("blocks", path)
        self.B = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.B)

    def test_every_rule_resolves(self):
        import re
        ids = set()
        for name, pat in (("audit.py", r'finding\(\s*"(S\d-[A-Z0-9-]+)"'),
                          ("schema_check.py", r'"id":\s*"(S\d-[A-Z0-9-]+)"')):
            with open(os.path.join(self.B.SCRIPTS, name), encoding="utf-8") as fh:
                ids |= set(re.findall(pat, fh.read()))
        v = self.B.variants()
        self.assertGreater(len(ids), 50)
        self.assertEqual(sorted(ids - set(v)), [])

    def test_every_rule_in_the_readme_tables_resolves(self):
        """A rule in "What breaks" that blocks.py cannot see has a Blocks? cell nobody can
        regenerate. S1-HOST-DRIFT, built in verify.py, was one."""
        import re
        with open(os.path.join(self.B.SCRIPTS, "..", "README.md"), encoding="utf-8") as fh:
            text = fh.read()
        section = text.split("## What breaks", 1)[1].split("\n## ", 1)[0]
        ids = set(re.findall(r"`(S\d-[A-Z0-9-]+)`", section))
        self.assertIn("S1-HOST-DRIFT", ids)
        self.assertEqual(sorted(ids - set(self.B.variants())), [])

    def test_paired_ternaries_are_not_crossed(self):
        v = self.B.variants()
        self.assertEqual(v["S1-HOST-DRIFT"], {("critical", "high"), ("high", "medium")})
        self.assertEqual(self.B.row(v["S1-HOST-DRIFT"]),
                         ("critical, high (yes); high, medium (no)", "depends on severity"))

    def test_loop_tuple_severity(self):
        v = self.B.variants()
        self.assertEqual(v["S4-CWV-POOR"], {("high", "high"), ("medium", "high")})
        self.assertEqual(self.B.row(v["S4-CWV-POOR"]),
                         ("high, high (yes); medium, high (no)", "depends on severity"))

    def test_unresolvable_exits(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        with open(os.path.join(d, "audit.py"), "w", encoding="utf-8") as fh:
            fh.write('sev = pick()\nfinding("S9-X", 1, sev, "m", [])\n')
        for empty in ("schema_check.py", "verify.py"):
            with open(os.path.join(d, empty), "w", encoding="utf-8") as fh:
                fh.write("")
        self.B.SCRIPTS = d
        with self.assertRaises(SystemExit) as cm:
            self.B.variants()
        self.assertIn("audit.py:2: S9-X", str(cm.exception.code))


if __name__ == "__main__":
    unittest.main(verbosity=2)
