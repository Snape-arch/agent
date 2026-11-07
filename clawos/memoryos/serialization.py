"""Row conversion shared by task and evolution repositories."""
import json


def json_loads(value, default):
    try:
        return json.loads(value or "")
    except Exception:
        return default


def task_row_to_dict(row) -> dict:
    item = dict(row)
    item["metadata"] = json_loads(item.get("metadata"), {})
    item["attempt"] = int(item.get("attempt") or 1)
    item["cancellation_requested"] = bool(item.get("cancellation_requested"))
    return item
