# es/es-py/index/sitemap_index/utils.py

from html.parser import HTMLParser
import re

_WS_RUN   = re.compile(r"[ \t\r\f\v]+")
_PARA_RUN = re.compile(r"\n\s*\n+")

# Block-level elements we want separated by newlines
_BLOCKS = {
    "p","li","ul","ol",
    "h1","h2","h3","h4","h5","h6",
    "div","section","article","nav","aside",
    "header","footer","main",
    "table","thead","tbody","tfoot","tr","td","th",
    "pre","blockquote","figure","figcaption"
}

class _Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._buf: list[str] = []
        self._skip_depth = 0
        self._in_head = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in ("script","style","noscript"):
            self._skip_depth += 1
            return
        if tag == "head":
            self._in_head = True
            return
        # start newline only for <br>
        if tag == "br":
            self._buf.append("\n")
        # capture <img alt="">
        if tag == "img":
            alt = next((v for k,v in attrs if k.lower()=="alt" and v), None)
            if alt:
                self._buf.append(f" {alt} ")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("script","style","noscript"):
            if self._skip_depth > 0:
                self._skip_depth -= 1
            return
        if tag == "head":
            self._in_head = False
            return
        # newline at the end of block elements
        if tag in _BLOCKS:
            self._buf.append("\n")

    def handle_data(self, data):
        if self._skip_depth or self._in_head or not data:
            return
        # normalise NBSP to space
        self._buf.append(data.replace("\xa0", " "))

    def text(self) -> str:
        txt = "".join(self._buf)
        txt = _WS_RUN.sub(" ", txt)
        txt = _PARA_RUN.sub("\n\n", txt)
        return txt.strip()

def html_to_text(html: str) -> str:
    p = _Extractor()
    p.feed(html)
    p.close()
    return p.text()