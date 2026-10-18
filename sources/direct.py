"""Public HTML listing adapter; registry declares exact hosts/selectors.

No login/CAPTCHA bypass. Pagination ends on exhausted/repeated pages, or an
explicit time budget (reported partial, never reported complete).
"""
from __future__ import annotations
import hashlib
import time
from urllib.parse import urljoin,urlsplit
import requests
from bs4 import BeautifulSoup
from sources.catalogue import ROLE,canonical_url
from sources.verification import HEADERS,job_schema,schema_fields
from sources.coverage import tracked,request_result,partial

def fetch_site(site,budget_seconds=90):
    url=site["url"];end=time.monotonic()+budget_seconds
    visited=set();keys=set();jobs=[];pending=[]
    while url and url not in visited:
        if time.monotonic()>=end:partial("listing time budget exhausted");break
        visited.add(url)
        try:
            r=requests.get(url,headers=HEADERS,timeout=15)
            request_result(status=r.status_code)
            if r.status_code!=200:break
            soup=BeautifulSoup(r.text,"html.parser")
            for a in soup.select(site["job_selector"]):
                link=canonical_url(urljoin(url,a.get("href","")))
                title=a.get_text(" ",strip=True)
                if not link or link in keys or not ROLE.search(title):continue
                keys.add(link)
                row=a.find_parent("tr")
                location=row.select_one(".colLocation") if row else None
                jobs.append({"id":"direct_"+hashlib.sha256(link.encode()).hexdigest()[:20],
                             "title":title,"company":site["name"],"link":link,
                             "location":location.get_text(" ",strip=True) if location else site.get("country_hint",""),
                             "source":site["name"],"posted":None,"description":""})
            for a in soup.select('.pagination a[href],a.page-numbers[href]'):
                other=urljoin(url,a.get('href',''))
                if other not in visited and other not in pending and urlsplit(other).hostname==urlsplit(site['url']).hostname:
                    pending.append(other)
            next_link=soup.select_one('a[rel="next"],a[aria-label="Next"],a.next')
            if not next_link and site.get("next_selector"):next_link=soup.select_one(site["next_selector"])
            url=urljoin(url,next_link.get("href","")) if next_link else None
            if not url and pending: url=pending.pop(0)
            if url and urlsplit(url).hostname!=urlsplit(site["url"]).hostname:
                partial("cross-host pagination not followed");break
        except requests.RequestException as exc:
            request_result(error=type(exc).__name__);break
    return jobs

def fetch_direct_sites(registry):
    jobs=[]
    for site in registry.get("sources",[]):
        if site.get("adapter")=="html_listing" and site.get("enabled"):
            jobs.extend(tracked("direct:"+site["name"],lambda s=site:fetch_site(s)))
    return jobs
