"""CI-only commit with bounded push retry and lossless JSON merge on remote races.

Run only from a clean, ephemeral GitHub Actions checkout. Preserve recovery
artifacts using upload-artifact if all pushes fail, and stop the workflow.
"""
from __future__ import annotations

import copy
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sources.state import (load_json, save_json, validate_seen,
                           validate_outbox, validate_discovery)
from sources.outbox import empty_outbox
from sources.catalogue import validate_catalogue, validate_applications, empty_catalogue
from sources.discovery_store import export

DATA = Path("data")
PATHS = [DATA / "seen_jobs.json", DATA / "notification_outbox.json", DATA / "discovery_state.json"]
VALIDATORS = [validate_seen, validate_outbox, validate_discovery]
DEFAULTS = [{}, empty_outbox(), {"linkedin_last_sweep_at": ""}]
PATHS += [DATA / "vacancies.json", DATA / "applications.json", DATA / "discovery_report.json"]
VALIDATORS += [validate_catalogue, validate_applications, lambda x:x]
DEFAULTS += [empty_catalogue(), {"version":1,"records":{}}, {}]


def git(*args, check=True):
    p = subprocess.run(["git", *args], text=True, capture_output=True)
    if check and p.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {p.stderr[:500]}")
    return p


def merge_seen(local, remote):
    merged = dict(remote)
    for jid, day in local.items():
        if jid not in merged or day < merged[jid]:
            merged[jid] = day
    return validate_seen(merged)


def merge_outbox(local, remote):
    result = copy.deepcopy(remote)
    for jid, item in local["jobs"].items():
        if jid not in result["jobs"]:
            result["jobs"][jid] = copy.deepcopy(item)
            continue
        prior = result["jobs"][jid]
        for channel, state in item["channels"].items():
            old = prior["channels"].get(channel)
            if old is None:
                prior["channels"][channel] = copy.deepcopy(state)
            elif old["status"] == "sent" or state["status"] == "sent":
                # Either branch's receipt must prevail; never requeue sent.
                receipt = old if old["status"] == "sent" else state
                prior["channels"][channel] = copy.deepcopy(receipt)
                prior["channels"][channel]["attempts"] = max(old["attempts"], state["attempts"])
            elif state.get("last_attempt_at", "") > old.get("last_attempt_at", ""):
                prior["channels"][channel] = copy.deepcopy(state)
            else:
                prior["channels"][channel]["attempts"] = max(old["attempts"], state["attempts"])
    return validate_outbox(result)


def merge_discovery(local, remote):
    result = {**local, **remote}
    result["linkedin_last_sweep_at"] = max(local.get("linkedin_last_sweep_at", ""), remote.get("linkedin_last_sweep_at", ""))
    baseline = [x.get("baseline_initialized_at") for x in (local,remote) if x.get("baseline_initialized_at")]
    if baseline: result["baseline_initialized_at"] = min(baseline)
    return validate_discovery(result)


def merge_catalogue(local, remote):
    result = copy.deepcopy(remote)
    for key, job in local["jobs"].items():
        old = result["jobs"].get(key,{})
        newer,older = (job,old) if job.get("last_seen_at","") >= old.get("last_seen_at","") else (old,job)
        merged = {**older,**newer}
        merged["aliases"] = sorted(set(old.get("aliases",[])+job.get("aliases",[])))
        merged["sources"] = sorted(set(old.get("sources",[])+job.get("sources",[])))
        discovered=[j["date_discovered"] for j in (old,job) if j.get("date_discovered")]
        if discovered: merged["date_discovered"]=min(discovered)
        result["jobs"][key]=merged
    result["runs"] = sorted({__import__('json').dumps(r,sort_keys=True):r for r in local.get("runs",[])+remote.get("runs",[])}.values(),key=lambda r:r["at"])
    result["legacy_imported_at"] = remote.get("legacy_imported_at") or local.get("legacy_imported_at")
    return validate_catalogue(result)


def merge_applications(local, remote):
    result = copy.deepcopy(remote)
    for key, record in local["records"].items():
        old=result["records"].get(key,{})
        history=sorted({__import__('json').dumps(e,sort_keys=True):e for e in old.get("history",[])+record.get("history",[])}.values(),key=lambda e:e["at"])
        merged={**old,**record,"history":history}
        if history:merged.update(status=history[-1]["to"],updated_at=history[-1]["at"])
        result["records"][key]=merged
    return validate_applications(result)


def commit_if_changed(message):
    git("add", *(str(x) for x in PATHS if x.exists()), *(["data/vacancies.csv"] if Path("data/vacancies.csv").exists() else []))
    if git("diff", "--cached", "--quiet", check=False).returncode == 0:
        return False
    git("commit", "-m", message)
    return True


def main(branch):
    if branch != 'main':
        raise ValueError('State push prohibited: only main is an approved production state branch')
    if not (os.environ.get('GITHUB_ACTIONS') == 'true'
            and os.environ.get('GITHUB_REPOSITORY') == 'HarkunwarS/jobs-tracker'
            and os.environ.get('GITHUB_REF_NAME') == 'main'):
        raise ValueError('State push prohibited outside production GitHub Actions')
    import yaml
    cfg = yaml.safe_load(Path('config.yaml').read_text()) or {}
    if cfg.get('runtime', {}).get('mode') != 'production':
        raise ValueError('State push prohibited in staging mode; use disposable local remote')
    git("config", "user.name", "job-tracker-bot")
    git("config", "user.email", "bot@users.noreply.github.com")
    # Validate files before any commit/overwrite to avoid publishing damage.
    local = [load_json(path, val, default) for path, val, default in zip(PATHS, VALIDATORS, DEFAULTS)]
    commit_if_changed("chore: persist tracker state [skip ci]")
    for attempt in range(1, 4):
        push = git("push", "origin", f"HEAD:{branch}", check=False)
        if push.returncode == 0:
            print(f"✅ Tracker state pushed (attempt {attempt})")
            return 0
        print(f"⚠️ State push attempt {attempt} failed: {push.stderr[:350]}")
        if attempt == 3:
            break
        git("fetch", "origin", branch)
        # This script is ONLY for the ephemeral Actions checkout, and must
        # never run from a developer's working tree. Snapshot is held in RAM.
        git("reset", "--hard", "FETCH_HEAD")
        remote = [load_json(path, val, default) for path, val, default in zip(PATHS, VALIDATORS, DEFAULTS)]
        merged = [merge_seen(local[0], remote[0]), merge_outbox(local[1], remote[1]),
                  merge_discovery(local[2], remote[2]), merge_catalogue(local[3],remote[3]),
                  merge_applications(local[4],remote[4]), max((local[5],remote[5]),key=lambda r:r.get("at",""))]
        for path, data, val in zip(PATHS, merged, VALIDATORS):
            save_json(path, data, val)
        export(merged[3])
        local = merged
        commit_if_changed("chore: reconcile tracker state [skip ci]")
        time.sleep(2 ** attempt)
    raise RuntimeError("All GitHub state pushes failed; preserved state files must be recovered from workflow artifact")


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1] if len(sys.argv) == 2 else ""))
    except Exception as exc:
        print(f"❌ State persistence failed closed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
