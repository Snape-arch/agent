from pathlib import Path
import tempfile
import unittest
from xml.sax.saxutils import escape

from services.pdf_math_renderer import PdfMathRenderer


class PdfMathRendererTests(unittest.TestCase):
    def test_supported_formulas_render_real_images_and_keep_currency_and_code(self):
        source = r"LoRA $W'=W+BA$, $A\in R^{d\times r}$, $\frac{x_1}{\sqrt{y^2}}$; $5.00$; cost $5 versus $10; `$a$`."
        renderer = PdfMathRenderer()
        try:
            value = renderer.inline(source, escape)
            self.assertEqual(3, renderer.rendered)
            self.assertEqual(0, renderer.unsupported)
            self.assertEqual(3, value.count('<img '))
            self.assertIn('$5.00$', value)
            self.assertIn('cost $5 versus $10', value)
            self.assertIn('`$a$`', value)
            self.assertIn(r'$\frac{x_1}{\sqrt{y^2}}$', source)
        finally: renderer.close()

    def test_unknown_commands_are_preserved_with_visible_warning(self):
        renderer = PdfMathRenderer()
        try:
            source = r'$\input{private.txt}$'
            value = renderer.inline(source, escape)
            self.assertIn(source, value)
            self.assertIn('公式未渲染', value)
            self.assertEqual(1, renderer.unsupported)
            self.assertNotIn('<img ', value)
        finally: renderer.close()

    def test_multiline_display_math_and_fenced_code_are_distinct(self):
        self.assertTrue(PdfMathRenderer.has_math('$$\n\\frac{x}{y}\n$$'))
        self.assertFalse(PdfMathRenderer.has_math('```\n$a$\n```'))
        lines = PdfMathRenderer.markdown_lines('$$\n\\frac{x}{y}\n$$\n```python\nprice = "$a$"\n```')
        self.assertEqual(r'$$\frac{x}{y}$$', lines[0])
        renderer = PdfMathRenderer()
        try:
            self.assertIn('<img ', renderer.inline(lines[0], escape))
            self.assertNotIn('<img ', renderer.inline(lines[1], escape))
        finally: renderer.close()

    def test_pdf_integrates_images_and_preserves_unsupported_source(self):
        from pypdf import PdfReader
        from workspace_services import WorkspaceServices
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'report.pdf'
            WorkspaceServices._write_learning_analysis_reportlab_pdf(
                object.__new__(WorkspaceServices), path, 'LoRA',
                r'# LoRA'+'\n'+r"- Matrix $W'=W+BA$, $A\in R^{d\times r}$."+'\n'+r'Unknown $\unsupported{x}$')
            reader = PdfReader(path)
            self.assertTrue(any(list(page.images) for page in reader.pages))
            self.assertIn(r'\unsupported{x}', ''.join(page.extract_text() for page in reader.pages))


if __name__ == '__main__': unittest.main()
