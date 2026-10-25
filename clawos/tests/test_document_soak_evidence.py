"""Counterexamples that must never earn a successful long-load verdict."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from document_soak_evidence import Coverage, execution_request, source_fingerprints


class Clock:
    def __init__(self):
        self.mono = 0.
        self.wall = 1000.

    def advance(self, seconds, wall_seconds=None):
        self.mono += seconds
        self.wall += seconds if wall_seconds is None else wall_seconds


class DocumentSoakEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.guard = Coverage(12, 30, lambda: self.clock.mono, lambda: self.clock.wall)

    def active(self):
        for i in range(12):
            self.guard.write(i)
            self.guard.packet(i, 'document', self.guard.clients[i]['version'] + 1)
            self.guard.packet(i, 'cursors')

    def test_real_intervals_require_every_client_and_monotonic_events(self):
        for _ in range(9):
            self.clock.advance(10)
            self.active()
            self.assertEqual(self.guard.check(), [])
        self.assertEqual(self.guard.covered_seconds, 90)
        self.assertTrue(self.guard.clients_pass())
        with self.assertRaisesRegex(ValueError, 'non_monotonic'):
            self.guard.packet(0, 'document', 9)
        self.assertEqual(len(self.guard.summary()['per_client']), 12)

    def test_old_suspend_failure_is_not_credited_and_cannot_resume_to_pass(self):
        self.clock.advance(10)
        self.active()
        self.guard.check()
        self.clock.advance(5453.69)
        self.active()  # Aggregate counters could look healthy after resume.
        self.assertIn('monitor_gap', self.guard.check())
        self.assertEqual(self.guard.covered_seconds, 10)
        self.clock.advance(10)
        self.active()
        self.guard.check()
        self.assertEqual(self.guard.covered_seconds, 10)
        self.assertFalse(self.guard.summary()['continuous_coverage_pass'])

    def test_suspend_with_paused_monotonic_clock_is_detected(self):
        self.clock.advance(1, 3601)
        self.active()
        self.assertIn('clock_discontinuity', self.guard.check())
        self.assertEqual(self.guard.covered_seconds, 0)

    def test_backward_wall_clock_never_adds_credit(self):
        self.clock.advance(10, -100)
        self.assertIn('clock_discontinuity', self.guard.check())
        self.assertEqual(self.guard.covered_seconds, 0)

    def test_one_dead_writer_fails_even_when_total_counters_keep_growing(self):
        for n in range(10):
            self.clock.advance(10)
            for i in range(12):
                if i != 7:
                    self.guard.write(i)
                self.guard.packet(i, 'cursors')
            failures = self.guard.check()
        self.assertIn('writer_7_stalled', failures)
        self.assertFalse(self.guard.clients_pass())

    def test_one_dead_stream_fails_despite_healthy_writes(self):
        for _ in range(10):
            self.clock.advance(10)
            for i in range(12):
                self.guard.write(i)
                if i != 2:
                    self.guard.packet(i, 'cursors')
            failures = self.guard.check()
        self.assertIn('stream_2_stalled', failures)

    def test_fingerprint_catches_changed_added_and_removed_handlers_not_runtime_data(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'services').mkdir()
            code = root / 'services' / 'handler.py'
            code.write_text('original')
            baseline = source_fingerprints(root)
            (root / 'output').mkdir()
            (root / 'output' / 'runtime.py').write_text('irrelevant')
            self.assertEqual(source_fingerprints(root), baseline)
            code.write_text('changed')
            self.assertNotEqual(source_fingerprints(root), baseline)
            code.unlink()
            self.assertNotEqual(source_fingerprints(root), baseline)
            (root / 'services' / 'new.py').write_text('added')
            self.assertNotEqual(source_fingerprints(root), baseline)

    def test_idle_sleep_request_is_released_on_failure(self):
        import ctypes
        with patch('document_soak_evidence.os.name', 'nt'), patch.object(ctypes, 'windll', create=True) as windll:
            windll.kernel32.SetThreadExecutionState.return_value = 1
            with self.assertRaisesRegex(RuntimeError, 'owned failure'):
                with execution_request() as active:
                    self.assertTrue(active)
                    raise RuntimeError('owned failure')
            self.assertEqual([call.args[0] for call in windll.kernel32.SetThreadExecutionState.call_args_list],
                             [0x80000001, 0x80000000])


if __name__ == '__main__':
    unittest.main()
