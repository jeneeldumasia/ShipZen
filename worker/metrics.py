from prometheus_client import Gauge, Counter, Histogram, start_http_server

# Metrics
shipzen_messages_in_flight = Gauge(
    'shipzen_messages_in_flight', 
    'Current number of messages in flight (PEL) delivered to workers but unacknowledged'
)

shipzen_dlq_depth = Gauge(
    'shipzen_dlq_depth', 
    'Current number of messages in the Dead Letter Queue'
)

shipzen_retry_total = Counter(
    'shipzen_retry_total', 
    'Total number of deployment retries'
)

shipzen_queue_latency_seconds = Histogram(
    'shipzen_queue_latency_seconds', 
    'Latency of deployment messages in the queue (from queued to building)',
    buckets=(1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0)
)

def start_metrics_server(port=8000):
    start_http_server(port)

# shipzen_deployment_success_total removed from worker — the controller is the
# authoritative source for this metric (it observes the Running transition).
# Having it in both registries creates duplicate timeseries in Prometheus.
shipzen_deployment_failure_total = Counter(
    'shipzen_deployment_failure_total',
    'Total deployments that ended in Failed or DLQ state'
)
