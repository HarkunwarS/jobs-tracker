"""v7 behaviour: recall-first delivery, best-first ordering, queue expiry, email tidy-up."""
import unittest
from datetime import datetime, timedelta, timezone
from sources import notify
from sources.outbox import expire_stale, enqueue, empty_outbox


def j(i, title, company="Acme", score=0.4, **kw):
    return dict(id=i, title=title, company=company, location="Dublin, Ireland", link=f"https://x/{i}",
                score=score, scope="ireland", category="software", source="Greenhouse", posted="None", **kw)


class EmailTests(unittest.TestCase):
    def test_dedupe_and_internship_split_and_sorting(self):
        alerts = [j("1", "Graduate Data Analyst", score=0.6), j("2", "Software Engineering Intern", score=0.7),
                  j("3", "Graduate Data Analyst", score=0.5)]  # duplicate of 1
        rest = [j("4", "Business Analyst", company="Other", score=0.3), j("5", "Placement Students", company="Z", score=0.45)]
        html = notify.build_email_html(alerts, rest)
        self.assertEqual(html.count("Graduate Data Analyst"), 1)
        self.assertLess(html.index("Graduate Data Analyst"), html.index("Business Analyst"))
        self.assertLess(html.index("Business Analyst"), html.index("Internships / placements"))
        self.assertLess(html.index("Internships / placements"), html.index("Software Engineering Intern"))

    def test_placeholder_dates_and_unavailable_hidden(self):
        self.assertEqual(notify._tidy_posted("Recent"), "")
        self.assertEqual(notify._tidy_posted("None"), "")
        self.assertEqual(notify._tidy_posted("2026-10-16T14:22:23.768Z"), "2026-10-16")
        self.assertEqual(notify._tidy_location("Dublin, UNAVAILABLE, Ireland"), "Dublin, Ireland")


class QueueTests(unittest.TestCase):
    def test_stale_pending_expires_sent_kept(self):
        box = empty_outbox()
        old = datetime.now(timezone.utc) - timedelta(days=12)
        enqueue(box, [], [j("a", "Old job")], now=old)
        enqueue(box, [], [j("b", "New job")])
        self.assertEqual(expire_stale(box, 10), 1)
        self.assertEqual(list(box["jobs"]), ["b"])


class SeniorityTests(unittest.TestCase):
    def test_weak_entry_words_do_not_override_senior(self):
        from sources.filters import seniority_of
        for t in ["Senior Associate - DevOps Engineer", "Staff Backend Engineer", "Team Lead, Data Engineering",
                  "Staff Machine Learning Engineer - Wildfire"]:
            self.assertEqual(seniority_of(t), "senior", t)

    def test_real_entry_roles_still_entry(self):
        from sources.filters import seniority_of
        for t in ["Graduate Data Analyst", "Junior Software Engineer", "Associate Software Engineer",
                  "AI & Data Graduate Programme FY28", "Software Engineer Intern", "Data Analyst I"]:
            self.assertEqual(seniority_of(t), "entry", t)


if __name__ == "__main__":
    unittest.main()
