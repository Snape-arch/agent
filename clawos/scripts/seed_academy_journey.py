"""Seed labelled synthetic learning evidence in an isolated preview session only."""
import argparse
from datetime import timedelta
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from memoryos.memory_store import MemoryStore
from services.academy_materials import AcademyMaterials
from services.academy_journey import utc_now


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=18904)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]/'output/learning-preview/academy-journey'
    root.mkdir(parents=True,exist_ok=True)
    s=AcademyMaterials(MemoryStore(str(root/'learning.db')),root/'output/academy-materials')
    text='# 证据与回答\n检索系统只在证据充分时回答。没有证据时必须拒答，不能猜测。\n\n# 检查适用范围\n结论必须限定在原文描述的条件内，不能把一个例子推广为所有情况。\n\n# 独立检查\n检查引用与问题是否一致，保留原始资料和自己的推理过程。\n\n本材料为合成验收数据，评阅结果由脚本预置，不代表真实模型评价。'
    state=s.upload('学习旅程合成验收.md',text.encode())
    mid=state['document']['id']
    for i,chapter in enumerate(state['chapters'][:2]):
        quote=chapter['text'].splitlines()[1]
        questions=dict(questions=[dict(dimension=d,question=q,quote=quote,criterion='解释条件与结论之间的关系，并指出资料缺失时不能推测。') for d,q in zip(('concept','reasoning','transfer'),('什么是有依据的回答？','为什么需要明确适用条件？','如果材料缺少费用说明，你会怎样回答费用问题？'))])
        q=s.save_chapter_questions(mid,chapter['id'],'证据推理',questions)
        answers=['只有能从原文找到依据时才回答，无法找到时应说明缺少证据。']*3
        response=s.chapter_response(mid,chapter['id'],answers,dict(question='如何判断费用问题能否回答？',method='搜索原文中的费用说明。',result='没有发现费用说明。',reflection='不能将开放时间推测为费用。',quote=quote),question_event_id=q['id'])
        judge=dict(dimensions={d:dict(score=1 if i==1 and d=='reasoning' else 2,reason='合成评阅：检查条件和结论的连接。',student_quote='无法找到时应说明缺少证据',source_quote=quote,next_step='找出条件句，补全为什么缺少证据不能推出结论。') for d in ('concept','reasoning','transfer')})
        review=s.save_chapter_review(mid,response['id'],[judge,judge])
        with s.store._conn() as c:
            c.execute('UPDATE academy_material_events SET created_at=? WHERE id=?',((utc_now()-timedelta(days=2)).isoformat(),review['id']))
    print(f'http://127.0.0.1:{args.port}/academy/materials?material={mid}&step=journey')


if __name__=='__main__':main()
