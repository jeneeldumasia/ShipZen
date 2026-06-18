import redis
import time
import logging
from config import config
from queue_client import QueueClient
from state_machine import StateMachine, DeploymentState
from metrics import (
    start_metrics_server, 
    shipzen_retry_total, 
    shipzen_queue_latency_seconds,
    shipzen_deployment_failure_total
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('worker')

# Fix #7 (worker): builder queue name sourced from config/env rather than
# hardcoded, so it stays in sync with the builder's own BUILDER_QUEUE env var.
BUILDER_QUEUE = config.BUILDER_QUEUE_NAME


def handoff_to_builder(queue: QueueClient, deployment_id: str, data: dict):
    """Enqueues a build task to the separate builder_queue."""
    build_data = {
        "deployment_id": deployment_id,
        "repo_url": data.get("repo_url", ""),
        "branch": data.get("branch", "main"),
        "image_name": data.get("image_name", "")
    }
    queue.r.xadd(BUILDER_QUEUE, build_data)
    logger.info(f"Deployment {deployment_id} handed off to {BUILDER_QUEUE}")


def process_message(queue: QueueClient, state_machine: StateMachine, message_id: str, data: dict):
    deployment_id = data.get("deployment_id")
    if not deployment_id:
        logger.error(f"Message {message_id} missing deployment_id. Moving to DLQ.")
        queue.add_to_dlq(message_id, data)
        return

    queued_at = data.get("queued_at")
    if queued_at:
        try:
            latency = time.time() - float(queued_at)
            shipzen_queue_latency_seconds.observe(latency)
        except (ValueError, TypeError):
            pass

    retries = int(data.get("retries", "0"))

    # Fix #10: expanded idempotency guard to include BUILDING and DEPLOYING.
    # Previously only RUNNING and VERIFYING were checked, meaning a deployment
    # already in BUILDING would get a second build job dispatched.
    deployment = state_machine.get_deployment(deployment_id)
    if deployment and deployment.get("state") in [
        DeploymentState.BUILDING,
        DeploymentState.DEPLOYING,
        DeploymentState.VERIFYING,
        DeploymentState.RUNNING,
    ]:
        logger.info(f"Deployment {deployment_id} already in-progress (state={deployment['state']}). Acking.")
        queue.ack_message(message_id)
        return

    logger.info(f"Processing deployment {deployment_id}, attempt {retries + 1}")

    try:
        state_machine.update_state(deployment_id, DeploymentState.BUILDING)

        # Fix #2.7: xadd to builder queue BEFORE acking the worker message.
        # If xadd raises, we don't ack — the message stays pending and will be
        # re-claimed by recover_pending_messages() on the next cycle.
        handoff_to_builder(queue, deployment_id, data)
        queue.ack_message(message_id)
        logger.info(f"Deployment {deployment_id} successfully queued for building")

    except Exception as e:
        logger.error(f"Error processing {deployment_id}: {e}")
        retries += 1
        shipzen_retry_total.inc()

        if retries > config.MAX_RETRIES:
            logger.error(f"Max retries exceeded for {deployment_id}. Moving to DLQ.")
            state_machine.update_state(deployment_id, DeploymentState.DLQ, error_msg=str(e))
            queue.add_to_dlq(message_id, data)
            shipzen_deployment_failure_total.inc()
        else:
            state_machine.update_state(deployment_id, DeploymentState.RETRY, error_msg=str(e))
            backoff = 2 ** retries
            logger.info(f"Backing off {backoff}s before retry.")
            time.sleep(backoff)

            # Fix #9: reset queued_at on re-queue so the latency metric
            # measures only the time this specific attempt spent waiting,
            # not the accumulated time across all prior attempts.
            data["retries"] = str(retries)
            data["queued_at"] = str(time.time())
            queue.r.xadd(queue.stream, data)
            queue.ack_message(message_id)


def main():
    start_metrics_server(port=8000)
    queue = QueueClient()
    state_machine = StateMachine()

    logger.info(f"Worker {config.CONSUMER_NAME} started. Listening on stream {config.STREAM_NAME}")

    # Ensure builder_queue and builder_group exist so KEDA can scale the builder
    try:
        queue.r.xgroup_create(BUILDER_QUEUE, "builder_group", id='0', mkstream=True)
        logger.info(f"Initialized consumer group 'builder_group' for stream '{BUILDER_QUEUE}'")
    except redis.exceptions.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            logger.warning(f"Failed to initialize builder_group: {e}")

    while True:
        try:
            queue.recover_pending_messages()
            messages = queue.get_messages(count=5, block_ms=2000)
            if messages:
                for stream_name, msg_list in messages:
                    for msg_id, data in msg_list:
                        process_message(queue, state_machine, msg_id, data)
        except Exception as e:
            logger.error(f"Queue read error: {e}")
            time.sleep(2)


if __name__ == "__main__":
    main()
