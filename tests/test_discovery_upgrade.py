import unittest
import os
from unittest.mock import patch
from types import SimpleNamespace
from datetime import date
from sources.catalogue import (canonical_url,empty_catalogue,update_catalogue,
                               eligibility,rank,set_status)
from sources.verification import verify,schema_fields
from sources.ats import fetch_smartrecruiters,fetch_workday,fetch_ashby,fetch_lever
from sources.aggregators import fetch_arbeitnow,fetch_jooble,fetch_adzuna

CFG={"locations":{"ireland":True},"filtering":{"international_candidates":True}}
def job(**kw):
    return {"id":"one","title":"Graduate Software Engineer","company":"Example",
            "location":"Cork, Ireland","link":"https://example.com/jobs/1",
            "description":"Python and SQL. Graduate role.",**kw}
def response(data=None,html="",status=200):
    return SimpleNamespace(json=lambda:data,text=html,status_code=status,url="https://example.com/jobs/1")

class DiscoveryUpgradeTests(unittest.TestCase):
    def test_url_dedup_retains_meaningful_query(self):
        self.assertEqual(canonical_url("https://example.com/job?jobId=1&utm_source=x#apply"),"https://example.com/job?jobId=1")
        self.assertNotEqual(canonical_url("https://example.com/job?jobId=1"),canonical_url("https://example.com/job?jobId=2"))
    def test_cross_source_url_merges_history(self):
        c=empty_catalogue();update_catalogue(c,[job()],CFG,"2026-10-01T00:00:00Z")
        update_catalogue(c,[job(id="two",source="Other",link="https://example.com/jobs/1?utm_source=x",description="")],CFG,"2026-10-18T00:00:00Z")
        self.assertEqual(len(c["jobs"]),1)
        item=next(iter(c["jobs"].values()))
        self.assertEqual(item["date_discovered"],"2026-10-01T00:00:00Z")
        self.assertIn("Python",item["description"])
    def test_different_requisitions_not_fuzzy_merged(self):
        c=empty_catalogue();update_catalogue(c,[job(requisition_id="1"),job(id="two",link="https://example.com/jobs/2",requisition_id="2")],CFG)
        self.assertEqual(len(c["jobs"]),2)
        self.assertTrue(all(j["possible_duplicate_ids"] for j in c["jobs"].values()))
    def test_discovery_does_not_change_application(self):
        ledger={"version":1,"records":{}};set_status(ledger,"one","Applied","User confirmed")
        c=empty_catalogue();update_catalogue(c,[job()],CFG)
        self.assertEqual(ledger["records"]["one"]["status"],"Applied")
        self.assertEqual(len(ledger["records"]["one"]["history"]),1)
    def test_ireland_no_visa_wording_retained(self):
        c=empty_catalogue();update_catalogue(c,[job()],CFG);self.assertEqual(len(c["jobs"]),1)
        self.assertEqual(eligibility(job())["sponsorship"],"unknown")
    def test_international_not_sponsorship(self):
        e=eligibility(job(description="We welcome international candidates. Relocation support available."))
        self.assertEqual(e["international_candidates"],"explicitly_considered")
        self.assertEqual(e["sponsorship"],"unknown")
    def test_explicit_restriction_flagged(self):
        self.assertTrue(eligibility(job(description="You must hold unrestricted right to work in Ireland."))["restriction_flag"])
    def test_false_sponsorship_not_inferred_from_query(self):
        with patch("sources.aggregators.requests.get",return_value=response({"data":[{"slug":"x","title":"Developer"}]})):
            jobs=fetch_arbeitnow(pages=1)
        self.assertFalse(jobs[0]["sponsors_visa"])
    def test_http_200_not_open(self):
        self.assertEqual(verify(job(),get=lambda *a,**k:response(html="Careers home"))["verification_status"],"unverified")
    def test_block_not_expiry(self):
        self.assertEqual(verify(job(),get=lambda *a,**k:response(status=403))["verification_status"],"access_blocked")
    def test_expired_structured_job(self):
        html='<script type="application/ld+json">{"@type":"JobPosting","title":"Graduate Software Engineer","validThrough":"2020-01-01"}</script>'
        self.assertEqual(verify(job(),get=lambda *a,**k:response(html=html))["verification_status"],"closed_deadline")
    def test_structured_fields(self):
        fields=schema_fields({"datePosted":"2026-10-17","validThrough":"2026-10-20","jobLocation":{"address":{"addressLocality":"Cork","addressCountry":"IE"}},"baseSalary":{"currency":"EUR","value":40000}})
        self.assertEqual(fields["country"],"IE");self.assertEqual(fields["salary"]["currency"],"EUR")
    def test_later_graduation_flag(self):
        r=rank(job(description="Graduating in 2027. Python SQL."),date(2026,10,18))
        self.assertEqual(r["priority"],"Eligibility Check Required")
    def test_smartrecruiters_fetches_beyond_first_page(self):
        pages=[response({"content":[{"id":str(i)} for i in range(100)],"totalFound":101}),response({"content":[{"id":"last"}],"totalFound":101})]
        with patch("sources.ats._safe_get",side_effect=pages) as get:
            self.assertEqual(len(fetch_smartrecruiters("Example","example")),101)
            self.assertIn("offset=100",get.call_args.args[0])
    def test_workday_pagination(self):
        pages=[response({"jobPostings":[{"externalPath":"/job/one"}],"total":2}),response({"jobPostings":[{"externalPath":"/job/two"}],"total":2})]
        with patch("sources.ats.requests.post",side_effect=pages):self.assertEqual(len(fetch_workday("Example","example",1,"External")),2)
    def test_ashby_missing_ids_still_unique_and_correct_fields(self):
        data={"jobs":[{"title":"Engineer","location":"Cork","jobUrl":"https://example.com/1","publishedAt":"2026-10-18"},{"title":"Analyst","location":"Dublin","jobUrl":"https://example.com/2"}]}
        with patch("sources.ats._safe_get",return_value=response(data)):
            jobs=fetch_ashby("Example","example")
        self.assertNotEqual(jobs[0]["id"],jobs[1]["id"]);self.assertEqual(jobs[0]["location"],"Cork")
        self.assertEqual(jobs[0]["posted"],"2026-10-18")
    def test_lever_milliseconds(self):
        with patch("sources.ats._safe_get",return_value=response([{"id":"1","createdAt":0}])):
            self.assertTrue(fetch_lever("Example","example")[0]["posted"].startswith("1970-01-01"))
    def test_irrelevant_engineering_not_retained(self):
        c=empty_catalogue();update_catalogue(c,[job(title="Graduate Rail Engineer")],CFG)
        self.assertFalse(c["jobs"])
    def test_duplicate_first_page_does_not_skip_later_query_pages(self):
        pages=[response({"jobs":[{"id":"a"}],"totalCount":1}),
               response({"jobs":[{"id":"a"}],"totalCount":2}),
               response({"jobs":[{"id":"b"}],"totalCount":2})]
        with patch.dict(os.environ,{"JOOBLE_API_KEY":"test"}), patch("sources.aggregators.requests.post",side_effect=pages):
            self.assertEqual({j["id"] for j in fetch_jooble(["graduate","junior"])},{"jo_a","jo_b"})
    def test_adzuna_query_overlap_does_not_stop_pagination(self):
        pages=[response({"results":[{"id":"a"}],"count":1}),
               response({"results":[{"id":"a"}],"count":51}),
               response({"results":[{"id":"b"}],"count":51})]
        with patch.dict(os.environ,{"ADZUNA_APP_ID":"test","ADZUNA_APP_KEY":"test"}), patch("sources.aggregators.requests.get",side_effect=pages):
            self.assertEqual({j["id"] for j in fetch_adzuna(["graduate","junior"],["gb"])},{"az_gb_a","az_gb_b"})
    def test_workday_cannot_apply_is_closed(self):
        j=job(link="https://example.wd1.myworkdayjobs.com/External/job/one")
        result=verify(j,get=lambda *a,**k:response({"jobPostingInfo":{"canApply":False}}))
        self.assertEqual(result["verification_status"],"closed")
    def test_workday_detail_verifies_description(self):
        j=job(link="https://example.wd1.myworkdayjobs.com/External/job/one")
        result=verify(j,get=lambda *a,**k:response({"jobPostingInfo":{"title":j["title"],"jobDescription":"Python SQL","canApply":True}}))
        self.assertEqual(result["verification_status"],"open")
        self.assertEqual(result["description"],"Python SQL")
    def test_untouched_catalogue_deadline_expires(self):
        c=empty_catalogue();update_catalogue(c,[job(deadline="2026-10-20",verification_status="open")],CFG,"2026-10-18T00:00:00Z")
        update_catalogue(c,[],CFG,"2026-10-21T00:00:00Z")
        item=next(iter(c["jobs"].values()))
        self.assertEqual(item["verification_status"],"closed_deadline")
        self.assertEqual(item["priority"],"Closed")
    def test_ie_country_code_and_unverified_priority(self):
        r=rank(job(country="IE",location="Cork",verification_status="unverified"))
        self.assertEqual(r["geographic_priority"],1)
        self.assertEqual(r["priority"],"Eligibility Check Required")

if __name__=="__main__":unittest.main()
