"""Public vacancy-page checks with explicit uncertainty and structured evidence."""
from __future__ import annotations
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from urllib.parse import urlsplit, urljoin
from difflib import SequenceMatcher
import requests
from bs4 import BeautifulSoup
from sources.catalogue import plain, now, rank, canonical_url

HEADERS={"User-Agent":"IrelandCareerTracker/7 (personal vacancy research)","Accept":"text/html,application/json"}
CLOSED=re.compile(r"(?:this (?:job|position|vacancy).{0,25}(?:no longer available|has (?:been filled|expired|closed)))|"
                  r"(?:no longer accepting applications)|(?:job posting (?:has expired|is closed))",re.I)

def job_schema(html):
    soup=BeautifulSoup(html,"html.parser")
    found=[]
    def visit(item):
        if isinstance(item,list):
            for value in item:visit(value)
        elif isinstance(item,dict):
            kind=item.get("@type",[])
            if kind=="JobPosting" or isinstance(kind,list) and "JobPosting" in kind:found.append(item)
            if "@graph" in item:visit(item["@graph"])
    for node in soup.select('script[type="application/ld+json"]'):
        try:visit(json.loads(node.string or node.get_text()))
        except (ValueError,TypeError):continue
    return found

def schema_fields(schema):
    fields={"title":schema.get("title"),"description":plain(schema.get("description")),
            "posted":schema.get("datePosted"),"posted_kind":"published",
            "deadline":schema.get("validThrough"),"employment_type":schema.get("employmentType"),
            "qualifications":plain(schema.get("qualifications")) or None,
            "required_skills":plain(schema.get("skills")) or None,
            "experience_requirements":plain(schema.get("experienceRequirements")) or None,
            "salary":schema.get("baseSalary")}
    org=schema.get("hiringOrganization") or {}
    if isinstance(org,dict):fields["company"]=org.get("name")
    identifier=schema.get("identifier")
    fields["requisition_id"]=identifier.get("value") if isinstance(identifier,dict) else identifier
    locations=schema.get("jobLocation") or []
    if isinstance(locations,dict):locations=[locations]
    addresses=[l.get("address",{}) for l in locations if isinstance(l,dict)]
    cities=[];countries=[]
    for a in addresses:
        if not isinstance(a,dict):continue
        country=a.get("addressCountry","")
        if isinstance(country,dict):country=country.get("name","")
        countries.append(country)
        cities.append(", ".join(str(x) for x in (a.get("addressLocality"),a.get("addressRegion"),country) if x))
    if cities:fields["location"]="; ".join(cities)
    if len(set(countries))==1:fields["country"]=countries[0]
    if schema.get("jobLocationType")=="TELECOMMUTE":fields["work_model"]="Remote"
    return {k:v for k,v in fields.items() if v not in (None,"",[],{})}

def public_url(url):
    try:
        parts=urlsplit(url)
        host=parts.hostname or ""
        return parts.scheme in ("https","http") and "." in host and not parts.username and not re.match(
            r"^(?:localhost|127\.|10\.|192\.168\.|169\.254\.|172\.(?:1[6-9]|2\d|3[01])\.)",host)
    except ValueError:return False

def detail_url(job):
    """Use only observed public ATS detail routes on known ATS hosts."""
    url=job.get("detail_api","")
    if url and public_url(url) and (urlsplit(url).hostname or "").endswith((".myworkdayjobs.com",".smartrecruiters.com")):
        return url
    parts=urlsplit(job.get("link", ""))
    if (parts.hostname or "").endswith(".myworkdayjobs.com"):
        pieces=parts.path.strip("/").split("/")
        if "job" in pieces:
            index=pieces.index("job")
            if index:
                tenant=parts.hostname.split(".")[0]
                board=pieces[index-1]
                return f"https://{parts.hostname}/wday/cxs/{tenant}/{board}/"+"/".join(pieces[index:])
    return ""

