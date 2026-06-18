import logging
import redis
from config import config
from metrics import shipzen_messages_in_flight, shipzen_dlq_depth

logger = logging.getLogger(__name__)


class QueueClient:
    def __init__(self):
        self.r = redis.Redis(host=config.REDIS_HOST, port=config.REDIS_PORT, decode_responses=True)
        self.stream = config.STREAM_NAME
        self.group = config.CONSUMER_GROUP
        self.consumer = config.CONSUMER_NAME
        self.dlq_stream = f"{self.stream}_dlq"
        self._ensure_group()

    def _ensure_group(self):
        try:
            self.r.xgroup_create(self.stream, self.group, id='0', mkstream=True)
        except redis.exceptions.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    def get_messages(self, count=1, block_ms=5000):
        messages = self.r.xreadgroup(
            self.group, self.consumer, {self.stream: '>'}, count=count, block=block_ms
        )
        self.update_metrics()
        return messages

    def ack_message(self, message_id):
        self.r.xack(self.stream, self.group, message_id)

    def add_to_dlq(self, message_id, data):
        """Move message to DLQ and ACK it from main stream."""
        self.r.xadd(self.dlq_stream, data)
        self.ack_message(message_id)
        # Fix #24: was print(), now uses logger
        logger.warning(f"Message {message_id} moved to DLQ")

    def recover_pending_messages(self):
        """Pending Message Recovery via XAUTOCLAIM."""
        start_id = '0-0'
        all_claimed = []
        while True:
            result = self.r.xautoclaim(
                self.stream, self.group, self.consumer,
                config.PENDING_MESSAGE_TIMEOUT_MS,
                start_id=start_id, count=100
            )
            next_start = result[0]
            claimed_messages = result[1]
            for msg in claimed_messages:
                # msg is typically [message_id, data]
                message_id = msg[0]
                logger.info(f"Recovered pending message {message_id} via XAUTOCLAIM")
                all_claimed.append(msg)
                
            if next_start == '0-0':
                break
            start_id = next_start
        return all_claimed

    def update_metrics(self):
        try:
            info = self.r.xinfo_groups(self.stream)
            for g in info:
                if g['name'] == self.group:
                    shipzen_messages_in_flight.set(g['pending'])
            dlq_len = self.r.xlen(self.dlq_stream)
            shipzen_dlq_depth.set(dlq_len)
        except Exception:
            pass
