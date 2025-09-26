# fetch_information_from_site.py

"""Sitemap page fetcher.

Discovers, fetches, and shapes website pages into sitemap documents for
Elasticsearch. Uses the site's sitemap XML to collect same-origin URLs,
normalises legacy routes, filters blocked/non-HTML payloads, and extracts a
page title plus plain-text content.

All functionality is exposed via the `FetchSitemapFromSite` class.

GitHub `.md` fallback for data-collection pages
-----------------------------------------------
If a `/data-portal/data-collection/<slug>` page yields only a loader (e.g.
"Loading...") or otherwise too little useful content (<200 chars), the fetcher:

1) Downloads the raw markdown from:
   https://raw.githubusercontent.com/igsr/gca_1000genomes_website/master/data-portal/data-collections/<slug>.md
2) Strips YAML front matter (--- ... ---) if present.
3) Derives the title from the first markdown heading (ATX `#` or setext), and
   drops junk titles like `layout: angularjs_partial`. Falls back to the slug.
4) Converts markdown to plain text:
   - removes code fences, bullets, quotes, etc.
   - converts images to their alt text and links to their link text
   - strips any residual HTML
5) Post-cleans the body (removes site chrome crumbs etc.) and trims.
"""

# ──────────────────────────────────────────────────────────────
# Imports
# ──────────────────────────────────────────────────────────────

from typing import Any, Dict, Iterator, Optional, List
import concurrent.futures as cf
import gzip, html, json, re, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from urllib.parse import urlsplit, urlunsplit, quote
from .utils import html_to_text

# ──────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────

_URL_RE = re.compile(r"^https?://", re.I)
REQUEST_HEADERS = {"User-Agent": "es-py-sitemap/1.0 (+IGSR)", "Accept-Encoding": "gzip, deflate"}
BLOCK_EXT_RE = re.compile(r"\.(?:pdf|docx?|pptx?|xlsx?|rtf|zip|gz|tgz|bz2|7z|rar|tar)$", re.I)

# URL encoding safety sets
PATH_SAFE  = "/:@&+$,-_.~!*'()%"
QUERY_SAFE = "=&;%+,:@/?%"

# Default fetcher settings
DEFAULT_HTTP_WORKERS = 8
DEFAULT_HTTP_TIMEOUT = 15
DEFAULT_MAX_PAGES    = 2000
DEFAULT_MAX_CHARS    = 200_000

# Extraction thresholds
_MIN_USEFUL_CHARS = 20  # keep low to allow short but meaningful content

# Exclude families we never want
PATH_EXCLUDE_RE = re.compile(r"^/(?:category/|node/)", re.I)
TRAILING_ENSEMBL_RE = re.compile(r"/(?:www\.)?ensembl\.org/?$", re.I)

# Treat these path families as belonging to this site even if absolute links point to prod
SITE_FAMILIES_RE = re.compile(
    r"^/(?:$|announcements|faq|data-portal|data_collections|participants|about|help|tools|data|media|analysis)(?:/|$)",
    re.I,
)

# Hub paths we pre-seed so the crawl can fan out
SEED_PATHS = [
    "/", "/announcements", "/faq", "/data-portal",
    "/data-portal/data-collections",  # legacy/plural listing that links to the items
    "/data-portal/data-collection",   # in case there is an index page here
    "/data_collections",              # old docs tree
    "/participants", "/about", "/help", "/tools", "/data", "/media", "/analysis",
]

# Heuristics to yank collection targets even when they’re not in <a href="...">
COLLECTION_PATH_ANY_RE   = re.compile(r"/data-portal/data-collection/[a-z0-9-]+", re.I)
COLLECTIONS_LEGACY_RE    = re.compile(r"/data-portal/data-collections/([a-z0-9-]+)(?:\.html)?", re.I)

# Common crumbs/labels we never want in the captured body (only at line starts)
_CRUMB_RE = re.compile(
    r"^\s*(?:Home|About|Help|Contact|News|Blog|Events|FAQ|"
    r"Data(?: portal)?|Data access|Data reuse|Publications|Resources)\s*$",
    re.I,
)

