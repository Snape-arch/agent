import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from services.scanned_table_benchmark import evaluate

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run fixed real scanned table/critical condition checks")
    parser.add_argument("--workspace",type=Path,default=ROOT.parent)
    parser.add_argument("--out",type=Path,required=True)
    args = parser.parse_args()
    result = evaluate(args.workspace,args.out)
    (args.out/"table-report.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"metrics":result["metrics"],"acceptance":result["acceptance"]},indent=2))
    raise SystemExit(0 if result["acceptance"]["passed"] else 1)
