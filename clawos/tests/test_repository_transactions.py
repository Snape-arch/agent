"""Cross-domain repository calls must retain one transaction and thread-local session."""
import tempfile
import unittest
from pathlib import Path

from memoryos.memory_store import MemoryStore


class RepositoryTransactionTests(unittest.TestCase):
    def test_direct_domain_writes_roll_back_together(self):
        with tempfile.TemporaryDirectory() as folder:
            store = MemoryStore(str(Path(folder) / 'memory.db'))
            with self.assertRaisesRegex(ValueError, 'workflow rejected'):
                with store.transaction():
                    store.tasks.start_task('scope', 'Pending delivery')
                    store.memory.set_profile('name', 'fixture')
                    store.conversations.add_message('scope', 'user', 'fixture')
                    raise ValueError('workflow rejected')
            self.assertEqual(store.list_tasks(), [])
            self.assertEqual(store.get_all_profiles(), [])
            self.assertEqual(store.get_session_messages('scope'), [])

    def test_nested_domain_failure_preserves_outer_savepoint(self):
        with tempfile.TemporaryDirectory() as folder:
            store = MemoryStore(str(Path(folder) / 'memory.db'))
            with store.transaction():
                store.conversations.add_message('scope', 'user', 'keep')
                with self.assertRaises(ValueError):
                    with store.tasks.transaction():
                        store.tasks.start_task('scope', 'rollback')
                        raise ValueError('inner failure')
                store.memory.set_profile('name', 'keep')
            self.assertEqual(store.list_tasks(), [])
            self.assertEqual(store.get_profile('name')['value'], 'keep')
            self.assertEqual(store.get_session_messages('scope')[0]['content'], 'keep')