# Site-brand suffix to drop from titles
SITE_BRAND_SUFFIX_RE = re.compile(
    r"\s*\|\s*(?:1000\s*Genomes|IGSR|International Genome Sample Resource|"
    r"The International Genome Sample Resource)\s*$",
    re.I,
)

# One-word heading bodies we should not accept on their own
_HEADING_ONLY_RE = re.compile(
    r"^(overview|summary|introduction|about|principles|help|faq|news)$", re.I
)

# ──────────────────────────────────────────────────────────────
# Helpers (URL + text utilities)
# ──────────────────────────────────────────────────────────────

def _strip_brand_suffix(title: str) -> str:
    """Remove site-brand trailer like ' | 1000 Genomes'."""
    return SITE_BRAND_SUFFIX_RE.sub("", title or "").strip()

def _looks_heading_only(text: Optional[str]) -> bool:
    """
    Return True if the text looks like a bare heading (e.g., 'Overview') or is
    trivially short. This avoids accepting containers that only capture H1/H2.
    """
    if not text:
        return True
    s = text.strip()
    if not s:
        return True
    # very short single-line with no sentence punctuation → heading-ish
    if "\n" not in s and len(s.split()) <= 6 and not re.search(r"[.!?;:]", s):
        return bool(_HEADING_ONLY_RE.match(s)) or len(s) <= 30
    return False

def _remove_standalone_crumb_lines(text: str) -> str:
    out_lines = []
    for ln in text.splitlines():
        if _CRUMB_RE.match(ln.strip()):
            continue
        out_lines.append(ln)
    return "\n".join(out_lines).strip()

def _encode_for_request(url: str) -> str:
    s = urlsplit(url)
    return urlunsplit(
        (s.scheme, s.netloc,
         quote(s.path, safe=PATH_SAFE),
         quote(s.query, safe=QUERY_SAFE),
         "")
    )

def _legacy_norm(path: str) -> str:
    # legacy /data-collections/foo.html → /data-collection/foo
    m = re.match(r"^/data-portal/data-collections/([^.]+)\.html$", path, re.I)
    return f"/data-portal/data-collection/{m.group(1)}" if m else path

def _title_from_html(html_src: str) -> Optional[str]:
    m = re.search(r"<title[^>]*>(.+?)</title>", html_src, re.I | re.S)
    return html.unescape(re.sub(r"\s+", " ", m.group(1)).strip()) if m else None

def _h1_from_html(html_src: str) -> Optional[str]:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html_src, re.I | re.S)
    if not m:
        return None
    return re.sub(r"\s+", " ", html_to_text(m.group(1))).strip()

def _strip_chrome(text: str) -> str:
    """Remove footer/nav boilerplate and other site furniture."""
    patterns = [
        r"\bToggle navigation\b",
        r"IGSR:\s*The International Genome Sample Resource",
        r"Supporting\s+open\s+human\s+variation\s+data",
        r"\bHome\b\s+\bAbout\b\s+\bData\b\s+\bHelp\b",
        r"©\s*EMBL-EBI\s*\d{4}(?:-\d{4})?",
        r"Site maintained by EMBL-EBI.*?(?:Cookies|$)",
        r"Terms of Use, Privacy and Cookies",
        r"\bLoading\.\.\.\b",
        r"To cite IGSR please use our NAR publication",
        r"The International Genome Sample Resource \(IGSR\).+(?:new data|new analysis)\.",
    ]
    for pat in patterns:
        text = re.sub(pat, " ", text, flags=re.I | re.S)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def _drop_leading_crumb_lines(text: str) -> str:
    lines = [ln.rstrip() for ln in text.splitlines()]
    out, started = [], False
    for ln in lines:
        if not started and (not ln or _CRUMB_RE.match(ln)):
            continue
        started = True
        out.append(ln)
    return "\n".join(out).strip()

