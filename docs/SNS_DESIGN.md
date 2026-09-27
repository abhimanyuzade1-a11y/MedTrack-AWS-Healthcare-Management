# MedTrack SNS design

## Current implementation status

Optional Amazon SNS publishing is implemented in `services/notification_service.py`. It uses boto3 and is disabled whenever SQLite is selected. It can run only with the DynamoDB backend and when `MEDTRACK_SNS_ENABLED` is truthy and `SNS_TOPIC_ARN` is configured. The SNS client is created lazily only when a notification is sent. No topic, subscription, or AWS resource has been created or verified.

## Planned role

SNS can distribute minimal application notifications after MedTrack commits relevant changes. The service currently publishes for:

- Patient appointment request created (`Pending`).
- Doctor changes an appointment to `Confirmed`, `Completed`, or `Cancelled`; this includes completion caused by successful diagnosis submission.
- Diagnosis submission itself is **not** an SNS event. When it completes an open appointment, only the appointment status-change event is sent. Diagnosis and medical-history content is never sent.

The health timeline, pre-visit intake, vital readings, follow-up details, and in-app notifications are stored in the configured data store. They are not included in SNS messages.

Registration/login and profile edits are not notification events.

## Intended flow

1. The Flask route invokes a service operation.
2. The data-store operation succeeds (for DynamoDB, transactional writes commit where used).
3. When enabled, `MedTrackService` asks the notification service to publish a minimal event containing event name, opaque appointment ID, and (for status changes) the new status.
4. SNS delivers to explicitly configured, consented endpoints or downstream subscribers.

Notification publishing happens after the business write succeeds. SNS errors are logged by exception type only and are swallowed, so appointment creation and status updates remain successful when SNS is unavailable. Delivery is best effort: a database write and SNS publish do not share a transaction, and the application currently has no outbox/retry mechanism.

## Future configuration and permissions

`SNS_TOPIC_ARN` identifies the configured topic; `AWS_REGION` optionally selects the region; `MEDTRACK_SNS_ENABLED` is the opt-in switch and defaults to disabled. The application also requires `MEDTRACK_DATA_STORE=dynamodb`; SQLite mode forces SNS off. boto3's default credential provider chain is used, with no credentials in application configuration. The EC2 application role should receive only `sns:Publish` on the specific topic ARN. Subscription changes and topic administration should be performed separately and should not be granted to normal application runtime.

SNS topic provisioning, subscriptions, message content/privacy review, enhanced delivery-failure handling, IAM permission, and live verification are all future work. The AWS account is currently reported to be blocked on account activation. No SNS resources were created.
