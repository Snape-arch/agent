"""Regression boundaries for integrated source and portable application paths."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

from project_layout import APP_ROOT, REPOSITORY_ROOT, ROUTER_ROOT, VISUALIZATION_ROOT, WEB_ROOT
from services.vision_runtime import VisionRuntime


class ProductLayoutTests(unittest.TestCase):
    def test_internal_worker_is_available_without_starting_it_or_creating_data(self):
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder)/'uncreated'
            runtime=VisionRuntime(data)
            try:
                self.assertEqual(runtime.source,VISUALIZATION_ROOT)
                self.assertTrue(runtime.status()['source_available'])
                self.assertFalse(runtime.status()['running'])
                self.assertFalse(data.exists())
            finally:runtime.close()

    def test_desktop_resolves_same_internal_router_in_source_and_portable_layout(self):
        spec=importlib.util.spec_from_file_location('layout_desktop',REPOSITORY_ROOT/'desktop/clawos_desktop.py')
        desktop=importlib.util.module_from_spec(spec);spec.loader.exec_module(desktop)
        self.assertEqual(desktop.application_paths(REPOSITORY_ROOT),(APP_ROOT,ROUTER_ROOT.parent))
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);app=root/'app/clawos';app.mkdir(parents=True)
            self.assertEqual(desktop.application_paths(root),(app,app/'mtclaw'))

    def test_product_modules_resolve_inside_application(self):
        for path in (ROUTER_ROOT,VISUALIZATION_ROOT,WEB_ROOT):
            self.assertTrue(path.is_relative_to(APP_ROOT))
            self.assertTrue(path.is_dir())
