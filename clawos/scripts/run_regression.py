"""Run the full suite with tool subprocess DB/output isolated from user data."""
import os
from pathlib import Path
import subprocess
import sys
import uuid
import argparse
import hashlib
import json
import time
import unittest
import tempfile


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def shard_for(test, count):
    # Keep module/class fixtures together. Import failures are tests too.
    module = test.__class__.__module__
    if module == 'unittest.loader':
        module = test._testMethodName
    return int.from_bytes(hashlib.sha256(module.encode()).digest()[:8], 'big') % count


def annotation(value):
    return str(value).replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')


class CIResult(unittest.TextTestResult):
    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.annotate(test, err)

    def addError(self, test, err):
        super().addError(test, err)
        self.annotate(test, err)

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self.annotate(subtest, err)

    def annotate(self, test, err):
        if os.environ.get('GITHUB_ACTIONS') == 'true':
            # API annotations remain readable even when raw log downloads need login.
            detail = self._exc_info_to_string(err, test)[-12000:]
            print('::error title=' + annotation(test.id()).replace(',', '%2C').replace(':', '%3A')
                  + '::' + annotation(detail), flush=True)


def run_worker(project, args):
    suite = unittest.defaultTestLoader.discover(str(project/'tests'), pattern=args.pattern)
    tests = list(flatten(suite))
    selected = [test for test in tests if shard_for(test, args.shard_count) == args.shard_index]
    report = dict(discovered_tests=len(tests), selected_tests=len(selected),
                  shard_index=args.shard_index, shard_count=args.shard_count,
                  test_ids=[test.id() for test in selected])
    report_path = Path(os.environ['CLAWOS_REGRESSION_REPORT'])
    report_path.with_name('selection.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'Shard {args.shard_index + 1}/{args.shard_count}: {len(selected)}/{len(tests)} tests', flush=True)
    if not tests or not selected:
        report.update(successful=False, error='No tests selected; refusing a false green check')
        report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
        return 2
    started = time.monotonic()
    result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1, resultclass=CIResult).run(unittest.TestSuite(selected))
    report.update(tests_run=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                  skipped=len(result.skipped), unexpected_successes=len(result.unexpectedSuccesses),
                  successful=result.wasSuccessful(), duration_seconds=time.monotonic()-started)
    report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    return 0 if result.wasSuccessful() else 1


def main():
    project=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser()
    parser.add_argument('--pattern',default='test*.py',help='unittest discovery filename pattern')
    parser.add_argument('--verbose',action='store_true',help='log each test for long-run progress inspection')
    parser.add_argument('--shard-count',type=int,default=1)
    parser.add_argument('--shard-index',type=int,default=0,help='Zero-based module shard index')
    parser.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
        parser.error('require shard-count >= 1 and 0 <= shard-index < shard-count')
    if args.worker:
        return run_worker(project, args)
    root=project/'output'/'regression'/uuid.uuid4().hex
    root.mkdir(parents=True)
    env=dict(os.environ,CLAWOS_SKIP_LOCAL_ENV='1',CLAWOS_MEMORY_DB=str(root/'memoryos.db'),CLAWOS_OUTPUT_DIR=str(root/'artifacts'),PYTHONPATH=str(project)+os.pathsep+os.environ.get('PYTHONPATH',''),
             PYTHONIOENCODING='utf-8',PYTHONUNBUFFERED='1',CLAWOS_REGRESSION_REPORT=str(root/'summary.json'))
    # Hosted Windows may publish TEMP as C:\\Users\\RUNNER~1. Python/Git
    # canonicalize existing paths to the long name; generate fixtures there too.
    temp_root=str(Path(tempfile.gettempdir()).resolve(strict=True))
    env.update(TEMP=temp_root,TMP=temp_root)
    print('Isolated regression workspace: '+str(root),flush=True)
    command=[sys.executable,str(Path(__file__).resolve()),'--worker','--pattern',args.pattern,
             '--shard-count',str(args.shard_count),'--shard-index',str(args.shard_index)]
    if args.verbose:command.append('--verbose')
    with (root/'unittest.log').open('w',encoding='utf-8') as log:
        process=subprocess.Popen(command,cwd=project.parent,env=env,stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace')
        try:
            for line in process.stdout:
                sys.stdout.write(line);sys.stdout.flush();log.write(line);log.flush()
            return process.wait()
        finally:
            process.stdout.close()


if __name__=='__main__':raise SystemExit(main())
