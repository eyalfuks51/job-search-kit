"""Pull every watched board, diff against what was seen before, and add new roles to me/roles.csv.

    python3 kit/collect.py [--only NAME ...] [--workers 8]

Prints one JSON summary. A failed board never aborts the run and never touches its seen rows.
Nothing is dropped because of its title; only roles located somewhere else ('out') are counted and left out.
"""
import argparse
import collections
import concurrent.futures
import datetime as dt
import html
import json
import os
import re
import sys
import threading
import urllib.request
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import keys  # noqa: E402

UA = {'User-Agent': 'Mozilla/5.0 (personal job search; low volume)', 'Accept': 'application/json'}
PER_HOST = 2
_hosts = {}
_hosts_lock = threading.Lock()


def _host_slot(host):
    with _hosts_lock:
        return _hosts.setdefault(host, threading.BoundedSemaphore(PER_HOST))


def get(url):
    """GET a JSON document. At most PER_HOST concurrent requests per host, 30 s timeout."""
    req = urllib.request.Request(url, headers=UA)
    with _host_slot(urlparse(url).netloc.lower()):
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode('utf-8', 'replace'))


def text(s):
    s = html.unescape(s or '')
    s = re.sub(r'<(br|/p|/li|/h\d|/div)[^>]*>', '\n', s, flags=re.I)
    s = html.unescape(re.sub(r'<[^>]+>', ' ', s))
    return re.sub(r'\n\s*\n+', '\n', re.sub(r'[ \t\xa0]+', ' ', s)).strip()


def job(provider, company, title, location, url, jd=''):
    return {'provider': provider, 'company': company, 'title': (title or '').strip(),
            'location': (location or '').strip(), 'url': url or '', 'jd': jd}


def pull(c, cfg=None):
    """Return the jobs of one board as dicts. Raises when the board cannot be read."""
    p, t, co = c['ats_provider'], c.get('ats_token'), c['name']
    if p == 'comeet':
        uid, tok = t.split('::', 1)
        d = get(f'https://www.comeet.co/careers-api/2.0/company/{uid}/positions?token={tok}&details=true')
        out = []
        for j in (d if isinstance(d, list) else d.get('positions', [])):
            l = j.get('location') or {}
            jd = '\n'.join(f"{x.get('name', '')}:\n{text(x.get('value'))}" for x in (j.get('details') or []) if x.get('value'))
            loc = ' '.join(str(x) for x in (l.get('name'), l.get('city'), l.get('country')) if x)
            out.append(job(p, co, j.get('name'), loc, j.get('url_comeet_hosted_page') or j.get('url_active_page'), jd))
        return out
    if p == 'greenhouse':
        d = get(f'https://boards-api.greenhouse.io/v1/boards/{t}/jobs?content=true')
        return [job(p, co, j['title'], (j.get('location') or {}).get('name'), j['absolute_url'], text(j.get('content'))) for j in d['jobs']]
    if p == 'lever':
        out = []
        for j in get(f'https://api.lever.co/v0/postings/{t}?mode=json'):
            lists = '\n'.join(f"{x.get('text', '')}:\n{text(x.get('content'))}" for x in j.get('lists', []))
            jd = '\n'.join(x for x in (j.get('descriptionPlain', ''), lists, j.get('additionalPlain', '')) if x)
            out.append(job(p, co, j['text'], (j.get('categories') or {}).get('location'), j.get('hostedUrl'), jd))
        return out
    if p == 'ashby':
        out = []
        for j in get(f'https://api.ashbyhq.com/posting-api/job-board/{t}?includeCompensation=false')['jobs']:
            loc = (j.get('location') or '') + ' ' + ' '.join(x.get('location', '') for x in j.get('secondaryLocations') or [])
            out.append(job(p, co, j['title'], loc, j.get('jobUrl'), j.get('descriptionPlain') or text(j.get('descriptionHtml'))))
        return out
    if p == 'smartrecruiters':
        cc = (cfg or {}).get('smartrecruiters_country')
        out, offset = [], 0
        while True:
            d = get(f'https://api.smartrecruiters.com/v1/companies/{t}/postings?limit=100&offset={offset}' + (f'&country={cc}' if cc else ''))
            page = d.get('content') or []
            for j in page:
                l = j.get('location') or {}
                x = job(p, co, j['name'], f"{l.get('city', '')} {l.get('country', '')}", f"https://jobs.smartrecruiters.com/{t}/{j.get('id')}")
                x['_sr'] = f"https://api.smartrecruiters.com/v1/companies/{t}/postings/{j.get('id')}"  # job text is fetched later, only if the role is written
                out.append(x)
            offset += len(page)
            if not page or offset >= (d.get('totalFound') or 0):
                return out
    if p == 'recruitee':
        return [job(p, co, j['title'], j.get('location'), j.get('careers_url'),
                    text((j.get('description') or '') + '\n' + (j.get('requirements') or '')))
                for j in get(f'https://{t}.recruitee.com/api/offers/').get('offers', [])]
    raise ValueError(f'unknown provider {p!r}')


