"""AWS DynamoDB implementation of the MedTrack repository contract.

This adapter never creates tables or indexes. The configured table and GSIs must
be provisioned separately. The boto3 default credential provider chain is used.
"""

from datetime import datetime, timezone
from threading import local
from uuid import uuid4

import boto3
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import BotoCoreError, ClientError

from services.data_store import AppointmentConflictError, DataStoreError, DuplicateEmailError


class DynamoDBDataStore:
    """Single-table DynamoDB repository using explicitly configured access patterns."""

    def __init__(self, table_name: str, region_name: str | None = None):
        self.table_name = table_name
        self.region_name = region_name
        self._thread_state = local()
        self._serializer = TypeSerializer()

    def _table(self):
        # Defer resource/client construction until the first operation. Selecting
        # DynamoDB therefore makes no AWS request and does not require credentials
        # merely to start the Flask process.
        if not hasattr(self._thread_state, "table"):
            session = boto3.Session(region_name=self.region_name)
            self._thread_state.table = session.resource("dynamodb").Table(self.table_name)
        return self._thread_state.table

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")

    @staticmethod
    def _email_key(email):
        return email.strip().lower()

    def _safe_call(self, operation, callback):
        try:
            return callback()
        except DataStoreError:
            raise
        except (ClientError, BotoCoreError) as exc:
            # Never include the SDK exception message: it may contain request or
            # environment details. The Flask handler logs only the exception type.
            raise DataStoreError(f"DynamoDB {operation} failed. Please try again.") from exc

    def _serialize(self, item):
        return {key: self._serializer.serialize(value) for key, value in item.items()}

    def _transact(self, items, conditional_error=None):
        try:
            self._table().meta.client.transact_write_items(TransactItems=items)
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            reasons = exc.response.get("CancellationReasons", [])
            conditional_failure = any(reason.get("Code") == "ConditionalCheckFailed" for reason in reasons)
            if error_code == "TransactionCanceledException" and conditional_failure and conditional_error:
                exception_type, message = conditional_error
                raise exception_type(message) from exc
            raise DataStoreError("DynamoDB transaction failed. Please try again.") from exc
        except BotoCoreError as exc:
            raise DataStoreError("DynamoDB transaction failed. Please try again.") from exc

    @staticmethod
    def _key(pk, sk="META"):
        return {"PK": pk, "SK": sk}

    def _raw_item(self, pk, sk="META"):
        response = self._safe_call("read", lambda: self._table().get_item(
            Key=self._key(pk, sk), ConsistentRead=True))
        return response.get("Item")

    @staticmethod
    def _public(item):
        if not item:
            return None
        return {key: value for key, value in item.items()
                if key not in {"PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK", "GSI3PK", "GSI3SK", "item_type"}}

    def _query_all(self, index_name, partition_key, partition_value, sort_key=None, sort_prefix=None,
                   scan_index_forward=False):
        def query_pages():
            table = self._table()
            items = []
            key_condition = Key(partition_key).eq(partition_value)
            if sort_prefix is not None:
                key_condition = key_condition & Key(sort_key).begins_with(sort_prefix)
            args = {"KeyConditionExpression": key_condition, "ScanIndexForward": scan_index_forward}
            if index_name:
                args["IndexName"] = index_name
            while True:
                response = table.query(**args)
                items.extend(response.get("Items", []))
                last_key = response.get("LastEvaluatedKey")
                if not last_key:
                    return items
                args["ExclusiveStartKey"] = last_key
        return self._safe_call("query", query_pages)

    def user_by_email(self, email):
        normalized = self._email_key(email)
        index = self._raw_item(f"EMAIL#{normalized}", "UNIQUE")
        if not index:
            return None
        user = self._raw_item(f"USER#{index['user_id']}")
        return self._public(user)

    def user(self, user_id):
        return self._public(self._raw_item(f"USER#{user_id}"))

    def create_user(self, role, name, email, password_hash, phone="", date_of_birth="", specialty=""):
        normalized_email = self._email_key(email)
        user_id = str(uuid4())
        created_at = self._now()
        user = {
            "PK": f"USER#{user_id}", "SK": "META", "item_type": "USER", "id": user_id,
            "role": role, "name": name, "email": normalized_email, "password_hash": password_hash,
            "phone": phone, "date_of_birth": date_of_birth, "specialty": specialty,
            "created_at": created_at,
        }
        if role == "doctor":
            user["GSI1PK"] = "ROLE#DOCTOR"
            user["GSI1SK"] = f"{name.casefold()}#{user_id}"
        email_record = {
            "PK": f"EMAIL#{normalized_email}", "SK": "UNIQUE", "item_type": "EMAIL_INDEX",
            "user_id": user_id,
        }
        items = [
            {"Put": {"TableName": self.table_name, "Item": self._serialize(user),
                     "ConditionExpression": "attribute_not_exists(PK)"}},
            {"Put": {"TableName": self.table_name, "Item": self._serialize(email_record),
                     "ConditionExpression": "attribute_not_exists(PK)"}},
        ]
        self._transact(items, (DuplicateEmailError, "An account with that email already exists."))
        return user_id

    def update_patient(self, user_id, name, phone, date_of_birth):
        self._safe_call("update patient", lambda: self._table().update_item(
            Key=self._key(f"USER#{user_id}"),
            UpdateExpression="SET #name=:name, phone=:phone, date_of_birth=:birth",
            ConditionExpression="#role=:patient AND attribute_exists(PK)",
            ExpressionAttributeNames={"#name": "name", "#role": "role"},
            ExpressionAttributeValues={":name": name, ":phone": phone, ":birth": date_of_birth, ":patient": "patient"},
        ))

    def doctors(self):
        items = self._query_all("GSI1", "GSI1PK", "ROLE#DOCTOR", scan_index_forward=True)
        return [{"id": item["id"], "name": item["name"], "specialty": item.get("specialty", "")} for item in items]

    def appointment(self, appointment_id):
        item = self._raw_item(f"APPOINTMENT#{appointment_id}")
        if not item:
            return None
        patient = self.user(item["patient_id"])
        doctor = self.user(item["doctor_id"])
        if not patient or not doctor:
            raise DataStoreError("Appointment participant data is unavailable.")
        result = self._public(item)
        result.update({"patient_name": patient["name"], "patient_email": patient["email"],
                       "patient_phone": patient.get("phone", ""), "doctor_name": doctor["name"],
                       "doctor_specialty": doctor.get("specialty", "")})
        return result

    def _appointments(self, index_name, partition_key, partition_value):
        sort_key = "GSI2SK" if index_name == "GSI2" else "GSI3SK"
        items = self._query_all(index_name, partition_key, partition_value, sort_key, "APPOINTMENT#")
        results = []
        for item in items:
            appointment = self.appointment(item["id"])
            if appointment:
                results.append(appointment)
        return results

    def appointments_for_patient(self, patient_id):
        return self._appointments("GSI2", "GSI2PK", f"PATIENT#{patient_id}")

    def appointments_for_doctor(self, doctor_id):
        return self._appointments("GSI3", "GSI3PK", f"DOCTOR#{doctor_id}")

    def _slot_key(self, role, user_id, appointment_at):
        return self._key(f"SLOT#{role}#{user_id}#{appointment_at}", "RESERVATION")

    def appointment_conflict(self, patient_id, doctor_id, appointment_at):
        patient_slot = self._raw_item(self._slot_key("PATIENT", patient_id, appointment_at)["PK"], "RESERVATION")
        doctor_slot = self._raw_item(self._slot_key("DOCTOR", doctor_id, appointment_at)["PK"], "RESERVATION")
        return patient_slot is not None or doctor_slot is not None

    def create_appointment(self, patient_id, doctor_id, appointment_at, reason):
        appointment_id = str(uuid4())
        created_at = self._now()
        sort_value = f"APPOINTMENT#{appointment_at}#{appointment_id}"
        appointment = {
            "PK": f"APPOINTMENT#{appointment_id}", "SK": "META", "item_type": "APPOINTMENT",
            "id": appointment_id, "patient_id": str(patient_id), "doctor_id": str(doctor_id),
            "appointment_at": appointment_at, "reason": reason, "status": "Pending", "created_at": created_at,
            "GSI2PK": f"PATIENT#{patient_id}", "GSI2SK": sort_value,
            "GSI3PK": f"DOCTOR#{doctor_id}", "GSI3SK": sort_value,
        }
        patient_reservation = {**self._slot_key("PATIENT", patient_id, appointment_at),
                               "item_type": "SLOT_RESERVATION", "appointment_id": appointment_id}
        doctor_reservation = {**self._slot_key("DOCTOR", doctor_id, appointment_at),
                              "item_type": "SLOT_RESERVATION", "appointment_id": appointment_id}
        items = []
        for item in (appointment, patient_reservation, doctor_reservation):
            items.append({"Put": {"TableName": self.table_name, "Item": self._serialize(item),
                                   "ConditionExpression": "attribute_not_exists(PK)"}})
        self._transact(items, (AppointmentConflictError, "That appointment time is no longer available."))
        return appointment_id

    def _status_update(self, appointment_id, status, appointment):
        key = self._key(f"APPOINTMENT#{appointment_id}")
        update = {"Update": {
            "TableName": self.table_name, "Key": self._serialize(key),
            "UpdateExpression": "SET #status=:new_status",
            "ConditionExpression": "attribute_exists(PK) AND #status IN (:pending,:confirmed)",
            "ExpressionAttributeNames": {"#status": "status"},
            "ExpressionAttributeValues": self._serialize({":new_status": status, ":pending": "Pending", ":confirmed": "Confirmed"}),
        }}
        if status not in ("Completed", "Cancelled"):
            return self._safe_call("update appointment status", lambda: self._table().update_item(
                Key=self._key(f"APPOINTMENT#{appointment_id}"),
                UpdateExpression="SET #status=:new_status",
                ConditionExpression="attribute_exists(PK) AND #status IN (:pending,:confirmed)",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={":new_status": status, ":pending": "Pending", ":confirmed": "Confirmed"},
            ))
        patient_reservation = self._slot_key("PATIENT", appointment["patient_id"], appointment["appointment_at"])
        doctor_reservation = self._slot_key("DOCTOR", appointment["doctor_id"], appointment["appointment_at"])
        deletes = []
        for slot_key in (patient_reservation, doctor_reservation):
            deletes.append({"Delete": {"TableName": self.table_name, "Key": self._serialize(slot_key),
                                        "ConditionExpression": "appointment_id=:appointment_id",
                                        "ExpressionAttributeValues": self._serialize({":appointment_id": str(appointment_id)})}})
        self._transact([update, *deletes])

    def update_appointment_status(self, appointment_id, status):
        if status not in {"Pending", "Confirmed", "Completed", "Cancelled"}:
            raise ValueError("Invalid appointment status.")
        appointment = self._raw_item(f"APPOINTMENT#{appointment_id}")
        if not appointment:
            return
        self._status_update(appointment_id, status, appointment)

    def _diagnoses(self, index_name, partition_key, partition_value, sort_key, sort_prefix):
        items = self._query_all(index_name, partition_key, partition_value, sort_key, sort_prefix)
        results = []
        for item in items:
            person_id = item["doctor_id"] if partition_key == "GSI2PK" else item["patient_id"]
            person = self.user(person_id)
            if not person:
                raise DataStoreError("Diagnosis participant data is unavailable.")
            result = self._public(item)
            result["doctor_name" if partition_key == "GSI2PK" else "patient_name"] = person["name"]
            results.append(result)
        return results

    def diagnoses_for_patient(self, patient_id):
        return self._diagnoses("GSI2", "GSI2PK", f"PATIENT#{patient_id}", "GSI2SK", "DIAGNOSIS#")

    def diagnoses_for_doctor(self, doctor_id):
        return self._diagnoses("GSI3", "GSI3PK", f"DOCTOR#{doctor_id}", "GSI3SK", "DIAGNOSIS#")

    def _add_diagnosis(self, appointment_id, patient_id, doctor_id, diagnosis, notes, complete_appointment,
                       observations="", followup_date="", followup_notes=""):
        appointment = self._raw_item(f"APPOINTMENT#{appointment_id}")
        if (not appointment or appointment["patient_id"] != str(patient_id) or
                appointment["doctor_id"] != str(doctor_id)):
            raise DataStoreError("The appointment could not be found for this diagnosis.")
        diagnosis_id = str(uuid4())
        created_at = self._now()
        sort_value = f"DIAGNOSIS#{created_at}#{diagnosis_id}"
        item = {
            "PK": f"DIAGNOSIS#{diagnosis_id}", "SK": "META", "item_type": "DIAGNOSIS",
            "id": diagnosis_id, "appointment_id": str(appointment_id), "patient_id": str(patient_id),
            "doctor_id": str(doctor_id), "appointment_at": appointment["appointment_at"],
            "diagnosis": diagnosis, "notes": notes, "observations": observations,
            "followup_date": followup_date, "followup_notes": followup_notes, "created_at": created_at,
            "GSI2PK": f"PATIENT#{patient_id}", "GSI2SK": sort_value,
            "GSI3PK": f"DOCTOR#{doctor_id}", "GSI3SK": sort_value,
        }
        put = {"Put": {"TableName": self.table_name, "Item": self._serialize(item),
                       "ConditionExpression": "attribute_not_exists(PK)"}}
        if not complete_appointment:
            self._safe_call("create diagnosis", lambda: self._table().put_item(
                Item=item, ConditionExpression="attribute_not_exists(PK)"))
            return diagnosis_id

        update = {"Update": {
            "TableName": self.table_name,
            "Key": self._serialize(self._key(f"APPOINTMENT#{appointment_id}")),
            "UpdateExpression": "SET #status=:completed",
            "ConditionExpression": "attribute_exists(PK) AND #status IN (:pending,:confirmed)",
            "ExpressionAttributeNames": {"#status": "status"},
            "ExpressionAttributeValues": self._serialize({":completed": "Completed", ":pending": "Pending", ":confirmed": "Confirmed"}),
        }}
        patient_slot = self._slot_key("PATIENT", patient_id, appointment["appointment_at"])
        doctor_slot = self._slot_key("DOCTOR", doctor_id, appointment["appointment_at"])
        deletes = [{"Delete": {"TableName": self.table_name, "Key": self._serialize(slot),
                               "ConditionExpression": "appointment_id=:appointment_id",
                               "ExpressionAttributeValues": self._serialize({":appointment_id": str(appointment_id)})}}
                   for slot in (patient_slot, doctor_slot)]
        self._transact([put, update, *deletes])
        return diagnosis_id

    def add_diagnosis(self, appointment_id, patient_id, doctor_id, diagnosis, notes):
        return self._add_diagnosis(appointment_id, patient_id, doctor_id, diagnosis, notes, False)

    def add_diagnosis_and_complete_appointment(self, appointment_id, patient_id, doctor_id,
                                               diagnosis, notes, complete_appointment,
                                               observations="", followup_date="", followup_notes=""):
        return self._add_diagnosis(appointment_id, patient_id, doctor_id, diagnosis, notes,
                                   complete_appointment, observations, followup_date, followup_notes)

    def create_vital(self, patient_id, recorded_by, recorded_at, blood_pressure, heart_rate,
                     temperature, weight, spo2, appointment_id=""):
        vital_id = str(uuid4())
        item = {"PK": f"VITAL#{vital_id}", "SK": "META", "item_type": "VITAL", "id": vital_id,
                "patient_id": str(patient_id), "recorded_by": str(recorded_by),
                "doctor_id": str(recorded_by) if str(recorded_by) != str(patient_id) else "",
                "appointment_id": str(appointment_id), "recorded_at": recorded_at,
                "blood_pressure": blood_pressure, "heart_rate": heart_rate, "temperature": temperature,
                "weight": weight, "spo2": spo2, "GSI2PK": f"PATIENT#{patient_id}",
                "GSI2SK": f"VITAL#{recorded_at}#{vital_id}"}
        if item["doctor_id"]:
            item.update({"GSI3PK": f"DOCTOR#{recorded_by}", "GSI3SK": f"VITAL#{recorded_at}#{vital_id}"})
        self._safe_call("create vital", lambda: self._table().put_item(
            Item=item, ConditionExpression="attribute_not_exists(PK)"))
        return vital_id

    def vitals_for_patient(self, patient_id):
        items = self._query_all("GSI2", "GSI2PK", f"PATIENT#{patient_id}", "GSI2SK", "VITAL#")
        return [self._public(item) for item in items]

    def upsert_intake(self, patient_id, appointment_id, fields):
        existing = self._raw_item(f"APPOINTMENT#{appointment_id}", "INTAKE")
        intake_id = existing.get("id") if existing else str(uuid4())
        item = {"PK": f"APPOINTMENT#{appointment_id}", "SK": "INTAKE", "item_type": "INTAKE",
                "id": intake_id, "patient_id": str(patient_id), "appointment_id": str(appointment_id),
                "created_at": self._now(), **fields}
        self._safe_call("save pre-visit intake", lambda: self._table().put_item(Item=item))
        return intake_id

    def intake_for_appointment(self, appointment_id):
        return self._public(self._raw_item(f"APPOINTMENT#{appointment_id}", "INTAKE"))

    def create_followup(self, patient_id, doctor_id, appointment_id, followup_date, reason, notes, status="Scheduled"):
        followup_id = str(uuid4())
        created_at = self._now()
        item = {"PK": f"FOLLOWUP#{followup_id}", "SK": "META", "item_type": "FOLLOWUP",
                "id": followup_id, "patient_id": str(patient_id), "doctor_id": str(doctor_id),
                "appointment_id": str(appointment_id), "followup_date": followup_date,
                "reason": reason, "notes": notes, "status": status, "created_at": created_at,
                "GSI2PK": f"PATIENT#{patient_id}", "GSI2SK": f"FOLLOWUP#{followup_date}#{followup_id}",
                "GSI3PK": f"DOCTOR#{doctor_id}", "GSI3SK": f"FOLLOWUP#{followup_date}#{followup_id}"}
        self._safe_call("create follow-up", lambda: self._table().put_item(
            Item=item, ConditionExpression="attribute_not_exists(PK)"))
        return followup_id

    def _followups(self, index_name, partition_key, partition_value):
        items = self._query_all(index_name, partition_key, partition_value,
                                "GSI2SK" if index_name == "GSI2" else "GSI3SK", "FOLLOWUP#")
        output = []
        for item in items:
            person_id = item["doctor_id"] if index_name == "GSI2" else item["patient_id"]
            person = self.user(person_id)
            result = self._public(item)
            result["doctor_name" if index_name == "GSI2" else "patient_name"] = (person or {}).get("name", "")
            output.append(result)
        return output

    def followups_for_patient(self, patient_id):
        return self._followups("GSI2", "GSI2PK", f"PATIENT#{patient_id}")

    def followups_for_doctor(self, doctor_id):
        return self._followups("GSI3", "GSI3PK", f"DOCTOR#{doctor_id}")

    def update_followup_status(self, followup_id, status):
        self._safe_call("update follow-up", lambda: self._table().update_item(
            Key=self._key(f"FOLLOWUP#{followup_id}"), UpdateExpression="SET #status=:status",
            ExpressionAttributeNames={"#status": "status"}, ExpressionAttributeValues={":status": status},
            ConditionExpression="attribute_exists(PK)"))

    def add_timeline_event(self, patient_id, event_type, event_time, related_id, title, description, doctor_id=""):
        event_id = str(uuid4())
        item = {"PK": f"EVENT#{event_id}", "SK": "META", "item_type": "TIMELINE_EVENT",
                "id": event_id, "patient_id": str(patient_id), "doctor_id": str(doctor_id),
                "event_type": event_type, "event_time": event_time, "related_id": str(related_id),
                "title": title, "description": description, "GSI2PK": f"PATIENT#{patient_id}",
                "GSI2SK": f"EVENT#{event_time}#{event_id}"}
        self._safe_call("create timeline event", lambda: self._table().put_item(
            Item=item, ConditionExpression="attribute_not_exists(PK)"))
        return event_id

    def timeline_for_patient(self, patient_id):
        items = self._query_all("GSI2", "GSI2PK", f"PATIENT#{patient_id}", "GSI2SK", "EVENT#")
        return [self._public(item) for item in items]

    def create_notification(self, user_id, event_type, title, message, related_id=""):
        notification_id = str(uuid4())
        created_at = self._now()
        item = {"PK": f"USER#{user_id}", "SK": f"NOTIFICATION#{created_at}#{notification_id}",
                "item_type": "NOTIFICATION", "id": notification_id, "user_id": str(user_id),
                "event_type": event_type, "title": title, "message": message,
                "related_id": str(related_id), "created_at": created_at, "read_at": ""}
        self._safe_call("create notification", lambda: self._table().put_item(
            Item=item, ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)"))
        return notification_id

    def notifications_for_user(self, user_id):
        items = self._query_all(None, "PK", f"USER#{user_id}", "SK", "NOTIFICATION#")
        return [self._public(item) for item in items]
