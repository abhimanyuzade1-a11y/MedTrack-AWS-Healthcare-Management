# MedTrack – AWS Cloud-Enabled Healthcare Management System

MedTrack is a SkillWallet AWS Cloud Practitioner capstone application. It provides patient and doctor workflows for appointments and visit records, with a local Flask runtime and a boto3 DynamoDB repository prepared for a later AWS deployment.

> **Deployment status:** The application has not been deployed to AWS. The project owner reports that the AWS console currently shows the account activation/setup page. No DynamoDB table, SNS topic, IAM role, or EC2 instance has been created for this project.

## Problem statement

Patients and care teams need an organized way to manage appointment requests and the diagnosis information recorded for visits. MedTrack brings those workflows into one role-separated web application and prepares a cloud data layer for the capstone's future AWS phase.

## Project objective

Build a Python/Flask healthcare management application locally, preserve a clean data-store boundary, and prepare a direct boto3 DynamoDB implementation that can later run on EC2 with IAM role credentials. AWS resource provisioning and live deployment remain future work.

## Features

- Separate Patient and Doctor portals on one Flask website, with role-protected routes.
- Patient registration, login, profile, appointment booking/cancellation, pre-visit intake, health timeline, health snapshot, records, follow-ups, and in-app notifications.
- Doctor login, schedule and request management, connected-patient directory, patient detail, care timeline, consultation/diagnosis workspace, follow-up management, and analytics.
- Structured pre-visit intake helps a doctor prepare; it is not a medical diagnosis. Health readings are recorded values and receive no automated medical assessment.
- UUID-based entities for appointments, diagnoses, vitals, pre-visit intakes, follow-ups, timeline events, and notifications.
- Password hashing, signed Flask sessions, role authorization, CSRF checks for POST requests, and server-side validation.
- Optional best-effort SNS events for appointment activity; disabled by default. No diagnosis/history content is sent to SNS.
- Explicit `seed-demo` command creates synthetic sample records only; it does not run automatically.

## Technology stack

- Python 3.10+, Flask, Jinja2, HTML, CSS, JavaScript.
- Bootstrap 5.3 and Bootstrap Icons, loaded from CDNs.
- SQLite (`sqlite3`) for local development.
- boto3 for the implemented DynamoDB repository.

`requirements.txt` contains Flask, boto3, and Gunicorn. Gunicorn is for production WSGI hosting; local startup continues to use `python app.py`.

## Architecture

**Local mode:** Browser → Flask → SQLite; SNS is disabled by default. Routes call `MedTrackService` and the `DataStore` contract. **AWS target mode:** Browser → EC2/Flask → DynamoDB, with optional appointment-event publishing to SNS. Patient and doctor identities are application records, not IAM users.

The intended cloud arrangement is an EC2-hosted Flask WSGI application using an attached IAM role to access DynamoDB. Optional SNS publishing is implemented for appointment events, but no AWS resources have been created.

See [Architecture](docs/ARCHITECTURE.md), [Project Flow](docs/PROJECT_FLOW.md), and the [ER Diagram](docs/ER_DIAGRAM.md).

## Local setup

SQLite is selected by default. Local development does not require AWS credentials, DynamoDB Local, LocalStack, or any AWS resources.

1. Create and activate a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   On Linux/macOS: `python3 -m venv .venv && source .venv/bin/activate`.

2. Install project requirements:

   ```sh
   python -m pip install -r requirements.txt
   ```

3. Optionally set a stable session key (the app otherwise generates a temporary random key):

   ```powershell
   $env:MEDTRACK_SECRET_KEY = (python -c "import secrets; print(secrets.token_urlsafe(48))")
   ```

4. Start the local application and open `http://127.0.0.1:5000/`:

   ```sh
   python app.py
   ```

The SQLite file defaults to `instance/medtrack.sqlite3`. Create a doctor account from the project directory with `flask --app app create-doctor`; the password is prompted interactively.

Seed the optional synthetic demo dataset with `flask --app app seed-demo`. It creates one doctor and three patients with appointment, diagnosis, intake, reading, follow-up, timeline, and notification examples. It does not run at application startup. If a demo account already exists, it makes no changes; use a clean database path to seed a fresh dataset.

**Demo-only credentials** (public sample accounts; never use these for a real or production deployment):

| Role | Email | Password |
|---|---|---|
| Doctor | `demo.doctor@medtrack.test` | `MedTrackDemo-2026!` |
| Patient | `demo.patient@medtrack.test` | `MedTrackDemo-2026!` |

The additional synthetic patients use the same demo-only password. These fixed credentials are intentionally public for a local evaluator walkthrough; never use them for production or real patient data.

The current SQLite schema uses UUIDs. Initialization creates missing tables and safely adds optional consultation columns. A database with the earlier integer-ID schema is detected and left unchanged; use a backup and a new `MEDTRACK_DATABASE_PATH` for this version. There is no automatic destructive migration.

## Environment variables

