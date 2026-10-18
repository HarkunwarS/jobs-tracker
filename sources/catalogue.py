"""Lossless vacancy catalogue and explicit, user-managed application history.

Discovery never changes application status. Unknown facts remain null. Scores
are transparent heuristics, not probabilities of getting an interview.
"""
from __future__ import annotations
import copy
import hashlib
import re
from datetime import datetime, timezone, date
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from bs4 import BeautifulSoup
from sources.filters import (scope_of, seniority_of, is_rejected_sector,
                             POSITIVE_SPONSORSHIP, NEGATIVE_SPONSORSHIP)
from sources.state import load_json, save_json, StateError

STATUSES = {"Discovered", "Shortlisted", "Planning to Apply", "Applied", "Assessment",
            "Interview", "Offer", "Rejected", "Withdrawn", "Closed"}
TRACKING = {"trk", "trid", "trackingid", "ref", "source", "gh_src", "lever-source",
            "rsid", "fbclid", "gclid", "mc_cid", "mc_eid"}
ROLE = re.compile(r"data|software|developer|python|java|backend|full.?stack|front.?end|"
                  r"machine learning|\bai\b|analytics|\bbi\b|reporting|business.*analyst|"
                  r"systems.*analyst|technology|digital|\bit\b|cloud|devops|platform|"
                  r"product.*analyst|operations.*analyst|project.*(?:analyst|coordinator|manager)|"
                  r"\bpmo\b|scrum|agile|technical.*(?:support|consult)|support.*engineer|"
                  r"quality.*(?:data|software)|test.*engineer|\bqa\b|solutions engineer|programme?.*(?:analyst|manager)|graduate.*consult", re.I)
SKILLS = {"python": r"\bpython\b", "java": r"\bjava\b", "sql": r"\bsql\b",
          "r": r"\br\b", "javascript": r"\bjavascript\b", "react": r"\breact\b",
          "spring boot": r"spring boot", "fastapi": r"fastapi", "flask": r"\bflask\b",
          "postgresql": r"postgres", "docker": r"docker", "aws": r"\baws\b",
          "azure": r"azure", "terraform": r"terraform", "git": r"\bgit\b",
          "machine learning": r"machine learning", "statistics": r"statistic|\bglm\b",
          "pandas": r"pandas", "numpy": r"numpy", "langchain": r"langchain|\brag\b",
          "agile": r"agile|scrum", "jira": r"jira", "data quality": r"data quality|data.integrity"}
GAPS = {"power bi": r"power\s*bi", "tableau": r"tableau", "spark": r"\bspark\b",
        "dbt": r"\bdbt\b", "snowflake": r"snowflake", "airflow": r"airflow"}

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def plain(value):
    return BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True)

def normal(value):
    return re.sub(r"[^a-z0-9]+", " ", plain(value).lower()).strip()

def canonical_url(url):
    try:
        s = urlsplit(url or "")
        if s.scheme not in ("http", "https") or not s.hostname:
            return ""
        host = s.hostname.lower().removeprefix("www.")
        path = re.sub(r"/+", "/", s.path).rstrip("/")
        if host.endswith("linkedin.com"):
            m = re.search(r"(?:/view/(?:.*-)?|currentJobId=)(\d+)", url)
            if m:
                return "https://www.linkedin.com/jobs/view/" + m.group(1)
        query = sorted((k, v) for k, v in parse_qsl(s.query) if
                       k.lower() not in TRACKING and not k.lower().startswith("utm_"))
        return urlunsplit(("https", host, path, urlencode(query), ""))
    except ValueError:
        return ""

def identities(job):
    result = []
    if job.get("id"):
        result.append("id:" + str(job["id"]))
    company = normal(job.get("company"))
    req = job.get("requisition_id")
    if req and company:
        result.append("req:" + company + ":" + str(req))
    url = canonical_url(job.get("canonical_url") or job.get("link"))
    if url:
        result.append("url:" + url)
    # Title/location are used to FLAG possible duplicates, not merge distinct reqs.
    return result

