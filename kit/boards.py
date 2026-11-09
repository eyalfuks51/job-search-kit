"""The employers she watches (me/companies.json): detect an ATS, check a board, add/disable/list.

    python3 kit/boards.py detect URL
    python3 kit/boards.py check PROVIDER TOKEN
    python3 kit/boards.py add FILE.json
    python3 kit/boards.py add-pack israel-tech
    python3 kit/boards.py replace FILE.json
    python3 kit/boards.py disable NAME --reason TEXT
    python3 kit/boards.py enable NAME
    python3 kit/boards.py list
"""
import argparse
import collections
import datetime as dt
import glob
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import keys  # noqa: E402

UA = {'User-Agent': 'Mozilla/5.0', 'Accept': '*/*'}  # a longer fake-Chrome string gets dropped by some bot filters
GENERIC = {'embed', 'api', 'v1', 'jobs', 'job', 'js', 'careers', 'www', 'boards', 'widget', 'static', 'assets'}
_T = r'([A-Za-z0-9][A-Za-z0-9_-]*)'
# (provider, regex with the token as group 1). Searched in the URL, then in the page HTML.
PATTERNS = [
    ('greenhouse', r'boards-api\.greenhouse\.io/v1/boards/' + _T),
    ('greenhouse', r'greenhouse\.io/embed/job_board(?:/js)?\?(?:[^"\'\s<>]*&)?for=' + _T),
    ('greenhouse', r'boards(?:\.[a-z]{2})?\.greenhouse\.io/' + _T),
    ('lever', r'jobs(?:\.eu)?\.lever\.co/' + _T),
    ('ashby', r'jobs\.ashbyhq\.com/' + _T),
    ('smartrecruiters', r'(?:jobs|careers)\.smartrecruiters\.com/' + _T),
    ('recruitee', r'//' + _T + r'\.recruitee\.com'),
]
COMEET_PAGE = re.compile(r'comeet\.com/jobs/([\w-]+)/([0-9A-Fa-f]{2}\.[0-9A-Fa-f]{3})\b')
COMEET_UID = re.compile(r'(?:(?:company|comeet)[-_ ]?uid["\']?\s*[:=]\s*["\']?|careers-api/2\.0/company/)([0-9A-Fa-f]{2}\.[0-9A-Fa-f]{3})\b', re.I)
COMEET_TOKEN = re.compile(r'token["\']?\s*[:=]\s*["\']?([0-9A-Fa-f]{20,})\b', re.I)


def fetch(url):
    """Page text (at most 2 MB, 30 s timeout). Tests replace this."""
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read(2_000_000).decode('utf-8', 'replace')


def _top(counter):
    return counter.most_common(1)[0][0] if counter else None


def scan(s, comeet=False):
    """Fingerprints in a URL or page text: ATS tokens by provider, plus Comeet slug / UID / API token.
    A page token only counts as Comeet's when the text mentions Comeet (or comeet=True: it is a comeet.com page)."""
    s = s.replace('\\/', '/').replace('\\"', '"').replace('&amp;', '&')
    found = collections.Counter()
    for prov, rx in PATTERNS:
        for m in re.finditer(rx, s, re.I):
            if m.group(1).lower() not in GENERIC:
                found[(prov, m.group(1).lower() if prov == 'recruitee' else m.group(1))] += 1
    pages = collections.Counter((slug, uid.upper()) for slug, uid in COMEET_PAGE.findall(s))
    uids = collections.Counter(u.upper() for u in COMEET_UID.findall(s))
    for (_, uid), n in pages.items():
        uids[uid] += n
    toks = collections.Counter(COMEET_TOKEN.findall(s)) if comeet or 'comeet' in s.lower() else collections.Counter()
    slug, page_uid = _top(pages) or (None, None)
    return {'found': found, 'slug': slug, 'uid': _top(uids) or page_uid, 'token': _top(toks)}


