"""ASGI + standalone CPU training, with explicitly artificial process fixtures."""
import base64
import json
import sys
import time
from pathlib import Path

from acceptance_support import local_api, local_worker, authenticate, request
from synthesis_acceptance import seed, wait

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from synthetic_renderer import numpy, png

def image_samples(colors):
    return [{'id':f'image-{i}','label':label,'imageBase64':base64.b64encode(png(numpy().broadcast_to(color,(24,24,3)))).decode(),
             'conditions':{'fixture':'artificial-colors'}} for i,(label,color) in enumerate(colors)]

def seed_images(client):
    real=client.create_image_dataset('Process fixture train (not real industrial evidence)',image_samples([
        ('gear',[20,210,140]),('gear',[30,230,150]),('bolt',[190,30,180]),('bolt',[210,40,190])]),purpose='train')
    test=client.create_image_dataset('Process fixture held-out (not industrial evidence)',image_samples([
        ('gear',[25,220,145]),('bolt',[200,35,185])]),purpose='test')
    return real,test

def main():
    with local_api() as (url,root):
        token=authenticate(url,use_environment=False)
        client,plan,_=seed(url,token)
        with local_worker(root):
            rendered=wait(client,client.render_scene(plan['id']))
            synthetic=client.register_synthesis_dataset(rendered['id'])
            real,test=seed_images(client)
            experiment=client.create_training_comparison(real['id'],synthetic['id'],test['id'],config={'epochs':12})
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                done=client.get_training_comparison(experiment['id'])
                if done['status'] in {'completed','failed'}:break
                time.sleep(.1)
            assert done['status']=='completed',done
            result=done['result']
            assert result['trainingSamples']=={'baseline':4,'candidate':7}
            assert result['baseline']['testSetId']==result['candidate']['testSetId']
            assert result['baseline']['provenance']['kind']=='cpu-rgb-softmax/1'
            for run_id in (done['baselineRunId'],done['candidateRunId']):
                run=request(url,'/api/runs/'+run_id,token=token)['data']
                assert run['status']=='completed' and len(run['metrics'])==12 and run['artifacts']
                assert run['metrics'][-1]['trainLoss']<run['metrics'][0]['trainLoss']
            print(json.dumps({'ok':True,'transport':'ASGI','worker':'standalone','provider':result['provider'],'trainingSamples':result['trainingSamples'],
                'testSamples':result['baseline']['summary']['total'],'accuracyDelta':result['accuracyDelta'],'fixtureOnly':True}))

if __name__=='__main__':main()
