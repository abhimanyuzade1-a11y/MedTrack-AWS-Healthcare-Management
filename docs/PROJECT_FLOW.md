# MedTrack project flow

This document describes the application flow present in the repository. The local SQLite store is the active default; the boto3 DynamoDB repository is implemented but requires an existing AWS table and has not been connected to AWS.

## Patient journey

1. **Register:** A visitor opens `/patient/register` and submits name, email, password, and optional contact details. Flask applies the CSRF check, then `MedTrackService.register_patient()` validates the fields and hashes the password. The configured data store creates a patient account. Registration starts a signed Flask session and redirects to the patient dashboard.
2. **Sign in:** A patient uses `/patient/login` (the legacy `/login` path remains available). The service looks up the normalized email, checks the stored password hash and the patient role, and returns a safe user record. A successful login starts a session. Patient-only routes use the patient role guard.
3. **Profile:** The patient can update their name, phone, and date of birth at `/patient/profile`. The account email is displayed as read-only.
4. **Book a visit:** The patient opens `/patient/appointments/book`, chooses a doctor returned by the data store, and submits a future date/time and reason. The service validates the fields and checks for an exact-time conflict. The repository performs its own conflict-safe create. New requests have `Pending` status.
5. **Review/cancel visits:** `/patient/appointments` lists the patient's visits and statuses. The patient may cancel a future `Pending` or `Confirmed` appointment. Cancellation is a status change, not a delete.
6. **Prepare for a visit:** `/patient/appointments/<id>/intake` lets the patient submit or update main concern, symptoms, duration, self-described severity, allergies, medications, and notes for their own upcoming appointment. The page explicitly says this information is not a diagnosis. The assigned doctor can review it before consultation.
7. **Health snapshot and timeline:** `/patient/health` displays stored readings and allows a patient to enter values as recorded. `/patient/timeline` shows stored appointment, intake, diagnosis, follow-up, and vital events newest first. Values are informational; MedTrack does not interpret them.
8. **Follow-ups and notifications:** `/patient/followups` shows care-team follow-ups; `/patient/notifications` lists stored, non-SNS in-app coordination updates.
9. **View health history:** `/patient/history` lists diagnosis/consultation records shared with the patient. Recent records also appear on the dashboard.

## Doctor journey

1. **Account provisioning:** There is no doctor self-registration page. A local operator creates a doctor account with `flask --app app create-doctor`; the password is entered interactively and hashed before storage.
2. **Sign in:** A doctor uses `/doctor/login`. The same password-hash check is applied, and the account must have the doctor role. Doctor-only routes are role protected.
3. **Manage appointments:** `/doctor/dashboard` and `/doctor/appointments` show the doctor's schedule. The doctor can review intake, update an open appointment to `Pending`, `Confirmed`, `Completed`, or `Cancelled`, and open the consultation workspace. `Completed` and `Cancelled` appointments are treated as closed by the route.
4. **Review connected patients:** `/doctor/patients` is built only from the logged-in doctor's appointments and supports name and latest appointment status filters. `/doctor/patients/<id>` rechecks the assignment and shows only this doctor's diagnosis/follow-up history, related intake, permitted readings, and related timeline events.
5. **Consultation and follow-up:** The consultation workspace stores doctor-entered diagnosis, notes, observations, optional vital readings, and an optional future follow-up. If the visit was `Pending` or `Confirmed`, the diagnosis and appointment completion are written atomically by SQLite or DynamoDB. Other timeline/notification writes happen after that transaction.
6. **Coordinate care:** `/doctor/followups` lists and updates follow-up status; `/doctor/timeline` shows timeline events limited to patients/appointments connected to the doctor. `/doctor/notifications` shows stored in-app updates.

Logout is a CSRF-protected POST action. Every application POST is subject to the Flask CSRF check.

## Request and data flow

```text
Browser form/page
      │ HTTP request / rendered HTML
      ▼
Flask app and role-protected route
      │ input checks and workflow selection
      ▼
MedTrackService
      │ repository contract (plain records)
      ▼
Configured DataStore
      ├── SQLiteDataStore (default local runtime)
      └── DynamoDBDataStore (boto3; selected by configuration)
```

Templates are rendered with Jinja2. Routes use service operations and the repository's named methods; they do not issue SQL. The local adapter uses SQLite and is initialized by the app factory. `MEDTRACK_DATA_STORE=dynamodb` selects the AWS adapter; `DYNAMODB_TABLE_NAME` must identify a table whose key schema and indexes already match the repository. Constructing that adapter does not make an AWS request, but actual reads/writes require AWS access and credentials from boto3's provider chain.

New stored entities are health vitals, one pre-visit intake per appointment, follow-ups, care timeline events, and in-app notifications. New application actions add events; existing historical appointments are not given fabricated timeline entries. `flask --app app seed-demo` creates explicitly synthetic sample data and stops without changes if one of its demo identities already exists.

## Current versus AWS runtime

- **Current local runtime:** SQLite is selected by default and persists data under `instance/medtrack.sqlite3`. Fresh databases initialize all current tables automatically. Diagnosis columns are added safely when missing. A legacy integer-ID user schema is detected and startup stops without modifying it; use a backup and a new database path.
- **Implemented AWS repository:** The boto3 adapter supports the same repository contract, UUID IDs, indexes, and conditional/transactional writes. It has not been exercised against AWS.
- **Optional SNS integration:** Appointment request creation and status changes can publish minimal notifications when enabled and configured; local SNS is disabled by default. SNS topic/subscriptions, EC2 deployment, and an EC2 IAM role are not provisioned or deployed.
