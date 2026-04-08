"""Find probable duplicate article groups in a ``CollectionOutput`` JSON.

What counts as a duplicate here
--------------------------------
PubMed does not give a single canonical “same paper” key across preprints,
meetings, and versions. This module therefore reports **probable** duplicates
for human review, not automatic deletion.

**High confidence (merged into one cluster)**

1. **Same DOI** — After normalizing ``https://doi.org/`` prefixes and case, two
   records with the same non-empty DOI are treated as the same publication
   object (even if PMIDs differ, e.g. ahead-of-print vs final).

2. **Same normalized title + same publication year** — Title is lowercased,
   punctuation stripped, whitespace collapsed. Same string + same ``publication_year``
   (when both years present) catches many conference vs journal double-hits.

**Medium confidence**

3. **Fuzzy title + optional abstract check** — Within **blocks** (see below),
   ``rapidfuzz`` ``ratio`` on normalized titles ≥ 90, or ``token_sort_ratio`` ≥ 92
   (word-order differences). If **both** abstracts exist, we also require
   ``token_sort_ratio`` ≥ 78 on abstracts so we do not merge unrelated papers
   that share a short boilerplate title. If either abstract is missing, we rely
   on title similarity only (weaker).

**Where we draw the line**
- We **do not** merge on PMID alone (different PMIDs are expected for true
  duplicates in PubMed).
- We **do not** claim retracted vs replacement automatically; we **flag**
  publication types / titles containing “retract” for reviewers.
- Thresholds favor **precision** over recall: some true duplicates may be
  missed; reported pairs are meant to be **reviewed**.

**Scalability (~10k articles)**
- DOI and exact (title, year) grouping is **O(n)**.
- Fuzzy comparisons are **not** all-pairs: we **block** by ``(year, first few
  title tokens)`` so only similar-sized cohorts are compared. Buckets larger than
  ``MAX_BLOCK`` are split by title-length bands to avoid pathological
  ``O(k²)`` blocks (e.g. thousands of “review” papers).

**Output**
- Clusters with PMIDs, primary reason, confidence, optional reviewer notes
  (retraction hints). A short ``methodology`` string is included for downstream
  tools; use JSON + optional Markdown for humans.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from article_miner.domain.article import Article, CollectionOutput

# --- Thresholds (tune for precision vs recall) ---
FUZZY_TITLE_RATIO_MIN = 90
FUZZY_TITLE_TOKEN_SORT_MIN = 92
ABSTRACT_TOKEN_SORT_MIN = 78
MAX_BLOCK_SIZE = 280
_TITLE_PREFIX_WORDS = 4


class DuplicateCluster(BaseModel):
    """One connected component of duplicate candidates."""

    cluster_id: int
    pmids: list[str] = Field(description="PubMed IDs in this group (sorted)")
    primary_reason: str = Field(
        description="Dominant link type in the cluster (for reviewer orientation)"
    )
    confidence: Literal["high", "medium"]
    detail: str = Field(
        default="",
        description="Short explanation of why these were grouped",
    )
    reviewer_notes: list[str] = Field(
        default_factory=list,
        description="Flags such as possible retraction (not definitive)",
    )


class DedupReport(BaseModel):
    """Full report for JSON export."""

    source_article_count: int
    duplicate_group_count: int
    articles_in_some_duplicate_group: int
    methodology: str = Field(description="How duplicates were defined (for audit)")
    clusters: list[DuplicateCluster]
    stats: dict[str, int | float] = Field(
        default_factory=dict,
        description="Diagnostics (e.g. fuzzy pairs compared)",
    )


def format_dedup_markdown(report: DedupReport) -> str:
    """Human-readable Markdown summary for duplicate clusters (reviewers)."""
    lines = [
        "# Probable duplicate groups",
        "",
        f"- Source articles: **{report.source_article_count}**",
        f"- Duplicate groups (size ≥ 2): **{report.duplicate_group_count}**",
        f"- Articles appearing in some group: **{report.articles_in_some_duplicate_group}**",
        f"- Fuzzy pair comparisons: **{report.stats.get('fuzzy_pairs_compared', 0)}**",
        "",
        "## Definition (summary)",
        "",
        report.methodology,
        "",
        "## Groups",
        "",
    ]
    for c in report.clusters:
        lines.append(f"### Cluster {c.cluster_id} — `{c.primary_reason}` ({c.confidence})")
        lines.append("")
        lines.append(c.detail)
        lines.append("")
        lines.append("| PMID |")
        lines.append("|------|")
        for p in c.pmids:
            lines.append(f"| {p} |")
        if c.reviewer_notes:
            lines.append("")
            lines.append("**Reviewer notes:**")
            for n in c.reviewer_notes:
                lines.append(f"- {n}")
        lines.append("")
    return "\n".join(lines)


@dataclass
class _UnionFind:
    parent: list[int]
    rank: list[int]

    @classmethod
    def new(cls, n: int) -> _UnionFind:
        return cls(list(range(n)), [0] * n)

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1


def normalize_doi(doi: str | None) -> str | None:
    """Lowercase DOI, strip common URL prefixes. ``None`` if missing."""
    if not doi:
        return None
    s = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if s.startswith(prefix):
            s = s[len(prefix) :]
    s = s.strip()
    return s or None


def normalize_title(title: str | None) -> str:
    """Lowercase, strip punctuation, collapse whitespace (NFKD)."""
    if not title:
        return ""
    t = unicodedata.normalize("NFKD", title)
    t = t.lower()
    t = re.sub(r"[^\w\s]", " ", t, flags=re.UNICODE)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _title_prefix_key(norm: str) -> str:
    if not norm:
        return ""
    parts = norm.split()[:_TITLE_PREFIX_WORDS]
    return " ".join(parts)


def _abstract_norm(ab: str | None) -> str:
    if not ab:
        return ""
    t = unicodedata.normalize("NFKD", ab)
    t = re.sub(r"\s+", " ", t.lower().strip())
    return t[:8000]


def _maybe_retraction_notes(a: Article) -> list[str]:
    notes: list[str] = []
    title_l = (a.title or "").lower()
    if "retract" in title_l:
        notes.append(f"PMID {a.pmid}: title mentions retraction (verify in PubMed)")
    for pt in a.publication_types:
        if "retract" in pt.lower():
            notes.append(
                f"PMID {a.pmid}: publication type includes “{pt}” (verify replacement)"
            )
            break
    return notes


def _cluster_primary_reason(indices: list[int], articles: list[Article]) -> tuple[str, Literal["high", "medium"], str]:
    """Derive display reason from articles in one union-find component (|indices| >= 2)."""
    subset = [articles[i] for i in indices]
    # Same DOI?
    doi_map: dict[str, list[str]] = defaultdict(list)
    for a in subset:
        d = normalize_doi(a.doi)
        if d:
            doi_map[d].append(a.pmid)
    for _doi, pmids in doi_map.items():
        if len(set(pmids)) >= 2:
            return (
                "same_doi",
                "high",
                "Same normalized DOI across different PMIDs.",
            )

    # Exact title + year?
    key_counts: dict[tuple[str, int | None], int] = defaultdict(int)
    for a in subset:
        nt = normalize_title(a.title)
        key = (nt, a.publication_year)
        if nt:
            key_counts[key] += 1
    for (_nt, _y), c in key_counts.items():
        if c >= 2:
            return (
                "same_normalized_title_and_year",
                "high",
                "Identical normalized title and publication year.",
            )

    return (
        "fuzzy_title_and_or_abstract",
        "medium",
        "Similar title (and abstract when present) via fuzzy matching within blocks.",
    )


def build_duplicate_report(collection: CollectionOutput) -> DedupReport:
    """Cluster articles using DOI, exact (title, year), then blocked fuzzy pairs."""
    articles = collection.articles
    n = len(articles)
    uf = _UnionFind.new(n)
    fuzzy_pairs_compared = 0

    # 1) Same DOI
    doi_to_indices: dict[str, list[int]] = defaultdict(list)
    for i, a in enumerate(articles):
        d = normalize_doi(a.doi)
        if d:
            doi_to_indices[d].append(i)
    for group in doi_to_indices.values():
        if len(group) < 2:
            continue
        head = group[0]
        for j in group[1:]:
            uf.union(head, j)

    # 2) Exact (normalized title, year) — require non-empty title
    exact_key: dict[tuple[str, int | None], list[int]] = defaultdict(list)
    for i, a in enumerate(articles):
        nt = normalize_title(a.title)
        if not nt:
            continue
        exact_key[(nt, a.publication_year)].append(i)
    for group in exact_key.values():
        if len(group) < 2:
            continue
        head = group[0]
        for j in group[1:]:
            uf.union(head, j)

    # 3) Fuzzy blocking
    block: dict[str, list[int]] = defaultdict(list)
    for i, a in enumerate(articles):
        nt = normalize_title(a.title)
        if len(nt) < 12:
            continue
        y = a.publication_year
        prefix = _title_prefix_key(nt)
        if not prefix:
            continue
        # Spread huge "None year" buckets using a stable hash of title
        if y is None:
            h = hashlib.sha256(nt.encode()).hexdigest()[:6]
            key = f"ny|{h}|{prefix}"
        else:
            key = f"{y}|{prefix}"
        block[key].append(i)

    def split_oversized(bucket: list[int]) -> list[list[int]]:
        if len(bucket) <= MAX_BLOCK_SIZE:
            return [bucket]
        # Split by length quantile bands to keep comparisons local
        indexed = [(i, len(normalize_title(articles[i].title))) for i in bucket]
        indexed.sort(key=lambda x: x[1])
        chunks: list[list[int]] = []
        chunk: list[int] = []
        for idx, _ln in indexed:
            chunk.append(idx)
            if len(chunk) >= MAX_BLOCK_SIZE // 2:
                chunks.append(chunk)
                chunk = []
        if chunk:
            chunks.append(chunk)
        return chunks

    for _key, bucket in block.items():
        for sub in split_oversized(bucket):
            m = len(sub)
            for ii in range(m):
                for jj in range(ii + 1, m):
                    i, j = sub[ii], sub[jj]
                    if uf.find(i) == uf.find(j):
                        continue
                    ai, aj = articles[i], articles[j]
                    ti = normalize_title(ai.title)
                    tj = normalize_title(aj.title)
                    if not ti or not tj:
                        continue
                    # Length guard: wildly different lengths rarely duplicates
                    li, lj = len(ti), len(tj)
                    if li > 20 and lj > 20:
                        shorter, longer = min(li, lj), max(li, lj)
                        if shorter < longer * 0.55:
                            continue

                    fuzzy_pairs_compared += 1
                    tr = fuzz.ratio(ti, tj)
                    ts = fuzz.token_sort_ratio(ti, tj)
                    title_ok = tr >= FUZZY_TITLE_RATIO_MIN or ts >= FUZZY_TITLE_TOKEN_SORT_MIN
                    if not title_ok:
                        continue

                    abi = _abstract_norm(ai.abstract)
                    abj = _abstract_norm(aj.abstract)
                    if abi and abj:
                        if fuzz.token_sort_ratio(abi, abj) < ABSTRACT_TOKEN_SORT_MIN:
                            continue

                    uf.union(i, j)

    # Collect components of size >= 2
    comp: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        comp[uf.find(i)].append(i)

    clusters: list[DuplicateCluster] = []
    cid = 0
    in_group = 0
    for _root, indices in sorted(comp.items(), key=lambda x: min(x[1])):
        if len(indices) < 2:
            continue
        indices.sort(key=lambda x: int(articles[x].pmid))
        pmids = [articles[i].pmid for i in indices]
        primary, conf, detail = _cluster_primary_reason(indices, articles)
        notes: list[str] = []
        for i in indices:
            notes.extend(_maybe_retraction_notes(articles[i]))
        # Dedupe note strings
        seen: set[str] = set()
        uniq_notes = []
        for note in notes:
            if note not in seen:
                seen.add(note)
                uniq_notes.append(note)

        cid += 1
        in_group += len(indices)
        clusters.append(
            DuplicateCluster(
                cluster_id=cid,
                pmids=sorted(pmids, key=int),
                primary_reason=primary,
                confidence=conf,
                detail=detail,
                reviewer_notes=uniq_notes[:20],
            )
        )

    methodology = (
        "Duplicates are probable groups for human review. "
        "High: same normalized DOI, or same normalized title + same year. "
        "Medium: fuzzy title (ratio≥90 or token_sort≥92) within year+title-prefix blocks; "
        f"if both abstracts exist, token_sort≥{ABSTRACT_TOKEN_SORT_MIN} on abstract text. "
        "Retractions are flagged heuristically, not merged automatically with replacements."
    )

    return DedupReport(
        source_article_count=n,
        duplicate_group_count=len(clusters),
        articles_in_some_duplicate_group=in_group,
        methodology=methodology,
        clusters=clusters,
        stats={
            "fuzzy_pairs_compared": fuzzy_pairs_compared,
            "blocks_used": len(block),
        },
    )


def load_collection(path: str) -> CollectionOutput:
    """Load JSON written by ``collect-pubmed``."""
    return CollectionOutput.model_validate_json(Path(path).read_text(encoding="utf-8"))
