import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from memoryos.memory_store import MemoryStore
from security.policy import ToolSecurityPolicy
from workspace_services import WorkspaceServices


class ReportMetadataProjectionTests(unittest.TestCase):
    def test_large_geometry_is_referenced_without_overflow_or_modifying_original(self):
        with tempfile.TemporaryDirectory() as td:
            store=MemoryStore(str(Path(td)/'memory.db'));service=WorkspaceServices(store,ToolSecurityPolicy([td]))
            metadata={'geometry':'x'*(9*1024*1024)};raw=json.dumps(metadata)
            with store._conn() as c:
                mid=c.execute('INSERT INTO research_documents(title,file_path,file_hash,page_count,metadata) VALUES(?,?,?,?,?)',
                              ('Study',str(Path(td)/'source.pdf'),'source-digest',1,raw)).lastrowid
                c.execute('INSERT INTO research_chunks(document_id,page_number,chunk_index,content) VALUES(?,?,?,?)',
                          (mid,1,1,'The study describes evidence checks and their limitations.'))
            result=service.generate_research_learning_analysis(document_id=mid,output_dir=Path(td)/'reports',formats=['json'],depth=1,question_count=6)
            artifact=Path(result['report']['json_path'])
            self.assertLess(artifact.stat().st_size,64*1024)
            exported=json.loads(artifact.read_text(encoding='utf-8'))['document']
            self.assertFalse(exported['metadata']['included'])
            expected=hashlib.sha256(json.dumps(metadata,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
            self.assertEqual(expected,exported['metadata']['source_sha256'])
            self.assertEqual('source-digest',exported['file_hash'])
            with store._conn() as c:self.assertEqual(raw,c.execute('SELECT metadata FROM research_documents WHERE id=?',(mid,)).fetchone()[0])


if __name__=='__main__':unittest.main()
