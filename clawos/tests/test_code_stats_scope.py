import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import tool_runner


class CodeStatsScopeTests(unittest.TestCase):
    def test_source_stats_exclude_backups_binary_weights_and_runtime_outputs(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/'main.py').write_text('value=1\nprint(value)\n')
            (root/'README.md').write_text('Source documentation.\n')
            (root/'pyproject.toml').write_text('name="source"\n')
            (root/'memoryos.db').write_bytes(b'SQLite binary\n'*100)
            for name in ('Backups','tools','output'):
                (root/name).mkdir();(root/name/'generated.py').write_text('do_not_count\n'*20)
            (root/'model.gguf').write_bytes(b'weights\n'*100)
            (root/'diagnostic.log').write_text('Explicit text opt-in.\n')
            for requested,expected_files,expected_lines in [(None,3,4),(['.log'],1,1)]:
                output=io.StringIO()
                payload=dict(path=str(root))
                if requested:payload['file_types']=requested
                with patch.object(tool_runner,'input_data',payload),contextlib.redirect_stdout(output):
                    tool_runner.tool_code_stats()
                result=json.loads(output.getvalue())
                self.assertEqual(expected_files,result['total_files'])
                self.assertEqual(expected_lines,result['total_lines'])


if __name__=='__main__':unittest.main()
