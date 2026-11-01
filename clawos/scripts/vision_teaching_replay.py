"""Read an exported teaching report and re-execute bounded CPU mechanisms only."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.vision_teaching import digest, implementation_hashes
from services import vision_teaching_engine as engine


def replay(record):
    payload=record['report']
    if payload.get('schema')!='clawos.teaching-experiment.v1' or digest(payload)!=record['hash']:
        raise ValueError('报告摘要或版本无效')
    current=implementation_hashes()
    if current!=payload['source_hashes']:raise ValueError('实现指纹不同，请使用导出时版本；不执行未知代码或路径')
    request=payload['request']
    result=engine.execute(request['template'],request['value'],request['seed'])
    return dict(passed=digest(result)==digest(payload['result']),original_hash=digest(payload['result']),
                replay_hash=digest(result),metrics=[a['metric'] for a in result['arms']],
                boundary='同实现与当前 Python 数学运行时的合成教学实验复跑；非模型、GPU、真实学习效果或跨平台数值一致性验收。')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.report.stat().st_size>2*1024*1024:raise SystemExit('Report exceeds 2MB')
    result=replay(json.loads(args.report.read_text(encoding='utf-8')))
    with args.output.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps(result,ensure_ascii=False));return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
