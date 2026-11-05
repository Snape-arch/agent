"""Import one verified capture through the existing document and textbook parsers."""
import hashlib
import uuid
from pathlib import Path
from memoryos.document_ingestion import ingest_file

def import_capture(paper,raw,*,store,upload_dir,materials,staging,refresh=None):
    if hashlib.sha256(raw).hexdigest()!=paper['raw_sha256']:raise ValueError('原件摘要不一致')
    root=Path(staging);root.mkdir(parents=True,exist_ok=True)
    folder=root/uuid.uuid4().hex;folder.mkdir()
    source=folder/(paper['version']+'.pdf')
    try:
        source.write_bytes(raw)
        doc=ingest_file(store,Path(upload_dir),source,title=paper['title'],category='research')
        material=materials.upload(paper['version']+'.pdf',raw,title=paper['title'])['document']
        if material['status']!='ready':raise ValueError('教材原文未成功解析；已有论文原件保留')
        if refresh:refresh()
        return dict(document_id=doc['id'],material_id=material['id'],material_revision=material['payload']['revision'],
            reader_url='/academy/paper?document='+str(doc['id'])+'&reader=window&notes=collapsed',
            material_url='/academy/materials?material='+material['id']+'&step=guide',
            teacher_url='/academy/materials?material='+material['id']+'&step=seminar',
            knowledge_chunks=doc.get('chunk_count',0),teacher_verified=False)
    finally:
        source.unlink(missing_ok=True);folder.rmdir()
