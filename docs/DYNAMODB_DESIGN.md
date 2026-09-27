# DynamoDB repository design

This describes `DynamoDBDataStore` as currently implemented. It uses boto3's real DynamoDB API, does not create tables/indexes, and has not been connected to AWS.

## Configuration and credential handling

- Select the repository with `MEDTRACK_DATA_STORE=dynamodb`.
- Set `DYNAMODB_TABLE_NAME` to the name of a pre-provisioned table.
- Set `AWS_REGION` to select the region explicitly; when omitted, boto3 uses its normal region configuration.
- boto3 uses its default credential provider chain. The application has no credential fields or hard-coded keys. On a future EC2 host, an attached IAM role can provide credentials.
- DynamoDB resource construction is deferred until the first repository operation. The app does not call DynamoDB or require credentials just to start.

## Expected table and index schema

The table uses string keys `PK` and `SK`. The repository expects three global secondary indexes, all projecting `ALL` attributes:

| Index | Partition key | Sort key | Query purpose |
|---|---|---|---|
| Base table | `PK` | `SK` | Direct reads for user, appointment, email mapping, and slot reservation items. |
| `GSI1` | `GSI1PK` | `GSI1SK` | Doctor listing by `GSI1PK=ROLE#DOCTOR`, ordered by case-folded name and UUID. |
| `GSI2` | `GSI2PK` | `GSI2SK` | Patient appointment, diagnosis, vital, follow-up, and timeline histories. |
| `GSI3` | `GSI3PK` | `GSI3SK` | Doctor appointment, diagnosis, vital, and follow-up histories. |

### Item key patterns

| Item | Base key | Relevant attributes/index keys |
|---|---|---|
| User | `PK=USER#<uuid>`, `SK=META` | User profile, role, email, password hash, and timestamps. Doctor items additionally carry GSI1 role/name keys. |
| Email uniqueness mapping | `PK=EMAIL#<normalized-email>`, `SK=UNIQUE` | `item_type=EMAIL_INDEX`, `user_id`. |
| Appointment | `PK=APPOINTMENT#<uuid>`, `SK=META` | Appointment fields; GSI2 keys `PATIENT#<patient_id>` / `APPOINTMENT#<appointment_at>#<uuid>`; GSI3 keys `DOCTOR#<doctor_id>` / the same sort key. |
| Diagnosis | `PK=DIAGNOSIS#<uuid>`, `SK=META` | Diagnosis fields and stored appointment time; GSI2 keys `PATIENT#<patient_id>` / `DIAGNOSIS#<created_at>#<uuid>`; GSI3 keys `DOCTOR#<doctor_id>` / the same sort key. |
| Health vital | `PK=VITAL#<uuid>`, `SK=META` | Patient, recorder, optional appointment, readings, and timestamp; GSI2 keys `PATIENT#<patient_id>` / `VITAL#<recorded_at>#<uuid>`. Doctor-recorded vitals also carry GSI3 keys `DOCTOR#<doctor_id>` / the same sort key. |
| Pre-visit intake | `PK=APPOINTMENT#<appointment_id>`, `SK=INTAKE` | One upserted intake per appointment; direct `GetItem` by appointment key. No new GSI. |
| Follow-up | `PK=FOLLOWUP#<uuid>`, `SK=META` | Patient, doctor, optional appointment, date, reason, notes, and status; GSI2 uses `PATIENT#<patient_id>` / `FOLLOWUP#<followup_date>#<uuid>`; GSI3 uses `DOCTOR#<doctor_id>` / the same sort key. |
| Care timeline event | `PK=EVENT#<uuid>`, `SK=META` | Patient, optional doctor, type/time, related ID, title, and generic description; GSI2 uses `PATIENT#<patient_id>` / `EVENT#<event_time>#<uuid>`. |
| In-app notification | `PK=USER#<user_id>`, `SK=NOTIFICATION#<created_at>#<uuid>` | Private application notification; queried by the user partition and sort-key prefix. The existing user item remains at `SK=META`. |
| Patient slot reservation | `PK=SLOT#PATIENT#<patient_id>#<appointment_at>`, `SK=RESERVATION` | `item_type=SLOT_RESERVATION`, owning `appointment_id`. |
| Doctor slot reservation | `PK=SLOT#DOCTOR#<doctor_id>#<appointment_at>`, `SK=RESERVATION` | `item_type=SLOT_RESERVATION`, owning `appointment_id`. |

## Access patterns and writes

- **User by ID:** `GetItem` on `USER#<uuid>`.
- **User by email:** strongly consistent `GetItem` for the email mapping, then a user `GetItem`.
- **Create user/email uniqueness:** `TransactWriteItems` with conditional puts for both user and email mapping (`attribute_not_exists(PK)`). The mapping's base key, rather than a GSI, serializes claims for a normalized email.
- **List doctors:** `Query` on GSI1.
- **Appointments by patient/doctor:** `Query` on GSI2/GSI3 using appointment sort-key prefixes. The repository hydrates appointment display details with current patient/doctor user reads.
- **Diagnoses by patient/doctor:** `Query` on GSI2/GSI3 using diagnosis sort-key prefixes. Diagnosis items store `appointment_at`; the repository reads the other participant's user item for display names.
- **Vitals by patient:** `Query` GSI2 with `PATIENT#<patient_id>` and `VITAL#` prefix, newest first.
- **Intake by appointment:** direct `GetItem` on `PK=APPOINTMENT#<appointment_id>`, `SK=INTAKE`; saving the form replaces the one intake for that appointment.
- **Follow-ups by patient/doctor:** `Query` GSI2/GSI3 with patient/doctor partition and `FOLLOWUP#` prefix. Status updates use `UpdateItem`.
- **Timeline by patient:** `Query` GSI2 with `PATIENT#<patient_id>` and `EVENT#` prefix, newest first.
- **Notifications by user:** base-table `Query` on `PK=USER#<user_id>` with `NOTIFICATION#` sort-key prefix. Notifications do not include diagnosis text or intake/vitals content.
- **Appointment conflict:** strongly consistent `GetItem` reads of patient and doctor reservation keys. The service performs this pre-check for feedback, but creation does not rely on it for correctness.
- **Create appointment:** `TransactWriteItems` conditionally puts the appointment and both reservation items. If either reservation already exists, the transaction fails, preventing concurrent exact-slot duplication.
- **Update status:** `UpdateItem` conditionally updates an open appointment. For terminal `Completed`/`Cancelled` status, a transaction updates the appointment and conditionally deletes its two reservation items.
- **Diagnosis and completion:** if the appointment is pending or confirmed, `TransactWriteItems` writes the diagnosis, conditionally marks the appointment completed, and releases both reservations. Otherwise diagnosis creation is a conditional `PutItem`.

## Why the repository uses denormalized access paths

DynamoDB does not provide SQL joins. GSI partition/sort attributes put each appointment and diagnosis under the patient and doctor identifiers used by the app's list pages. The diagnosis stores its visit time so that a diagnosis history read does not need to retrieve the appointment for that field. Appointment lists still read current user records to supply participant display information. GSI query results are eventually consistent.

The repository uses the existing `PK`/`SK` and `GSI1`/`GSI2`/`GSI3` key schema; new entities overload current GSIs with typed sort-key prefixes and add no new GSI. Timeline and notification writes are separate from the underlying appointment/diagnosis business transaction. The application does not provision this table or its indexes. Before deployment, validate permissions for `GetItem`, `Query`, `PutItem`, `UpdateItem`, and existing transactional operations. AWS is currently reported blocked on account activation, so these new access patterns have not been tested against AWS and no resources were created.
