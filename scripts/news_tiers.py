"""Where to look, by what kind of claim it is.

Tavily ranks by relevance, not by authority, and has no notion of which sources a fact-check
should rest on. That judgement lives here: a fixed table of evidence tiers per field (fixed,
because a table the model reinvents on every run changes on every run), searched from the top
down with Tavily's include_domains, plus PubMed for medicine because the systematic reviews a
medical verdict should rest on are indexed there and not on the open web.

Tier 1: bodies that measured or ruled (statistics offices, regulators, courts, systematic
        reviews, primary archives). Tier 2: peer-reviewed journals, research institutes, wire
        services. Tier 3: everything else on the web - enough to find where a claim came from,
        never enough on its own to settle it.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

from core.tavily_client import get_search
from polyjury.llm import chat, parse_json

FIELDS = {
    "medicine": {
        1: ["cochranelibrary.com", "who.int", "cdc.gov", "fda.gov", "nih.gov", "ema.europa.eu",
            "ecdc.europa.eu", "nice.org.uk", "gov.uk"],
        2: ["nejm.org", "thelancet.com", "bmj.com", "jamanetwork.com", "nature.com", "science.org",
            "annals.org", "pmc.ncbi.nlm.nih.gov", "academic.oup.com", "sciencedirect.com"],
    },
    "economics": {
        1: ["imf.org", "worldbank.org", "oecd.org", "bis.org", "federalreserve.gov", "ecb.europa.eu",
            "bls.gov", "bea.gov", "census.gov", "eurostat.ec.europa.eu", "ons.gov.uk"],
        2: ["nber.org", "aeaweb.org", "brookings.edu", "piie.com", "voxeu.org", "academic.oup.com",
            "sciencedirect.com", "peri.umass.edu", "reuters.com", "ft.com"],
    },
    "law": {
        1: ["justice.gov", "supremecourt.gov", "uscourts.gov", "courtlistener.com", "sec.gov", "ftc.gov",
            "epa.gov", "arb.ca.gov", "curia.europa.eu", "legislation.gov.uk", "congress.gov"],
        2: ["reuters.com", "apnews.com", "bbc.co.uk", "crsreports.congress.gov", "everycrsreport.com",
            "law.cornell.edu", "oyez.org"],
    },
    "history": {
        1: ["archives.gov", "loc.gov", "nationalarchives.gov.uk", "bnf.fr", "gallica.bnf.fr",
            "europeana.eu", "si.edu"],
        2: ["jstor.org", "cambridge.org", "academic.oup.com", "britannica.com", "history.ac.uk",
            "napoleon.org", "metmuseum.org"],
    },
    "statistics": {
        1: ["ourworldindata.org", "data.worldbank.org", "un.org", "who.int", "oecd.org", "census.gov",
            "bls.gov", "ons.gov.uk", "eurostat.ec.europa.eu"],
        2: ["pewresearch.org", "gallup.com", "statista.com", "reuters.com", "apnews.com"],
    },
    "science": {
        1: ["nasa.gov", "noaa.gov", "ipcc.ch", "nist.gov", "esa.int", "usgs.gov"],
        2: ["nature.com", "science.org", "pnas.org", "arxiv.org", "sciencedirect.com", "iop.org"],
    },
}
FIELDS["general"] = {1: sorted({d for f in FIELDS.values() for d in f[1]}),
                     2: ["reuters.com", "apnews.com", "bbc.co.uk", "nature.com", "science.org"]}

# Government bodies of the place the claim is about join tier 1 whatever the field.
REGIONS = {
    "KR": ["kosis.kr", "kostat.go.kr", "kdca.go.kr", "mfds.go.kr", "bok.or.kr", "law.go.kr", "scourt.go.kr", "korea.kr"],
    "US": ["cdc.gov", "fda.gov", "census.gov", "bls.gov", "justice.gov", "congress.gov"],
    "UK": ["ons.gov.uk", "gov.uk", "nhs.uk", "nationalarchives.gov.uk"],
    "EU": ["europa.eu", "ec.europa.eu", "ema.europa.eu", "ecdc.europa.eu"],
    "JP": ["mhlw.go.jp", "stat.go.jp", "e-gov.go.jp"],
}
OFFICIAL_SUFFIX = (".gov", ".go.kr", ".gov.uk", ".int", ".mil", ".go.jp", ".gc.ca", ".gov.au", ".europa.eu")

CLASSIFY_PROMPT = """Classify a claim for a fact-checker. JSON only:
{"fields": [one or two of "medicine","economics","law","history","statistics","science","general",
            main one first; "law" covers regulators, courts and official investigations],
 "region": two-letter code of the country the claim is about (KR, US, UK, EU, JP...) or "",
 "source_queries": [up to 3 short search queries an expert would type into official or academic
                    sources to find the data or ruling that settles it],
 "pubmed_query": for medicine only, a PubMed query with the exposure AND the outcome terms
                 only (no publication-type, date or NOT filters - those are added later), else ""}"""

FILTER = re.compile(r"\s*\b(?:AND|NOT|OR)\s+(?:\([^()]*\[(?:Publication Type|pt|dp|Date[^\]]*)\][^()]*\)|"
                    r"[^()]*?\[(?:Publication Type|pt|dp|Date[^\]]*)\])", re.I)


def clean_pubmed(query: str) -> str:
    """Filters the model adds on its own (often invalid, like "cohort study[Publication Type]")
    turn the search empty; the review and cohort filters are applied by pubmed() itself."""
    prev = None
    while prev != query:
        prev, query = query, FILTER.sub("", query)
    return query.strip()


def classify(claim: str) -> dict:
    try:
        raw, _ = chat(CLASSIFY_PROMPT, claim, think=False, max_tokens=400, temperature=0, timeout=60)
        data = parse_json(raw) or {}
    except Exception:  # noqa: BLE001
        data = {}
    fields = [f for f in (data.get("fields") or [data.get("field")]) if f in FIELDS][:2] or ["general"]
    field = fields[0]
    region = str(data.get("region") or "").upper()[:2]
    queries = [q for q in data.get("source_queries") or [] if isinstance(q, str) and q.strip()][:3]
    return {"field": field, "fields": fields, "region": region if region in REGIONS else "",
            "queries": queries or [claim],
            "pubmed": clean_pubmed(str(data.get("pubmed_query") or "")) if "medicine" in fields else ""}


def ladder(profile: dict) -> dict[int, list[str]]:
    tiers = {1: [], 2: []}
    for f in profile.get("fields") or [profile["field"]]:
        for t in (1, 2):
            tiers[t] += [d for d in FIELDS[f][t] if d not in tiers[t]]
    tiers[1] += [d for d in REGIONS.get(profile["region"], []) if d not in tiers[1]]
    return tiers


def tier_of(url: str, profile: dict | None = None) -> int:
    host = urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")
    tiers = ladder(profile) if profile else {1: FIELDS["general"][1], 2: FIELDS["general"][2]}
    for t in (1, 2):
        if any(host == d or host.endswith("." + d) for d in tiers[t]):
            return t
    if host.endswith(OFFICIAL_SUFFIX) or "pubmed.ncbi.nlm.nih.gov" in host:
        return 1
    if host.endswith(".edu") or host.endswith(".ac.uk") or host.endswith(".ac.kr"):
        return 2
    return 3


def _search(query: str, domains: list[str], n: int = 5) -> list[dict]:
    try:
        return get_search()._client.search(query=query, max_results=n, search_depth="advanced",
                                           include_raw_content=True, include_domains=domains[:300]).get("results", [])
    except Exception as exc:  # noqa: BLE001
        print("  tier search failed:", exc)
        return []


STOP = {"that", "this", "with", "from", "have", "were", "than", "their", "there", "about", "into",
        "cause", "causes", "caused", "percent", "times", "rise", "fall", "high", "legal", "average"}


def key_terms(claim: str) -> tuple[set[str], set[str]]:
    """Common words and names. Names (capitalised after the first word, or acronyms like MMR)
    are what makes a page about this claim rather than about the same everyday words."""
    words = re.findall(r"[A-Za-z][A-Za-z-]+", claim)
    names = {w.lower() for i, w in enumerate(words) if (w.isupper() and len(w) >= 3) or (i > 0 and w[0].isupper())}
    if words and words[0][0].isupper() and words[0].lower() not in STOP and len(words[0]) > 3 \
            and words[0].lower() not in {"countries", "most", "people", "every", "many"}:
        names.add(words[0].lower())
    common = {w.lower() for w in words if len(w) >= 4 and w.lower() not in STOP} - names
    return common, names


def on_topic(text: str, terms: tuple[set[str], set[str]]) -> bool:
    """A restricted search always returns something; count it only if it is about the claim."""
    common, names = terms
    low = text.lower()
    if names:
        return any(n in low for n in names) and sum(t in low for t in common) >= 1
    return sum(t in low for t in common) >= min(2, len(common))


RELEVANT_PROMPT = """A fact-checker searched official and academic sites for a claim. For each
numbered excerpt, decide whether the document itself holds evidence that bears DIRECTLY on the
claim (a measurement, a figure, a ruling, a study result about exactly this), as opposed to only
mentioning the same names or words (a catalogue entry, a guide, an unrelated topic).
JSON only: {"direct":[numbers of the excerpts that do]}"""


def _excerpt(text: str, terms: tuple[set[str], set[str]], claim: str = "", size: int = 700) -> str:
    """The two passages densest in the claim's words and numbers. The first mention of a name is
    usually the page title or site banner, not the evidence."""
    common, names = terms
    nums = set(re.findall(r"\d+(?:\.\d+)?", claim))
    chunks = [text[i:i + size] for i in range(0, min(len(text), 120000), size // 2)]

    def score(c: str) -> int:
        low = c.lower()
        return (3 * sum(n in low for n in names) + sum(w in low for w in common)
                + 3 * sum(bool(re.search(rf"(?<![\d.]){re.escape(n)}(?![\d])", c)) for n in nums))

    best = sorted(sorted(range(len(chunks)), key=lambda i: -score(chunks[i]))[:2])
    return " ... ".join(chunks[i] for i in best) if chunks else ""


def keep_direct(claim: str, found: list[tuple[str, str]], terms: tuple[set[str], set[str]]) -> tuple[list[int], bool]:
    """Word overlap cannot tell a library catalogue that names Napoleon from a record of his
    height. One short call to the chair can. Returns the kept indices and whether the check ran."""
    if not found:
        return [], True
    listing = "\n\n".join(f"[{i}] {u}\n{' '.join(_excerpt(t, terms, claim).split())}" for i, (u, t) in enumerate(found))
    for _ in range(2):
        try:
            raw, _ = chat(RELEVANT_PROMPT, f"CLAIM: {claim}\n\n{listing[:40000]}", think=False,
                          max_tokens=300, temperature=0, timeout=90)
            got = parse_json(raw)
            picked = got if isinstance(got, list) else (got or {}).get("direct")  # "[]" also answers
            why = f"unreadable answer {(raw or '')[:80]!r}"
        except Exception as exc:  # noqa: BLE001
            picked, why = None, f"{type(exc).__name__}: {str(exc)[:80]}"
        if isinstance(picked, list):
            return [i for i in picked if isinstance(i, int) and 0 <= i < len(found)], True
    print("    relevance check failed:", why)
    # the check failed: keep the documents rather than lose evidence, but do not trust them
    return list(range(len(found))), False


def gather_tiered(profile: dict, claim: str = "", enough: int = 3, per_tier: int = 5) -> tuple[dict[str, bytes], list[str]]:
    """Search tier 1 first; widen to tier 2 only if tier 1 did not yield enough documents that
    are actually about the claim. Returns documents named /work/sources/T<tier>-NN.txt and a
    log of what was searched."""
    docs, seen, log = {}, set(), []
    terms = key_terms(claim)
    for tier, domains in ladder(profile).items():
        found = []
        for q in profile["queries"]:
            for r in _search(q, domains):
                url, text = r.get("url", ""), r.get("raw_content") or ""
                if url in seen or len(text) < 800 or not on_topic(text, terms):
                    continue
                seen.add(url)
                found.append((url, text))
        direct, checked = keep_direct(claim, found, terms)
        direct = direct[:per_tier]
        for i in direct:
            url, text = found[i]
            docs[f"/work/sources/T{tier}-{len(docs):02d}.txt"] = (url + "\n" + text[:60000]).encode("utf-8")
        got = len(direct) if checked else 0  # unchecked documents never make a tier "enough"
        log.append(f"tier {tier} ({len(domains)} domains): {len(found)} on topic, "
                   + (f"{got} with direct evidence" if checked else f"relevance check failed, kept {len(direct)} unchecked"))
        if tier == 1 and got >= enough:
            log.append("tier 1 was enough; tier 2 not searched")
            break
    return docs, log


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"user-agent": "polyjury-news-probe"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def pubmed(query: str, n: int = 5) -> dict[str, bytes]:
    """Systematic reviews and meta-analyses first; large cohorts only if there are none."""
    if not query:
        return {}
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    out = {}
    for label, term in (("review", f"({query}) AND (meta-analysis[pt] OR systematic review[pt])"),
                        ("cohort", f"({query}) AND (cohort studies[mh])")):
        try:
            ids = json.loads(_get(base + "esearch.fcgi?" + urllib.parse.urlencode(
                {"db": "pubmed", "term": term, "retmax": n, "sort": "relevance", "retmode": "json"})))["esearchresult"]["idlist"]
        except Exception as exc:  # noqa: BLE001
            print("  pubmed search failed:", exc)
            ids = []
        for pmid in ids:
            try:
                text = _get(base + "efetch.fcgi?" + urllib.parse.urlencode(
                    {"db": "pubmed", "id": pmid, "rettype": "abstract", "retmode": "text"})).decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                continue
            if len(text) > 300:
                out[f"/work/sources/T1-pm{len(out):02d}.txt"] = (
                    f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/\n[PubMed {label}]\n{text[:20000]}").encode("utf-8")
        print(f"    PubMed {label}s: {len(ids)}")
        if out:
            break
    return out


def file_tier(path: str, docs: dict[str, bytes], profile: dict) -> int:
    m = re.search(r"/T([123])-", path)
    if m:
        return int(m.group(1))
    if path.startswith("/work/data/"):
        return 2  # replication data: rows, but assembled by someone
    first = docs.get(path, b"").split(b"\n", 1)[0].decode("utf-8", "replace")
    return tier_of(first, profile)


def strength(sub: dict, docs: dict[str, bytes], profile: dict) -> tuple[int, str]:
    files = [q.get("file", "") for q in sub.get("quotes") or []] + list(sub.get("data") or [])
    if not files:
        return 0, "no evidence"
    best = min(file_tier(f, docs, profile) for f in files)
    return best, {1: "tier 1: measured or ruled by the responsible body",
                  2: "tier 2: peer-reviewed or research source",
                  3: "tier 3: web sources only - not enough to settle it"}[best]
