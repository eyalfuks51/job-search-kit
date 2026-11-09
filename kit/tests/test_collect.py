import json
import os
import shutil
import sys
import tempfile
import unittest

_TMP0 = tempfile.mkdtemp(prefix='jobkit-')
os.environ.setdefault('JOBKIT_ME', _TMP0)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import collect  # noqa: E402
import common  # noqa: E402

SEARCH = {'locations': {'include': ['israel', 'tel.?aviv', r'\bIL\b', 'תל אביב', 'haifa', 'חיפה'],
                        'exclude': ['US-IL', r'chicago(,\s*IL\b)?', 'illinois'], 'keep_unplaced_remote': True},
          'priority_keywords': ['customer success', 'הצלחת לקוח']}


def read_jd(row):
    with open(os.path.join(common.ROOT, row['jd_file']), encoding='utf-8') as f:
        return f.read()


def gh(title, loc, jid, content='<p>About the role</p>'):
    return {'title': title, 'location': {'name': loc}, 'absolute_url': f'https://boards.greenhouse.io/acme/jobs/{jid}', 'content': content}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='jobkit-')
        self.old_me, self.old_get = common.ME, collect.get
        common.ME = self.tmp
        self.feeds = {}  # board token -> list of greenhouse jobs, or an Exception
        self.calls = []
        collect.get = self.fake_get
        self.write_search(SEARCH)
        self.boards([('Acme', 'acme')])

    def tearDown(self):
        common.ME, collect.get = self.old_me, self.old_get
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fake_get(self, url):
        self.calls.append(url)
        if 'boards-api.greenhouse.io' in url:
            feed = self.feeds[url.split('/boards/')[1].split('/')[0]]
            if isinstance(feed, Exception):
                raise feed
            return {'jobs': feed}
        raise AssertionError('unexpected url ' + url)

    def write_search(self, cfg):
        common.save_json(common.SEARCH(), cfg)

    def boards(self, pairs, **extra):
        common.save_json(common.COMPANIES(), [dict({'name': n, 'ats_provider': 'greenhouse', 'ats_token': t}, **extra) for n, t in pairs])

    def run_collect(self, day='2026-11-09', **kw):
        return collect.collect(today=day, **kw)

    def rows(self):
        return common.read_roles()


