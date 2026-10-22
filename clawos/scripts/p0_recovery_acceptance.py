"""Six synthetic workflow persistence/recovery cases in separate real processes.

This is a model-free service acceptance, not browser interaction or semantic quality.
Only newly created directories under ignored output are moved; live data is untouched.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))


def dump(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def seed(root):
    from memoryos.memory_store import MemoryStore
    from memoryos.document_ingestion import ingest_file
    from services.academy_materials import AcademyMaterials
    from services.academy_documents import AcademyDocuments
    from services.academy_learning_lab import AcademyLearningLab
    from services.artifact_delivery_service import ArtifactDeliveryService
    from services.maintenance_service import MaintenanceService
    from services.recovery_bundle import RecoveryBundle,sha
    live=root/'live';live.mkdir();store=MemoryStore(str(live/'memory.db'))
    source=live/'source.md';source.write_text('# Evidence\nEvidence supports a conclusion under stated conditions.\n',encoding='utf-8')
    doc=ingest_file(store,live/'uploads',source,title='Synthetic evidence fixture')
    knowledge=store.add_knowledge('P0 persistence marker','Evidence supports a conclusion under stated conditions.',source='synthetic:p0')
    note=AcademyDocuments(store).save(dict(title='P0 note',blocks=[dict(id='p',type='paragraph',text='A durable synthetic annotation.')]))
    report=live/'report.md';report.write_text('Synthetic report\nSource: '+str(doc['id'])+'\nEvidence supports a conclusion under stated conditions.',encoding='utf-8')
    delivery=ArtifactDeliveryService(live/'output/artifact_delivery/index.json',[live]);artifact=delivery.register(report)
    checkpoint=live/'checkpoint.json';checkpoint.write_text('{"completed_units":2,"total_units":5}',encoding='utf-8')
    task=store.start_task('p0','Synthetic project checkpoint',metadata={'checkpoint_path':str(checkpoint),'latest_checkpoint':{'uri':str(checkpoint),'digest':sha(checkpoint)}})
    materials=AcademyMaterials(store,live/'output/academy-materials');material=materials.upload('textbook.md',source.read_bytes())['document']
    lab=AcademyLearningLab(materials);graph=lab.graph.state(material['id'],'local-user');passage=material['payload']['passages'][0]
    lab.graph.save(material['id'],'local-user',dict(nodes=[dict(id='evidence',title='Evidence',chapter='ch0001',explanation='Synthetic source-bound concept.',source={'citation':passage['id'],'quote':'Evidence supports a conclusion under stated conditions.'})],edges=[],covered_chapters=['ch0001']),0,graph['revision'])
    ops=MaintenanceService(store=store,db_path=live/'memory.db',base_dir=live,config={});bundle=RecoveryBundle(ops).backup('p0-six-workflows')
    assert bundle['status']=='complete'
    dump(root/'state.json',dict(document=doc['id'],note=note['id'],artifact=artifact['id'],task=task['id'],material=material['id'],bundle=bundle['path'],live_db_sha=sha(live/'memory.db')))


def restore(root):
    from memoryos.memory_store import MemoryStore
    from memoryos.services.vector_store import MemoryVectorStore
    from services.maintenance_service import MaintenanceService
    from services.recovery_bundle import RecoveryBundle,sha
    from services.academy_documents import AcademyDocuments
    from services.academy_materials import AcademyMaterials
    from services.academy_learning_lab import AcademyLearningLab
    from services.artifact_delivery_service import ArtifactDeliveryService
    state=json.loads((root/'state.json').read_text(encoding='utf-8'))
    home=root/'recovery-home';home.mkdir();store=MemoryStore(str(home/'empty.db'))
    ops=MaintenanceService(store=store,db_path=home/'empty.db',base_dir=home,config={})
    result=RecoveryBundle(ops).restore_isolated(root/'archive')
    restored=MemoryStore(result['database']);target=Path(result['target'])
    note=AcademyDocuments(restored).get(state['note'])
    _,artifact=ArtifactDeliveryService(result['delivery_registry'],[target]).resolve(state['artifact'])
    metadata=restored.get_task(state['task'])['task']['metadata']
    with restored._conn() as c:doc=dict(c.execute('SELECT * FROM documents WHERE id=?',(state['document'],)).fetchone())
    materials=AcademyMaterials(restored,result['material_root']);book=materials.document(state['material'])
    vector=MemoryVectorStore(result['database'],provider='lightweight',embedding_provider='hash')
    try:retrieved=bool(vector.search('Evidence supports a conclusion',min_score=0))
    finally:vector.close()
    checks=dict(knowledge_capture=bool(restored.search_knowledge('P0 persistence marker')),
                document_analysis_notes=note['blocks'][0]['text']=='A durable synthetic annotation.',
                report_delivery=artifact.read_text(encoding='utf-8').startswith('Synthetic report'),
                project_checkpoint=Path(metadata['checkpoint_path']).is_file() and sha(metadata['checkpoint_path'])==metadata['latest_checkpoint']['digest'],
                search_source_chain=retrieved and Path(doc['file_path']).is_file(),
                education=sha(Path(result['material_root'])/book['id']/book['filename'])==book['digest'] and len(AcademyLearningLab(materials).graph.state(book['id'],'local-user')['nodes'])==1,
                originals_unavailable=not (root/'live').exists(),
                original_db_unchanged=sha(root/'originals-unavailable/memory.db')==state['live_db_sha'])
    dump(root/'report.json',dict(schema='clawos.p0-workflows.v1',passed=all(checks.values()),checks=checks,recovery=result,
        model_calls=0,synthetic_inputs=True,fresh_seed_and_restore_processes=True,browser_verified=False,
        semantic_quality_verified=False,arbitrary_execution_resume_verified=False))
    assert all(checks.values()),checks


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--phase',choices=['seed','restore']);p.add_argument('--workspace');args=p.parse_args()
    allowed=(PROJECT/'output').resolve()
    if args.phase:
        root=Path(args.workspace).resolve()
        if allowed not in root.parents:raise ValueError('Only an owned ignored-output workspace is allowed')
        (seed if args.phase=='seed' else restore)(root);return 0
    root=allowed/'p0-workflows'/uuid.uuid4().hex;root.mkdir(parents=True)
    for phase in ('seed','restore'):
        subprocess.run([sys.executable,str(Path(__file__).resolve()),'--phase',phase,'--workspace',str(root)],check=True,timeout=180)
        if phase=='seed':
            state=json.loads((root/'state.json').read_text(encoding='utf-8'));bundle=Path(state['bundle']).resolve()
            if (root/'live').resolve() not in bundle.parents:raise ValueError('Unexpected snapshot directory')
            bundle.rename(root/'archive')
            (root/'live').rename(root/'originals-unavailable')
    result=json.loads((root/'report.json').read_text(encoding='utf-8'))
    print(json.dumps(dict(passed=result['passed'],checks=result['checks'],report=str(root/'report.json')),ensure_ascii=True))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
