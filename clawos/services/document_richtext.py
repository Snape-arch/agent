"""Primitive rich spans with explicit mark and URL allowlists."""
import re


def validate_inline(value):
    if not isinstance(value, list) or len(value) > 4000:
        raise ValueError('富文本片段过多')
    result, length = [], 0
    for span in value:
        if not isinstance(span, dict) or not isinstance(span.get('text'), str):
            raise ValueError('富文本片段无效')
        length += len(span['text'])
        marks = span.get('marks', [])
        if length > 30000 or not isinstance(marks, list) or len(marks) > 7:
            raise ValueError('富文本长度或格式过多')
        clean, seen = [], set()
        for mark in marks:
            if not isinstance(mark, dict) or mark.get('type') not in ('bold', 'italic', 'strike', 'code', 'underline', 'highlight', 'link') or mark['type'] in seen:
                raise ValueError('不支持或重复的文字格式')
            seen.add(mark['type'])
            item = dict(type=mark['type'])
            if mark['type'] == 'link':
                href = mark.get('href')
                if not isinstance(href, str) or len(href) > 2000 or not re.match(r'^(https?://|mailto:)\S+$', href, re.I) or any(ord(c) < 32 for c in href):
                    raise ValueError('链接地址无效')
                item['href'] = href
            clean.append(item)
        result.append(dict(text=span['text'], marks=clean))
    return result


def inline_markdown(spans):
    rows = []
    for span in spans:
        text = span['text']
        marks = {m['type']: m for m in span['marks']}
        if 'code' in marks:
            fence = '`' * max(1, max((len(m.group()) + 1 for m in re.finditer(r'`+', text)), default=1))
            pad = ' ' if text.startswith(('`', ' ')) or text.endswith(('`', ' ')) else ''
            text = fence + pad + text.replace('\n', ' ') + pad + fence
        else:
            text = re.sub(r'([\\*_`~\[\]])', r'\\\1', text)
        for kind, fence in (('bold', '**'), ('italic', '*'), ('strike', '~~')):
            if kind in marks and text:
                content = text.strip()
                if content:
                    left = text[:len(text)-len(text.lstrip())]
                    right = text[len(text.rstrip()):]
                    text = left + fence + content + fence + right
        if 'link' in marks:
            from urllib.parse import quote
            text = '[' + text + '](' + quote(marks['link']['href'], safe=':/?=#&%+@.,;!-_') + ')'
        rows.append(text)
    return ''.join(rows)
