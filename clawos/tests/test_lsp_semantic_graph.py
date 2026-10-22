from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from services.coding_multilanguage_benchmark import CodingMultilanguageBenchmark
from services.coding_context_service import CodingContextService
from services.coding_diagnostics_service import CodingDiagnosticsService
from services.lsp_bridge_service import LanguageServerManager
from services.lsp_semantic_graph_service import LSPSemanticGraphService, LanguageServerDiscovery


def fixture_repo(root: Path) -> Path:
    repo = root / "repo"; repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    (repo / "maths.py").write_text("def add(a,b):\n    return a+b\n\ndef use():\n    return add(1,2)\n", encoding="utf-8")
    (repo / "test_maths.py").write_text("from maths import add\nassert add(2,3)==5\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=ClawOS Test", "-c", "user.email=test@clawos.local", "commit", "-m", "fixture"],
        cwd=repo, check=True, capture_output=True,
    )
    return repo


def fake_server(root: Path) -> list[str]:
    path = root / "fake_semantic_lsp.py"
    path.write_text(
        "import json,sys\n"
        "docs={}\n"
        "def send(x):\n b=json.dumps(x,separators=(',',':')).encode();sys.stdout.buffer.write(f'Content-Length: {len(b)}\\r\\n\\r\\n'.encode()+b);sys.stdout.buffer.flush()\n"
        "def loc(uri,line): return {'uri':uri,'range':{'start':{'line':line,'character':0},'end':{'line':line,'character':3}}}\n"
        "while True:\n"
        " h={}\n"
        " while True:\n"
        "  line=sys.stdin.buffer.readline()\n"
        "  if not line: raise SystemExit\n"
        "  if line in (b'\\r\\n',b'\\n'): break\n"
        "  k,_,v=line.decode().partition(':');h[k.lower().strip()]=v.strip()\n"
        " m=json.loads(sys.stdin.buffer.read(int(h['content-length'])));method=m.get('method');rid=m.get('id');p=m.get('params') or {}\n"
        " if method=='initialize': send({'jsonrpc':'2.0','id':rid,'result':{'capabilities':{'documentSymbolProvider':True,'definitionProvider':True,'referencesProvider':True,'diagnosticProvider':True,'callHierarchyProvider':True,'workspaceSymbolProvider':True}}})\n"
        " elif method=='textDocument/didOpen': docs[p['textDocument']['uri']]=p['textDocument']['text']\n"
        " elif method=='textDocument/didChange': docs[p['textDocument']['uri']]=p['contentChanges'][0]['text']\n"
        " elif method=='textDocument/documentSymbol':\n"
        "  uri=p['textDocument']['uri'];send({'jsonrpc':'2.0','id':rid,'result':[{'name':'add','kind':12,'range':loc(uri,0)['range'],'selectionRange':loc(uri,0)['range']},{'name':'use','kind':12,'range':loc(uri,3)['range'],'selectionRange':loc(uri,3)['range']}] if uri.endswith('maths.py') else []})\n"
        " elif method=='workspace/symbol': send({'jsonrpc':'2.0','id':rid,'result':[]})\n"
        " elif method=='textDocument/definition':\n"
        "  uri=p['textDocument']['uri'];send({'jsonrpc':'2.0','id':rid,'result':loc(uri,0)})\n"
        " elif method=='textDocument/references':\n"
        "  uri=p['textDocument']['uri'];send({'jsonrpc':'2.0','id':rid,'result':[loc(uri,3)]})\n"
        " elif method=='textDocument/diagnostic':\n"
        "  send({'jsonrpc':'2.0','id':rid,'result':{'items':[{'range':{'start':{'line':3,'character':11},'end':{'line':3,'character':14}},'severity':2,'code':'W1','source':'fixture','message':'review call'}]}})\n"
        " elif method=='textDocument/prepareCallHierarchy':\n"
        "  uri=p['textDocument']['uri'];send({'jsonrpc':'2.0','id':rid,'result':[{'name':'use','kind':12,'uri':uri,'range':loc(uri,3)['range'],'selectionRange':loc(uri,3)['range']}]})\n"
        " elif method=='callHierarchy/incomingCalls': send({'jsonrpc':'2.0','id':rid,'result':[]})\n"
        " elif method=='callHierarchy/outgoingCalls':\n"
        "  item=p['item'];send({'jsonrpc':'2.0','id':rid,'result':[{'to':{'name':'add','kind':12,'uri':item['uri'],'range':loc(item['uri'],0)['range'],'selectionRange':loc(item['uri'],0)['range']},'fromRanges':[]} ]})\n"
        " elif method=='shutdown': send({'jsonrpc':'2.0','id':rid,'result':None})\n"
        " elif method=='exit': raise SystemExit\n",
        encoding="utf-8",
    )
    return [sys.executable, str(path)]


