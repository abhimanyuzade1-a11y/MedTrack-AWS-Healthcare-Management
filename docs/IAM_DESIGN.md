# MedTrack IAM design

## Application sign-in and AWS authorization are separate

Patients and doctors are MedTrack application accounts stored by the configured repository. Flask checks password hashes, establishes the web session, and protects routes according to the application's `patient`/`doctor` role. These users are **not IAM users**, and IAM must not be used for their application login.

AWS authorization is for the server process. In the intended deployment, EC2 receives an IAM instance role. boto3's default credential provider chain can obtain temporary role credentials from the instance metadata service; no access keys are placed in application code or repository configuration.

## Intended EC2 role permissions

The runtime role should be limited to the resources and API operations the deployed application needs:

- DynamoDB operations present in the repository: `GetItem`, `Query`, `PutItem`, `UpdateItem`, and `TransactWriteItems`.
- Scope table operations to the MedTrack table ARN; scope index queries to that table's `/index/*` ARNs as required by IAM authorization.
- The transaction permission is needed for conditional email registration, appointment-plus-slot writes, terminal appointment updates/reservation removal, and diagnosis-plus-completion writes.
- If SNS publishing is later implemented, add `sns:Publish` only for the specific MedTrack topic ARN. SNS is not currently used by code.

Do not grant broad DynamoDB access, account-wide topic administration, IAM administration, or permission to create tables to the application runtime role. Resource provisioning should use a separate operator/deployment identity and process.

## Status

This is a least-privilege design, not a deployed IAM policy. No role, instance profile, or policy has been created. The AWS account is reported to be at its activation/setup page, so resource creation and permission validation remain blocked. Exact resource ARNs and final policy conditions can only be set after the account and intended region/resources are available.
