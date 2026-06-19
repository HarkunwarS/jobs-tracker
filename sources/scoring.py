"""
Relevance scoring: cosine similarity between job description and your CV,
with keyword boost for your core skills and role types.

Fixes vs original:
  - Job text now includes description snippet (when available), not just title
  - Keyword boost: direct +0.08 if title matches your core skills
  - Junior/grad boost: +0.05 for entry-level signals
  - Threshold calibrated to 0.40 (realistic for title-only cosine similarity)

Score interpretation (re-calibrated):
  0.35 - 0.42  weak match — noise, skip
  0.42 - 0.48  decent match — relevant, email only
  0.48 - 0.55  good match — worth applying, Telegram
  0.55 +       strong match — drop everything, apply now
"""

import re
import os
from pathlib import Path
from typing import Dict, List

import numpy as np

_model = None
_cv_embedding = None

# ── Keyword boost config ─────────────────────────────────────────────────────

# Your core technical skills — if ANY appear in the title, add boost
CORE_SKILL_PATTERNS = [
    re.compile(r"\bpython\b", re.I),
    re.compile(r"\bjava\b(?!script)", re.I),   # Java but not JavaScript
    re.compile(r"\bjavascript\b", re.I),
    re.compile(r"\breact\b", re.I),
    re.compile(r"\bspring\b", re.I),
    re.compile(r"\bfull.?stack\b", re.I),
    re.compile(r"\bfullstack\b", re.I),
    re.compile(r"\bdata\s+(science|scientist|engineer|engineering|analyst)\b", re.I),
    re.compile(r"\bmachine\s+learning\b", re.I),
    re.compile(r"\bml\s+engineer\b", re.I),
    re.compile(r"\bai\s+engineer\b", re.I),
    re.compile(r"\bbackend\b", re.I),
    re.compile(r"\bsoftware\s+(engineer|developer)\b", re.I),
    re.compile(r"\bdevops\b", re.I),
    re.compile(r"\bcloud\s+(engineer|developer)\b", re.I),
    re.compile(r"\baws\b", re.I),
]

# Entry-level signals — your sweet spot, give a boost
JUNIOR_PATTERNS = [
    re.compile(r"\bjunior\b", re.I),
    re.compile(r"\bgraduate\b", re.I),
    re.compile(r"\bgrad\s+programme\b", re.I),
    re.compile(r"\bassociate\b", re.I),
    re.compile(r"\bentry.?level\b", re.I),
    re.compile(r"\btrainee\b", re.I),
    re.compile(r"\bnew\s+grad\b", re.I),
]

CORE_SKILL_BOOST = 0.08   # added to score if a core skill matches title
JUNIOR_BOOST = 0.05       # added if an entry-level signal is present
MAX_BOOST = 0.12          # cap total boost so a garbage job can't score high purely via keywords


def _load_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    return _model


def get_cv_embedding(cv_path: str) -> np.ndarray:
    global _cv_embedding
    if _cv_embedding is not None:
        return _cv_embedding

    cache_path = Path(cv_path).with_suffix(".embedding.npy")
    cv_path_obj = Path(cv_path)

    if not cv_path_obj.exists():
        raise FileNotFoundError(f"CV text file not found at {cv_path}")

    if cache_path.exists():
        cv_mtime = cv_path_obj.stat().st_mtime
        cache_mtime = cache_path.stat().st_mtime
        if cache_mtime > cv_mtime:
            _cv_embedding = np.load(cache_path)
            return _cv_embedding

    cv_text = cv_path_obj.read_text(encoding="utf-8")
    model = _load_model()
    _cv_embedding = model.encode(cv_text, normalize_embeddings=True)
    np.save(cache_path, _cv_embedding)
    return _cv_embedding


def _keyword_boost(title: str) -> float:
    """Return a score boost based on keyword matches in the job title."""
    boost = 0.0

    # Check core skills
    for pattern in CORE_SKILL_PATTERNS:
        if pattern.search(title):
            boost += CORE_SKILL_BOOST
            break  # one skill match is enough for the boost

    # Check junior/grad signals
    for pattern in JUNIOR_PATTERNS:
        if pattern.search(title):
            boost += JUNIOR_BOOST
            break

    return min(boost, MAX_BOOST)


def score_jobs(jobs: List[Dict], cv_path: str) -> List[Dict]:
    """
    Add a `score` field (cosine similarity + keyword boost) to each job.
    Returns the same list sorted by score desc.
    """
    if not jobs:
        return jobs

    cv_vec = get_cv_embedding(cv_path)
    model = _load_model()

    # Build richer text per job — use description if available
    job_texts = []
    for j in jobs:
        title = j.get("title", "")
        company = j.get("company", "")
        location = j.get("location", "")
        description = j.get("description", "")  # LinkedIn sometimes returns this

        # Title repeated 3x to weight it most heavily in the embedding
        text = (
            f"{title}. {title}. {title}. "
            f"Company: {company}. "
            f"Location: {location}."
        )
        if description:
            # Include first 300 chars of description if available
            text += f" {description[:300]}"

        job_texts.append(text)

    job_vecs = model.encode(job_texts, normalize_embeddings=True, batch_size=32)
    cosine_scores = (job_vecs @ cv_vec).tolist()

    for job, cosine in zip(jobs, cosine_scores):
        boost = _keyword_boost(job.get("title", ""))
        job["score"] = round(float(cosine) + boost, 4)
        job["cosine"] = round(float(cosine), 4)  # keep raw cosine for debugging
        job["boost"] = round(boost, 4)

    jobs.sort(key=lambda j: j["score"], reverse=True)
    return jobs


def split_by_threshold(jobs: List[Dict], threshold: float) -> tuple[List[Dict], List[Dict]]:
    high = [j for j in jobs if j.get("score", 0) >= threshold]
    rest = [j for j in jobs if j.get("score", 0) < threshold]
    return high, rest
