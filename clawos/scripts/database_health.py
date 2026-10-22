"""Inspect a database without initializing/migrating it; optionally make a verified backup."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.maintenance_service import MaintenanceService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--backup-dir', help='Create a SQLite backup; uploaded files are not included')
    args = parser.parse_args()
    path = Path(args.database).resolve()
    if not path.is_file():
        parser.error('database does not exist')
    service = MaintenanceService(store=None, db_path=path, base_dir=path.parent, config={})
    result = service.database_health()
    if args.backup_dir:
        result['backup'] = service.backup_database(args.backup_dir, 'verified')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
