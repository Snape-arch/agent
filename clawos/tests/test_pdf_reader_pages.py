from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.pdf_page_renderer import PdfPageRenderer
import fitz

class PdfReaderPageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'paper.pdf'
        with fitz.open() as pdf:
            p=pdf.new_page();p.insert_text((70,80),'Evidence supports a conclusion.')
            p=pdf.new_page();p.insert_text((70,80),'Missing evidence requires refusal.')
            pdf.set_toc([[1,'Evidence',1],[1,'Boundaries',2]]);pdf.save(self.path)
        self.r=PdfPageRenderer()
    def test_real_page_geometry_text_and_toc(self):
        first=self.r.render(self.path,1);second=self.r.render(self.path,2)
        self.assertEqual(first['pages'],2);self.assertNotEqual(first['image'],second['image'])
        self.assertTrue(first['image'].startswith('data:image/png;base64,'))
        self.assertEqual(first['toc'][1]['page'],2)
        self.assertIn('Missing evidence',second['text'][0]['text'])
        self.assertTrue(0<=first['text'][0]['x']<=1)
    def test_bounds_and_changed_source(self):
        for page in (0,3,True):
            with self.assertRaises(ValueError):self.r.render(self.path,page)
        first=self.r.render(self.path,1)
        new=self.path.with_name('new.pdf')
        with fitz.open() as pdf:
            p=pdf.new_page();p.insert_text((70,80),'Changed original source.');pdf.save(new)
        new.replace(self.path)
        self.assertNotEqual(self.r.render(self.path,1)['image'],first['image'])
    def test_rotated_page_keeps_image_without_misaligned_text(self):
        new=self.path.with_name('rotated.pdf')
        with fitz.open(self.path) as pdf:
            pdf[0].set_rotation(90);pdf.save(new)
        result=self.r.render(new,1)
        self.assertTrue(result['image']);self.assertEqual(result['text'],[])
if __name__=='__main__':unittest.main()
