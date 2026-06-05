from prometheus_client import Counter, Summary, start_http_server

# Fix: was a Gauge — rate() on a Gauge always returns 0 and the drift alert
# was silently broken. Counter is correct for a monotonically increasing event total.
deployhub_drift_total = Counter(
    'deployhub_drift_total',
    'Total number of detected drift incidents (missing or orphaned resources)'
)

deployhub_reconciliation_duration_seconds = Summary(
    'deployhub_reconciliation_duration_seconds',
    'Time spent in the reconciliation loop'
)

def start_metrics_server(port: int = 9090):
    # Fix: was 8080, which collides with the controller's own app port.
    # Metrics now bind on 9090.
    start_http_server(port)
