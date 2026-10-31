import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"backend"))
import database,durable_queue,observability,worker_health
from object_store import LocalObjectStore


class ObservabilityTests(unittest.TestCase):
    def setUp(self): observability.reset_for_tests()

    def test_w3c_trace_context_propagates_into_durable_tasks(self):
        incoming="00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"queue.db"
            with patch.object(database,"DB_PATH",path),patch.object(database,"DATABASE_URL",f"sqlite:///{path}"):
                database.init_database()
                context=observability.adopt_traceparent(incoming)
                task=durable_queue.enqueue("default","training","run-a",{},"trace")
        self.assertEqual(context["traceId"],"0123456789abcdef0123456789abcdef")
        self.assertEqual(context["parentSpanId"],"0123456789abcdef")
        self.assertTrue(task["payload"]["_traceparent"].startswith("00-0123456789abcdef0123456789abcdef-"))

    def test_metrics_cover_database_queue_and_object_store(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{"CLAWVISION_OBJECT_DIR":folder,"CLAWVISION_SLOW_QUERY_SECONDS":"0"}):
            path=Path(folder)/"metrics.db"
            with patch.object(database,"DB_PATH",path),patch.object(database,"DATABASE_URL",f"sqlite:///{path}"):
                database.init_database();durable_queue.enqueue("default","training","run-a",{},"metrics");state=durable_queue.queue_metrics()
            store=LocalObjectStore();store.put_json("probe.json",{"ok":True});self.assertEqual(store.get_json("probe.json"),{"ok":True})
        rendered=observability.render_prometheus()
        self.assertEqual(state["counts"]["queued"],1)
        for metric in ("clawvision_db_connections_opened_total","clawvision_db_slow_queries_total","clawvision_queue_tasks","clawvision_tasks_enqueued_total","clawvision_object_store_operations_total"):
            self.assertIn(metric,rendered)
        self.assertIn('clawvision_queue_tasks{status="dead-letter"} 0',rendered)

    def test_worker_health_marks_stale_heartbeats(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(worker_health,"ROOT",Path(folder)):
            worker_health.write("worker-test",state="idle",completed=2,failed=1)
            current=worker_health.statuses(max_age_seconds=45)[0]
            self.assertTrue(current["healthy"]);self.assertEqual(current["completed"],2)
            value=json.loads((Path(folder)/"worker-test.json").read_text())
            value["updatedAt"]="2000-01-01T00:00:00+00:00";(Path(folder)/"worker-test.json").write_text(json.dumps(value))
            self.assertFalse(worker_health.current_healthy("worker-test",45))

    def test_histogram_and_span_are_prometheus_safe(self):
        with patch.dict(os.environ,{"CLAWVISION_TRACE_LOG":"false"}):
            with observability.span("test.span",traceparent="invalid") as item:
                self.assertEqual(len(item.trace_id),32);observability.observe("test_latency_seconds",.2,route='a"b')
        rendered=observability.render_prometheus()
        self.assertIn("test_latency_seconds_bucket",rendered);self.assertIn('route="a\\"b"',rendered)

    def test_worker_span_inherits_queued_parent_span(self):
        incoming="00-0123456789abcdef0123456789abcdef-fedcba9876543210-01"
        with patch.dict(os.environ,{"CLAWVISION_TRACE_LOG":"false"}):
            with observability.span("worker.task",traceparent=incoming) as item:
                self.assertEqual(item.trace_id,"0123456789abcdef0123456789abcdef");self.assertEqual(item.parent_span_id,"fedcba9876543210")

    def test_histograms_keep_bounded_aggregates_not_samples(self):
        for value in range(100_000):observability.observe("hot_path_seconds",value/1000,route="api")
        self.assertEqual(observability.metric_storage_size()["histograms"],1)
        rendered=observability.render_prometheus()
        self.assertIn('hot_path_seconds_count{route="api"} 100000',rendered)

    def test_worker_health_purges_retired_instances(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(worker_health,"ROOT",Path(folder)):
            worker_health.write("retired",state="idle")
            path=Path(folder)/"retired.json";value=json.loads(path.read_text());value["updatedAt"]="2000-01-01T00:00:00+00:00";path.write_text(json.dumps(value))
            self.assertEqual(worker_health.statuses(purge_after_seconds=300),[]);self.assertFalse(path.exists())


if __name__=="__main__":unittest.main()
