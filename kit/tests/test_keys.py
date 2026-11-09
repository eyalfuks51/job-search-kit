import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import keys  # noqa: E402

CFG = {'locations': {'include': ['israel', 'tel.?aviv', r'\bIL\b', 'תל אביב', 'haifa', 'חיפה'],
                     'exclude': ['US-IL', r'chicago(,\s*IL\b)?', 'illinois'], 'keep_unplaced_remote': True}}
C = keys.compile_locations(CFG)
UUID = '3f2a1b4c-1111-2222-3333-444455556666'


class UrlKey(unittest.TestCase):
    def test_providers(self):
        cases = {
            f'https://jobs.ashbyhq.com/Acme/{UUID.upper()}?utm_source=x': f'ashby:acme/{UUID}',
            f'https://jobs.lever.co/Acme/{UUID}/apply': f'lever:acme/{UUID}',
            'https://jobs.smartrecruiters.com/Acme/743999-customer-success': 'smartrecruiters:acme/743999',
            'https://www.comeet.com/jobs/acme/72.006/customer-success/9A.123': 'comeet:72.006/9A.123',
            'https://boards.greenhouse.io/acme/jobs/555?gh_src=1': 'greenhouse:555',
            'https://acme.com/careers?gh_jid=777&utm_x=1': 'greenhouse:777',
        }
        for url, want in cases.items():
            self.assertEqual(keys.url_key(url), want, url)

    def test_generic_strips_tracking_and_sorts(self):
        self.assertEqual(keys.url_key('HTTPS://Careers.Acme.com:443/job/1?b=2&utm_medium=x&a=1&fbclid=z#top'),
                         'other:https://careers.acme.com/job/1?a=1&b=2')

    def test_no_host(self):
        self.assertIsNone(keys.url_key(''))
        self.assertIsNone(keys.url_key(None))


class Norm(unittest.TestCase):
    def test_norm(self):
        self.assertEqual(keys.norm('Senior Customer-Success / Manager (Jr.)'), 'customer success manager')
        self.assertEqual(keys.norm(None), '')
        self.assertEqual(keys.norm('מנהל הצלחת לקוח'), 'מנהל הצלחת לקוח')


class Classify(unittest.TestCase):
    def test_classes(self):
        cl = lambda s: keys.classify_location(s, C)
        self.assertEqual(cl('Tel Aviv, Israel'), 'area')
        self.assertEqual(cl('תל אביב'), 'area')
        self.assertEqual(cl(''), 'unknown')
        self.assertEqual(cl('Remote'), 'remote')
        self.assertEqual(cl('Remote - US'), 'out')
        self.assertEqual(cl('Berlin, Germany'), 'out')
        self.assertEqual(cl('Remote, Israel'), 'area')

    def test_chicago_il_excluded(self):
        self.assertEqual(keys.classify_location('Chicago, IL', C), 'out')
        self.assertEqual(keys.classify_location('Springfield, US-IL', C), 'out')
        self.assertEqual(keys.classify_location('Chicago, IL / Tel Aviv', C), 'area')

    def test_keep_remote_off(self):
        c = keys.compile_locations({'locations': {'include': ['israel'], 'keep_unplaced_remote': False}})
        self.assertEqual(keys.classify_location('Remote', c), 'out')


class RoleKey(unittest.TestCase):
    def test_leftmost_city(self):
        self.assertEqual(keys.role_key('Acme Ltd.', 'Senior CS Manager', 'Haifa / Tel Aviv', C), 'acme ltd|cs manager|haifa')
        self.assertEqual(keys.role_key('Acme Ltd.', 'Senior CS Manager', 'Tel Aviv, Haifa', C), 'acme ltd|cs manager|tel aviv')

    def test_two_cities_two_keys(self):
        a = keys.role_key('Acme', 'CSM', 'Tel Aviv', C)
        b = keys.role_key('Acme', 'CSM', 'Haifa', C)
        self.assertNotEqual(a, b)

    def test_unplaced(self):
        self.assertEqual(keys.role_key('Acme', 'CSM', '', C), 'acme|csm|')


class Tier(unittest.TestCase):
    def test_tier_only_labels(self):
        p = keys.compile_priority({'priority_keywords': ['customer success', 'הצלחת לקוח']})
        self.assertEqual(keys.tier('Customer Success Manager', p), 'priority')
        self.assertEqual(keys.tier('מנהל הצלחת לקוח', p), 'priority')
        self.assertEqual(keys.tier('Backend Engineer', p), 'other')
        self.assertEqual(keys.tier('Anything', []), 'other')


if __name__ == '__main__':
    unittest.main()