def _remove_title_lines(text: str, title_main: Optional[str], h1: Optional[str]) -> str:
    """Remove the first line if it is the HTML <title> or the <h1>."""
    if not text:
        return text

    def strip_first_line(t: str, needle: str) -> str:
        pat = r"^\s*" + re.escape(needle) + r"\s*(?:\r?\n|$)"
        return re.sub(pat, "", t, count=1, flags=re.I | re.M)

    if title_main:
        text = strip_first_line(text, title_main.strip())
    if h1 and h1.lower() != (title_main or "").lower():
        text = strip_first_line(text, h1.strip())
    return text.strip()

def _remove_related_questions_block(text: str) -> str:
    return re.sub(r"\n\s*Related questions:.*$", "", text, flags=re.I | re.S).strip()

def _meta_description(html_src: str) -> Optional[str]:
    m = re.search(
        r'<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]*content=["\'](.*?)["\']',
        html_src, re.I | re.S
    )
    if not m:
        return None
    return html.unescape(re.sub(r"\s+", " ", m.group(1)).strip())

# ──────────────────────────────────────────────────────────────
# Content extraction
# ──────────────────────────────────────────────────────────────

def _extract_from_semantic(html_src: str) -> Optional[str]:
    """
    Return the *HTML* of the most likely main content container. We score
    candidates by the length of their text (after HTML→text), not HTML size.
    """
    patterns = [
        r"<main\b[^>]*>(.*?)</main>",
        r"<article\b[^>]*>(.*?)</article>",
        r"<section\b[^>]*>(.*?)</section>",
        r"<div\b[^>]*role=['\"]main['\"][^>]*>(.*?)</div>",
        r"<div\b[^>]*id=['\"]content['\"][^>]*>(.*?)</div>",
        # Drupal/IGSR-ish content containers
        r"<div\b[^>]*class=['\"][^\"']*(?:region-content|page-content|node__content|"
        r"field--name-body|field-name-body|content-body|pane-content|pane-node|"
        r"entry-content|article|content)[^\"']*['\"][^>]*>(.*?)</div>",
    ]
    best_html, best_len = None, 0
    for pat in patterns:
        for m in re.finditer(pat, html_src, flags=re.I | re.S):
            seg_html = m.group(1)
            seg_txt  = re.sub(r"\s+", " ", html_to_text(seg_html)).strip()
            L = len(seg_txt)
            if L > best_len:
                best_html, best_len = seg_html, L
    return best_html

def _extract_from_noscript(html_src: str) -> Optional[str]:
    ns = []
    for m in re.finditer(r"<noscript[^>]*>(.*?)</noscript>", html_src, re.I | re.S):
        ns.append(m.group(1))
    if not ns:
        return None
    best = max(ns, key=len)
    return html_to_text(best)

def _jsonld_article_text(html_src: str) -> Optional[str]:
    out = []
    for m in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html_src, re.I | re.S):
        raw = m.group(1).strip()
        try:
            data = json.loads(raw)
        except Exception:
            continue
        def collect(x):
            if isinstance(x, dict):
                for k in ("articleBody", "text", "description"):
                    v = x.get(k)
                    if isinstance(v, str) and v.strip():
                        out.append(v.strip())
                for v in x.values():
                    collect(v)
            elif isinstance(x, list):
                for it in x:
                    collect(it)
        collect(data)
    if not out:
        return None
    text = "\n\n".join(out)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def _extract_framework_boot_json(html_src: str) -> Optional[str]:
    """Heuristic: framework boot JSON can contain readable content copies."""
    blobs: List[str] = []
    for m in re.finditer(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html_src, re.I | re.S):
        blobs.append(m.group(1).strip())
    for m in re.finditer(r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>', html_src, re.I | re.S):
        blobs.append(m.group(1).strip())
    for m in re.finditer(r'window\.__NUXT__\s*=\s*({.*?})\s*[,;]<', html_src + "<", re.I | re.S):
        blobs.append(m.group(1).strip())
    for m in re.finditer(r'window\.__INITIAL_[A-Z_]*\s*=\s*({.*?})\s*[,;]<', html_src + "<", re.I | re.S):
        blobs.append(m.group(1).strip())

    texts: List[str] = []
    def collect_strings(x):
        if isinstance(x, str):
            s = x.strip()
            if len(s) >= 80 and re.search(r"[a-zA-Z]\s+[a-zA-Z]", s) and re.search(r"[.!?]", s):
                texts.append(s)
        elif isinstance(x, list):
            for it in x:
                collect_strings(it)
        elif isinstance(x, dict):
            for v in x.values():
                collect_strings(v)

    for raw in blobs:
        try:
            data = json.loads(raw)
            collect_strings(data)
        except Exception:
            try:
                pseudo = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)", r'\1"\2"\3', raw)
                data = json.loads(pseudo)
                collect_strings(data)
            except Exception:
                continue

    if not texts:
        return None
    texts = sorted(set(texts), key=len, reverse=True)[:5]
    return "\n\n".join(texts)

