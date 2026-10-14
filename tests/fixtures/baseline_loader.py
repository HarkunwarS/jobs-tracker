"""Read immutable compressed test baseline without touching the live seen database."""
import base64
import gzip
from pathlib import Path

def original_seen_bytes():
    src = Path(__file__).with_name('baseline_seen_jobs.json.gz.b64').read_bytes().strip()
    return gzip.decompress(base64.b64decode(src))