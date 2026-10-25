"""Fail-closed evidence for real-time collaboration load; no simulated runtime."""
from contextlib import contextmanager
import hashlib
import os
import time


class Coverage:
    def __init__(self, workers, interval, monotonic=time.monotonic, wall=time.time):
        self.monotonic, self.wall = monotonic, wall
        self.started = self.previous = monotonic()
        self.wall_started = self.wall_previous = wall()
        self.check_interval = min(10, interval)
        self.max_gap = max(5, self.check_interval * 3)
        self.client_timeout = max(30, interval * 3)
        self.covered_seconds = 0.0
        self.max_observed_gap = 0.0
        self.failed = False
        self.clients = [dict(writes=0, document_events=0, cursor_events=0,
                             reconnects=0, last_write=self.started,
                             last_stream=self.started, version=0) for _ in range(workers)]

    def write(self, worker):
        client = self.clients[worker]
        client['writes'] += 1
        client['last_write'] = self.monotonic()

    def packet(self, worker, name, version=None):
        client = self.clients[worker]
        client['last_stream'] = self.monotonic()
        if name == 'document':
            if type(version) is not int or version <= client['version']:
                raise ValueError('non_monotonic_event')
            client['version'] = version
            client['document_events'] += 1
        elif name == 'cursors':
            client['cursor_events'] += 1

    def check(self):
        now, wall_now = self.monotonic(), self.wall()
        delta, wall_delta = now - self.previous, wall_now - self.wall_previous
        self.previous, self.wall_previous = now, wall_now
        self.max_observed_gap = max(self.max_observed_gap, delta, wall_delta)
        failures = []
        # Comparing both clocks catches suspension on hosts whose monotonic clock
        # pauses, and clock corrections invalidate evidence rather than add credit.
        if min(delta, wall_delta) < 0 or abs(delta - wall_delta) > 2:
            failures.append('clock_discontinuity')
        if max(delta, wall_delta) > self.max_gap:
            failures.append('monitor_gap')
        for i, client in enumerate(self.clients):
            if now - client['last_write'] > self.client_timeout:
                failures.append(f'writer_{i}_stalled')
            if now - client['last_stream'] > self.client_timeout:
                failures.append(f'stream_{i}_stalled')
        if failures:
            self.failed = True
        if not self.failed:
            self.covered_seconds += delta
        return failures

    def summary(self):
        now = self.monotonic()
        return dict(covered_seconds=round(self.covered_seconds, 3),
                    load_elapsed_seconds=round(now - self.started, 3),
                    wall_elapsed_seconds=round(self.wall() - self.wall_started, 3),
                    max_check_gap_seconds=round(self.max_observed_gap, 3),
                    maximum_allowed_gap_seconds=self.max_gap,
                    client_timeout_seconds=self.client_timeout,
                    continuous_coverage_pass=not self.failed,
                    per_client=[{**{k: v for k, v in c.items() if not k.startswith('last_')},
                                 'write_age_seconds': round(now - c['last_write'], 3),
                                 'stream_age_seconds': round(now - c['last_stream'], 3)}
                                for c in self.clients])

    def clients_pass(self):
        return all(c['writes'] and c['document_events'] and c['cursor_events'] for c in self.clients)


def source_fingerprints(root):
    # Include handlers, imports, QA harness and frontend, but never runtime data,
    # weights or local configuration. No Git requirement for exported source trees.
    paths = list(root.glob('*.py'))
    for folder, suffixes in [('services', {'.py'}), ('api', {'.py'}),
                             ('memoryos', {'.py'}), ('scripts', {'.py'}),
                             ('static', {'.js', '.css', '.html'})]:
        paths.extend(p for p in (root / folder).rglob('*') if p.suffix in suffixes and p.is_file())
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(set(paths))}


@contextmanager
def execution_request():
    """Prevent automatic Windows idle sleep only while this process is alive.

    Explicit suspend, shutdown and failure remain possible and must fail coverage.
    There is no persistent power-plan change or attempt to hide an observation gap.
    """
    active = False
    if os.name == 'nt':
        import ctypes
        active = bool(ctypes.windll.kernel32.SetThreadExecutionState(0x80000001))
    try:
        yield active
    finally:
        if active:
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
