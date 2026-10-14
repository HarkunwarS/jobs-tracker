"""Phase 6 adversarial geographical safety cases (offline, no IO or network)."""
import unittest
from pathlib import Path
import yaml
from sources.filters import scope_of, is_ireland, filter_jobs, _US_NAMES, _US_CODES

CFG = yaml.safe_load((Path(__file__).resolve().parents[1] / 'config.yaml').read_text())


def job(location='', **kwargs):
    data = {'id': 'P6-1', 'title': 'Graduate Software Engineer', 'company':'Fake Test Company',
            'location':location, 'description':'', 'source':'fixture', 'link':'https://example.invalid',
            'posted':'2026-10-14'}
    data.update(kwargs)
    return data


class AdversarialGeography(unittest.TestCase):
    def assertUnverifiedNotIreland(self, location, **kwargs):
        with self.subTest(location=location, kwargs=kwargs):
            self.assertFalse(is_ireland(location))
            self.assertEqual(scope_of(job(location, **kwargs), CFG), 'eligibility_unverified')
            kept, pending, counts = filter_jobs([job(location, **kwargs)], CFG)
            self.assertEqual(len(kept), 0)
            self.assertEqual(len(pending), 1)
            self.assertEqual(counts['unverified'], 1)

    def test_four_phase5_reproductions(self):
        for loc in ('Dublin, CA', 'Dublin, OH', 'Dublin, Georgia', 'Cork, Kentucky'):
            self.assertUnverifiedNotIreland(loc)

    def test_full_state_and_abbreviation_variants(self):
        for loc in ('Dublin, California', 'Dublin, Ohio', 'Dublin, Georgia, USA',
                    'Cork, KY', 'Dublin, GA', 'Dublin (CA)', 'Cork - KY',
                    'Dublin, NY', 'Dublin, TX', 'Dublin, PA', 'Dublin, IN',
                    'Dublin, CA, Ireland', 'Cork, KY, Republic of Ireland',
                    'Dublin, Ohio, Ireland', 'Dublin, Georgia (IE)',
                    'Dublin, United States', 'Cork, Canada', 'Dublin, Germany'):
            self.assertUnverifiedNotIreland(loc)

    def test_all_50_us_states_and_district_qualifiers(self):
        self.assertEqual(len(_US_NAMES),51)
        self.assertEqual(len(_US_CODES),51)
        for state in _US_NAMES:
            with self.subTest(full_state=state):
                self.assertNotEqual(scope_of(job(f'Dublin, {state}'),CFG),'ireland')
        for code in _US_CODES:
            with self.subTest(postal_state=code):
                self.assertEqual(scope_of(job(f'Cork, {code}'),CFG),'eligibility_unverified')

    def test_remote_irish_city_and_conflicted_fields(self):
        self.assertNotEqual(scope_of(job('Remote - Dublin, Ireland'),CFG),'ireland')
        self.assertEqual(scope_of(job('Dublin, Ireland',country='IE',
                                      physical_location='Dublin, GA'),CFG),'eligibility_unverified')
        self.assertEqual(scope_of(job('Dublin, Ireland', country='United Kingdom'),CFG),
                         'eligibility_unverified')

    def test_northern_ireland_does_not_belong_to_roi(self):
        for loc in ('Belfast, Northern Ireland', 'Derry, UK', 'Dublin / Belfast, Ireland'):
            with self.subTest(loc=loc):
                self.assertFalse(is_ireland(loc))
                self.assertNotEqual(scope_of(job(loc), CFG), 'ireland')

    def test_positive_roi_country_and_postal(self):
        for loc in ('Dublin, Ireland','Cork, Ireland', 'Dublin, Republic of Ireland',
                    'Cork, IE', 'Dublin (IE)', 'Dublin 2', 'Co. Cork'):
            with self.subTest(loc=loc):
                self.assertTrue(is_ireland(loc))
                self.assertEqual(scope_of(job(loc),CFG),'ireland')
        for country in ('Ireland', 'Republic of Ireland', 'IE', 'IRL'):
            with self.subTest(country=country):
                self.assertEqual(scope_of(job('Cork',country=country), CFG), 'ireland')

    def test_unknown_city_name_no_country_is_unverified(self):
        for loc in ('Dublin','Cork','Dublin CA', 'Cork Kentucky', 'Dublin, Mystery Province'):
            with self.subTest(loc=loc):
                self.assertFalse(is_ireland(loc))
                self.assertEqual(scope_of(job(loc), CFG), 'eligibility_unverified')

    def test_conflicting_country_and_physical_fields(self):
        for kw in (
            {'country':'US'}, {'country':'United States'}, {'country':'CA'},
            {'country':'Germany'}, {'country':'Unknownland'},
            {'physical_location':'California, USA'},
            {'physical_location':'Toronto, Ontario'},
            {'physical_location':'Dublin, Georgia'},
        ):
            with self.subTest(kw=kw):
                self.assertEqual(scope_of(job('Dublin, Ireland',**kw), CFG), 'eligibility_unverified')
        self.assertEqual(scope_of(job('Dublin', country='IE', physical_location='Cork'),CFG),'ireland')
        self.assertEqual(scope_of(job('Dublin', country='Ireland', physical_location='Belfast'),CFG), None)

    def test_remote_and_restriction_precedence(self):
        self.assertEqual(scope_of(job('Remote - EMEA'),CFG), 'eligibility_unverified')
        self.assertEqual(scope_of(job('Remote - EU', country='USA'),CFG), 'eligibility_unverified')
        self.assertEqual(scope_of(job('Remote - EU', physical_location='Dublin, OH'),CFG),'eligibility_unverified')
        for restriction in ('US only', 'UK only','Must be based in United States',
                            'Only within the UK', 'UK applicants only',
                            'US-based applicants only', 'Only UK-based candidates',
                            'Candidates must reside in United States'):
            with self.subTest(restriction=restriction):
                self.assertIsNone(scope_of(job('Dublin, Ireland', employer_restrictions=restriction), CFG))
        self.assertIsNone(scope_of(job('Cork, Ireland', description='This role is US-only'),CFG))
        self.assertEqual(scope_of(job('Remote - EU'), CFG), 'eu_remote')
        self.assertEqual(scope_of(job('Remote worldwide'), CFG), 'remote')
        self.assertIsNone(scope_of(job('Fully Remote'), CFG))

    def test_title_does_not_make_a_location_irish(self):
        self.assertIsNone(scope_of(job('Unknown', title='Dublin Graduate Engineer'),CFG))
        self.assertFalse(is_ireland('London, UK','Dublin Graduate Engineer'))

if __name__ == '__main__': unittest.main()