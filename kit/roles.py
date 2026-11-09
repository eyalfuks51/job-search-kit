"""Her role list (me/roles.csv): inbox, show, apply (reviews/decisions/manual adds), summary, list.

    python3 kit/roles.py inbox [--tier T] [--limit N] [--titles-only] [--after-id N]
    python3 kit/roles.py show ID [ID ...] [--max-chars 6000]
    python3 kit/roles.py apply FILE.json
    python3 kit/roles.py summary
    python3 kit/roles.py list [--verdict V] [--decision D] [--limit N]
"""
import argparse
import collections
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import keys  # noqa: E402

TIER_ORDER = {'manual': 0, 'priority': 1, 'other': 2}
INBOX_FIELDS = ['id', 'kind', 'tier', 'company', 'title', 'location', 'loc_class', 'jd_chars', 'first_seen']


def today():
    return dt.date.today().isoformat()


def _id(v):
    return str(v).strip()


def _by_id(rows):
    return {r['id']: r for r in rows}


def _public(r):
    return {k: v for k, v in r.items() if k != 'key'}


def inbox(tier='all', limit=None, after_id=None):
    rows = [r for r in common.read_roles() if not r['verdict']]
    by_tier = collections.Counter(r['tier'] for r in rows)
    rows.sort(key=lambda r: int(r['id']) if r['id'].isdigit() else 0)
    rows.sort(key=lambda r: r['first_seen'], reverse=True)
    rows.sort(key=lambda r: TIER_ORDER.get(r['tier'], 3))  # stable: tier, newest first, id
    if tier != 'all':
        rows = [r for r in rows if r['tier'] == tier]
    if after_id is not None:  # a stable cursor for skimming page by page: id order, only ids after the last one seen
        rows = sorted((r for r in rows if r['id'].isdigit() and int(r['id']) > after_id), key=lambda r: int(r['id']))
    if limit is not None:
        rows = rows[:limit]
    return {'unreviewed': sum(by_tier.values()), 'by_tier': dict(by_tier), 'paged': after_id is not None,
            'roles': [{k: r[k] for k in INBOX_FIELDS} for r in rows]}


def inbox_text(res):
    n = len(res['roles'])
    head = f"# {res['unreviewed']} unreviewed" + (f' (showing {n}' + (f", next page: --after-id {res['roles'][-1]['id']}" if n and res.get('paged') else ', page with --tier and --after-id' if n else '') + ')' if n < res['unreviewed'] else '')
    clean = lambda s: ' '.join(str(s).split())
    return '\n'.join([head] + ['\t'.join(clean(r[k]) for k in ('id', 'tier', 'company', 'title', 'location')) for r in res['roles']])


def show(ids, max_chars=6000):
    rows = _by_id(common.read_roles())
    missing = [i for i in map(_id, ids) if i not in rows]
    if missing:
        raise common.KitError('No role with id: ' + ', '.join(missing))
    out = []
    for i in map(_id, ids):
        r = _public(rows[i])
        path = os.path.join(common.ROOT, r['jd_file']) if r['jd_file'] else ''
        if path and os.path.isfile(path):
            with open(path, encoding='utf-8') as f:
                text = f.read()
            r['job_text'] = text[:max_chars]
            if len(text) > max_chars:
                r['truncated'] = True
        else:
            r['job_text'], r['job_text_missing'] = '', True
        out.append(r)
    return out


# ---- apply ----

def _check_fields(item, where, errors):
    v = item.get('verdict')
    if 'verdict' in item and v not in ('',) + common.VERDICTS:
        errors.append(f'{where}: verdict {v!r} is not one of {", ".join(common.VERDICTS)}')
    elif v in ('no-fit', 'set-aside') and not str(item.get('reasons') or '').strip():
        errors.append(f'{where}: verdict {v} needs non-empty reasons')
    d = item.get('decision')
    if 'decision' in item and d not in ('',) + common.DECISIONS:
        errors.append(f'{where}: decision {d!r} is not one of {", ".join(common.DECISIONS)}')
    elif d == 'skipped' and not str(item.get('decision_reason') or '').strip():
        errors.append(f'{where}: decision skipped needs decision_reason')


def validate(items, existing_ids):
    errors = []
    if not isinstance(items, list):
        return ['The file must contain a JSON list.']
    for n, item in enumerate(items):
        where = f'item {n}'
        if not isinstance(item, dict):
            errors.append(f'{where}: not an object')
            continue
        if item.get('add'):
            for f in ('company', 'title'):
                if not str(item.get(f) or '').strip():
                    errors.append(f'{where}: add needs {f}')
            if not (str(item.get('url') or '').strip() or str(item.get('job_text') or '').strip()):
                errors.append(f'{where}: add needs url or job_text')
        elif 'ids' in item or 'id' in item:
            ids = item['ids'] if 'ids' in item else [item['id']]
            if not isinstance(ids, list) or not ids:
                errors.append(f'{where}: ids must be a non-empty list')
                ids = []
            bad = [_id(i) for i in ids if _id(i) not in existing_ids]
            if bad:
                errors.append(f'{where}: no role with id ' + ', '.join(bad))
        else:
            errors.append(f'{where}: needs id, ids or add')
        _check_fields(item, where, errors)
    return errors


