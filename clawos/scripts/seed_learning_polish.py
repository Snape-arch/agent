"""Synthetic browser acceptance fixture, confined to the named QA preview store."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from memoryos.memory_store import MemoryStore
from services.academy_materials import AcademyMaterials

root = Path(__file__).resolve().parents[1] / 'output/learning-preview/data-learning-polish'
root.mkdir(parents=True, exist_ok=True)
service = AcademyMaterials(MemoryStore(str(root/'learning.db')), root/'output/academy-materials')
text = '# 证据与回答\n检索系统只在证据充分时回答。没有证据时必须拒答，不能猜测。\n\n# 检查适用范围\n结论必须限定在原文描述的条件内，不能把一个例子推广为所有情况。'
state = service.upload('证据阅读验收.md', text.encode())
mid = state['document']['id']; chapter = state['chapters'][0]
questions = dict(questions=[dict(dimension=d,question=q,quote='没有证据时必须拒答，不能猜测。',criterion='解释证据与结论之间的条件关系，并明确缺少证据时的处理方式。') for d,q in zip(('concept','reasoning','transfer'), ('什么是有依据的回答？','为什么没有证据时不能继续推测？','材料没有说明报名费用，你会如何回答费用问题？'))])
event = service.save_chapter_questions(mid, chapter['id'], '证据推理', questions)
answers = ['只有能从原文找到依据时才回答，无法找到时应说明缺少证据。'] * 3
response = service.chapter_response(mid, chapter['id'], answers, dict(question='如何判断费用问题能否回答？',method='搜索原文中的费用说明。',result='没有发现费用说明。',reflection='不能将开放时间推测为费用。',quote='没有证据时必须拒答，不能猜测。'),question_event_id=event['id'])
judge = dict(dimensions={d:dict(score=1 if d=='reasoning' else 2,reason='说明了处理方式，推理还缺少条件与结论的连接。',student_quote='无法找到时应说明缺少证据',source_quote='没有证据时必须拒答，不能猜测。',next_step='找出原文中的条件句，写出为什么缺少证据不能推出费用。') for d in ('concept','reasoning','transfer')})
service.save_chapter_review(mid,response['id'],[judge,judge])
service.event(mid,'tutor',dict(citation=chapter['citation'],question='怎么补全推理？',answer='先明确**条件与结论**。\n\n1. 找到原文条件。\n   - 证据充分时回答。\n   - 缺少证据时拒答。\n2. 用自己的例子检查。\n\n| 情形 | 做法 |\n| --- | --- |\n| 原文没有费用 | 说明缺少依据 |'))
print(f'http://127.0.0.1:18903/academy/materials?material={mid}&step=chapters')