def fetch_sr_text(j):
    """SmartRecruiters lists carry no job text: fetch the detail page (best effort)."""
    if j.get('_sr') and not j['jd']:
        try:
            sec = get(j['_sr']).get('jobAd', {}).get('sections', {})
            j['jd'] = '\n'.join(f"{v.get('title', '')}:\n{text(v.get('text'))}" for v in sec.values() if isinstance(v, dict))
        except Exception:
            pass


def diff(seen, jobs, today, compiled, listed=()):
    """Pure apart from updating `seen` in place. Jobs are in-scope dicts; each gets 'url_key' and 'key'.
    Returns (new, reposts, still_open): every job lands in exactly one list."""
    known = {}  # every url_key ever seen for a role, from before this run (a role listed under two URLs stays known under both)
    for k, e in seen.items():
        for u in e.get('url_keys') or ([e['url_key']] if e.get('url_key') else []):
            known[u] = k
    this_run = set()
    new, reposts, still_open = [], [], []
    for j in jobs:
        uk = keys.url_key(j['url']) or ''
        k = keys.role_key(j['company'], j['title'], j['location'], compiled)
        j['url_key'], j['key'] = uk, k
        if uk and uk in known:
            seen[known[uk]]['last_seen'] = today
            still_open.append(j)
        elif uk and uk in listed:  # already in roles.csv (added by hand): remember it, do not list it twice
            e = seen.setdefault(k, {'first_seen': today, 'company': j['company'], 'title': j['title'], 'url_keys': []})
            e['url_keys'] = sorted(set((e.get('url_keys') or []) + [uk]))
            e.update(url_key=uk, last_seen=today)
            known[uk] = k
            still_open.append(j)
        elif uk and uk in this_run:  # the same URL listed twice in one pull
            still_open.append(j)
        elif k in seen and not uk:  # no URL to compare: same key is the same role
            seen[k]['last_seen'] = today
            still_open.append(j)
        elif k in seen:  # same company + title + city under a new URL
            e = seen[k]
            e['url_keys'] = sorted(set((e.get('url_keys') or ([e['url_key']] if e.get('url_key') else [])) + [uk]))
            e.update(url_key=uk, last_seen=today)
            reposts.append(j)
        else:
            seen[k] = {'first_seen': today, 'last_seen': today, 'company': j['company'], 'title': j['title'], 'url_key': uk,
                       'url_keys': [uk] if uk else []}
            new.append(j)
        if uk:
            this_run.add(uk)
    return new, reposts, still_open


def _err(c, e):
    return f"{c['name']} ({c['ats_provider']}): {type(e).__name__} {getattr(e, 'code', '')}".strip()


def pull_all(boards, cfg, workers):
    def one(c):
        try:
            return c, pull(c, cfg), None
        except Exception as e:  # a bad board must never stop the run
            return c, None, e
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(one, boards))
    jobs = [j for c, got, e in results if e is None for j in got]
    failed = [_err(c, e) for c, got, e in results if e is not None]
    empty = sum(1 for c, got, e in results if e is None and not got)
    return jobs, failed, empty


