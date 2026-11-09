"""Role identity, location matching and title priority. Pure functions, no I/O.

url_key (from job-discovery sync_jobs.py; provider + job id, never the slug or tracking query):
    ashby            ashby:<org>/<uuid>
    lever            lever:<org>/<uuid>
    smartrecruiters  smartrecruiters:<company>/<digits>
    comeet           comeet:<UID>/<POS>
    greenhouse       greenhouse:<id>      (gh_jid query parameter, else /jobs/<id> on a greenhouse.io host)
    anything else    other:<scheme>://<host><path>[?<sorted query without utm_*, gclid, fbclid>]

role key = normalized company | normalized title | city.
The city is the first match of the user's own location terms, so the same title in two cities is two roles.
A role with the same key but a new url_key is a repost.
"""
import re

_UUID = re.compile(r'^[0-9a-f-]{36}$')
_TRACKING = ('gclid', 'fbclid')
REMOTE = re.compile(r'remote|anywhere|worldwide|global|work from home|\bwfh\b|מהבית|היברידי מלא', re.I)


def _split(url):
    rest = re.sub(r'^[A-Za-z][A-Za-z0-9+.-]*://', '', (url or '').strip())
    m = re.match(r'^([^/?#]*)([^?#]*)(?:\?([^#]*))?', rest)
    if not m:
        return '', [], ''
    host = re.sub(r':[0-9]+$', '', re.sub(r'^[^@]*@', '', m.group(1))).lower()
    segs = [s for s in m.group(2).split('/') if s]
    return host, segs, m.group(3) or ''


def _generic_key(url, host, query):
    stripped = (url or '').strip()
    sm = re.match(r'^([A-Za-z][A-Za-z0-9+.-]*)://', stripped)
    scheme = sm.group(1).lower() if sm else None
    rest = stripped[sm.end():] if sm else stripped
    m = re.match(r'^([^/?#]*)([^?#]*)(?:\?([^#]*))?', rest)
    auth = re.sub(r'^[^@]*@', '', m.group(1))
    pm = re.search(r':([0-9]+)$', auth)
    port = pm.group(1) if pm else None
    if (scheme == 'http' and port == '80') or (scheme == 'https' and port == '443'):
        port = None
    kept = sorted((q for q in query.split('&')
                   if q != '' and not q.split('=', 1)[0].lower().startswith('utm_') and q.split('=', 1)[0].lower() not in _TRACKING),
                  key=lambda q: q.split('=', 1)[0])
    key = 'other:' + (scheme + '://' if scheme else '') + host + (':' + port if port else '') + m.group(2)
    if kept:
        key += '?' + '&'.join(kept)
    return key


def url_key(url):
    """Canonical key for a job URL, or None when the URL has no host."""
    host, segs, query = _split(url)
    if not host:
        return None
    n = len(segs)
    if host == 'jobs.ashbyhq.com' and n >= 2 and _UUID.match(segs[1].lower()):
        return f'ashby:{segs[0].lower()}/{segs[1].lower()}'
    if host == 'jobs.lever.co' and n >= 2 and _UUID.match(segs[1].lower()):
        return f'lever:{segs[0].lower()}/{segs[1].lower()}'
    if host == 'jobs.smartrecruiters.com' and n >= 2 and re.match(r'^[0-9]+', segs[1]):
        return f"smartrecruiters:{segs[0].lower()}/{re.match(r'^[0-9]+', segs[1]).group(0)}"
    if host in ('www.comeet.com', 'comeet.com') and n >= 4 and segs[0] == 'jobs':
        return f'comeet:{segs[2].upper()}/{segs[-1].upper()}'
    gh = re.search(r'(?:^|&)gh_jid=([0-9]+)', query)
    gid = gh.group(1) if gh else None
    if gid is None and host.endswith('greenhouse.io'):
        m = re.search(r'/jobs/([0-9]+)', '/' + '/'.join(segs))
        gid = m.group(1) if m else None
    if gid is not None:
        return f'greenhouse:{gid}'
    return _generic_key(url, host, query)


def norm(s):
    s = re.sub(r'[/.\-–—()|,:]+', ' ', (s or '').lower())
    return re.sub(r'\s+', ' ', s).strip()  # seniority words are kept: a Junior and a Senior opening are different roles


def compile_locations(cfg):
    """(include, exclude, keep_remote) from search.json. Terms are case-insensitive regular expressions."""
    loc = cfg.get('locations') or {}
    inc = [re.compile(t, re.I) for t in loc.get('include') or []]
    exc = [re.compile(t, re.I) for t in loc.get('exclude') or []]
    return inc, exc, bool(loc.get('keep_unplaced_remote', True))


def area_match(location, inc, exc):
    """The first include match after removing exclude matches, lowercased, or ''.
    Exclude terms remove look-alikes first: 'Chicago, IL' with exclude 'chicago(,\\s*IL\\b)?' no longer matches '\\bIL\\b'."""
    s = location or ''
    for x in exc:
        s = x.sub(' ', s)
    hits = [m for m in (p.search(s) for p in inc) if m]
    if not hits:
        return ''
    return min(hits, key=lambda m: m.start()).group(0).lower().strip()  # leftmost, as one alternation would match


def classify_location(location, compiled):
    """'area' (one of her places), 'remote' (says remote and names no place of hers or other), 'unknown' (empty),
    or 'out' (somewhere else). Only 'out' is left out of her inbox, and it is counted in the run summary."""
    inc, exc, keep_remote = compiled
    if area_match(location, inc, exc):
        return 'area'
    if not (location or '').strip():
        return 'unknown'
    if keep_remote and REMOTE.search(location) and not _names_a_place(location):
        return 'remote'
    return 'out'


_PLACE = re.compile(r'[A-Za-z֐-׿]{2,}')
_NOT_PLACES = {'remote', 'anywhere', 'worldwide', 'global', 'work', 'from', 'home', 'wfh', 'hybrid', 'fully', 'only', 'office', 'flexible', 'first', 'job', 'jobs', 'position', 'role', 'based', 'friendly', 'opportunity', 'or', 'and', 'in', 'of', 'the', 'מהבית'}


def _names_a_place(location):
    """True when a remote location also names somewhere ('Remote - US', 'Remote, Germany')."""
    words = [w.lower() for w in _PLACE.findall(location)]
    return any(w not in _NOT_PLACES for w in words)


def role_key(company, title, location, compiled):
    city = area_match(location, compiled[0], compiled[1])
    return f'{norm(company)}|{norm(title)}|{city}'


def compile_priority(cfg):
    return [re.compile(t, re.I) for t in cfg.get('priority_keywords') or []]


def tier(title, priority):
    """'priority' when the title matches one of her keywords, else 'other'. Ordering only: never a reason to hide a role."""
    return 'priority' if any(p.search(title or '') for p in priority) else 'other'