class Diffing(Base):
    def test_first_run_everything_new_and_invariant(self):
        self.feeds['acme'] = [gh('Customer Success Manager', 'Tel Aviv', 1), gh('Backend Engineer', 'Haifa, Israel', 2),
                              gh('Support', '', 3), gh('CSM', 'Remote', 4), gh('CSM US', 'Remote - US', 5), gh('Sales', 'London', 6)]
        s = self.run_collect()
        self.assertEqual((s['pulled'], s['in_scope'], s['out_of_area']), (6, 4, 2))
        self.assertEqual(s['in_scope'], s['still_open'] + s['new'] + s['reposts'])
        self.assertEqual((s['new'], s['reposts'], s['still_open']), (4, 0, 0))
        self.assertEqual((s['unknown_location'], s['remote_unplaced'], s['new_priority']), (1, 1, 1))
        self.assertEqual(s['unreviewed_total'], 4)
        self.assertEqual(len(self.rows()), 4)
        self.assertEqual(sorted(x[0] for x in s['out_of_area_top']), ['London', 'Remote - US'])

    def test_title_never_drops(self):
        self.feeds['acme'] = [gh('Backend Engineer', 'Tel Aviv', 1)]
        self.run_collect()
        (r,) = self.rows()
        self.assertEqual((r['title'], r['tier']), ('Backend Engineer', 'other'))

    def test_same_url_next_day_is_still_open(self):
        self.feeds['acme'] = [gh('Customer Success Manager', 'Tel Aviv', 1)]
        self.run_collect('2026-11-09')
        s = self.run_collect('2026-11-10')
        self.assertEqual((s['new'], s['reposts'], s['still_open']), (0, 0, 1))
        (r,) = self.rows()
        self.assertEqual((r['first_seen'], r['last_seen']), ('2026-11-09', '2026-11-10'))
        seen = common.load_json(common.SEEN())
        (e,) = seen.values()
        self.assertEqual(e['last_seen'], '2026-11-10')

    def test_repost_new_url_same_key(self):
        self.feeds['acme'] = [gh('Customer Success Manager', 'Tel Aviv', 1)]
        self.run_collect('2026-11-09')
        self.feeds['acme'] = [gh('Customer Success Manager', 'Tel Aviv, Israel', 2)]
        s = self.run_collect('2026-11-10')
        self.assertEqual((s['new'], s['reposts'], s['still_open']), (0, 1, 0))
        rows = self.rows()
        self.assertEqual([r['kind'] for r in rows], ['new', 'repost'])
        (e,) = common.load_json(common.SEEN()).values()
        self.assertEqual(e['url_key'], 'greenhouse:2')
        # the new posting is now the same posting on day 3
        self.assertEqual(self.run_collect('2026-11-11')['still_open'], 1)
        self.assertEqual(len(self.rows()), 2)

    def test_same_key_twice_in_one_pull(self):
        self.feeds['acme'] = [gh('CSM', 'Tel Aviv', 1), gh('CSM', 'Tel Aviv', 2)]
        s = self.run_collect()
        self.assertEqual((s['new'], s['reposts']), (1, 1))
        self.assertEqual(s['in_scope'], 2)
        self.assertEqual([r['kind'] for r in self.rows()], ['new', 'repost'])

    def test_two_live_urls_same_key_do_not_repost_daily(self):
        self.feeds['acme'] = [gh('CSM', 'Tel Aviv', 1), gh('CSM', 'Tel Aviv', 2)]
        s1 = self.run_collect('2026-11-09')
        self.assertEqual((s1['new'], s1['reposts']), (1, 1))
        for day in ('2026-11-10', '2026-11-11'):
            s = self.run_collect(day)
            self.assertEqual((s['new'], s['reposts'], s['still_open']), (0, 0, 2), day)
        self.assertEqual(len(self.rows()), 2)

    def test_repost_note_carries_earlier_decision(self):
        self.feeds['acme'] = [gh('CSM', 'Tel Aviv', 1)]
        self.run_collect('2026-11-09')
        rows = self.rows()
        rows[0].update(decision='skipped', decided_on='2026-11-09', decision_reason='too far', verdict='possible')
        common.write_roles(rows)
        self.feeds['acme'] = [gh('CSM', 'Tel Aviv', 9)]
        s = self.run_collect('2026-11-12')
        self.assertEqual(s['reposts'], 1)
        note = self.rows()[-1]['note']
        self.assertEqual(note, 'repost of #1 (skipped 2026-11-09: too far); earlier verdict possible')

    def test_senior_and_junior_are_different_roles(self):
        self.feeds['acme'] = [gh('Senior CSM', 'Tel Aviv', 1)]
        self.run_collect('2026-11-09')
        self.feeds['acme'] = [gh('Junior CSM', 'Tel Aviv', 2)]
        s = self.run_collect('2026-11-10')
        self.assertEqual((s['new'], s['reposts']), (1, 0))
        self.assertEqual(self.rows()[-1]['note'], '')

    def test_role_added_by_hand_is_not_listed_twice(self):
        r = {f: '' for f in common.ROLE_FIELDS}
        r.update(id='1', kind='manual', tier='manual', company='Acme', title='CSM', url='https://boards.greenhouse.io/acme/jobs/5',
                 url_key='greenhouse:5', decision='skipped', decision_reason='too far')
        common.write_roles([r])
        self.feeds['acme'] = [gh('CSM', 'Tel Aviv', 5)]
        s = self.run_collect('2026-11-10')
        self.assertEqual((s['new'], s['reposts'], s['still_open']), (0, 0, 1))
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.run_collect('2026-11-11')['still_open'], 1)

    def test_blocked_roles_file_leaves_seen_untouched(self):
        self.feeds['acme'] = [gh('CSM', 'Tel Aviv', 1)]
        real = common.write_roles
        def blocked(rows):
            raise common.KitError('Cannot write roles.csv: the file is open in another program')
        common.write_roles = blocked
        try:
            with self.assertRaises(common.KitError):
                self.run_collect('2026-11-09')
        finally:
            common.write_roles = real
        self.assertEqual(self.run_collect('2026-11-09')['new'], 1)  # the retry still finds the role

    def test_city_collision_two_rows(self):
        self.feeds['acme'] = [gh('CSM', 'Tel Aviv', 1), gh('CSM', 'Haifa', 2)]
        s = self.run_collect()
        self.assertEqual((s['new'], s['reposts']), (2, 0))
        self.assertEqual(len({r['key'] for r in self.rows()}), 2)

    def test_chicago_il_is_out(self):
        self.feeds['acme'] = [gh('CSM', 'Chicago, IL', 1), gh('CSM', 'Tel Aviv', 2)]
        s = self.run_collect()
        self.assertEqual((s['out_of_area'], s['new']), (1, 1))
        self.assertEqual(s['out_of_area_top'], [['Chicago, IL', 1]])
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(len(common.load_json(common.SEEN())), 1)

    def test_out_of_area_not_written(self):
        self.feeds['acme'] = [gh('CSM', 'Berlin', 1)]
        s = self.run_collect()
        self.assertEqual((s['in_scope'], s['out_of_area'], s['new']), (0, 1, 0))
        self.assertEqual(self.rows(), [])
        self.assertEqual(common.load_json(common.SEEN()), {})

    def test_last_seen_updated_on_existing_rows(self):
        self.feeds['acme'] = [gh('CSM', 'Tel Aviv', 1), gh('Analyst', 'Tel Aviv', 2)]
        self.run_collect('2026-11-09')
        rows = self.rows()
        rows[1]['decision'] = 'saved'
        common.write_roles(rows)
        self.feeds['acme'] = [gh('CSM', 'Tel Aviv', 1)]
        self.run_collect('2026-11-10')
        got = {r['title']: r for r in self.rows()}
        self.assertEqual(got['CSM']['last_seen'], '2026-11-10')
        self.assertEqual(got['Analyst']['last_seen'], '2026-11-09')
        self.assertEqual(got['Analyst']['decision'], 'saved')  # review state untouched

    def test_diff_is_pure_function_with_no_url(self):
        compiled = collect.keys.compile_locations(SEARCH)
        seen = {}
        j = lambda u: {'provider': 'x', 'company': 'Acme', 'title': 'CSM', 'location': 'Tel Aviv', 'url': u, 'jd': ''}
        new, rep, still = collect.diff(seen, [j('')], 'd1', compiled)
        self.assertEqual((len(new), len(rep), len(still)), (1, 0, 0))
        new, rep, still = collect.diff(seen, [j('')], 'd2', compiled)
        self.assertEqual((len(new), len(rep), len(still)), (0, 0, 1))
        self.assertEqual(list(seen.values())[0]['last_seen'], 'd2')