def identify(url):
    """(provider, token, name_guess), or (None, reason, None)."""
    info = scan(url)
    if not info['found'] and not info['uid']:
        info = scan(fetch(url))
    if info['found']:
        prov, tok = _top(info['found'])
        return prov, tok, tok.replace('-', ' ').replace('_', ' ').title()
    if info['uid'] and info['slug']:
        # a Comeet job/company page link: Comeet's own company page is the reliable source of the API token
        try:
            info['token'] = scan(fetch(f"https://www.comeet.com/jobs/{info['slug']}/{info['uid']}"), comeet=True)['token'] or info['token']
        except OSError:
            pass
    if info['uid'] and info['token']:
        return 'comeet', f"{info['uid']}::{info['token']}", (info['slug'] or info['uid']).replace('-', ' ').title()
    if info['uid']:
        return None, 'Comeet found but its API token is not on the page. Ask the employer for it, or skip.', None
    return None, 'No known ATS (Greenhouse, Lever, Ashby, SmartRecruiters, Recruitee, Comeet) found at that address.', None


def detect(url):
    url = url.strip()
    if not re.match(r'^https?://', url, re.I):
        url = 'https://' + url
    try:
        prov, tok, guess = identify(url)
    except OSError as e:  # URLError, HTTPError, timeouts, SSL errors
        return {'provider': None, 'reason': f'Could not open the page ({type(e).__name__} {getattr(e, "code", "") or e}).'}
    if not prov:
        return {'provider': None, 'reason': tok}
    res = {'provider': prov, 'token': tok, 'name_guess': guess, 'verified': False, 'jobs': None}
    try:
        import collect
        res['jobs'] = len(collect.pull({'name': guess, 'ats_provider': prov, 'ats_token': tok}))
        res['verified'] = True
    except Exception:  # not verified is an answer, not an error (also when collect is unavailable)
        pass
    return res


def check(provider, token):
    try:
        import collect
        jobs = collect.pull({'name': token, 'ats_provider': provider, 'ats_token': token})
    except Exception as e:
        return {'ok': False, 'error': f'{type(e).__name__} {getattr(e, "code", "") or e}'.strip()}
    res = {'ok': True, 'jobs': len(jobs), 'in_area': None, 'sample_titles': [j['title'] for j in jobs[:8]]}
    try:
        comp = keys.compile_locations(common.load_search())
    except common.KitError:
        return res
    inside = [j for j in jobs if keys.classify_location(j.get('location', ''), comp) != 'out']
    res['in_area'] = len(inside)
    res['sample_titles'] = [j['title'] for j in (inside or jobs)[:8]]
    return res


# ---- me/companies.json ----

def _same(a, b):
    return (a['ats_provider'].lower(), str(a['ats_token']).lower()) == (b['ats_provider'].lower(), str(b['ats_token']).lower())


def add(items):
    cos = common.load_companies()
    added, dups = [], []
    for it in items:
        missing = [f for f in ('name', 'ats_provider', 'ats_token') if not it.get(f)]
        if missing:
            raise common.KitError(f'Board {it.get("name") or it!r} is missing: {", ".join(missing)}.')
        if any(_same(it, c) for c in cos):
            dups.append(it['name'])
            continue
        entry = {k: it[k] for k in ('name', 'ats_provider', 'ats_token', 'careers_url') if it.get(k)}
        entry['added'] = dt.date.today().isoformat()
        cos.append(entry)
        added.append(it['name'])
    common.save_json(common.COMPANIES(), cos)
    return {'added': added, 'duplicates': dups}


def add_pack(name):
    packs = {os.path.splitext(os.path.basename(p))[0]: p for p in glob.glob(os.path.join(common.SEEDS, '*.json'))}
    if name not in packs:
        raise common.KitError(f'Unknown pack {name!r}. Available: {", ".join(sorted(packs)) or "none"}.')
    cos = common.load_companies()
    n = already = 0
    for it in common.load_json(packs[name], []):
        if not it.get('ats_provider') or not it.get('ats_token'):
            continue
        if any(_same(it, c) for c in cos):
            already += 1
            continue
        keep = ('name', 'ats_provider', 'ats_token', 'careers_url', 'disabled', 'disabled_reason', 'disabled_since')
        cos.append({k: it[k] for k in keep if k in it})
        n += 1
    common.save_json(common.COMPANIES(), cos)
    return {'added': n, 'already': already, 'total': len(cos)}


_OFF = ('disabled', 'disabled_reason', 'disabled_since')


