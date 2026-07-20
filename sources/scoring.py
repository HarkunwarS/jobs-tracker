"""
Relevance scoring v6: cosine similarity between job text and CV, plus
keyword boosts.

Fixes vs v5:
  - CV embedding cache is keyed by a CONTENT HASH, not mtime. Git checkout
    resets mtimes, so the v5 mtime check re-encoded the CV every run.
  - Job text uses up to 1000 chars of description (was 300).
  - Per-scope Telegram thresholds: Ireland alerts fire at a lower bar than
    abroad, because an Ireland match is worth interrupting your day for.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Dict, List

import numpy as np

_model = None
_cv_embedding = None

CORE_SKILL_PATTERNS = [re.compile(p, re.I) for p in [
    r"\bpython\b", r"\bjava\b(?!script)", r"\bjavascript\b", r"\breact\b",
    r"\bsql\b", r"\bspring\b", r"\bfull.?stack\b",
    r"\bdata\s+(science|scientist|engineer|engineering|analyst|analytics)\b",
    r"\bmachine\s+learning\b", r"\bml\s+engineer\b", r"\bai\b",
    r"\bbackend\b", r"\bsoftware\s+(engineer|developer)\b",
    r"\bdevops\b", r"\bcloud\b", r"\baws\b", r"\banalyst\b",
    r"\bbusiness intelligence\b", r"\bstatistic", r"\bsupply chain\b",
    r"\bproject\b", r"\bprogramme? manager\b",
]]

JUNIOR_PATTERNS = [re.compile(p, re.I) for p in [
    r"\bjunior\b", r"\bgraduate\b", r"\bgrad\b", r"\bassociate\b",
    r"\bentry.?level\b", r"\btrainee\b", r"\bnew\s+grad\b", r"\bintern",
    r"\bearly.?career\b", r"\bcampus\b",
]]

CORE_SKILL_BOOST = 0.08
JUNIOR_BOOST = 0.05
MAX_BOOST = 0.12


def _load_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    return _model


def get_cv_embedding(cv_path: str) -> np.ndarray:
    """Content-hash-keyed cache: survives git checkouts, invalidates on edit."""
    global _cv_embedding
    if _cv_embedding is not None:
        return _cv_embedding

    cv_path_obj = Path(cv_path)
    if not cv_path_obj.exists():
        raise FileNotFoundError(f"CV text file not found at {cv_path}")

    try:
        cv_text = cv_path_obj.read_text(encoding="utf-8")
    except Exception as e:
        raise IOError(f"Failed to read CV file {cv_path}: {e}")

    if not cv_text.strip():
        raise ValueError(f"CV file {cv_path} is empty")

    digest = hashlib.sha256(cv_text.encode("utf-8")).hexdigest()[:16]
    cache_path = cv_path_obj.with_stem(f"{cv_path_obj.stem}.{digest}").with_suffix(".npy")

    if cache_path.exists():
        try:
            _cv_embedding = np.load(cache_path)
            print(f"  ✓ CV embedding loaded from cache")
            return _cv_embedding
        except Exception as e:
            print(f"  ⚠️  Failed to load cached embedding: {e}, re-encoding…")

    # Clean stale hash caches, then encode fresh
    for old in cv_path_obj.parent.glob(f"{cv_path_obj.stem}.*.npy"):
        try:
            old.unlink(missing_ok=True)
        except Exception as e:
            print(f"  ⚠️  Failed to clean cache {old}: {e}")

    try:
        print(f"  📝 Encoding CV text ({len(cv_text)} chars)…")
        _cv_embedding = _load_model().encode(cv_text, normalize_embeddings=True)
    except Exception as e:
        raise RuntimeError(f"Failed to encode CV with model: {e}")

    # Try to save cache, but don't fail if we can't
    try:
        np.save(cache_path, _cv_embedding)
        print(f"  ✓ CV embedding cached")
    except Exception as e:
        print(f"  ⚠️  Failed to save CV cache: {e} (continuing without cache)")

    return _cv_embedding


def _keyword_boost(title: str) -> float:
    boost = 0.0
    if any(p.search(title) for p in CORE_SKILL_PATTERNS):
        boost += CORE_SKILL_BOOST
    if any(p.search(title) for p in JUNIOR_PATTERNS):
        boost += JUNIOR_BOOST
    return min(boost, MAX_BOOST)


def score_jobs(jobs: List[Dict], cv_path: str) -> List[Dict]:
    """Attach `score` to each job; return the list sorted by score desc."""
    if not jobs:
        return jobs

    try:
        cv_vec = get_cv_embedding(cv_path)
    except Exception as e:
        raise RuntimeError(f"Failed to get CV embedding: {e}")

    model = _load_model()

    texts = []
    for j in jobs:
        title = j.get("title", "")
        text = (f"{title}. {title}. "
                f"Company: {j.get('company', '')}. "
                f"Location: {j.get('location', '')}.")
        if j.get("description"):
            text += f" {j['description'][:1000]}"
        texts.append(text)

    try:
        print(f"  🔄 Encoding {len(texts)} job descriptions…")
        vecs = model.encode(texts, normalize_embeddings=True, batch_size=32)
        # Ensure cv_vec is 1D for proper matrix multiplication
        cv_vec = np.squeeze(cv_vec)
        cosines = (vecs @ cv_vec).tolist()
    except Exception as e:
        raise RuntimeError(f"Failed to encode jobs or compute similarities: {e}")

    for job, cosine in zip(jobs, cosines):
        boost = _keyword_boost(job.get("title", ""))
        job["cosine"] = round(float(cosine), 4)
        job["boost"] = round(boost, 4)
        job["score"] = round(float(cosine) + boost, 4)

    jobs.sort(key=lambda j: j["score"], reverse=True)
    print(f"  ✓ Scored {len(jobs)} jobs")
    return jobs


def route_jobs(jobs: List[Dict], scoring_cfg: Dict) -> tuple:
    """
    Split into (telegram_alerts, email_rest, dropped) using per-scope
    thresholds and a floor below which jobs are dropped entirely to keep
    the email readable.
    """
    thresholds = scoring_cfg.get("telegram_thresholds", {})
    default_thr = float(thresholds.get("default", 0.50))
    ireland_thr = float(thresholds.get("ireland", 0.44))
    floor = float(scoring_cfg.get("email_floor", 0.28))

    alerts, rest, dropped = [], [], []
    for j in jobs:
        score = j.get("score", 0.0)
        thr = ireland_thr if j.get("scope") == "ireland" else default_thr
        if score >= thr:
            alerts.append(j)
        elif score >= floor:
            rest.append(j)
        else:
            dropped.append(j)
    return alerts, rest, dropped
