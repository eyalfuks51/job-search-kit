import contextlib
import datetime as dt
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault('JOBKIT_ME', tempfile.mkdtemp(prefix='jobkit-test-'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import common  # noqa: E402
import roles  # noqa: E402

TODAY = dt.date.today().isoformat()


def row(id, **kw):
    r = {f: '' for f in common.ROLE_FIELDS}
    r.update(id=str(id), kind='new', first_seen='2026-11-01', last_seen='2026-11-01', company='Acme', title='CS Manager',
             location='Tel Aviv', loc_class='area', tier='other', provider='lever', url=f'https://x.test/{id}', jd_chars='0')
    r.update(kw)
    return r


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='jobkit-')
        self._me, common.ME = common.ME, self.tmp
        self.addCleanup(lambda: (setattr(common, 'ME', self._me), shutil.rmtree(self.tmp, ignore_errors=True)))

    def put(self, *rows):
        common.write_roles(list(rows))

    def by_id(self):
        return {r['id']: r for r in common.read_roles()}

    def file(self, obj):
        p = os.path.join(self.tmp, 'in.json')
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False)
        return p

    def search(self):
        common.save_json(common.SEARCH(), {'locations': {'include': ['tel.?aviv']}})

    def cli(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            roles.main(list(argv))
        return buf.getvalue()


class ApplyTests(Base):
    def test_all_or_nothing(self):
        self.put(row(1), row(2))
        items = [{'id': 1, 'verdict': 'strong', 'reasons': 'ok'}, {'id': 99, 'verdict': 'possible'}, {'id': 2, 'verdict': 'bogus'},
                 {'id': 2, 'verdict': 'no-fit'}]
        with self.assertRaises(common.KitError) as cm:
            roles.apply_file(self.file(items))
        msg = str(cm.exception)
        for n in ('item 1', 'item 2', 'item 3'):
            self.assertIn(n, msg)
        self.assertNotIn('item 0', msg)
        self.assertEqual({r['verdict'] for r in common.read_roles()}, {''})

    def test_review_and_decision_in_one_item(self):
        self.put(row(1))
        res = roles.apply_file(self.file([{'id': 1, 'verdict': 'strong', 'reasons': 'fits', 'gaps': 'none', 'decision': 'saved', 'note': 'n'}]))
        r = self.by_id()['1']
        self.assertEqual(res, {'updated': 1, 'added': [], 'existing': []})
        self.assertEqual((r['verdict'], r['reviewed_on'], r['decision'], r['decided_on'], r['note']), ('strong', TODAY, 'saved', TODAY, 'n'))

    def test_skipped_needs_reason(self):
        self.put(row(1))
        with self.assertRaises(common.KitError):
            roles.apply_file(self.file([{'id': 1, 'decision': 'skipped'}]))
        roles.apply_file(self.file([{'id': 1, 'decision': 'skipped', 'decision_reason': 'too far'}]))
        self.assertEqual(self.by_id()['1']['decision_reason'], 'too far')

    def test_bulk_set_aside(self):
        self.put(row(1), row(2), row(3))
        with self.assertRaises(common.KitError):
            roles.apply_file(self.file([{'ids': [1, 2], 'verdict': 'set-aside', 'reasons': ' '}]))
        res = roles.apply_file(self.file([{'ids': [1, 2], 'verdict': 'set-aside', 'reasons': 'title: software engineering'}]))
        got = self.by_id()
        self.assertEqual(res['updated'], 2)
        self.assertEqual([got[i]['verdict'] for i in '123'], ['set-aside', 'set-aside', ''])
        self.assertEqual(got['2']['reasons'], 'title: software engineering')

    def test_manual_add_and_dedupe(self):
        self.search()
        self.put(row(1))
        item = {'add': True, 'company': 'Wix', 'title': 'Onboarding Lead', 'location': 'Tel Aviv, Israel',
                'url': 'https://jobs.lever.co/wix/2f1c1b6e-1111-2222-3333-444455556666?utm_source=x', 'job_text': 'Do things',
                'verdict': 'possible', 'reasons': 'r'}
        res = roles.apply_file(self.file([item]))
        self.assertEqual(res, {'updated': 0, 'added': [2], 'existing': []})
        r = self.by_id()['2']
        self.assertEqual((r['kind'], r['tier'], r['loc_class'], r['provider'], r['verdict']), ('manual', 'manual', 'area', 'manual', 'possible'))
        self.assertEqual(r['url_key'], 'lever:wix/2f1c1b6e-1111-2222-3333-444455556666')
        self.assertEqual((r['first_seen'], r['last_seen']), (TODAY, TODAY))
        self.assertIn('Do things', roles.show([2])[0]['job_text'])
        again = dict(item, url='https://jobs.lever.co/wix/2f1c1b6e-1111-2222-3333-444455556666/apply', verdict='stretch')
        res = roles.apply_file(self.file([again]))
        self.assertEqual((res['added'], res['existing']), ([], [2]))
        self.assertEqual(len(common.read_roles()), 2)
        self.assertEqual(self.by_id()['2']['verdict'], 'stretch')

    def test_manual_add_validation_and_no_url(self):
        self.put(row(1))
        for bad in ({'add': True, 'title': 'T', 'job_text': 'x'}, {'add': True, 'company': 'C', 'title': 'T'}):
            with self.assertRaises(common.KitError):
                roles.apply_file(self.file([bad]))
        res = roles.apply_file(self.file([{'add': True, 'company': 'C', 'title': 'T', 'job_text': 'pasted'}]))
        self.assertEqual(res['added'], [2])
        r = self.by_id()['2']
        self.assertEqual((r['url_key'], r['loc_class']), ('', 'unknown'))  # no search.json, no url
        roles.apply_file(self.file([{'add': True, 'company': 'C', 'title': 'T2', 'job_text': 'pasted2'}]))  # no url: never deduped
        self.assertEqual(len(common.read_roles()), 3)

    def test_hebrew_round_trip(self):
        self.put(row(1, title='מנהל הצלחת לקוח', location='תל אביב'))
        roles.apply_file(self.file([{'id': 1, 'verdict': 'strong', 'reasons': 'מתאים מאוד', 'note': 'שלום'}]))
        r = roles.show([1])[0]
        self.assertEqual((r['title'], r['reasons'], r['note']), ('מנהל הצלחת לקוח', 'מתאים מאוד', 'שלום'))
        roles.apply_file(self.file([{'add': True, 'company': 'חברה', 'title': 'מיישם', 'location': 'חיפה', 'job_text': 'תיאור המשרה'}]))
        self.assertIn('תיאור המשרה', roles.show([2])[0]['job_text'])
        self.assertIn('מנהל הצלחת לקוח', self.cli('inbox', '--titles-only') + self.cli('list'))


class ReadTests(Base):
    def test_inbox_order_and_filters(self):
        self.put(row(1, tier='other', first_seen='2026-11-05'), row(2, tier='priority', first_seen='2026-11-01'),
                 row(3, tier='priority', first_seen='2026-11-05'), row(4, tier='manual', first_seen='2026-10-01'),
                 row(5, tier='priority', first_seen='2026-11-05'), row(6, tier='other', verdict='no-fit', reasons='x'))
        res = roles.inbox()
        self.assertEqual([r['id'] for r in res['roles']], ['4', '3', '5', '2', '1'])
        self.assertEqual((res['unreviewed'], res['by_tier']), (5, {'other': 1, 'priority': 3, 'manual': 1}))
        self.assertEqual([r['id'] for r in roles.inbox('priority', 2)['roles']], ['3', '5'])
        self.assertEqual(set(res['roles'][0]), set(roles.INBOX_FIELDS))

    def test_titles_only(self):
        self.put(row(1, title='A\tB', company='Co'), row(2, tier='priority', location='Haifa'))
        lines = self.cli('inbox', '--titles-only').splitlines()
        self.assertEqual(lines[0], '# 2 unreviewed')
        self.assertEqual(lines[1], '2\tpriority\tAcme\tCS Manager\tHaifa')
        self.assertEqual(lines[2], '1\tother\tCo\tA B\tTel Aviv')
        self.assertEqual(self.cli('inbox', '--titles-only', '--limit', '1').splitlines()[0], '# 2 unreviewed (showing 1, page with --tier and --after-id)')

    def test_titles_paging_cursor_survives_set_asides(self):
        self.put(*[row(i) for i in range(1, 8)])
        page1 = self.cli('inbox', '--titles-only', '--tier', 'other', '--limit', '3').splitlines()
        self.assertEqual(page1[0], '# 7 unreviewed (showing 3, next page: --after-id 3)')
        roles.apply_file(self.file([{'ids': [1, 2], 'verdict': 'set-aside', 'reasons': 'title: hardware'}]))  # recorded between pages
        page2 = self.cli('inbox', '--titles-only', '--tier', 'other', '--limit', '3', '--after-id', '3').splitlines()
        self.assertEqual([l.split('	')[0] for l in page2[1:]], ['4', '5', '6'])
        default = self.cli('inbox', '--titles-only', '--tier', 'other').splitlines()
        self.assertEqual(len(default), 1 + 5)

    def test_show_truncate_and_missing(self):
        path = common.save_jd(1, 'Acme', 'T', 'L', 'u', 'x' * 100)
        self.put(row(1, jd_file=path), row(2, jd_file='nope/missing.txt'), row(3))
        a, b, c = roles.show([1, 2, 3], max_chars=20)
        self.assertEqual((len(a['job_text']), a['truncated']), (20, True))
        self.assertTrue(b['job_text_missing'] and c['job_text_missing'])
        self.assertNotIn('key', a)
        with self.assertRaises(common.KitError):
            roles.show([42])

    def test_summary(self):
        self.put(row(1, verdict='strong', decision='saved', last_seen='2026-11-09'), row(2, verdict='possible', decision='applied'),
                 row(3, tier='priority'), row(4, decision='saved', verdict='stretch', last_seen='2026-11-09'))
        self.assertIsNone(roles.summary()['last_run'])
        common.append_run({'date': '2026-11-09', 'new': 1})
        s = roles.summary()
        self.assertEqual((s['total'], s['unreviewed'], s['unreviewed_by_tier']), (4, 1, {'priority': 1}))
        self.assertEqual(s['verdicts'], {'strong': 1, 'possible': 1, 'stretch': 1})
        self.assertEqual(s['decisions'], {'saved': 2, 'applied': 1})
        self.assertEqual(s['last_run']['date'], '2026-11-09')
        self.assertEqual([(x['id'], x['on_board_last_run']) for x in s['saved']], [(1, True), (4, True)])
        self.assertEqual([(x['id'], x['on_board_last_run']) for x in s['applied']], [(2, False)])

    def test_list_filters(self):
        self.put(row(1, verdict='strong'), row(2, verdict='strong', decision='saved'), row(3))
        self.assertEqual([r['id'] for r in roles.list_roles(verdict='strong')], ['1', '2'])
        self.assertEqual([r['id'] for r in roles.list_roles(decision='saved')], ['2'])
        self.assertEqual(len(roles.list_roles(limit=1)), 1)
        self.assertNotIn('key', roles.list_roles()[0])


if __name__ == '__main__':
    unittest.main()
