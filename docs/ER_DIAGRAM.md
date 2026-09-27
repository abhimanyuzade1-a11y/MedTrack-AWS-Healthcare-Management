# MedTrack entity relationship diagram

Patients and doctors are roles in one `users` table/item type. The ER diagram shows the application records represented by the current SQLite adapter and DynamoDB repository. DynamoDB stores these in one physical table using separate item key patterns.

```mermaid
erDiagram
    USER {
        string id PK "UUID"
        string role "patient or doctor"
        string name
        string email
        string password_hash
        string phone
        string date_of_birth
        string specialty
        string created_at
    }
    APPOINTMENT {
        string id PK "UUID"
        string patient_id FK
        string doctor_id FK
        string appointment_at
        string reason
        string status
        string created_at
    }
    DIAGNOSIS {
        string id PK "UUID"
        string appointment_id FK
        string patient_id FK
        string doctor_id FK
        string diagnosis
        string notes
        string observations
        string followup_date
        string followup_notes
        string created_at
    }
    HEALTH_VITAL {
        string id PK "UUID"
        string patient_id FK
        string recorded_by FK
        string doctor_id
        string appointment_id
        string recorded_at
        string blood_pressure
        string heart_rate
        string temperature
        string weight
        string spo2
    }
    PRE_VISIT_INTAKE {
        string id PK "UUID"
        string patient_id FK
        string appointment_id FK "Unique"
        string main_concern
        string symptoms
        string duration
        string severity
        string allergies
        string medications
        string additional_notes
        string created_at
    }
    FOLLOW_UP {
        string id PK "UUID"
        string patient_id FK
        string doctor_id FK
        string appointment_id
        string followup_date
        string reason
        string notes
        string status
        string created_at
    }
    CARE_TIMELINE_EVENT {
        string id PK "UUID"
        string patient_id FK
        string doctor_id
        string event_type
        string event_time
        string related_id
        string title
        string description
    }
    NOTIFICATION {
        string id PK "UUID"
        string user_id FK
        string event_type
        string title
        string message
        string related_id
        string created_at
        string read_at
    }
    EMAIL_INDEX {
        string PK "EMAIL#normalized-email"
        string SK "UNIQUE"
        string item_type
        string user_id
    }

    USER ||--o{ APPOINTMENT : patient
    USER ||--o{ APPOINTMENT : doctor
    APPOINTMENT ||--o{ DIAGNOSIS : records
    USER ||--o{ DIAGNOSIS : patient
    USER ||--o{ DIAGNOSIS : doctor
    USER ||--o{ HEALTH_VITAL : owns
    APPOINTMENT o|--o{ HEALTH_VITAL : associated_visit
    USER ||--o{ HEALTH_VITAL : records
    USER ||--o{ PRE_VISIT_INTAKE : submits
    APPOINTMENT ||--o| PRE_VISIT_INTAKE : has_intake
    USER ||--o{ FOLLOW_UP : patient
    USER ||--o{ FOLLOW_UP : doctor
    APPOINTMENT o|--o{ FOLLOW_UP : related_visit
    USER ||--o{ CARE_TIMELINE_EVENT : has_events
    USER ||--o{ NOTIFICATION : receives
    USER ||--|| EMAIL_INDEX : unique_email_claim
```

## Relationship notes

- Patient and doctor accounts share `users`; the `role` attribute determines application permissions.
- Each appointment links one patient and one doctor. An appointment can have diagnosis records, at most one pre-visit intake, and optional related vitals/follow-ups.
- Vital readings are strings as entered, with `recorded_by` identifying the patient or doctor who entered them. No interpretation is stored.
- Follow-ups are associated with a patient, doctor, and optionally the originating appointment.
- Timeline events are explicit records created after application actions; old records are not backfilled as fabricated events.
- Notifications are private to the application account. SNS is separate and receives only the current minimal appointment event payload.
- `EMAIL_INDEX` is a DynamoDB uniqueness-claim item, not a separate SQLite table. SQLite enforces unique email on `users.email`.
- SQLite foreign keys constrain appointment, diagnosis, intake, vitals, and notification references where configured. DynamoDB has no relational FK constraint; authorized service/route checks guard doctor/patient access.
- DynamoDB PK/SK and GSI access patterns are detailed in [DYNAMODB_DESIGN.md](DYNAMODB_DESIGN.md). No AWS resources have been provisioned or validated.
