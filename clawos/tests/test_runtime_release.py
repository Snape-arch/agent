import tempfile
import unittest
from pathlib import Path
from services.runtime_release import RuntimeRelease, core_ready


class RuntimeReleaseTests(unittest.TestCase):
    def test_vector_fallback_or_inconsistency_cannot_be_core_ready(self):
        args=({'reachable': True}, True, {'restart_required': False})
        ready={'initialized': True, 'consistent': True, 'fallback_reason': ''}
        self.assertTrue(core_ready(*args,ready))
        for vector in [{},dict(ready,fallback_reason='missing dependency'),dict(ready,consistent=False)]:
            self.assertFalse(core_ready(*args,vector))
        self.assertFalse(core_ready({'reachable': False},True,args[2],ready))
        self.assertFalse(core_ready(args[0],True,{'restart_required': True},ready))

    def test_source_and_asset_changes_require_new_process_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'services').mkdir();(root/'static').mkdir()
            source=root/'services/service.py';source.write_text('answer=1')
            ui=root/'static/view.html';ui.write_text('<p>One</p>')
            old=RuntimeRelease(root);self.assertFalse(old.status()['restart_required'])
            source.write_text('answer=2');ui.write_text('<p>Two</p>')
            status=old.status();self.assertTrue(status['restart_required'])
            self.assertEqual(status['changed_files'],['services/service.py','static/view.html'])
            new=RuntimeRelease(root);self.assertFalse(new.status()['restart_required']);self.assertNotEqual(old.instance,new.instance)
            source.unlink();self.assertIn('services/service.py',new.status()['changed_files'])
            (root/'policy_optimizer.py').write_text('answer=3')
            self.assertIn('policy_optimizer.py',new.status()['changed_files'])

    def test_private_files_weights_and_outputs_are_not_read(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'services').mkdir();(root/'services/real.py').write_text('pass')
            release=RuntimeRelease(root)
            for folder,name in [('tools','weights.py'),('output','result.py'),('.venv','secret.py')]:
                (root/folder).mkdir();(root/folder/name).write_text('excluded')
            (root/'.env').write_text('PRIVATE=not-read')
            self.assertFalse(release.status()['restart_required'])
