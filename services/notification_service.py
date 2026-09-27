"""Optional, best-effort SNS notifications for non-sensitive appointment events."""

import json

import boto3
from botocore.exceptions import BotoCoreError, ClientError


class SNSNotificationService:
    """Publish minimal events when configured; failures never fail app workflows."""

    def __init__(self, enabled=False, topic_arn="", region=None, logger=None):
        self.enabled = bool(enabled and topic_arn)
        self.topic_arn = topic_arn
        self.region = region
        self.logger = logger
        self._client = None

    def notify(self, event, appointment_id, status=None):
        if not self.enabled:
            return

        message = {"event": event, "appointment_id": str(appointment_id)}
        if status is not None:
            message["status"] = status
        try:
            if self._client is None:
                self._client = boto3.client("sns", region_name=self.region)
            self._client.publish(
                TopicArn=self.topic_arn,
                Subject="MedTrack appointment update",
                Message=json.dumps(message),
            )
        except (BotoCoreError, ClientError) as exc:
            if self.logger:
                self.logger.warning("SNS notification failed (%s).", type(exc).__name__)
        except Exception as exc:
            # Keep an optional integration from interrupting a successful care workflow.
            if self.logger:
                self.logger.warning("SNS notification failed (%s).", type(exc).__name__)