def eligibility(job):
    text = plain(" ".join(str(job.get(k) or "") for k in
                         ("description", "sponsorship_terms", "employer_restrictions")))
    sentences = re.split(r"(?<=[.!?])\s+|\n", text)
    evidence = [s[:800] for s in sentences if re.search(
        r"sponsor|visa|work (?:permit|authori)|right to work|stamp\s*[124]|citizen|international candidates|relocat", s, re.I)]
    negative = bool(NEGATIVE_SPONSORSHIP.search(text))
    positive = bool(POSITIVE_SPONSORSHIP.search(text)) and not negative
    international = bool(re.search(r"(?:welcome|accept|consider|open to).{0,70}international (?:candidates|applicants)|"
                                   r"international (?:candidates|applicants).{0,60}(?:welcome|considered|apply)", text, re.I))
    restriction = bool(re.search(r"stamp\s*4|(?:EU|EEA|European Union)\s+(?:citizens?\s+only|citizenship\s+(?:required|essential))|"
                                 r"(?:must|require|hold|have).{0,55}unrestricted.{0,25}(?:right|authori)|"
                                 r"without.{0,40}(?:permit|sponsorship).{0,30}(?:future|now)", text, re.I))
    return {"sponsorship": "not_offered" if negative else "employer_stated" if positive else
            "source_reported" if job.get("sponsors_visa") is True else "unknown",
            "international_candidates": "explicitly_considered" if international else "unknown",
            "relocation": "mentioned" if re.search(r"relocation (?:support|assistance|package)", text, re.I) else "unknown",
            "stamp_1g": "mentioned" if re.search(r"stamp\s*1g", text, re.I) else "not_mentioned",
            "restriction_flag": restriction, "evidence": evidence,
            "candidate_permission": "unconfirmed"}

def geography(job):
    loc = " ".join(str(job.get(k) or "") for k in ("country", "location"))
    if re.search(r"northern ireland|belfast|londonderry", loc, re.I):
        return 2
    if job.get("scope") == "ireland" or re.search(r"\bireland\b|\bIRL\b|^IE$", loc, re.I):
        return 1
    if re.search(r"uk|united kingdom|england|scotland|wales|europe|germany|netherlands|france|spain|poland|sweden|switzerland|denmark|finland|portugal|austria|belgium|norway", loc, re.I):
        return 2
    if re.search(r"uae|united arab emirates|dubai|singapore|malaysia|japan|tokyo", loc, re.I):
        return 3
    return 4

def rank(job, today=None):
    today = today or date.today()
    text = plain(job.get("description"))
    title = job.get("title", "")
    combined = title + " " + text
    skills = [s for s,p in SKILLS.items() if re.search(p, combined, re.I)]
    gaps = [s for s,p in GAPS.items() if re.search(p, combined, re.I)]
    early = bool(re.search(r"graduate|junior|associate|entry.level|early.career|\b[01] ?[-–] ?[23] years", combined, re.I))
    years = [int(m.group(1)) for m in re.finditer(r"\b(\d+)\s*(?:\+|[-–]\s*\d+)?\s*(?:years|yrs).{0,30}experience", text, re.I)]
    minimum = min(years) if years else None
    signal = eligibility(job)
    geo = geography(job)
    score = {1:40,2:20,3:10,4:5}[geo] + min(len(skills)*4,28) + (15 if early else 0)
    if signal["sponsorship"] == "employer_stated": score += 8
    if signal["international_candidates"] == "explicitly_considered": score += 4
    if signal["stamp_1g"] == "mentioned": score += 3
    days = None
    try: days = (date.fromisoformat(str(job.get("deadline"))[:10])-today).days
    except (ValueError,TypeError): pass
    if days is not None and 0 <= days <= 7: score += 10
    try:
        age = (today-date.fromisoformat(str(job.get("posted"))[:10])).days
        if job.get("posted_kind") != "updated" and 0 <= age <= 14: score += 5
    except (ValueError,TypeError): pass
    issues = []
    if not text: issues.append("Full job description not verified")
    if minimum and minimum > 1: issues.append(f"Experience wording includes {minimum}+ years; review mandatory/preferred context")
    graduation = re.search(r"(?:graduating in|graduate in|graduation (?:date|year)|class of).{0,15}\b(202[7-9])\b", text, re.I)
    if graduation: issues.append("Later graduation cohort specified; candidate graduated in 2026")
    if re.search(r"\bintern(?:ship)?\b|\bco.op\b|placement", title, re.I): issues.append("Internship/placement; full-time graduate eligibility needs review")
    if signal["restriction_flag"]: issues.append("Explicit work-authorisation restriction")
    if geo > 1 and signal["sponsorship"] not in ("employer_stated","source_reported") and signal["international_candidates"] != "explicitly_considered":
        issues.append("International hiring support unverified")
    if job.get("scope") == "eligibility_unverified": issues.append("Country/remote-work scope requires verification")
    priority = "High Priority" if early and len(skills)>=2 else "Good Match"
    if minimum and minimum >=3: priority="Stretch Opportunity"
    if issues: priority="Eligibility Check Required"
    if days is not None and days < 0: priority="Closed"
    if days is not None and 0<=days<=3 and not issues and job.get("verification_status") == "open": priority="Apply Now"
    return {"priority":priority,"rank_score":max(0,min(score,100)),"geographic_priority":geo,
            "matched_skills":skills,"skills_not_evidenced":gaps,"review_flags":issues,
            "eligibility":signal,"experience_years_mentioned":minimum,
            "base_cv":"DS" if re.search(r"data|analytics|machine learning|\bai\b|\bbi\b",title,re.I) else "SE",
            "score_method":"Evidence keywords + geography + early-career + recency/deadline; not a probability"}