def _set_fields(row, item, day):
    """Copy review/decision fields from item onto row. Returns True when anything was set."""
    changed = False
    for f in ('verdict', 'reasons', 'gaps', 'decision', 'decision_reason', 'note'):
        if f in item:
            row[f] = str(item[f] or '')
            changed = True
    if 'verdict' in item:
        row['reviewed_on'] = day if row['verdict'] else ''
    if 'decision' in item:
        row['decided_on'] = day if row['decision'] else ''
    return changed


def _compiled():
    try:
        return keys.compile_locations(common.load_search())
    except common.KitError:
        return None


def apply(items):
    rows = common.read_roles()
    by_id = _by_id(rows)
    errors = validate(items, set(by_id))
    if errors:
        raise common.KitError('Nothing was changed. Fix these and retry:\n' + '\n'.join(errors))
    day, comp = today(), None
    updated, added, existing = set(), [], []
    for item in items:
        if not item.get('add'):
            for i in map(_id, item['ids'] if 'ids' in item else [item['id']]):
                if _set_fields(by_id[i], item, day):
                    updated.add(i)
            continue
        comp = comp or _compiled()
        url = str(item.get('url') or '').strip()
        uk = (keys.url_key(url) or '') if url else ''
        hit = next((r for r in rows if uk and r['url_key'] == uk), None)
        if hit:
            existing.append(int(hit['id']))
            if _set_fields(hit, item, day):
                updated.add(hit['id'])
            continue
        company, title, loc = item['company'].strip(), item['title'].strip(), str(item.get('location') or '').strip()
        text = str(item.get('job_text') or '')
        rid = str(common.next_id(rows))
        cls = keys.classify_location(loc, comp) if comp else 'unknown'
        row = {f: '' for f in common.ROLE_FIELDS}
        row.update(id=rid, kind='manual', tier='manual', first_seen=day, last_seen=day, company=company, title=title, location=loc,
                   loc_class='unknown' if cls == 'out' else cls, provider='manual', url=url, url_key=uk,
                   key=keys.role_key(company, title, loc, comp or keys.compile_locations({})),
                   jd_file=common.save_jd(rid, company, title, loc, url, text), jd_chars=str(len(text)))
        _set_fields(row, item, day)
        rows.append(row)
        by_id[rid] = row
        added.append(int(rid))
    common.write_roles(rows)
    return {'updated': len(updated), 'added': added, 'existing': existing}


def apply_file(path):
    items = common.load_json(path)
    if items is None:
        raise common.KitError(f'File not found: {path}')
    return apply(items)


# ---- summary / list ----

def summary():
    rows = common.read_roles()
    last = common.last_run()
    on = lambda r: {'id': int(r['id']), 'company': r['company'], 'title': r['title'], 'url': r['url'], 'last_seen': r['last_seen'],
                    'on_board_last_run': bool(last) and r['last_seen'] == last.get('date')}
    unrev = [r for r in rows if not r['verdict']]
    return {'total': len(rows), 'unreviewed': len(unrev),
            'unreviewed_by_tier': dict(collections.Counter(r['tier'] for r in unrev)),
            'verdicts': dict(collections.Counter(r['verdict'] for r in rows if r['verdict'])),
            'decisions': dict(collections.Counter(r['decision'] for r in rows if r['decision'])),
            'last_run': last,
            'saved': [on(r) for r in rows if r['decision'] == 'saved'],
            'applied': [on(r) for r in rows if r['decision'] == 'applied']}


def list_roles(verdict=None, decision=None, limit=None):
    rows = [r for r in common.read_roles() if (not verdict or r['verdict'] == verdict) and (not decision or r['decision'] == decision)]
    return [_public(r) for r in (rows[:limit] if limit is not None else rows)]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('inbox')
    p.add_argument('--tier', choices=['priority', 'other', 'manual', 'all'], default='all')
    p.add_argument('--limit', type=int)
    p.add_argument('--titles-only', action='store_true')
    p.add_argument('--after-id', type=int, help='only roles with a higher id, in id order (for paging)')
    p = sub.add_parser('show')
    p.add_argument('ids', nargs='+')
    p.add_argument('--max-chars', type=int, default=6000)
    sub.add_parser('apply').add_argument('file')
    sub.add_parser('summary')
    p = sub.add_parser('list')
    p.add_argument('--verdict', choices=list(common.VERDICTS))
    p.add_argument('--decision', choices=list(common.DECISIONS))
    p.add_argument('--limit', type=int)
    a = ap.parse_args(argv)
    if a.cmd == 'inbox':
        limit = a.limit if a.limit is not None else (300 if a.titles_only else None)  # keep one page inside a tool output
        # skimming one tier pages in id order with --after-id; across all tiers the order is manual, priority, other
        after = a.after_id if a.after_id is not None else (0 if a.titles_only and a.tier != 'all' else None)
        res = inbox(a.tier, limit, after)
        print(inbox_text(res)) if a.titles_only else common.out(res)
    elif a.cmd == 'show':
        common.out(show(a.ids, a.max_chars))
    elif a.cmd == 'apply':
        common.out(apply_file(a.file))
    elif a.cmd == 'summary':
        common.out(summary())
    else:
        common.out(list_roles(a.verdict, a.decision, a.limit))


if __name__ == '__main__':
    common.run(main)