def ats_detail(job,get):
    url=detail_url(job)
    if not url:return None
    response=get(url,headers=HEADERS,timeout=15)
    if response.status_code!=200:return None
    try:data=response.json()
    except (ValueError,TypeError):return None
    info=data.get("jobPostingInfo")
    if isinstance(info,dict) and info.get("canApply") is False:
        return {"verification_status":"closed", "detail_evidence_url":url,
                "verification_evidence":"ATS explicitly reports canApply=false"}
    if isinstance(info,dict) and info.get("title") and info.get("jobDescription") and info.get("canApply") is not False:
        return {"title":info["title"],"description":plain(info["jobDescription"]),
                "location":info.get("location",job.get("location")),"posted":info.get("startDate"),
                "posted_kind":"published","requisition_id":info.get("jobReqId"),
                "employment_type":info.get("timeType"),"detail_evidence_url":url}
    if data.get("name") and data.get("jobAd"):
        sections=data["jobAd"].get("sections",{})
        description=" ".join(plain(x.get("text")) for x in sections.values() if isinstance(x,dict))
        if description:return {"title":data["name"],"description":description,"detail_evidence_url":url}
    return None

def verify(job, get=None):
    result=dict(job)
    url=job.get("link","")
    result["verification_attempted_at"]=now()
    if not public_url(url):
        result["verification_status"]="invalid_url";return result
    try:
        detail=ats_detail(job,get or requests.get)
        if detail and detail.get("verification_status")=="closed":
            result.update(detail,date_last_verified=now())
            result.update(rank(result))
            return result
        if detail:
            result.update({k:v for k,v in detail.items() if v not in (None,"",[],{})})
            result.update(verification_status="open",date_last_verified=now(),verification_evidence="Live public ATS vacancy detail with title and description")
            if result.get("deadline") and str(result["deadline"])[:10] < date.today().isoformat(): result["verification_status"]="closed_deadline"
            result.update(rank(result))
            return result
        response=(get or requests.get)(url,headers=HEADERS,timeout=15)
        result["http_status"]=response.status_code
        if response.status_code in (404,410):
            result.update(verification_status="unavailable",date_last_verified=now(),verification_evidence=f"HTTP {response.status_code}")
            return result
        if response.status_code!=200:
            result.update(verification_status="access_blocked",verification_evidence=f"HTTP {response.status_code}; not closure evidence")
            return result
        html=response.text
        soup=BeautifulSoup(html,"html.parser")
        schemas=job_schema(html)
        text=soup.get_text(" ",strip=True)
        if re.search(r"verify (?:you are|you're) human|access denied|captcha",text[:2000],re.I):
            result["verification_status"]="access_blocked";return result
        if CLOSED.search(text):
            result.update(verification_status="closed",date_last_verified=now(),verification_evidence="Explicit vacancy closure text")
            return result
        # Only one JobPosting is safe to associate with this vacancy URL.
        title_match = len(schemas)==1 and SequenceMatcher(None,plain(schemas[0].get("title")).lower(),plain(job.get("title")).lower()).ratio() >= .55
        if title_match:
            result.update(schema_fields(schemas[0]))
            result.update(verification_status="open",date_last_verified=now(),verification_evidence="JobPosting structured data on vacancy detail page")
        else:
            title=plain(job.get("title","")).lower()
            htext=" ".join(n.get_text(" ",strip=True) for n in soup.select("h1,h2")).lower()
            apply=any(re.search(r"apply(?: now| for| to|$)",a.get_text(" ",strip=True),re.I) for a in soup.select("a,button"))
            if title and title in htext and apply:
                result.update(verification_status="open",date_last_verified=now(),verification_evidence="Matching vacancy heading and application control")
                body=soup.select_one('[itemprop="description"],.jobdescription,.job-description,.jdp-job-description,main,article')
                if body:result["description"]=plain(str(body))
            else:
                result["verification_status"]="unverified"
                result["verification_evidence"]="HTTP 200 alone is not evidence of an open vacancy"
        # A redirect to a generic careers landing page is not a working vacancy link.
        if response.url and public_url(response.url):result["resolved_url"]=response.url
        if result.get("deadline") and str(result["deadline"])[:10] < date.today().isoformat():
            result["verification_status"]="closed_deadline"
        if not result.get("work_model"):
            desc=plain(result.get("description"))
            if re.search(r"\bhybrid\b",desc,re.I):result["work_model"]="Hybrid (description)"
        result.update(rank(result))
        return result
    except requests.RequestException as exc:
        result.update(verification_status="request_failed",verification_evidence=type(exc).__name__)
        return result

def verify_candidates(jobs, budget_seconds=300, workers=6):
    deadline=time.monotonic()+budget_seconds
    def task(job):
        if time.monotonic()>=deadline:
            return dict(job,verification_status="deferred_budget",verification_evidence="Run time budget exhausted; retry next scan")
        return verify(job)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(task,jobs))
