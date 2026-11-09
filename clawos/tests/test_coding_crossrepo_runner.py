from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import run_coding_crossrepo as runner


class CrossRepositorySealTests(unittest.TestCase):
    def test_strict_receipts_do_not_make_a_process_startup_error_comparable(self):
        flags = dict.fromkeys(runner.BOUNDARY_FIELDS, True)
        self.assertTrue(runner.sandbox_verified(dict(exit_code=1, sandbox=flags)))
        self.assertFalse(runner.sandbox_verified(dict(exit_code=3221225781, sandbox=flags)))
        self.assertFalse(runner.sandbox_verified(dict(exit_code=1, timed_out=True, sandbox=flags)))

    def test_private_material_cannot_escape_output(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'output'
            output.mkdir()
            with patch.object(runner, 'OUTPUT', output):
                self.assertEqual(runner.contained(output / 'pack'), output / 'pack')
                with self.assertRaises(ValueError):
                    runner.contained(output / '..' / 'outside')

    def test_seal_binds_tests_and_rejects_dirty_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            repo = root / 'src'
            runner.seed(repo, {'a.py': b'x = 1\n', 'LICENSE': b'fixture'}, b'assert True\n')
            service = runner.CodingComparisonService(root / 'fixtures', witness=runner.RUNNER_WITNESS)
            case = dict(id='fixture', repo=str(repo), objective='Fix x', paths=['a.py'],
                        test_commands=[['python', 'acceptance_public.py']],
                        post_commands=[['python', '-c', 'assert True']],
                        requirements=[dict(id='contract', statement='Fix x', paths=['a.py'], test_indexes=[0])])
            check = dict(id=case['id'], case_digest=service.case(case)['case_digest'])
            seal = dict(schema=runner.SCHEMA, cases=[case], checks=[check], witness=service.witness, passed=True)
            frozen = runner.digest(seal)
            path = root / 'seal.json'
            with patch.object(runner, 'OUTPUT', root):
                runner.save(path, seal | dict(seal_digest=frozen))
                self.assertEqual(runner.verified_seal(root, frozen), seal)
                (repo / 'a.py').write_bytes(b'x = 2\n')
                with self.assertRaisesRegex(ValueError, 'clean explicit snapshot'):
                    runner.verified_seal(root, frozen)
                (repo / 'a.py').write_bytes(b'x = 1\n')
                case['post_commands'][0][-1] = 'assert False'
                runner.save(path, seal | dict(seal_digest=runner.digest(seal)))
                with self.assertRaisesRegex(ValueError, 'intact preflight seal'):
                    runner.verified_seal(root, frozen)


if __name__ == '__main__':
    unittest.main()
