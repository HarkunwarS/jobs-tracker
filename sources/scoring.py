"""
Relevance scoring: cosine similarity between job description and your CV.

Uses sentence-transformers/all-MiniLM-L6-v2 — 22MB, runs in <1s per job on
GitHub Actions free tier. The CV embedding is computed once per run and
cached. Each job is embedded once.

Score interpretation (rough, calibrated for tech CVs):
  0.30 - 0.45  weak match — probably noise
  0.45 - 0.55  decent match — relevant role but not a perfect fit
  0.55 - 0.65  strong match — good shot, Telegram-worthy
  0.65 +       very strong — drop everything and apply
"""

import os
from pathlib import Path
from typing import Dict, List

import numpy as np

# Lazy import — only load the model when scoring is actually called.
# Saves ~3s on cold runs when there are no new jobs.
_model = None
_cv_embedding = None


def _load_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    return _model


def get_cv_embedding(cv_path: str) -> np.ndarray:
    """Embed the CV once and cache the result on disk to skip re-embedding."""
    global _cv_embedding
    if _cv_embedding is not None:
        return _cv_embedding

    cache_path = Path(cv_path).with_suffix(".embedding.npy")
    cv_path_obj = Path(cv_path)

    if not cv_path_obj.exists():
        raise FileNotFoundError(
            f"CV text file not found at {cv_path}. "
            f"Create it with: copy your CV's text into {cv_path}"
        )

    # Use cached embedding if the CV file hasn't changed since the cache was made
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


def score_jobs(jobs: List[Dict], cv_path: str) -> List[Dict]:
    """
    Add a `score` field to each job dict, in-place.
    Embeds in batch for speed. Returns the same list, sorted by score desc.
    """
    if not jobs:
        return jobs

    cv_vec = get_cv_embedding(cv_path)
    model = _load_model()

    # Compose searchable text per job. Title is most important — repeat it
    # to weight it higher in the encoder.
    job_texts = [
        f"{j['title']}. {j['title']}. "
        f"Company: {j.get('company','')}. "
        f"Location: {j.get('location','')}."
        for j in jobs
    ]

    job_vecs = model.encode(job_texts, normalize_embeddings=True, batch_size=32)

    # Since both are normalised, dot product = cosine similarity
    scores = (job_vecs @ cv_vec).tolist()
    for job, score in zip(jobs, scores):
        job["score"] = float(score)

    jobs.sort(key=lambda j: j["score"], reverse=True)
    return jobs


def split_by_threshold(jobs: List[Dict], threshold: float) -> tuple[List[Dict], List[Dict]]:
    """Partition jobs into (high_relevance, rest) using the threshold."""
    high = [j for j in jobs if j.get("score", 0) >= threshold]
    rest = [j for j in jobs if j.get("score", 0) < threshold]
    return high, rest