| Variable | Purpose |
|---|---|
| `MEDTRACK_DATA_STORE` | `sqlite` (default) or `dynamodb`. |
| `MEDTRACK_DATABASE_PATH` | Optional SQLite database file path. |
| `DYNAMODB_TABLE_NAME` | Required for the DynamoDB backend; must already exist. |
| `AWS_REGION` | Optional explicit region; boto3 configuration is used when unset. |
| `SNS_TOPIC_ARN` | Optional SNS topic ARN used only when SNS is enabled. |
| `MEDTRACK_SNS_ENABLED` | Optional SNS switch; defaults to disabled (`0`). SNS is forcibly disabled while SQLite is selected; AWS notifications require `MEDTRACK_DATA_STORE=dynamodb`, this switch, and a topic ARN. |
| `MEDTRACK_SECRET_KEY` | Flask session signing key for stable/shared environments. |
| `MEDTRACK_COOKIE_SECURE` | Set to `1` for HTTPS. |

`MEDTRACK_DATABASE_PATH` configures the SQLite file (default `instance/medtrack.sqlite3`). No AWS access keys are required in application configuration. In a future EC2 deployment, boto3's default credential chain is intended to use the instance's attached IAM role. See [.env.example](.env.example) for safe placeholders; do not put real secrets in that file or commit a `.env` file.

## DynamoDB design

The implemented DynamoDB repository expects a pre-provisioned single table with `PK`/`SK` and three `ALL`-projection indexes: `GSI1` for doctor listing, `GSI2` for patient appointment/diagnosis histories, and `GSI3` for doctor appointment/diagnosis histories. It uses UUID identifiers, a transactional email-uniqueness mapping, conditional slot reservations, and a transaction for diagnosis plus appointment completion.

The repository does not create the table or indexes and has not been validated against a live AWS account. Review [DynamoDB Design](docs/DYNAMODB_DESIGN.md) before provisioning resources. GSI reads are eventually consistent; appointment times currently use the UI's local minute-precision value, so a deployment timezone and slot-duration policy still need a decision.

## IAM design

Patients and doctors authenticate through the Flask application. AWS authorization is separate: the future EC2 application should receive a least-privilege IAM role for the configured DynamoDB table and indexes. If SNS is enabled, the role will also need `sns:Publish` scoped to the configured topic. No IAM user, role, or policy has been created. See [IAM Design](docs/IAM_DESIGN.md).

## SNS design

Optional SNS publishing is implemented as best-effort notifications for appointment request creation and appointment status changes. SNS is disabled by default; no diagnosis/history content is sent. AWS topic setup, subscriptions, IAM permission, and live verification remain future work. See [SNS Design](docs/SNS_DESIGN.md).

## Patient and doctor workflows

The patient dashboard summarizes the next appointment, follow-ups, recent records, and latest recorded readings. Patients can submit pre-visit information for an upcoming appointment, add their own health readings, and view a chronological timeline. The doctor dashboard reports current appointment activity and follow-ups; the doctor directory includes only patients connected through that doctor's appointments. Doctors can review intake before consultation, add diagnosis/observations, record vitals, and create a follow-up from the consultation workspace. These are care-coordination records; MedTrack does not generate medical advice.

In-app notifications are stored using the selected data store. Events include appointment requests and status changes, intake submission, diagnosis record availability, and follow-up updates.

## EC2 deployment

The intended EC2/Gunicorn procedure is documented in [EC2 Deployment](docs/EC2_DEPLOYMENT.md). `wsgi.py` exposes the Flask application as `wsgi:application`. This is not a completed deployment: no instance, security group, role, public URL, or production WSGI process is running. AWS account activation, pre-provisioned DynamoDB resources, role setup, HTTPS front door, and live verification remain necessary.

## Testing and verification

The recorded checks are limited: a Python compile check and source scan passed after the repository refactor. An earlier SQLite empty-query smoke check preceded the UUID schema change, so it does not validate the current schema. No end-to-end browser workflow, AWS repository, SNS, IAM, or EC2 test result is recorded. See [Testing](docs/TESTING.md) for the exact record.

## Current deployment limitation and next step

AWS deployment could not yet be performed because the AWS account is currently showing the activation/setup page (as reported by the project owner). The next cloud step, after activation, is to provision the documented DynamoDB table/indexes and IAM role, then verify the repository before moving to SNS and EC2 deployment. Do not treat this repository's DynamoDB adapter or deployment guide as evidence that AWS resources are live.

## Submission documents

- [SkillWallet Checklist](docs/SKILLWALLET_CHECKLIST.md)
- [Prerequisites](docs/PREREQUISITES.md)
- [Project Flow](docs/PROJECT_FLOW.md)
- [Architecture](docs/ARCHITECTURE.md)
- [ER Diagram](docs/ER_DIAGRAM.md)
- [DynamoDB Design](docs/DYNAMODB_DESIGN.md)
- [SNS Design](docs/SNS_DESIGN.md)
- [IAM Design](docs/IAM_DESIGN.md)
- [EC2 Deployment](docs/EC2_DEPLOYMENT.md)
- [Testing](docs/TESTING.md)