def empty_catalogue(): return {"version":1,"jobs":{},"runs":[]}

def validate_catalogue(data):
    if not isinstance(data,dict) or data.get("version")!=1 or not isinstance(data.get("jobs"),dict):
        raise StateError("Invalid vacancy catalogue")
    for key, job in data["jobs"].items():
        if not isinstance(job,dict) or not isinstance(job.get("aliases",[]),list):
            raise StateError("Invalid catalogue record: "+str(key))
    return data

def update_catalogue(catalogue, jobs, cfg, timestamp=None):
    stamp=timestamp or now()
    index={alias:key for key,j in catalogue["jobs"].items() for alias in j.get("aliases",[])}
    counts={"new":0,"updated":0,"duplicates":0,"out_of_scope":0}
    touched=set()
    for raw in jobs:
        if not raw.get("title") or not raw.get("link"): continue
        title=raw["title"]
        if not ROLE.search(title) or is_rejected_sector(title) or seniority_of(title,plain(raw.get("description")))=="senior":
            counts["out_of_scope"]+=1;continue
        job=copy.deepcopy(raw)
        job["description"]=plain(job.get("description"))
        job["scope"]=scope_of(job,cfg) or job.get("scope") or "eligibility_unverified"
        signal=eligibility(job)
        irish_uncertain = job["scope"]=="eligibility_unverified" and re.search(r"\b(?:dublin|cork|galway|limerick|athlone|letterkenny|waterford|kilkenny|sligo|ireland)\b",job.get("location", ""),re.I)
        if geography(job)>1 and not irish_uncertain and not (
            signal["sponsorship"] in ("employer_stated","source_reported") or signal["international_candidates"]=="explicitly_considered"):
            counts["out_of_scope"]+=1;continue
        aliases=identities(job)
        if not aliases:continue
        matches={index[a] for a in aliases if a in index}
        key=sorted(matches)[0] if matches else hashlib.sha256(aliases[0].encode()).hexdigest()[:20]
        old=catalogue["jobs"].get(key,{})
        if key in touched: counts["duplicates"]+=1
        counts["updated" if old else "new"]+=1
        # Never erase existing enrichment with an empty listing-card field.
        merged={**old,**{k:v for k,v in job.items() if v not in (None, "", [], {})}}
        merged["aliases"]=sorted(set(old.get("aliases",[])+aliases))
        merged["sources"]=sorted(set(old.get("sources",[])+[str(job.get("source") or "unknown")]))
        merged["date_discovered"]=old.get("date_discovered",stamp)
        merged["last_seen_at"]=stamp
        merged["canonical_url"]=canonical_url(merged.get("link"))
        merged.setdefault("verification_status","unverified")
        for field in ("deadline","salary","work_model","qualifications","required_skills","preferred_skills","date_last_verified"):
            merged.setdefault(field,None)
        merged.update(rank(merged))
        if merged.get("deadline") and str(merged["deadline"])[:10] < stamp[:10]:
            merged["verification_status"]="closed_deadline"
        catalogue["jobs"][key]=merged
        for alias in merged["aliases"]: index[alias]=key
        touched.add(key)
    groups={}
    for key,j in catalogue["jobs"].items():
        fingerprint=(normal(j.get("company")),normal(j.get("title")),normal(j.get("location")))
        groups.setdefault(fingerprint,[]).append(key)
        j["possible_duplicate_ids"]=[]
        # Age is a review flag, never evidence that a vacancy is closed.
        try: j["stale_review_required"]=(date.fromisoformat(stamp[:10])-date.fromisoformat(j.get("date_last_verified")[:10])).days>7
        except (ValueError,TypeError): j["stale_review_required"]=True
    for keys in groups.values():
        if len(keys)>1:
            for key in keys: catalogue["jobs"][key]["possible_duplicate_ids"]=[k for k in keys if k!=key]
    catalogue["runs"].append({"at":stamp,**counts})
    return counts

def validate_applications(data):
    if not isinstance(data,dict) or data.get("version")!=1 or not isinstance(data.get("records"),dict):
        raise StateError("Invalid application ledger")
    for record in data["records"].values():
        if record.get("status") not in STATUSES or not isinstance(record.get("history"),list):
            raise StateError("Invalid application status/history")
    return data

def set_status(ledger,key,status,note="",timestamp=None):
    if status not in STATUSES: raise ValueError("Unsupported status")
    stamp=timestamp or now()
    record=ledger["records"].setdefault(key,{"status":"Discovered","history":[]})
    record["history"].append({"at":stamp,"from":record["status"],"to":status,"note":note})
    record.update(status=status,updated_at=stamp)
    return ledger
