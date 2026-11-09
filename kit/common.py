"""Shared paths, file I/O and output helpers. Standard library only, Python 3.9+.

Every kit command runs from the repo root and writes only under me/.
"""
import csv
import json
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ME = os.environ.get('JOBKIT_ME') or os.path.join(ROOT, 'me')  # tests point this at a temp dir
SEEDS = os.path.join(ROOT, 'seeds')


def me(*parts):
    return os.path.join(ME, *parts)


SEARCH = lambda: me('search.json')
COMPANIES = lambda: me('companies.json')
SEEN = lambda: me('state', 'seen.json')
ROLES = lambda: me('roles.csv')
RUNS = lambda: me('runs.jsonl')
JD_DIR = lambda: me('jd')

ROLE_FIELDS = [
    'id', 'kind', 'first_seen', 'last_seen', 'company', 'title', 'location', 'loc_class', 'tier', 'provider',
    'url', 'url_key', 'key', 'jd_file', 'jd_chars',
    'verdict', 'reasons', 'gaps', 'reviewed_on',
    'decision', 'decision_reason', 'decided_on', 'note',
]
KINDS = ('new', 'repost', 'manual')
VERDICTS = ('strong', 'possible', 'stretch', 'no-fit', 'set-aside')
DECISIONS = ('saved', 'applied', 'skipped')


class KitError(Exception):
    """A problem the user or Claude can fix. Printed as {"error": ...}, exit code 1."""


def utf8_stdout():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding='utf-8')
        except (AttributeError, ValueError):
            pass


def out(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=1))


def run(main):
    """Run a command's main(); turn KitError into a JSON error line and exit 1."""
    utf8_stdout()
    try:
        main()
    except KitError as e:
        out({'error': str(e)})
        sys.exit(1)


def _atomic_write(path, write):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.tmp-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8-sig' if path.endswith('.csv') else 'utf-8', newline='') as f:
            write(f)
        try:
            os.replace(tmp, path)
        except PermissionError:
            raise KitError(f'Cannot write {os.path.basename(path)}: the file is open in another program (Excel?). Close it and retry.')
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding='utf-8-sig') as f:
            return json.load(f)
    except ValueError as e:
        raise KitError(f'{os.path.basename(path)} is not valid JSON ({e}).')


def save_json(path, obj):
    _atomic_write(path, lambda f: json.dump(obj, f, ensure_ascii=False, indent=1))


def read_roles():
    path = ROLES()
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k in ROLE_FIELDS:
            r[k] = r.get(k) or ''
    return rows


def write_roles(rows):
    def w(f):
        wr = csv.DictWriter(f, fieldnames=ROLE_FIELDS, extrasaction='ignore')
        wr.writeheader()
        wr.writerows(rows)
    _atomic_write(ROLES(), w)


def next_id(rows):
    return max([int(r['id']) for r in rows if str(r.get('id', '')).isdigit()] or [0]) + 1


def append_run(obj):
    os.makedirs(ME, exist_ok=True)
    with open(RUNS(), 'a', encoding='utf-8') as f:
        f.write(json.dumps(obj, ensure_ascii=False) + '\n')


def last_run():
    if not os.path.exists(RUNS()):
        return None
    with open(RUNS(), encoding='utf-8') as f:
        lines = [x for x in f.read().splitlines() if x.strip()]
    return json.loads(lines[-1]) if lines else None


def safe_name(s):
    return re.sub(r'[^\w\-]+', '_', s or '', flags=re.UNICODE).strip('_')[:60]


def save_jd(role_id, company, title, location, url, text):
    """Write the job text to me/jd/<id>_<company>.txt and return the path relative to the repo root (forward slashes)."""
    os.makedirs(JD_DIR(), exist_ok=True)
    path = os.path.join(JD_DIR(), f'{role_id}_{safe_name(company)}.txt')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(f'{company} | {title}\n{location}\n{url}\n\n{text or ""}\n')
    return os.path.relpath(path, ROOT).replace(os.sep, '/')


def load_search():
    """me/search.json, validated. Raises KitError with a plain message when missing or broken."""
    cfg = load_json(SEARCH())
    if cfg is None:
        raise KitError('No search profile yet (me/search.json). Finish setup first.')
    loc = cfg.get('locations') or {}
    if not loc.get('include'):
        raise KitError('search.json: locations.include is empty. Add at least one place.')
    for field in ('include', 'exclude'):
        for t in loc.get(field) or []:
            try:
                re.compile(t)
            except re.error as e:
                raise KitError(f'search.json: locations.{field} term {t!r} is not a valid pattern ({e}).')
    for t in cfg.get('priority_keywords') or []:
        try:
            re.compile(t)
        except re.error as e:
            raise KitError(f'search.json: priority_keywords term {t!r} is not a valid pattern ({e}).')
    return cfg


def load_companies():
    cos = load_json(COMPANIES(), [])
    if not isinstance(cos, list):
        raise KitError('companies.json must be a list.')
    return cos
