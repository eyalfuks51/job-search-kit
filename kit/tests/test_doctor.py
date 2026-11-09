import contextlib
import io
import os
import shutil
import ssl
import sys
import tempfile
import unittest
import urllib.error

os.environ.setdefault('JOBKIT_ME', tempfile.mkdtemp(prefix='jobkit-test-'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import common  # noqa: E402
import doctor  # noqa: E402


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='jobkit-')
        self.me = os.path.join(self.tmp, 'me')
        self._me, common.ME = common.ME, self.me
        self._probe = doctor.probe
        self.addCleanup(lambda: (setattr(common, 'ME', self._me), setattr(doctor, 'probe', self._probe), shutil.rmtree(self.tmp, ignore_errors=True)))

    def run_doctor(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = doctor.main(list(argv))
        return code, buf.getvalue().splitlines()

    def test_missing_me(self):
        code, lines = self.run_doctor('--offline')
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith('OK Python'))
        self.assertTrue(any('setup not done yet' in x and x.startswith('FIX') for x in lines))
        code, lines = self.run_doctor('--offline', '--setup')
        self.assertEqual(code, 0)
        self.assertTrue(all(x.startswith('OK') for x in lines))

    def test_empty_me_dir(self):
        os.makedirs(self.me)
        code, lines = self.run_doctor('--offline')
        self.assertEqual(code, 1)
        self.assertTrue(any('search.json is missing' in x for x in lines))
        self.assertEqual(self.run_doctor('--offline', '--setup')[0], 0)

    def test_valid_me(self):
        common.save_json(common.SEARCH(), {'locations': {'include': ['haifa']}})
        common.save_json(common.COMPANIES(), [])
        common.write_roles([])
        code, lines = self.run_doctor('--offline')
        self.assertEqual(code, 0)
        self.assertLessEqual(len(lines), 6)
        self.assertTrue(all(x.startswith('OK') for x in lines), lines)

    def test_broken_files_reported(self):
        os.makedirs(self.me)
        with open(common.SEARCH(), 'w', encoding='utf-8') as f:
            f.write('{not json')
        common.save_json(common.COMPANIES(), {'a': 1})
        with open(common.ROLES(), 'w', encoding='utf-8') as f:
            f.write('id,title\n1,x\n')
        code, lines = self.run_doctor('--offline')
        text = '\n'.join(lines)
        self.assertEqual(code, 1)
        self.assertIn('search.json is not valid JSON', text)
        self.assertIn('companies.json must be a list', text)
        self.assertIn('roles.csv columns', text)
        self.assertLessEqual(len(lines), 6)

    def test_network_outcomes(self):
        os.makedirs(self.me)
        doctor.probe = lambda url: None
        self.assertEqual(doctor.check_network(), (True, 'OK internet access to job boards'))
        doctor.probe = lambda url: (_ for _ in ()).throw(urllib.error.URLError(ssl.SSLCertVerificationError(1, 'CERTIFICATE_VERIFY_FAILED')))
        ok, msg = doctor.check_network()
        self.assertFalse(ok)
        self.assertIn('Install Certificates.command', msg)
        doctor.probe = lambda url: (_ for _ in ()).throw(urllib.error.URLError('getaddrinfo failed'))
        self.assertEqual(doctor.check_network(), (False, 'FIX No internet access to job boards'))
        doctor.probe = lambda url: (_ for _ in ()).throw(TimeoutError())
        self.assertFalse(doctor.check_network()[0])


if __name__ == '__main__':
    unittest.main()
