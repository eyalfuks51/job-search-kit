"""Health check. Plain text, at most 6 lines, each starting with OK or FIX. Exit 0 = all good, 1 = something to fix.

    python3 kit/doctor.py [--setup] [--offline]

--setup  the user data folder (me/) not existing yet is fine (setup is about to create it)
--offline  skip the internet check
"""
import argparse
import os
import ssl
import sys
import tempfile
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

PROBE = 'https://boards-api.greenhouse.io/v1/boards/greenhouse/jobs'


def probe(url):
    """Open the URL (15 s). Raises on failure. Tests replace this."""
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    urllib.request.urlopen(req, timeout=15).read(1)


def check_python():
    v = sys.version_info
    ver = f'{v[0]}.{v[1]}.{v[2]}'
    return (True, f'OK Python {ver}') if v >= (3, 9) else (False, f'FIX Python {ver} is too old. Install Python 3.9 or newer.')


def check_me(setup):
    me = common.me()
    if not os.path.isdir(me):
        return (True, 'OK me/ will be created during setup') if setup else (False, 'FIX setup not done yet (the me/ folder does not exist)')
    try:
        fd, tmp = tempfile.mkstemp(dir=me, prefix='.doctor-')
        os.close(fd)
        os.remove(tmp)
    except OSError as e:
        return False, f'FIX me/ is not writable ({e})'
    return True, 'OK me/ exists and is writable'


def check_config(setup):
    if not os.path.isdir(common.me()):
        return (True, 'OK nothing to check yet') if setup else (False, 'FIX search.json and companies.json are missing until setup is done')
    problems = []
    for name, path, loader in (('search.json', common.SEARCH(), common.load_search), ('companies.json', common.COMPANIES(), common.load_companies)):
        if not os.path.exists(path):
            if not setup:
                problems.append(f'{name} is missing')
            continue
        try:
            loader()
        except common.KitError as e:
            problems.append(str(e))
    return (False, 'FIX ' + ' '.join(problems)) if problems else (True, 'OK search.json and companies.json')


def check_roles():
    path = common.ROLES()
    if not os.path.exists(path):
        return True, 'OK no roles file yet'
    with open(path, encoding='utf-8-sig') as f:
        header = f.readline().strip().split(',')
    if header == common.ROLE_FIELDS:
        return True, 'OK roles.csv columns'
    return False, 'FIX roles.csv columns are not the expected ones (do not edit the header in Excel)'


def check_network():
    try:
        probe(PROBE)
    except Exception as e:
        reason = getattr(e, 'reason', e)
        if isinstance(reason, ssl.SSLCertVerificationError) or 'CERTIFICATE_VERIFY_FAILED' in str(e):
            return False, "FIX Python cannot verify certificates. On a Mac, run 'Install Certificates.command' in the Python folder in Applications"
        if isinstance(e, urllib.error.HTTPError):  # the server answered: internet works
            return True, 'OK internet access to job boards'
        return False, 'FIX No internet access to job boards'
    return True, 'OK internet access to job boards'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--setup', action='store_true')
    ap.add_argument('--offline', action='store_true')
    a = ap.parse_args(argv)
    results = [check_python(), check_me(a.setup), check_config(a.setup), check_roles()]
    if not a.offline:
        results.append(check_network())
    print('\n'.join(m for _, m in results))
    return 0 if all(ok for ok, _ in results) else 1


if __name__ == '__main__':
    common.utf8_stdout()
    sys.exit(main())