class Boards(Base):
    def test_failed_board_does_not_abort(self):
        self.boards([('Good', 'good'), ('Bad', 'bad')])
        self.feeds['good'] = [gh('CSM', 'Tel Aviv', 1)]
        self.feeds['bad'] = ValueError('boom')
        s = self.run_collect()
        self.assertEqual(s['new'], 1)
        self.assertEqual(s['failed'], ['Bad (greenhouse): ValueError'])

    def test_failed_board_keeps_its_seen_rows(self):
        self.feeds['acme'] = [gh('CSM', 'Tel Aviv', 1)]
        self.run_collect('2026-11-09')
        self.boards([('Acme', 'acme'), ('Other', 'other')])
        self.feeds['other'] = [gh('Analyst', 'Tel Aviv', 9)]
        self.feeds['acme'] = OSError('down')
        self.run_collect('2026-11-10')
        e = [v for v in common.load_json(common.SEEN()).values() if v['company'] == 'Acme']
        self.assertEqual(e[0]['last_seen'], '2026-11-09')

    def test_all_failed_raises_and_writes_nothing(self):
        self.feeds['acme'] = OSError('down')
        with self.assertRaises(common.KitError):
            self.run_collect()
        self.assertFalse(os.path.exists(common.ROLES()))
        self.assertFalse(os.path.exists(common.SEEN()))
        self.assertFalse(os.path.exists(common.RUNS()))

    def test_disabled_skipped(self):
        common.save_json(common.COMPANIES(), [
            {'name': 'Acme', 'ats_provider': 'greenhouse', 'ats_token': 'acme'},
            {'name': 'Resident', 'ats_provider': 'greenhouse', 'ats_token': 'resident', 'disabled': True}])
        self.feeds['acme'] = [gh('CSM', 'Tel Aviv', 1)]
        s = self.run_collect()
        self.assertEqual((s['boards'], s['disabled_skipped']), (1, ['Resident']))
        self.assertFalse(any('resident' in u for u in self.calls))

    def test_no_boards(self):
        common.save_json(common.COMPANIES(), [])
        with self.assertRaises(common.KitError):
            self.run_collect()

    def test_only_filter(self):
        self.boards([('One', 'one'), ('Two', 'two')])
        self.feeds.update(one=[gh('CSM', 'Tel Aviv', 1)], two=[gh('CSM', 'Haifa', 2)])
        s = self.run_collect(only=['two'])
        self.assertEqual((s['boards'], s['new']), (1, 1))
        with self.assertRaises(common.KitError):
            self.run_collect(only=['nope'])

    def test_empty_board_counted(self):
        self.feeds['acme'] = []
        s = self.run_collect()
        self.assertEqual((s['empty_boards'], s['pulled']), (1, 0))

    def test_unknown_provider_fails_visibly(self):
        common.save_json(common.COMPANIES(), [{'name': 'X', 'ats_provider': 'workday', 'ats_token': 't'},
                                              {'name': 'Acme', 'ats_provider': 'greenhouse', 'ats_token': 'acme'}])
        self.feeds['acme'] = [gh('CSM', 'Tel Aviv', 1)]
        self.assertEqual(self.run_collect()['failed'], ['X (workday): ValueError'])