def _postclean(text: str, title_main: Optional[str], h1: Optional[str]) -> str:
    text = _strip_chrome(text)
    text = _drop_leading_crumb_lines(text)
    text = _remove_standalone_crumb_lines(text)
    text = _remove_title_lines(text, title_main, h1)
    text = _remove_related_questions_block(text)
    return text.strip()

def _extract_main_text(html_src: str, title_main: Optional[str]) -> str:
    """
    Try multiple strategies to extract useful body text from HTML.
    We reject captures that look like a bare heading (e.g., 'Overview').
    """
    h1 = _h1_from_html(html_src)

    seg = _extract_from_semantic(html_src)
    if seg:
        t = _postclean(html_to_text(seg), title_main, h1)
        if t and not _looks_heading_only(t) and len(t) >= _MIN_USEFUL_CHARS and "loading" not in t.lower():
            return t

    ns = _extract_from_noscript(html_src)
    if ns:
        t = _postclean(ns, title_main, h1)
        if t and not _looks_heading_only(t) and len(t) >= _MIN_USEFUL_CHARS and "loading" not in t.lower():
            return t

    jl = _jsonld_article_text(html_src)
    if jl:
        t = _postclean(jl, title_main, h1)
        if t and not _looks_heading_only(t) and len(t) >= _MIN_USEFUL_CHARS and "loading" not in t.lower():
            return t

    fj = _extract_framework_boot_json(html_src)
    if fj:
        t = _postclean(fj, title_main, h1)
        if t and not _looks_heading_only(t) and len(t) >= _MIN_USEFUL_CHARS and "loading" not in t.lower():
            return t

    md = _meta_description(html_src)
    if md:
        return md

    # fallback: raw HTML → text
    return _postclean(html_to_text(html_src), title_main, h1)

# ──────────────────────────────────────────────────────────────
# GitHub markdown fallback (collections + simple pages)
# ──────────────────────────────────────────────────────────────

def _github_md_url(slug: str) -> str:
    # Raw markdown file in repo (don’t use /blob/)
    return (
        "https://raw.githubusercontent.com/igsr/gca_1000genomes_website/master/"
        f"data-portal/data-collections/{slug}.md"
    )

