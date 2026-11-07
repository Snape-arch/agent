"""Pages HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from fastapi.responses import FileResponse


class PagesAPI:
    def __init__(self, *,
        static_dir_provider: Callable[[], Any],
    ):
        self.static_dir_provider = static_dir_provider
        self.router = APIRouter()
        self.router.add_api_route('/', self.root, methods=['GET'])
        self.router.add_api_route('/product', self.product_page, methods=['GET'])
        self.router.add_api_route('/academy', self.academy_page, methods=['GET'])
        self.router.add_api_route('/academy/path', self.academy_path_page, methods=['GET'])
        self.router.add_api_route('/academy/paper', self.academy_paper_page, methods=['GET'])
        self.router.add_api_route('/academy/code', self.academy_code_page, methods=['GET'])
        self.router.add_api_route('/academy/rag', self.academy_rag_page, methods=['GET'])
        self.router.add_api_route('/academy/notes', self.academy_notes_page, methods=['GET'])
        self.router.add_api_route('/academy/ingest', self.academy_ingest_page, methods=['GET'])
        self.router.add_api_route('/academy/quiz', self.academy_quiz_page, methods=['GET'])
        self.router.add_api_route('/console', self.console_page, methods=['GET'])
        self.router.add_api_route('/evolution-review', self.evolution_review_page, methods=['GET'])
        self.router.add_api_route('/academy/lab', self.academy_lab_page, methods=['GET'])
        self.router.add_api_route('/academy/research', self.research_watch_page, methods=['GET'])
        self.router.add_api_route('/data-lab', self.data_lab_page, methods=['GET'])
        self.router.add_api_route('/meetings', self.meetings_page, methods=['GET'])
        self.router.add_api_route('/academy/materials', self.academy_materials_page, methods=['GET'])

    async def root(self):
        return FileResponse(self.static_dir_provider() / "index.html")


    async def product_page(self):
        return FileResponse(self.static_dir_provider() / "product.html")


    async def academy_page(self):
        return FileResponse(self.static_dir_provider() / "academy-studio.html")


    async def academy_path_page(self):
        return FileResponse(self.static_dir_provider() / "academy-studio.html")


    async def academy_paper_page(self):
        return FileResponse(self.static_dir_provider() / "academy-paper.html")


    async def academy_code_page(self):
        return FileResponse(self.static_dir_provider() / "academy-code.html")


    async def academy_rag_page(self):
        return FileResponse(self.static_dir_provider() / "academy-rag.html")


    async def academy_notes_page(self):
        return FileResponse(self.static_dir_provider() / "academy-notes.html")


    async def academy_ingest_page(self):
        return FileResponse(self.static_dir_provider() / "academy-ingest.html")


    async def academy_quiz_page(self):
        return FileResponse(self.static_dir_provider() / "academy-quiz.html")


    async def console_page(self):
        return FileResponse(self.static_dir_provider() / "console.html")


    async def evolution_review_page(self): return FileResponse(self.static_dir_provider()/'evolution-review.html')


    async def academy_lab_page(self):
        return FileResponse(self.static_dir_provider() / 'academy-lab.html')


    async def research_watch_page(self):
        return FileResponse(self.static_dir_provider() / 'academy-research.html', headers={'Cache-Control': 'no-store'})


    async def data_lab_page(self): return FileResponse(self.static_dir_provider() / 'workbench.html')


    async def meetings_page(self): return FileResponse(self.static_dir_provider() / 'workbench.html')


    async def academy_materials_page(self):
        return FileResponse(self.static_dir_provider() / "academy-materials.html")