class SmartRecruiters(Base):
    def setUp(self):
        super().setUp()
        common.save_json(common.COMPANIES(), [{'name': 'Sr', 'ats_provider': 'smartrecruiters', 'ats_token': 'Sr'}])
        self.detail = []

    def fake_get(self, url):
        self.calls.append(url)
        if '/postings/' in url:
            self.detail.append(url)
            return {'jobAd': {'sections': {'jobDescription': {'title': 'Description', 'text': '<p>Do things</p>'}}}}
        off = int(url.split('offset=')[1].split('&')[0])
        ids = ['101', '102', '103']
        page = ids[off:off + 2]
        return {'totalFound': 3, 'content': [
            {'id': i, 'name': 'CSM ' + i, 'location': {'city': 'Tel Aviv', 'country': 'il'}} for i in page]}

    def test_pagination_and_country(self):
        s = self.run_collect()
        self.assertEqual((s['pulled'], s['new']), (3, 3))
        lists = [u for u in self.calls if '/postings?' in u]
        self.assertEqual(len(lists), 2)
        self.assertTrue(all('country=' not in u for u in lists))
        self.write_search(dict(SEARCH, smartrecruiters_country='il'))
        self.calls[:] = []
        self.run_collect('2026-11-10')
        self.assertTrue(all('country=il' in u for u in self.calls if '/postings?' in u))

    def test_detail_fetched_only_for_written_roles(self):
        self.run_collect('2026-11-09')
        self.assertEqual(len(self.detail), 3)
        self.assertIn('Do things', read_jd(self.rows()[0]))
        self.detail[:] = []
        self.run_collect('2026-11-10')
        self.assertEqual(self.detail, [])


class Hebrew(Base):
    def test_roundtrip(self):
        self.feeds['acme'] = [gh('מנהל הצלחת לקוח', 'תל אביב, ישראל', 1, '<p>דרישות התפקיד</p>')]
        s = self.run_collect()
        self.assertEqual(s['new_priority'], 1)
        (r,) = self.rows()
        self.assertEqual((r['title'], r['location'], r['tier']), ('מנהל הצלחת לקוח', 'תל אביב, ישראל', 'priority'))
        with open(common.ROLES(), encoding='utf-8-sig') as f:
            self.assertIn('מנהל הצלחת לקוח', f.read())
        self.assertIn('דרישות התפקיד', read_jd(r))

    def test_long_location_not_truncated(self):
        loc = 'Tel Aviv, ' + 'x' * 200
        self.feeds['acme'] = [gh('CSM', loc, 1)]
        self.run_collect()
        self.assertEqual(self.rows()[0]['location'], loc)

    def test_runs_line_appended(self):
        self.feeds['acme'] = [gh('CSM', 'Tel Aviv', 1)]
        self.run_collect()
        self.assertEqual(common.last_run()['new'], 1)


def tearDownModule():
    shutil.rmtree(_TMP0, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
