#!/usr/bin/env python3
# Auto-generated replay script for: Dev Health Check
# Generated: 2026-06-13T14:14:24Z
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_registry import execute_skill

def main():
    params = {}
    if len(sys.argv) > 1:
        params = json.loads(sys.argv[1])
    result = execute_skill('dev_health_check', params)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('ok') else 1

if __name__ == '__main__':
    raise SystemExit(main())
