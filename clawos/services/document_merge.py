"""Conservative three-way merge of versioned blocks; conflicts never overwrite."""
from copy import deepcopy


class MergeConflict(ValueError):
    pass


def text_change(base, value):
    start = 0
    while start < min(len(base), len(value)) and base[start] == value[start]:
        start += 1
    end, new_end = len(base), len(value)
    while end > start and new_end > start and base[end - 1] == value[new_end - 1]:
        end -= 1
        new_end -= 1
    return start, end, value[start:new_end]


def merge_text(base, local, remote):
    if local == base or local == remote:
        return remote
    if remote == base:
        return local
    a, b = text_change(base, local), text_change(base, remote)
    # A single contiguous edit per branch. Same-position insertions conflict.
    if max(a[0], b[0]) < min(a[1], b[1]) or a[0] == b[0] or (a[0] < b[0] < a[1]) or (b[0] < a[0] < b[1]):
        raise MergeConflict('同一段文字存在重叠编辑')
    result = base
    for start, end, text in sorted((a, b), reverse=True):
        result = result[:start] + text + result[end:]
    return result


def merge_value(base, local, remote, path='内容'):
    if local == base or local == remote:
        return deepcopy(remote)
    if remote == base:
        return deepcopy(local)
    if isinstance(base, str) and isinstance(local, str) and isinstance(remote, str):
        return merge_text(base, local, remote)
    if isinstance(base, dict) and isinstance(local, dict) and isinstance(remote, dict):
        # Rich runs and their text projection must change together.
        rich_result = None
        if 'inline' in local or 'inline' in remote or 'inline' in base:
            changed_local = (local.get('inline'), local.get('text')) != (base.get('inline'), base.get('text'))
            changed_remote = (remote.get('inline'), remote.get('text')) != (base.get('inline'), base.get('text'))
            if changed_local and changed_remote and (local.get('inline'), local.get('text')) != (remote.get('inline'), remote.get('text')):
                rich_result = merge_inline(base,local,remote)
        missing = object()
        result = {}
        for key in base.keys() | local.keys() | remote.keys():
            if rich_result is not None and key in ('inline','text'):
                continue
            b, l, r = base.get(key, missing), local.get(key, missing), remote.get(key, missing)
            if l == b: value = r
            elif r == b or l == r: value = l
            elif missing in (b, l, r): raise MergeConflict(path + '的字段被同时修改')
            else: value = merge_value(b, l, r, path + '.' + key)
            if value is not missing:
                result[key] = deepcopy(value)
        if rich_result is not None:
            from .document_richtext import inline_markdown
            result.update(inline=rich_result,text=inline_markdown(rich_result))
        return result
    if isinstance(base, list) and isinstance(local, list) and isinstance(remote, list) and len(base) == len(local) == len(remote):
        return [merge_value(b, l, r, path) for b, l, r in zip(base, local, remote)]
    raise MergeConflict(path + '存在并发修改')


def merge_inline(base, local, remote):
    import re
    def atoms(block):
        runs=block.get('inline')
        if runs is None:
            text=block.get('text','')
            if re.search(r'[*_`~\[\]\\]',text):
                raise MergeConflict('旧格式块需先保存为结构化富文本，再进行同块合并')
            runs=[dict(text=text,marks=[])]
        return [(char,tuple(sorted((m['type'],m.get('href','')) for m in run['marks']))) for run in runs for char in run['text']]
    try: merged=merge_text(atoms(base),atoms(local),atoms(remote))
    except MergeConflict as exc:raise MergeConflict('同一富文本块存在重叠编辑') from exc
    runs=[]
    for char,marks in merged:
        value=[dict(type=kind,**({'href':href} if kind=='link' else {})) for kind,href in marks]
        if runs and runs[-1]['marks']==value:runs[-1]['text']+=char
        else:runs.append(dict(text=char,marks=value))
    return runs


def merge_document(base, local, remote):
    result = {k: merge_value(base.get(k, ''), local.get(k, ''), remote.get(k, ''), k) for k in ('title', 'context')}
    maps = [{b['id']: b for b in d['blocks']} for d in (base, local, remote)]
    bm, lm, rm = maps
    merged = {}
    for bid in bm.keys() | lm.keys() | rm.keys():
        b, l, r = bm.get(bid), lm.get(bid), rm.get(bid)
        if b is None:
            if l is not None and r is not None and l != r:
                raise MergeConflict('新增块标识冲突')
            merged[bid] = deepcopy(l if l is not None else r)
        elif l is None or r is None:
            remaining = r if l is None else l
            if remaining is not None and remaining != b:
                raise MergeConflict('被删除的内容块仍有他人编辑')
        else:
            merged[bid] = merge_table(b,l,r) if all(x['type']=='table' for x in (b,l,r)) else merge_value(b, l, r, '内容块 ' + bid)
    common = set(bm) & set(lm) & set(rm)
    orders = [[b['id'] for b in d['blocks'] if b['id'] in common] for d in (base, local, remote)]
    if orders[1] != orders[0] and orders[2] != orders[0] and orders[1] != orders[2]:
        raise MergeConflict('内容块被同时重新排序')
    chosen = local if orders[1] != orders[0] else remote
    order = [b['id'] for b in chosen['blocks'] if b['id'] in merged]
    # Insert the other branch's additions after their nearest surviving anchor.
    other = remote if chosen is local else local
    for index, b in enumerate(other['blocks']):
        bid = b['id']
        if bid in order or bid not in merged:
            continue
        previous = next((p['id'] for p in reversed(other['blocks'][:index]) if p['id'] in order), None)
        if previous is None:
            order.insert(0, bid)
        else:
            order.insert(order.index(previous) + 1, bid)
    result['blocks'] = [merged[bid] for bid in order]
    return result


def merge_table(base,local,remote):
    if local==base or local==remote:return deepcopy(remote)
    if remote==base:return deepcopy(local)
    shapes=[(len(x['cells']),len(x['cells'][0])) for x in (base,local,remote)]
    if len(set(shapes))!=1:raise MergeConflict('表格尺寸和内容被同时修改')
    others=[{k:v for k,v in x.items() if k not in ('cells','cell_inline')} for x in (base,local,remote)]
    result=merge_value(*others,'表格')
    cells=[];inline=[]
    for i in range(shapes[0][0]):
        row=[];runs=[]
        for j in range(shapes[0][1]):
            values=[]
            for x in (base,local,remote):
                spans=x.get('cell_inline',[[None]*shapes[0][1] for _ in range(shapes[0][0])])[i][j]
                values.append(dict(text=x['cells'][i][j],inline=spans if spans is not None else [dict(text=x['cells'][i][j],marks=[])]))
            value=merge_value(*values,'表格单元格');row.append(value['text']);runs.append(value['inline'])
        cells.append(row);inline.append(runs)
    result.update(cells=cells,cell_inline=inline)
    return result