class LSPSemanticGraphTests(unittest.TestCase):
    def test_graph_unifies_symbols_definition_references_calls_and_diagnostics(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); repo = fixture_repo(root); command = fake_server(root)
            manager = LanguageServerManager()
            service = LSPSemanticGraphService(manager=manager, cache_root=root / "cache")
            graph = service.build(repo, language="python", command=command, include_calls=True)
            query = service.query(graph, path="maths.py", symbol="use", depth=2)
            manager.stop_all()
            self.assertEqual(graph["schema"], "clawos.lsp-semantic-graph.v1")
            self.assertGreaterEqual(graph["metrics"]["symbols"], 2)
            self.assertGreaterEqual(graph["metrics"]["definitions"], 1)
            self.assertGreaterEqual(graph["metrics"]["references"], 1)
            self.assertGreaterEqual(graph["metrics"]["calls"], 1)
            self.assertEqual(graph["diagnostics"][0]["related_symbol"]["name"], "use")
            self.assertTrue(query["seed_ids"])
            manifest = CodingContextService().build(repo, "inspect add", semantic_graph={
                "schema": "clawos.lsp-semantic-workspace.v1", "graphs": [graph],
                "metrics": graph["metrics"],
            })
            unified = CodingDiagnosticsService().analyze(
                repo, [], lsp_diagnostics=graph["diagnostics"], semantic_graph=graph,
            )
            self.assertTrue(manifest["semantic_graph"]["available"])
            self.assertTrue(unified["semantic_graph_used"])
            self.assertEqual(unified["diagnostics"][0]["source"], "lsp:fixture")

    def test_graph_is_incremental_and_reindexes_only_changed_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); repo = fixture_repo(root); command = fake_server(root)
            manager = LanguageServerManager(); service = LSPSemanticGraphService(manager=manager, cache_root=root / "cache")
            first = service.build(repo, language="python", command=command, include_calls=False)
            second = service.build(repo, language="python", command=command, include_calls=False)
            (repo / "maths.py").write_text((repo / "maths.py").read_text(encoding="utf-8") + "\n", encoding="utf-8")
            third = service.build(repo, language="python", command=command, include_calls=False)
            manager.stop_all()
        self.assertFalse(first["incremental"])
        self.assertTrue(second["incremental"])
        self.assertEqual(second["changed_files"], [])
        self.assertEqual(third["changed_files"], ["maths.py"])

    def test_discovery_reports_real_python_lsp_without_inventing_other_servers(self):
        result = LanguageServerDiscovery().discover()
        self.assertIn("python", result["languages"])
        self.assertEqual(result["languages"]["python"]["available"], bool(result["languages"]["python"]["command"]))
        self.assertIn("rust", result["languages"])

    def test_real_multilanguage_benchmark_reports_accuracy_and_repair_rate(self):
        report = CodingMultilanguageBenchmark().run()
        self.assertGreaterEqual(report["metrics"]["executed_cases"], 5)
        self.assertGreaterEqual(len(report["metrics"]["languages"]), 3)
        self.assertGreaterEqual(report["metrics"]["classification_accuracy"], 0.8, report)
        self.assertGreaterEqual(report["metrics"]["repair_success_rate"], 0.75, report)


if __name__ == "__main__": unittest.main()
