import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
import urllib.error

os.environ.setdefault('JOBKIT_ME', tempfile.mkdtemp(prefix='jobkit-test-'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import boards  # noqa: E402
import common  # noqa: E402

TOKEN = '2769D81626762C4E762762C4EC4E1626'


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='jobkit-')
        self._me, common.ME = common.ME, self.tmp
        self._seeds, common.SEEDS = common.SEEDS, os.path.join(self.tmp, 'seeds')
        self._fetch, self._collect = boards.fetch, sys.modules.get('collect')
        self.pages, self.fetched = {}, []

        def fake_fetch(url):
            self.fetched.append(url)
            if url not in self.pages:
                raise urllib.error.URLError('offline')
            return self.pages[url]
        boards.fetch = fake_fetch
        self.pulls = {}
        fake = types.ModuleType('collect')
        fake.pull = lambda b: self.pulls[b['ats_token']] if isinstance(self.pulls[b['ats_token']], list) else (_ for _ in ()).throw(self.pulls[b['ats_token']])
        sys.modules['collect'] = fake
        self.addCleanup(self.restore)

    def restore(self):
        common.ME, common.SEEDS, boards.fetch = self._me, self._seeds, self._fetch
        if self._collect is None:
            sys.modules.pop('collect', None)
        else:
            sys.modules['collect'] = self._collect
        shutil.rmtree(self.tmp, ignore_errors=True)

    def jobs(self, *tokens):
        for t in tokens:
            self.pulls[t] = [{'title': 'T', 'location': 'Tel Aviv'}]


class DetectTests(Base):
    def test_url_patterns_for_all_providers(self):
        cases = [
            ('https://boards.greenhouse.io/yotpo', 'greenhouse', 'yotpo'),
            ('https://job-boards.greenhouse.io/appsflyer/jobs/123', 'greenhouse', 'appsflyer'),
            ('https://boards-api.greenhouse.io/v1/boards/wix/jobs', 'greenhouse', 'wix'),
            ('https://boards.greenhouse.io/embed/job_board?for=monday', 'greenhouse', 'monday'),
            ('https://jobs.lever.co/lendbuzz', 'lever', 'lendbuzz'),
            ('https://jobs.lever.co/lendbuzz/2f1c1b6e-1111-2222-3333-444455556666', 'lever', 'lendbuzz'),
            ('https://jobs.ashbyhq.com/Deel/2f1c1b6e-1111-2222-3333-444455556666', 'ashby', 'Deel'),
            ('https://jobs.smartrecruiters.com/tradedesk', 'smartrecruiters', 'tradedesk'),
            ('https://careers.smartrecruiters.com/Armis/123-engineer', 'smartrecruiters', 'Armis'),
            ('https://huuuge.recruitee.com/o/some-job', 'recruitee', 'huuuge'),
            ('https://Huuuge.recruitee.com/', 'recruitee', 'huuuge'),
            ('jobs.lever.co/acme', 'lever', 'acme'),  # no scheme
        ]
        for url, prov, tok in cases:
            self.jobs(tok if prov != 'recruitee' else tok.lower())
            res = boards.detect(url)
            self.assertEqual((res['provider'], res['token'], res['verified'], res['jobs']), (prov, tok, True, 1), url)
        self.assertEqual(self.fetched, [])  # URL patterns never touch the network

    def test_comeet_job_url_fetches_company_page_for_token(self):
        self.pages['https://www.comeet.com/jobs/drivenets/72.006'] = '..."company_uid": "72.006", "token": "%s", "slug": "drivenets"...' % TOKEN
        self.jobs(f'72.006::{TOKEN}')
        res = boards.detect('https://www.comeet.com/jobs/drivenets/72.006/ai-specialist-engineer/9D.660')
        self.assertEqual((res['provider'], res['token'], res['name_guess'], res['verified']), ('comeet', f'72.006::{TOKEN}', 'Drivenets', True))
        self.assertEqual(self.fetched, ['https://www.comeet.com/jobs/drivenets/72.006'])

    def test_comeet_token_in_careers_page_html(self):
        self.pages['https://acme.test/careers'] = 'var comeetvar = {"comeet_token":"%s","comeet_uid":"82.00A","x":1}' % TOKEN
        res = boards.detect('https://acme.test/careers')
        self.assertEqual((res['provider'], res['token']), ('comeet', f'82.00A::{TOKEN}'))
        self.assertFalse(res['verified'])  # nothing in the fake pull table: verification fails, detection still answers
        self.assertIsNone(res['jobs'])

    def test_comeet_page_link_beats_unrelated_token_in_page(self):
        self.pages['https://acme.test/careers'] = ('<a href="https://www.comeet.com/jobs/acme/99.006">Jobs</a> "token":"%s"' % ('A1' * 16))
        self.pages['https://www.comeet.com/jobs/acme/99.006'] = '"company_uid": "99.006", "token": "%s"' % TOKEN
        self.assertEqual(boards.detect('https://acme.test/careers')['token'], f'99.006::{TOKEN}')

    def test_comeet_without_token_is_an_answer(self):
        self.pages['https://acme.test/careers'] = '<a href="https://www.comeet.com/jobs/acme/99.006">Jobs</a>'
        self.pages['https://www.comeet.com/jobs/acme/99.006'] = '<html>nothing</html>'
        res = boards.detect('https://acme.test/careers')
        self.assertIsNone(res['provider'])
        self.assertIn('Comeet', res['reason'])

    def test_greenhouse_embed_in_html(self):
        html = ('<script src="https://boards.greenhouse.io/embed/job_board/js?for=monday"></script>'
                '<a href="https://boards.greenhouse.io/embed/job_board?for=monday">x</a><a href="https://boards.greenhouse.io/other">y</a>')
        self.pages['https://monday.test/careers'] = html
        self.jobs('monday')
        res = boards.detect('https://monday.test/careers')
        self.assertEqual((res['provider'], res['token'], res['name_guess']), ('greenhouse', 'monday', 'Monday'))  # most frequent, never 'embed'

    def test_escaped_json_and_other_providers_in_html(self):
        self.pages['https://a.test/c'] = '{"url":"https:\\/\\/jobs.lever.co\\/acme-co\\/abc"}'
        self.assertEqual(boards.detect('https://a.test/c')['token'], 'acme-co')
        self.pages['https://b.test/c'] = '<iframe src="https://jobs.ashbyhq.com/Foo"></iframe>'
        self.assertEqual((boards.detect('https://b.test/c')['provider']), 'ashby')
        self.pages['https://c.test/c'] = '<a href="https://zed.recruitee.com/o/x">'
        self.assertEqual((boards.detect('https://c.test/c')['token']), 'zed')

    def test_not_found_and_fetch_failure_are_answers(self):
        self.pages['https://plain.test/'] = '<html>Join us! embed api v1 jobs</html>'
        res = boards.detect('https://plain.test/')
        self.assertIsNone(res['provider'])
        self.assertIn('reason', res)
        res = boards.detect('https://down.test/')
        self.assertIsNone(res['provider'])
        self.assertIn('URLError', res['reason'])

    def test_unverified_when_pull_fails(self):
        self.pulls['yotpo'] = ValueError('boom')
        res = boards.detect('https://boards.greenhouse.io/yotpo')
        self.assertEqual((res['provider'], res['verified'], res['jobs']), ('greenhouse', False, None))


class CheckTests(Base):
    def test_check_ok_with_and_without_search(self):
        self.pulls['x'] = [{'title': f'T{i}', 'location': 'Berlin' if i % 2 else 'Tel Aviv'} for i in range(12)]
        res = boards.check('lever', 'x')
        self.assertEqual((res['ok'], res['jobs'], res['in_area']), (True, 12, None))
        self.assertEqual(len(res['sample_titles']), 8)
        common.save_json(common.SEARCH(), {'locations': {'include': ['tel.?aviv']}})
        res = boards.check('lever', 'x')
        self.assertEqual((res['jobs'], res['in_area']), (12, 6))
        self.assertEqual(res['sample_titles'], ['T0', 'T2', 'T4', 'T6', 'T8', 'T10'])

    def test_check_failure_is_not_an_error(self):
        self.pulls['x'] = urllib.error.URLError('nope')
        res = boards.check('lever', 'x')
        self.assertFalse(res['ok'])
        self.assertIn('URLError', res['error'])


class CompaniesTests(Base):
    def test_add_dedupes_case_insensitively(self):
        res = boards.add([{'name': 'A', 'ats_provider': 'lever', 'ats_token': 'Acme', 'careers_url': 'https://a.test'},
                          {'name': 'A2', 'ats_provider': 'Lever', 'ats_token': 'acme'}])
        self.assertEqual(res, {'added': ['A'], 'duplicates': ['A2']})
        res = boards.add([{'name': 'A3', 'ats_provider': 'lever', 'ats_token': 'ACME'}, {'name': 'חברה', 'ats_provider': 'ashby', 'ats_token': 'x'}])
        self.assertEqual(res, {'added': ['חברה'], 'duplicates': ['A3']})
        cos = common.load_companies()
        self.assertEqual(len(cos), 2)
        self.assertEqual(set(cos[0]), {'name', 'ats_provider', 'ats_token', 'careers_url', 'added'})
        self.assertEqual(cos[1]['name'], 'חברה')

    def test_add_validates(self):
        with self.assertRaises(common.KitError):
            boards.add([{'name': 'A', 'ats_provider': 'lever'}])
        self.assertFalse(os.path.exists(common.COMPANIES()))

    def seed_pack(self):
        os.makedirs(common.SEEDS)
        pack = [{'name': 'One', 'ats_provider': 'lever', 'ats_token': 'one', 'domain': 'x'},
                {'name': 'Two', 'ats_provider': 'comeet', 'ats_token': '08.004::AB', 'disabled': True, 'disabled_reason': 'closed', 'disabled_since': '2026-01-01'}]
        with open(os.path.join(common.SEEDS, 'israel-tech.json'), 'w', encoding='utf-8') as f:
            json.dump(pack, f)

    def test_add_pack_dedupes_and_keeps_disabled(self):
        self.seed_pack()
        boards.add([{'name': 'Mine', 'ats_provider': 'lever', 'ats_token': 'ONE'}])
        res = boards.add_pack('israel-tech')
        self.assertEqual(res, {'added': 1, 'already': 1, 'total': 2})
        two = [c for c in common.load_companies() if c['name'] == 'Two'][0]
        self.assertEqual((two['disabled'], two['disabled_reason']), (True, 'closed'))
        self.assertNotIn('domain', two)
        self.assertEqual(boards.add_pack('israel-tech'), {'added': 0, 'already': 2, 'total': 2})

    def test_unknown_pack_lists_available(self):
        self.seed_pack()
        with self.assertRaises(common.KitError) as cm:
            boards.add_pack('nope')
        self.assertIn('israel-tech', str(cm.exception))

    def test_disable_enable_list(self):
        boards.add([{'name': 'Acme Ltd', 'ats_provider': 'lever', 'ats_token': 'a'}, {'name': 'Beta', 'ats_provider': 'ashby', 'ats_token': 'b'}])
        boards.set_disabled('acme ltd', 'hiring freeze')
        c = common.load_companies()[0]
        self.assertEqual((c['disabled'], c['disabled_reason']), (True, 'hiring freeze'))
        self.assertTrue(c['disabled_since'])
        lst = boards.list_boards()
        self.assertEqual((lst['active'], lst['disabled']), (1, 1))
        self.assertEqual(lst['boards'][0], {'name': 'Acme Ltd', 'provider': 'lever', 'disabled': True})
        boards.set_disabled('ACME LTD')
        self.assertEqual(set(common.load_companies()[0]), {'name', 'ats_provider', 'ats_token', 'added'})
        with self.assertRaises(common.KitError):
            boards.set_disabled('Nobody', 'x')


class ReplaceTests(Base):
    """Failed-board replacement: the destination is tested first, and exactly it stays active."""
    OTHER = {'name': 'Other Co', 'ats_provider': 'lever', 'ats_token': 'other', 'added': '2026-01-01'}

    def seed(self, *entries):
        common.save_json(common.COMPANIES(), [dict(e) for e in entries] + [dict(self.OTHER)])

    def acme(self, prov, tok, **extra):
        return dict({'name': 'Acme', 'ats_provider': prov, 'ats_token': tok, 'added': '2026-01-01'}, **extra)

    def active(self, name='acme'):
        return [(c['ats_provider'], c['ats_token']) for c in common.load_companies() if c['name'].lower() == name and not c.get('disabled')]

    def assert_other_untouched(self):
        self.assertEqual([c for c in common.load_companies() if c['name'] == 'Other Co'], [self.OTHER])

    def test_fresh_token(self):
        self.seed(self.acme('greenhouse', 'a'))
        self.jobs('b')
        res = boards.replace({'name': 'acme', 'ats_provider': 'lever', 'ats_token': 'b', 'careers_url': 'https://acme.test/jobs'})
        self.assertEqual(res, {'name': 'Acme', 'active': 'lever b', 'disabled': ['greenhouse a'], 'jobs': 1})
        self.assertEqual(self.active(), [('lever', 'b')])
        cos = common.load_companies()
        a = [c for c in cos if c['ats_token'] == 'a'][0]
        self.assertEqual((a['disabled'], a['disabled_reason']), (True, 'replaced by lever b'))
        b = [c for c in cos if c['ats_token'] == 'b'][0]
        self.assertEqual((b['name'], b['careers_url']), ('Acme', 'https://acme.test/jobs'))
        self.assertEqual(len(cos), 3)
        self.assert_other_untouched()

    def test_back_to_previously_disabled_board(self):
        self.seed(self.acme('greenhouse', 'a'))
        self.jobs('a', 'b')
        boards.replace({'name': 'Acme', 'ats_provider': 'lever', 'ats_token': 'b'})
        self.pulls['A'] = self.pulls['a']  # token case may differ from the stored one
        res = boards.replace({'name': 'Acme', 'ats_provider': 'greenhouse', 'ats_token': 'A'})
        self.assertEqual((res['active'], res['disabled']), ('greenhouse a', ['lever b']))
        self.assertEqual(self.active(), [('greenhouse', 'a')])
        cos = common.load_companies()
        self.assertEqual(len(cos), 3)  # A re-enabled in place, not added twice
        a = [c for c in cos if c['ats_token'] == 'a'][0]
        self.assertFalse(any(k in a for k in ('disabled', 'disabled_reason', 'disabled_since')))
        self.assertEqual(a['added'], '2026-01-01')
        self.assert_other_untouched()

    def test_failing_destination_changes_nothing(self):
        self.seed(self.acme('greenhouse', 'a'))
        before = common.load_companies()
        self.pulls['b'] = OSError('404')
        with self.assertRaises(common.KitError) as cm:
            boards.replace({'name': 'Acme', 'ats_provider': 'lever', 'ats_token': 'b'})
        self.assertIn('Nothing changed', str(cm.exception))
        self.assertEqual(common.load_companies(), before)
        self.assertEqual(self.active(), [('greenhouse', 'a')])

    def test_failing_previously_disabled_destination_changes_nothing(self):
        self.seed(self.acme('greenhouse', 'a', disabled=True, disabled_reason='replaced by lever b', disabled_since='2026-02-01'),
                  self.acme('lever', 'b'))
        before = common.load_companies()
        self.pulls['a'] = OSError('still down')
        with self.assertRaises(common.KitError):
            boards.replace({'name': 'Acme', 'ats_provider': 'greenhouse', 'ats_token': 'a'})
        self.assertEqual(common.load_companies(), before)
        self.assertEqual(self.active(), [('lever', 'b')])

    def test_refusals_change_nothing(self):
        self.seed(self.acme('greenhouse', 'a'))
        before = common.load_companies()
        self.jobs('other', 'x')
        for it in ({'name': 'Acme', 'ats_provider': 'lever', 'ats_token': 'other'},   # another employer's board
                   {'name': 'Nobody', 'ats_provider': 'lever', 'ats_token': 'x'},     # unknown employer
                   {'name': 'Acme', 'ats_provider': 'lever'}):                         # incomplete
            with self.assertRaises(common.KitError):
                boards.replace(it)
            self.assertEqual(common.load_companies(), before, it)

    def test_exactly_one_active_even_from_several(self):
        self.seed(self.acme('greenhouse', 'a'), self.acme('ashby', 'c'),
                  self.acme('lever', 'b', disabled=True, disabled_reason='old', disabled_since='2026-02-01'))
        self.jobs('b')
        res = boards.replace({'name': 'Acme', 'ats_provider': 'lever', 'ats_token': 'b'})
        self.assertEqual(self.active(), [('lever', 'b')])
        self.assertEqual(sorted(res['disabled']), ['ashby c', 'greenhouse a'])
        self.assertEqual(len(common.load_companies()), 4)
        self.assert_other_untouched()

    def test_already_disabled_boards_keep_their_reason(self):
        self.seed(self.acme('greenhouse', 'a', disabled=True, disabled_reason='closed', disabled_since='2026-02-01'), self.acme('lever', 'b'))
        self.jobs('c')
        boards.replace({'name': 'Acme', 'ats_provider': 'ashby', 'ats_token': 'c'})
        a = [c for c in common.load_companies() if c['ats_token'] == 'a'][0]
        self.assertEqual((a['disabled_reason'], a['disabled_since']), ('closed', '2026-02-01'))
        self.assertEqual(self.active(), [('ashby', 'c')])

    def test_enable_by_name_refuses_when_several_boards(self):
        self.seed(self.acme('greenhouse', 'a'))
        self.jobs('b')
        boards.replace({'name': 'Acme', 'ats_provider': 'lever', 'ats_token': 'b'})
        before = common.load_companies()
        with self.assertRaises(common.KitError) as cm:
            boards.set_disabled('Acme')
        self.assertIn('replace', str(cm.exception))
        self.assertEqual(common.load_companies(), before)
        self.assertEqual(self.active(), [('lever', 'b')])

    def test_cli_reads_one_object(self):
        self.seed(self.acme('greenhouse', 'a'))
        self.jobs('b')
        path = os.path.join(self.tmp, 'r.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'name': 'Acme', 'ats_provider': 'lever', 'ats_token': 'b'}, f)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            boards.main(['replace', path])
        self.assertEqual(json.loads(out.getvalue())['active'], 'lever b')
        self.assertEqual(self.active(), [('lever', 'b')])


if __name__ == '__main__':
    unittest.main()
