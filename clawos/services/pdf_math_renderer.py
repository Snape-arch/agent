"""Bounded inline Mathtext images; unsupported expressions retain their source."""
import hashlib
from io import BytesIO
from pathlib import Path
import re
import tempfile
from threading import RLock
from xml.sax.saxutils import escape


_MATH_LOCK = RLock()
_CODE_PREFIX = '\ue000clawos-code:'
_SPANS = re.compile(
    r'(?P<code>`+[^`\n]*`+)|(?P<math>(?<![\\$])\$\$[^\n]+?\$\$|'
    r'(?<![\\$])\$(?![\s$])[^\n$]+?(?<!\\)\$|\\\([^\n]+?\\\)|\\\[[^\n]+?\\\])')


class PdfMathRenderer:
    def __init__(self, max_width=420):
        self.max_width = max_width
        self._temp = tempfile.TemporaryDirectory(prefix='clawos-pdf-math-')
        self._cache = {}
        self.rendered = 0
        self.unsupported = 0

    @staticmethod
    def _body(raw):
        return raw[2:-2] if raw.startswith(('$$', r'\(', r'\[')) else raw[1:-1]

    @classmethod
    def has_math(cls, text):
        return any(m.group('math') and cls._is_formula(cls._body(m.group()))
                   for line in cls.markdown_lines(text) if not line.startswith(_CODE_PREFIX)
                   for m in _SPANS.finditer(line))

    @staticmethod
    def _is_formula(body):
        if re.fullmatch(r'[\d.,\s]+', body):
            return False
        # Do not pair two currency amounts such as "$5 versus $10".
        return not (body[:1].isdigit() and not re.search(r'[\\_^=+*/<>-]', body))

    @staticmethod
    def markdown_lines(markdown):
        """Join bounded display formulas; preserve code-fence contents literally."""
        lines = []; block = []; closer = None; fenced = False
        for line in str(markdown).splitlines():
            token = line.strip()
            if token.startswith('```') and closer is None:
                fenced = not fenced
                continue
            if fenced:
                lines.append(_CODE_PREFIX+line)
            elif closer:
                if token == closer:
                    opener = '$$' if closer == '$$' else r'\['
                    lines.append(opener+' '.join(block)+closer)
                    block = []; closer = None
                else:
                    block.append(line)
            elif token in ('$$', r'\['):
                closer = '$$' if token == '$$' else r'\]'
            else:
                lines.append(line)
        if closer:
            lines.extend(['[公式未闭合，请核对原式]', '$$' if closer=='$$' else r'\[', *block])
        return lines

    def inline(self, text, plain):
        if text.startswith(_CODE_PREFIX):
            return escape(text[len(_CODE_PREFIX):])
        parts = []; start = 0
        for match in _SPANS.finditer(text):
            parts.append(plain(text[start:match.start()]))
            raw = match.group()
            if match.group('code') or not self._is_formula(self._body(raw)):
                parts.append(plain(raw))
            else:
                parts.append(self._image(raw, plain))
            start = match.end()
        parts.append(plain(text[start:]))
        return ''.join(parts)

    def _image(self, raw, plain):
        if raw in self._cache:
            return self._cache[raw]
        body = self._body(raw)
        if len(body)>500 or body.count('{')>32 or len(self._cache)>=128:
            self.unsupported += 1
            return plain(raw + ' [公式未渲染，请核对原式]')
        try:
            # Mathtext parses a restricted expression language and never invokes
            # a TeX executable, shell, or document-provided file paths.
            from matplotlib.mathtext import math_to_image
            from matplotlib.font_manager import FontProperties
            from matplotlib import rc_context
            from PIL import Image
            stream = BytesIO()
            with _MATH_LOCK, rc_context({'text.usetex': False, 'mathtext.fontset': 'dejavusans'}):
                math_to_image('$'+body+'$', stream, prop=FontProperties(size=11, family='DejaVu Sans'),
                              dpi=180, format='png', color='#07111f')
            stream.seek(0)
            with Image.open(stream) as png:
                width, height = png.size
            if not width or not height or width*height>2_000_000:
                raise ValueError('formula image exceeds bounds')
            scale = min(72/180, self.max_width/width, 48/height)
            path = Path(self._temp.name)/(hashlib.sha256(body.encode()).hexdigest()+'.png')
            path.write_bytes(stream.getvalue())
            markup = f'<img src="{path.as_posix()}" width="{width*scale:.3f}" height="{height*scale:.3f}" valign="middle"/>'
            self.rendered += 1
        except (ImportError, ValueError, RuntimeError, OverflowError, RecursionError):
            self.unsupported += 1
            markup = plain(raw + ' [公式未渲染，请核对原式]')
        self._cache[raw] = markup
        return markup

    def close(self):
        self._temp.cleanup()