def _http_get_text_simple(url: str, timeout: int) -> Optional[str]:
    try:
        req = urllib.request.Request(
            _encode_for_request(url),
            headers={"User-Agent": REQUEST_HEADERS["User-Agent"], "Accept-Encoding": "gzip, deflate"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            if "gzip" in (resp.headers.get("Content-Encoding") or "").lower():
                try:
                    data = gzip.decompress(data)
                except OSError:
                    pass
            return data.decode("utf-8", "ignore")
    except urllib.error.URLError:
        return None

def _fetch_markdown_from_github(slug: str, timeout: int) -> Optional[str]:
    return _http_get_text_simple(_github_md_url(slug), timeout=timeout)

# small fallback for simple top-level pages (e.g. /sample_collection_principles)
def _fetch_markdown_for_simple_page(rel_path: str, timeout: int) -> Optional[str]:
    """
    Try a small set of repo locations for top-level pages
    (/foo → foo.md). Keeps scope tight to avoid unintended fetches.
    """
    slug = (rel_path or "/").strip("/").split("/", 1)[0]
    if not slug:
        return None
    candidates = [
        f"https://raw.githubusercontent.com/igsr/gca_1000genomes_website/master/{slug}.md",
        f"https://raw.githubusercontent.com/igsr/gca_1000genomes_website/master/_pages/{slug}.md",
        f"https://raw.githubusercontent.com/igsr/gca_1000genomes_website/master/_faq/{slug}.md",
    ]
    for url in candidates:
        md = _http_get_text_simple(url, timeout=timeout)
        if md:
            return md
    return None

# --- front-matter + heading cleaners ----------------------------------------

_FRONT_MATTER_RE = re.compile(r'^\ufeff?\s*---\s*\n.*?\n---\s*\n?', re.S)

def _strip_yaml_front_matter(md: str) -> str:
    """Remove top YAML front matter block if present."""
    return _FRONT_MATTER_RE.sub("", md, count=1)

def _clean_md_title(title: Optional[str]) -> Optional[str]:
    """Drop junk titles that look like YAML keys, e.g. 'layout: angularjs_partial'."""
    if not title:
        return None
    t = title.strip()
    if re.match(r'^\s*layout\s*:', t, flags=re.I):
        return None
    return t or None

# --- markdown-to-text helpers -----------------------------------------------

_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")  # [text](url)
_IMG_RE  = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)") # ![alt](url)
_CODE_FENCE_RE = re.compile(r"^```.*?$", re.M)
_HDR_RE  = re.compile(r"^\s{0,3}#{1,6}\s*", re.M)
_BULLET_RE = re.compile(r"^\s*[-*+]\s+", re.M)
_OL_RE   = re.compile(r"^\s*\d+[.)]\s+", re.M)
_BQ_RE   = re.compile(r"^\s*>\s?", re.M)
_BACKTICK_RE = re.compile(r"`([^`]+)`")

def _markdown_to_text(md: str) -> str:
    # remove code fences and markdown constructs
    md = _CODE_FENCE_RE.sub("", md)
    md = _IMG_RE.sub(lambda m: m.group(1).strip(), md)           # images → alt text
    md = _LINK_RE.sub(lambda m: (m.group(1) or m.group(2)).strip(), md)
    md = _HDR_RE.sub("", md)
    md = _BULLET_RE.sub("", md)
    md = _OL_RE.sub("", md)
    md = _BQ_RE.sub("", md)
    md = _BACKTICK_RE.sub(r"\1", md)
    # normalise newlines and spaces; strip leftover HTML (e.g. <center><img ...>)
    md = re.sub(r"\r\n?", "\n", md)
    md = html_to_text(md)
    md = re.sub(r"[ \t]+", " ", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()

def _first_heading_from_markdown(md: str) -> Optional[str]:
    # ATX (e.g., "# Title")
    for line in md.splitlines():
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip() or None
    # Setext (underline with === or ---)
    lines = [ln.rstrip() for ln in md.splitlines()]
    for i in range(len(lines) - 1):
        if lines[i] and (set(lines[i+1]) <= {"="} or set(lines[i+1]) <= {"-"}):
            if 3 <= len(lines[i+1]):
                return lines[i].strip()
    return None

def _looks_loaderish(text: Optional[str]) -> bool:
    if not text:
        return True
    t = text.strip().lower()
    return ("loading" in t and len(t) < 200)

# ──────────────────────────────────────────────────────────────
# Fetcher
# ──────────────────────────────────────────────────────────────

class FetchSitemapFromSite:
    def __init__(self, cfg: dict[str, Any]):
        if "site_root" not in cfg or "site_base" not in cfg:
            raise ValueError("config must provide [site] site_root and site_base")
        self.source = str(cfg["site_root"]).rstrip("/")
        self.base   = str(cfg["site_base"]).rstrip("/")
        if not _URL_RE.match(self.source):
            raise ValueError("lite fetcher requires HTTP mode")

        s = urllib.parse.urlsplit(self.source)
        b = urllib.parse.urlsplit(self.base)
        if not (s.scheme and s.netloc and b.scheme and b.netloc):
            raise ValueError("site_root/site_base must be absolute URLs")
        self._origin = (s.scheme, s.netloc)

        # module defaults
        self.http_workers = DEFAULT_HTTP_WORKERS
        self.http_timeout = DEFAULT_HTTP_TIMEOUT
        self.max_pages    = DEFAULT_MAX_PAGES
        self.max_chars    = DEFAULT_MAX_CHARS

    # ---- URL & HTTP helpers -------------------------------------------------

    def _same_origin(self, abs_url: str) -> bool:
        u = urllib.parse.urlsplit(abs_url)
        return (not u.netloc) or (u.netloc == self._origin[1])

    def _canon_to_source(self, url: str) -> str:
        """
        Make absolute on site_root, drop fragments; and if the URL is absolute
        but its *path* belongs to our site families, rewrite to our current origin.
        """
        if not url:
            return url
        if url.startswith("//"):
            url = f"{self._origin[0]}:{url}"
        u = urllib.parse.urlsplit(url)

        # relative/root-relative → absolute on site_root
        if not u.scheme and not u.netloc:
            absu = urllib.parse.urljoin(self.source + "/", url)
            us = urllib.parse.urlsplit(absu)
            return urllib.parse.urlunsplit((us.scheme, us.netloc, us.path, us.query, ""))

        # absolute: if path looks like our site, pin to our origin (helps dev vs prod hosts)
        if SITE_FAMILIES_RE.match(u.path or ""):
            return urllib.parse.urlunsplit((self._origin[0], self._origin[1], u.path, u.query, ""))

        # foreign – leave as-is (will be filtered by _same_origin downstream)
        return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, u.query, ""))

    def _abs_from_rel(self, rel_path: str) -> str:
        if not rel_path.startswith("/"):
            rel_path = "/" + rel_path
        return urllib.parse.urlunsplit((self._origin[0], self._origin[1], rel_path, "", ""))

    def _http_get_bytes(self, url: str) -> Optional[bytes]:
        try:
            req = urllib.request.Request(_encode_for_request(url), headers=REQUEST_HEADERS)
            with urllib.request.urlopen(req, timeout=self.http_timeout) as resp:
                data = resp.read()
                if "gzip" in (resp.headers.get("Content-Encoding") or "").lower():
                    try:
                        data = gzip.decompress(data)
                    except OSError:
                        pass
                return data
        except urllib.error.URLError:
            return None

    def _http_get_text(self, url: str) -> Optional[str]:
        try:
            req = urllib.request.Request(_encode_for_request(url), headers=REQUEST_HEADERS)
        except Exception:
            return None
        try:
            with urllib.request.urlopen(req, timeout=self.http_timeout) as resp:
                ct = (resp.headers.get("Content-Type") or "").lower()
                if not (
                    ct.startswith("text/html")
                    or "application/xhtml+xml" in ct
                    or ct.startswith("text/plain")
                    or ct.startswith("text/markdown")
                    or "text/x-markdown" in ct
                    or not ct
                ):
                    return None
                data = resp.read()
                if "gzip" in (resp.headers.get("Content-Encoding") or "").lower():
                    try:
                        data = gzip.decompress(data)
                    except OSError:
                        pass
                return data.decode("utf-8", "ignore")
        except urllib.error.URLError:
            return None

    # ---- URL discovery ------------------------------------------------------

    def _parse_sitemap_xml(self, raw: bytes) -> list[str]:
        try:
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            root = ET.fromstring(raw)
        except Exception:
            return []
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        urls = [(n.text or "").strip() for n in root.findall(".//sm:sitemap/sm:loc", ns) if (n.text or "").strip()]
        if urls:
            return urls
        return [(n.text or "").strip() for n in root.findall(".//sm:url/sm:loc", ns) if (n.text or "").strip()]

    def _extract_site_paths_for_crawl(self, html_src: str) -> list[str]:
        """
        Extract candidate site-relative/absolute same-site paths from:
          - <a href="...">
          - any quoted '/...' occurrences in HTML/inline JSON
          - any raw occurrences of '/data-portal/data-collection/<slug>' (even if unquoted)
          - legacy '/data-portal/data-collections/<slug>[.html]' rewritten to canonical
        """
        paths: list[str] = []

        # anchors
        for href in re.findall(r'href=["\']([^"\']+)["\']', html_src, flags=re.I):
            raw = html.unescape(href).strip()
            if not raw or raw.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
                continue
            paths.append(raw)

        # quoted site-relative paths anywhere
        for m in re.finditer(r'["\'](/[^"\'>\s]+)["\']', html_src, flags=re.I):
            paths.append(html.unescape(m.group(1)).strip())

        # raw collection paths, even if unquoted
        for p in COLLECTION_PATH_ANY_RE.findall(html_src):
            paths.append(p.strip())

        # legacy collections → canonical
        for m in COLLECTIONS_LEGACY_RE.finditer(html_src):
            slug = m.group(1).strip()
            if slug:
                paths.append(f"/data-portal/data-collection/{slug}")

        return paths

    def _crawl_expand(self, seeds: list[str]) -> list[str]:
        """
        Crawl same-origin pages by following anchors & harvested paths.
        Legacy-normalise paths and dedupe. Respects max_pages.
        """
        seen: set[str] = set()
        queue: list[str] = []
        out: list[str] = []

        def _enqueue(u: str):
            if not u:
                return
            u = self._canon_to_source(u)
            if not self._same_origin(u):
                return
            us = urllib.parse.urlsplit(u)
            path = _legacy_norm(us.path)

            # block file-like payloads
            if BLOCK_EXT_RE.search(path):
                return
            # block unwanted families
            if PATH_EXCLUDE_RE.match(path):
                return
            # block paths that end with '/ensembl.org'
            if TRAILING_ENSEMBL_RE.search(path):
                return

            u_norm = urllib.parse.urlunsplit((us.scheme, us.netloc, path, us.query, ""))
            if u_norm in seen:
                return
            seen.add(u_norm)
            queue.append(u_norm)

        # seed: sitemap URLs + hub roots
        for s in seeds:
            _enqueue(s)
        for rel in SEED_PATHS:
            _enqueue(self._abs_from_rel(rel))

        while queue and len(out) < self.max_pages:
            u = queue.pop(0)
            out.append(u)
            try:
                html_src = self._http_get_text(u)
            except Exception:
                html_src = None
            if not html_src:
                continue

            # harvest candidate links/paths
            for cand in self._extract_site_paths_for_crawl(html_src):
                if len(out) >= self.max_pages:
                    break
                _enqueue(urllib.parse.urljoin(u + "/", cand))

        return out

    def _discover_urls(self) -> list[str]:
        # 1) collect from sitemaps
        candidates = ["sitemap.xml", "sitemap_index.xml", "sitemap.xml.gz", "sitemap_index.xml.gz"]
        collected: list[str] = []
        for name in candidates:
            raw = self._http_get_bytes(urllib.parse.urljoin(self.source + "/", name))
            if not raw:
                continue
            urls = self._parse_sitemap_xml(raw)
            if not urls:
                continue
            expanded = []
            for su in urls:
                su = self._canon_to_source(su)
                if not self._same_origin(su):
                    continue
                sub = self._http_get_bytes(su)
                if sub:
                    expanded += self._parse_sitemap_xml(sub)
            collected = expanded or [self._canon_to_source(u) for u in urls]
            if collected:
                break

        # 2) expand by crawl
        discovered = self._crawl_expand(collected or [self.source])
        return discovered[: self.max_pages]

    # ---- Public API ---------------------------------------------------------

    def iter_docs(self) -> Iterator[Dict[str, Any]]:
        urls = self._discover_urls()

        def _fetch(u: str) -> Optional[Dict[str, Any]]:
            html_src = self._http_get_text(u)
            if not html_src:
                return None

            us = urlsplit(u)
            rel_path = _legacy_norm(us.path)
            is_collection = rel_path.lower().startswith("/data-portal/data-collection/")
            slug = rel_path.rsplit("/", 1)[-1] if is_collection else None

            # Title: drop brand suffix and the " | ..." trailer
            full_title = _title_from_html(html_src) or u
            title_main = (full_title.split("|", 1)[0] or "").strip()
            doc_title  = _strip_brand_suffix(title_main) or _strip_brand_suffix(full_title)

            # Extract content from HTML
            content = _extract_main_text(html_src, doc_title)

            # Fallback for data-collection pages (GitHub .md)
            if is_collection and (_looks_loaderish(content) or len(content) < _MIN_USEFUL_CHARS):
                md = _fetch_markdown_from_github(slug, timeout=self.http_timeout) if slug else None
                if md:
                    md_nf        = _strip_yaml_front_matter(md)
                    md_title_raw = _first_heading_from_markdown(md_nf)
                    md_title     = _clean_md_title(md_title_raw) or slug
                    md_text      = _markdown_to_text(md_nf)
                    md_text      = _postclean(md_text, md_title, None)
                    if md_text and len(md_text) >= _MIN_USEFUL_CHARS:
                        content   = md_text
                        doc_title = _strip_brand_suffix(md_title)

            # Gentle extra fallback for simple top-level pages (e.g. dev pages that render "Overview" only)
            if _looks_heading_only(content) or len(content or "") < 60:
                md2 = _fetch_markdown_for_simple_page(rel_path, timeout=self.http_timeout)
                if md2:
                    md2_nf        = _strip_yaml_front_matter(md2)
                    md2_title_raw = _first_heading_from_markdown(md2_nf)
                    md2_title     = _clean_md_title(md2_title_raw) or doc_title
                    md2_text      = _markdown_to_text(md2_nf)
                    md2_text      = _postclean(md2_text, md2_title, None)
                    if len(md2_text) >= 60 and not _looks_heading_only(md2_text):
                        content   = md2_text
                        doc_title = _strip_brand_suffix(md2_title)

            # If still loader-ish after fallbacks, skip indexing rather than store "Loading..."
            if _looks_loaderish(content):
                return None

            # Trim large bodies
            if self.max_chars and len(content) > self.max_chars:
                content = content[: self.max_chars].rstrip()

            # Rebase to site_base; normalise index paths and trailing slashes
            rel = rel_path + (f"?{us.query}" if us.query else "")
            if rel.endswith("/index.html"):
                rel = rel[:-10]
            if rel.endswith("index.html"):
                rel = rel[:-10]
            if rel != "/" and rel.endswith("/"):
                rel = rel[:-1]
            path, q = (rel.split("?", 1) + [""])[:2]
            url_out = f"{self.base}{quote(path, safe=PATH_SAFE)}" + (f"?{quote(q, safe=QUERY_SAFE)}" if q else "")

            return {"title": doc_title, "content": content, "url": url_out}

        seen, submitted = set(), 0
        with cf.ThreadPoolExecutor(max_workers=self.http_workers) as ex:
            futures = []
            for u in urls:
                if u in seen:
                    continue
                seen.add(u)
                futures.append(ex.submit(_fetch, u))
                submitted += 1
                if self.max_pages and submitted >= self.max_pages:
                    break
            for fut in cf.as_completed(futures):
                doc = fut.result()
                if doc:
                    yield doc