def collect(only=None, workers=8, today=None):
    today = today or dt.date.today().isoformat()
    cfg = common.load_search()
    cos = common.load_companies()
    disabled = [c['name'] for c in cos if c.get('disabled')]
    boards = [c for c in cos if not c.get('disabled')]
    if only:
        names = {n.lower() for n in only}
        boards = [c for c in boards if c['name'].lower() in names]
        if not boards:
            raise common.KitError(f"None of the named employers is an active board: {', '.join(only)}.")
    if not boards:
        raise common.KitError('No employers to watch yet. Add some first (boards.py add-pack israel-tech, or boards.py add FILE).')

    jobs, failed, empty = pull_all(boards, cfg, workers)
    if not jobs and failed:
        raise common.KitError(f'No jobs pulled from any board ({len(failed)} failed, e.g. {failed[0]}). Nothing written. Check the internet connection.')

    compiled = keys.compile_locations(cfg)
    priority = keys.compile_priority(cfg)
    in_scope, out_locs = [], collections.Counter()
    for j in jobs:
        j['loc_class'] = keys.classify_location(j['location'], compiled)
        if j['loc_class'] == 'out':
            out_locs[j['location']] += 1
        else:
            in_scope.append(j)

    seen = common.load_json(common.SEEN(), {})
    rows = common.read_roles()
    listed = {r['url_key'] for r in rows if r['url_key']}  # e.g. a role she pasted before its employer was watched
    new, reposts, still_open = diff(seen, in_scope, today, compiled, listed)

    today_urls = {j['url_key'] for j in in_scope if j['url_key']}
    today_keys = {j['key'] for j in in_scope}
    for r in rows:  # saved roles: tell Claude they are still on the board
        if (r['url_key'] and r['url_key'] in today_urls) or (r['key'] and r['key'] in today_keys):
            r['last_seen'] = today

    written = [(j, 'new') for j in new] + [(j, 'repost') for j in reposts]
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(fetch_sr_text, [j for j, _ in written]))
    rid = common.next_id(rows)
    by_key = {r['key']: r for r in rows if r['key']}  # the latest earlier row for each role key
    new_priority = 0
    for j, kind in written:
        t = keys.tier(j['title'], priority)
        note = ''
        prev = by_key.get(j['key']) if kind == 'repost' else None
        if prev:  # tell Claude what the user already decided about the earlier posting
            note = f"repost of #{prev['id']}"
            if prev['decision']:
                note += f" ({prev['decision']} {prev['decided_on']}" + (f": {prev['decision_reason']}" if prev['decision_reason'] else '') + ')'
            if prev['verdict']:
                note += f"; earlier verdict {prev['verdict']}"
        new_priority += t == 'priority'
        jd_file = common.save_jd(rid, j['company'], j['title'], j['location'], j['url'], j['jd'])
        rows.append({'id': str(rid), 'kind': kind, 'first_seen': today, 'last_seen': today, 'company': j['company'], 'title': j['title'],
                     'location': j['location'], 'loc_class': j['loc_class'], 'tier': t, 'provider': j['provider'], 'url': j['url'],
                     'url_key': j['url_key'], 'key': j['key'], 'jd_file': jd_file, 'jd_chars': str(len(j['jd'] or '')),
                     'note': note, **{f: '' for f in ('verdict', 'reasons', 'gaps', 'reviewed_on', 'decision', 'decision_reason', 'decided_on')}})
        by_key[j['key']] = rows[-1]
        rid += 1

    common.write_roles(rows)  # first: if this fails (file open in Excel), seen.json is untouched and a retry finds the same roles
    common.save_json(common.SEEN(), seen)
    summary = {
        'date': today, 'boards': len(boards), 'failed': failed, 'empty_boards': empty, 'pulled': len(jobs),
        'in_scope': len(in_scope), 'out_of_area': sum(out_locs.values()), 'out_of_area_top': [list(x) for x in out_locs.most_common(15)],
        'unknown_location': sum(j['loc_class'] == 'unknown' for j in in_scope),
        'remote_unplaced': sum(j['loc_class'] == 'remote' for j in in_scope),
        'new': len(new), 'reposts': len(reposts), 'still_open': len(still_open), 'new_priority': new_priority,
        'unreviewed_total': sum(1 for r in rows if not r['verdict'] and not r['decision']), 'disabled_skipped': disabled,
    }
    common.append_run(summary)
    return summary


def main():
    ap = argparse.ArgumentParser(description='Pull job boards and add new roles to me/roles.csv.')
    ap.add_argument('--only', nargs='+', metavar='NAME', help='only these boards (by name)')
    ap.add_argument('--workers', type=int, default=8)
    a = ap.parse_args()
    common.out(collect(a.only, a.workers))


if __name__ == '__main__':
    common.run(main)
