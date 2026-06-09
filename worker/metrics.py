from prometheus_client import Gauge, Counter, Histogram, start_http_server

# Metrics
deployhub_queue_depth = Gauge(
    'deployhub_queue_depth', 
    'Current number of pending deployments in the queue'
)

deployhub_dlq_depth = Gauge(
    'deployhub_dlq_depth', 
    'Current number of messages in the Dead Letter Queue'
)

deployhub_retry_total = Counter(
    'deployhub_retry_total', 
    'Total number of deployment retries'
)

deployhub_queue_latency_seconds = Histogram(
    'deployhub_queue_latency_seconds', 
    'Latency of deployment messages in the queue (from queued to building)',
    buckets=(1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0)
)

def start_metrics_server(port=8000):
    start_http_server(port)

# deployhub_deployment_success_total removed from worker — the controller is the
# authoritative source for this metric (it observes the Running transition).
# Having it in both registries creates duplicate timeseries in Prometheus.
deployhub_deployment_failure_total = Counter(
    'deployhub_deployment_failure_total',
    'Total deployments that ended in Failed or DLQ state'
)
