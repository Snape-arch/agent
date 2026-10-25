import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from scripts import tool_runner


class TodoScanScopeTests(unittest.TestCase):
    def scan(self, root, **options):
        output = io.StringIO()
        with patch.object(tool_runner, 'input_data', dict(path=str(root), **options)), contextlib.redirect_stdout(output):
            tool_runner.tool_find_todos()
        return json.loads(output.getvalue())

    def test_default_scope_excludes_generated_trees_case_insensitively(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root/'main.py').write_text('# TODO: source\n', encoding='utf-8')
            for name in ('Output', 'BACKUPS', 'tools', 'node_modules'):
                (root/name).mkdir()
                (root/name/'generated.py').write_text('# TODO: generated\n', encoding='utf-8')
            value = self.scan(root)
            self.assertEqual(1, value['files_scanned'])
            self.assertEqual(1, value['count'])
            self.assertEqual('main.py', Path(value['todos'][0]['file']).name)
            explicit = self.scan(root, exclude_dirs=[])
            self.assertEqual(5, explicit['files_scanned'])
            self.assertEqual(5, explicit['count'])

    def test_directory_links_do_not_expand_source_scope(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td);root=base/'workspace';root.mkdir();outside=base/'outside';outside.mkdir()
            (outside/'external.py').write_text('# TODO: external\n', encoding='utf-8')
            link=root/'alias'
            if os.name=='nt':
                result=subprocess.run(['cmd','/d','/c','mklink','/J',str(link),str(outside)],capture_output=True)
                self.assertEqual(0,result.returncode,result.stderr)
            else:
                link.symlink_to(outside,target_is_directory=True)
            self.assertEqual(0,self.scan(root)['files_scanned'])


if __name__=='__main__': unittest.main()
