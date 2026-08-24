# ShipZen Task Tracker

### Current
* Finalize AWS production infrastructure deployment via GitHub Actions (`deploy.yaml`).
* Verify that the Kyverno namespace exclusion correctly allows the Prometheus `node-exporter` pod to reach a `Running` state.

### Next
* Verify AWS Network Load Balancer (NLB) provisioning and validate DNS routing to the cluster.
* Configure the GitHub App with the correct Webhook URL pointing to the new ALB endpoint.
* Perform an end-to-end deployment test: connect a repository via the UI and verify the worker builds it, and the controller deploys it successfully to EKS.

### Backlog
* Integrate log streaming directly into the Next.js UI from S3 or Prometheus.
* Implement custom domains support for tenant deployments.

### Blocked
* None at the moment. Waiting on CI/CD pipeline execution results.
