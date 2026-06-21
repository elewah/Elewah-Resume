"""Job description keyword extraction — pure-stdlib, no NLP dependencies required."""

from __future__ import annotations

import re
import string
from collections import Counter
from html.parser import HTMLParser
from urllib.request import Request, urlopen

# Common English stopwords that carry no signal for resume/JD matching.
_STOPWORDS = frozenset(
    """
    a an the and or but if in on at to of for with by from as is are was were be
    been being have has had do does did will would could should may might must can
    shall not no nor so yet both either neither just very also only such more most
    less least about above after before between during into through under upon
    while since until now then there here where when who what which how all any
    each every few many much some any that this these those i me my we our you
    your he she it his her they them their its us
    """.split()
)


class _HTMLStripper(HTMLParser):
    """Collect visible text from an HTML string."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in {"script", "style", "head", "meta", "link"}:
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "head", "meta", "link"}:
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts)


def _strip_html(text: str) -> str:
    """Remove HTML tags and return visible text."""
    if "<" not in text:
        return text
    stripper = _HTMLStripper()
    stripper.feed(text)
    return stripper.get_text()


def _tokenize(text: str) -> list[str]:
    """Split text into lowercase word tokens, preserving hyphenated terms (e.g. CI/CD)."""
    # Keep alphanumeric, hyphens, slashes, dots (for e.g. "Node.js", "CI/CD")
    tokens = re.findall(r"[\w][\w./\-]*", text.lower())
    # Filter single-character tokens and pure numbers
    return [t for t in tokens if len(t) > 1 and not t.isdigit()]


def extract_keywords(jd_text: str) -> list[str]:
    """Extract candidate keywords and phrases from a job description.

    Returns a deduplicated list ordered by relevance (frequency). Multi-word
    technical bigrams (e.g. "machine learning", "CI/CD pipeline") are included
    when both constituent words appear together frequently.

    No external libraries required — pure stdlib.
    """
    if not jd_text or not jd_text.strip():
        return []

    text = _strip_html(jd_text)

    # Collect unigrams (non-stopword tokens ≥ 3 chars)
    tokens = _tokenize(text)
    unigrams = [t for t in tokens if t not in _STOPWORDS and len(t) >= 3]

    # Collect bigrams from adjacent non-stopword tokens in the original token stream
    bigrams: list[str] = []
    for i in range(len(tokens) - 1):
        a, b = tokens[i], tokens[i + 1]
        if a not in _STOPWORDS and b not in _STOPWORDS and len(a) >= 2 and len(b) >= 2:
            bigrams.append(f"{a} {b}")

    unigram_counts = Counter(unigrams)
    bigram_counts = Counter(bigrams)

    # Keep bigrams that appear ≥ 2 times
    selected_bigrams = [phrase for phrase, count in bigram_counts.most_common() if count >= 2]

    # Keep unigrams that appear ≥ 2 times, excluding those already covered by a selected bigram
    covered = set()
    for phrase in selected_bigrams:
        covered.update(phrase.split())

    selected_unigrams = [
        word
        for word, count in unigram_counts.most_common()
        if count >= 2 and word not in covered
    ]

    # If we have very few results (sparse JD), relax frequency threshold to 1
    if len(selected_bigrams) + len(selected_unigrams) < 10:
        selected_bigrams = [p for p, _ in bigram_counts.most_common(20)]
        selected_unigrams = [
            w for w, _ in unigram_counts.most_common(30) if w not in covered
        ]

    # Reconstruct with original casing where possible
    original_tokens = _tokenize(_strip_html(jd_text))
    # Build a case map: lowercase → first occurrence in original case
    case_map: dict[str, str] = {}
    raw_tokens = re.findall(r"[\w][\w./\-]*", jd_text)
    for t in raw_tokens:
        low = t.lower()
        if low not in case_map:
            case_map[low] = t

    def _restore_case(phrase: str) -> str:
        parts = phrase.split()
        return " ".join(case_map.get(p, p) for p in parts)

    result = [_restore_case(p) for p in selected_bigrams]
    result += [_restore_case(w) for w in selected_unigrams]

    # Deduplicate while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for kw in result:
        key = kw.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(kw)

    return deduped


def fetch_jd_from_url(url: str) -> str:
    """Fetch a job posting from a URL and return its visible text.

    Strips HTML tags; returns plain text suitable for ``extract_keywords``.
    Raises ``ValueError`` on network or HTTP errors.
    """
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; ats-resume-checker/1.0)"})
        with urlopen(req, timeout=15) as resp:
            raw = resp.read()
            charset = resp.headers.get_content_charset("utf-8")
            html_text = raw.decode(charset, errors="replace")
    except Exception as exc:
        raise ValueError(f"Could not fetch job description from {url!r}: {exc}") from exc

    return _strip_html(html_text)