def set_disabled(name, reason=None):
    cos = common.load_companies()
    hit = [c for c in cos if c['name'].lower() == name.strip().lower()]
    if not hit:
        raise common.KitError(f'No employer named {name!r}. Use "list" to see the names.')
    if reason is None and len(hit) > 1:  # enabling by name would turn on every board this employer ever had
        raise common.KitError(f'{hit[0]["name"]!r} has {len(hit)} boards. Use "replace" to choose the one to watch.')
    for c in hit:
        for k in _OFF:
            c.pop(k, None)
        if reason is not None:
            c.update(disabled=True, disabled_reason=reason, disabled_since=dt.date.today().isoformat())
    common.save_json(common.COMPANIES(), cos)
    return {'name': hit[0]['name'], 'disabled': reason is not None}


def replace(it):
    """Point an employer at a different board. The new board is tested first; on any failure nothing changes.
    Then, in one write, exactly that board is active for the employer (re-enabled if it was listed before)
    and the employer's other boards are disabled."""
    missing = [f for f in ('name', 'ats_provider', 'ats_token') if not it.get(f)]
    if missing:
        raise common.KitError(f'Replacement for {it.get("name") or it!r} is missing: {", ".join(missing)}.')
    cos = common.load_companies()
    key = it['name'].strip().lower()
    mine = [c for c in cos if c['name'].lower() == key]
    if not mine:
        raise common.KitError(f'No employer named {it["name"]!r}. Use "list" to see the names, or "add" for a new one.')
    other = [c for c in cos if _same(it, c) and c['name'].lower() != key]
    if other:
        raise common.KitError(f'That board is already watched as {other[0]["name"]!r}. Nothing changed.')
    try:
        import collect
        jobs = collect.pull({'name': mine[0]['name'], 'ats_provider': it['ats_provider'], 'ats_token': it['ats_token']})
    except Exception as e:
        why = f'{type(e).__name__} {getattr(e, "code", "") or e}'.strip()
        raise common.KitError(f'The new board did not work ({why}). Nothing changed.')
    today = dt.date.today().isoformat()
    target = next((c for c in mine if _same(it, c)), None)
    if target is None:
        target = {'name': mine[0]['name'], 'ats_provider': it['ats_provider'], 'ats_token': it['ats_token'], 'added': today}
        cos.append(target)
    for k in _OFF:
        target.pop(k, None)
    if it.get('careers_url'):
        target['careers_url'] = it['careers_url']
    turned_off = []
    for c in mine:
        if c is not target and not c.get('disabled'):
            c.update(disabled=True, disabled_reason=f"replaced by {it['ats_provider']} {it['ats_token']}", disabled_since=today)
            turned_off.append(f"{c['ats_provider']} {c['ats_token']}")
    common.save_json(common.COMPANIES(), cos)
    return {'name': target['name'], 'active': f"{target['ats_provider']} {target['ats_token']}", 'disabled': turned_off, 'jobs': len(jobs)}


def list_boards():
    cos = common.load_companies()
    off = sum(1 for c in cos if c.get('disabled'))
    return {'active': len(cos) - off, 'disabled': off,
            'boards': [{'name': c['name'], 'provider': c.get('ats_provider'), 'disabled': bool(c.get('disabled'))} for c in cos]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('detect').add_argument('url')
    p = sub.add_parser('check')
    p.add_argument('provider')
    p.add_argument('token')
    sub.add_parser('add').add_argument('file')
    sub.add_parser('add-pack').add_argument('pack')
    sub.add_parser('replace').add_argument('file')
    p = sub.add_parser('disable')
    p.add_argument('name')
    p.add_argument('--reason', required=True)
    sub.add_parser('enable').add_argument('name')
    sub.add_parser('list')
    a = ap.parse_args(argv)
    if a.cmd == 'detect':
        res = detect(a.url)
    elif a.cmd == 'check':
        res = check(a.provider, a.token)
    elif a.cmd == 'add':
        items = common.load_json(a.file)
        if not isinstance(items, list):
            raise common.KitError('The file must contain a JSON list of boards.')
        res = add(items)
    elif a.cmd == 'add-pack':
        res = add_pack(a.pack)
    elif a.cmd == 'replace':
        it = common.load_json(a.file)
        if not isinstance(it, dict):
            raise common.KitError('The file must contain one JSON object: {"name", "ats_provider", "ats_token", "careers_url"}.')
        res = replace(it)
    elif a.cmd == 'disable':
        res = set_disabled(a.name, a.reason)
    elif a.cmd == 'enable':
        res = set_disabled(a.name)
    else:
        res = list_boards()
    common.out(res)


if __name__ == '__main__':
    common.run(main)
