"""Connect the additive catalogue to the existing discovery/outbox pipeline."""
from __future__ import annotations
import csv
import json
from datetime import datetime,timezone,timedelta
from pathlib import Path
from collections import Counter
from sources.catalogue import (empty_catalogue,validate_catalogue,update_catalogue,
                               identities,rank,ROLE,now,geography)
from sources.filters import seniority_of,scope_of
from sources.coverage import reports
from sources.verification import verify_candidates
from sources.state import load_json,save_json

CATALOGUE=Path("data/vacancies.json")
REPORT=Path("data/discovery_report.json")

def refresh(jobs,outbox,cfg):
    catalogue=load_json(CATALOGUE,validate_catalogue,empty_catalogue())
    if not catalogue.get("legacy_imported_at"):
        update_catalogue(catalogue,[dict(e["job"],legacy_notification_record=True)
                         for e in outbox["jobs"].values()],cfg)
        catalogue["legacy_imported_at"]=now()
    known={a for entry in outbox["jobs"].values() for a in identities(entry["job"])}
    prior={a:j for j in catalogue["jobs"].values() for a in j.get("aliases",[])}
    candidates=[]
    candidate_ids=set()
    fetched_aliases={a for job in jobs for a in identities(job)}
    historical_checks=[]
    for old in catalogue["jobs"].values():
        if any(a in fetched_aliases for a in old.get("aliases",[])):continue
        if old.get("verification_status") in ("closed","closed_deadline"):continue
        try:
            attempted=datetime.fromisoformat((old.get("verification_attempted_at") or old.get("date_last_verified") or "").replace("Z","+00:00"))
            stale=attempted < datetime.now(timezone.utc)-timedelta(days=7)
        except (ValueError,TypeError):stale=True
        if stale and old.get("id"):
            historical_checks.append(dict(old))
    for job in jobs:
        if not ROLE.search(job.get("title", "")) or seniority_of(job.get("title", ""),job.get("description", ""))=="senior":continue
        if scope_of(job,cfg) is None and job.get("source")!="gradireland":continue
        old=next((prior[a] for a in identities(job) if a in prior),{})
        checked=old.get("date_last_verified")
        try:
            recent=datetime.fromisoformat(checked.replace("Z","+00:00")) > datetime.now(timezone.utc)-timedelta(hours=24)
        except (ValueError,TypeError,AttributeError):recent=False
        if recent and old.get("verification_status")=="open":
            job.update({k:v for k,v in old.items() if k not in ("id","aliases","sources","last_seen_at") and v not in (None,"",[],{})})
        elif job["id"] not in candidate_ids:
            candidates.append(job); candidate_ids.add(job["id"])
    candidates += [j for j in historical_checks if j["id"] not in candidate_ids]
    candidates.sort(key=lambda j:(geography(j),-rank(j)["rank_score"]))
    verified=verify_candidates(candidates,budget_seconds=cfg.get("catalogue",{}).get("verification_seconds",300))
    updates={j["id"]:j for j in verified}
    jobs=[updates.get(j["id"],j) for j in jobs]
    # Strong IDs / canonical URLs / company requisition IDs only. Possible
    # fuzzy duplicates remain separate and are exposed for manual review.
    aliases=set();unique=[];suppressed=set();merged_count=0
    for job in sorted(jobs,key=lambda j:(j.get("source") in ("LinkedIn","Jooble"),-len(j.get("description") or ""))):
        keys=identities(job)
        if any(k in known for k in keys):suppressed.add(job["id"])
        if any(k in aliases for k in keys):merged_count+=1;continue
        aliases.update(keys);unique.append(job)
    historical_updates=[updates[j["id"]] for j in historical_checks if j["id"] in updates]
    counts=update_catalogue(catalogue,jobs+historical_updates,cfg)
    save_json(CATALOGUE,catalogue,validate_catalogue)
    records=list(catalogue["jobs"].values())
    report={"at":now(),"raw_jobs":len(jobs),"unique_jobs":len(unique),"strong_duplicates":merged_count,
            "catalogue_records":len(records),"catalogue_changes":counts,
            "verification":dict(Counter(j.get("verification_status","unverified") for j in records)),
            "geography":dict(Counter(str(j.get("geographic_priority")) for j in records)),
            "priority":dict(Counter(j.get("priority","unknown") for j in records)),
            "sources":reports(reset=True),
            "historical_rechecks":len(historical_updates),
            "verified_open_ireland":sum(j.get("geographic_priority")==1 and j.get("verification_status")=="open" for j in records),
            "possible_duplicate_records":sum(bool(j.get("possible_duplicate_ids")) for j in records),
            "stale_review_records":sum(j.get("stale_review_required",True) for j in records),
            "limitations":["Unknown work permission requires candidate confirmation",
                "Search portals and failed ATS endpoints are not counted as automated coverage",
                "HTTP 200 is not sufficient to verify a vacancy",
                "Time budgets defer checks; there is no 20/50-job catalogue limit",
                "Legacy seen IDs are discovery history, not application records"]}
    save_json(REPORT,report,lambda x:x)
    export(catalogue)
    print("CATALOGUE_REPORT "+json.dumps({k:v for k,v in report.items() if k!="sources"}))
    return unique,suppressed

def export(catalogue,path=Path("data/vacancies.csv")):
    fields=["catalogue_id","company","title","location","country","work_model","priority","rank_score",
            "base_cv","verification_status","posted","deadline","salary","date_discovered","date_last_verified",
            "link","review_flags","matched_skills","skills_not_evidenced","eligibility"]
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",newline="",encoding="utf-8") as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for key,job in sorted(catalogue["jobs"].items(),key=lambda kv:(kv[1].get("geographic_priority",4),-kv[1].get("rank_score",0))):
            row={field:job.get(field) for field in fields};row["catalogue_id"]=key
            for field,value in row.items():
                if isinstance(value,(dict,list)):row[field]=json.dumps(value,ensure_ascii=False)
                if isinstance(row[field],str) and row[field].startswith(("=","+","-","@")):row[field]="'"+row[field]
            writer.writerow(row)
