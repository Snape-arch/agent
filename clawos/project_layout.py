"""Canonical source locations; runtime data and external models are not source."""
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = APP_ROOT.parent
WEB_ROOT = APP_ROOT / 'web'
VISUALIZATION_ROOT = APP_ROOT / 'visualization'
ROUTER_ROOT = APP_ROOT / 'mtclaw' / 'router'
PUBLISHED_WEB_ROOT = APP_ROOT / 'static' / 'vision'
