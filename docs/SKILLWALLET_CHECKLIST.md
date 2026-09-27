# SkillWallet submission checklist

Status reflects code and documentation in this repository plus the current AWS account activation limitation. A documented design is not the same as a deployed AWS resource.

| SkillWallet section | Status | Evidence / remaining work |
|---|---|---|
| ER Diagram | COMPLETE | [ER_DIAGRAM.md](ER_DIAGRAM.md) depicts account roles, appointments, diagnoses, vitals, intake, follow-ups, timeline events, notifications, and DynamoDB email mapping. |
| Pre-requisites | COMPLETE | [PREREQUISITES.md](PREREQUISITES.md) lists actual local dependencies and cloud prerequisites. |
| Project Flow | COMPLETE | [PROJECT_FLOW.md](PROJECT_FLOW.md) follows implemented browser, Flask, service, and data-store flows. |
| Epic 1: Web Application Development and Setup | PARTIALLY COMPLETE | Patient/doctor portals, care timeline, pre-visit intake, vitals snapshot, follow-ups, notifications, and demo seed workflow are implemented. End-to-end functional verification is not recorded. |
| Epic 2: AWS Account Setup | BLOCKED BY AWS ACCOUNT ACTIVATION | AWS is reported to show the account activation/setup page; account readiness has not been confirmed in this project. |
| Epic 3: DynamoDB Database Creation and Setup | PARTIALLY COMPLETE | boto3 repository and extended access patterns use the existing three GSIs. Table and GSIs are not provisioned or AWS-verified. |
| Epic 4: SNS Notification Setup | PARTIALLY COMPLETE | Optional best-effort SNS publishing remains appointment-only. Topic, subscriptions, IAM permission, and AWS verification are absent. In-app notifications use the data store. |
| Epic 5: IAM Role Setup | BLOCKED BY AWS ACCOUNT ACTIVATION | Least-privilege role design is documented; no role/policy is created or validated. |
| Epic 6: EC2 Instance setup | BLOCKED BY AWS ACCOUNT ACTIVATION | Intended host procedure is documented; no EC2 instance exists in this project. |
| Epic 7: Deployment Using EC2 | BLOCKED BY AWS ACCOUNT ACTIVATION | WSGI entry point and Gunicorn dependency are present, but no EC2 launch, live URL, or deployed application is present. |
| Epic 8: Testing and Deployment | PARTIALLY COMPLETE | Lightweight syntax/source checks are recorded. Local workflows lack recorded end-to-end results, and AWS deployment is untested. |
| Conclusion | PARTIALLY COMPLETE | Application and submission documentation are prepared. AWS resource setup, live deployment, and final end-to-end verification remain. |

## Submission evidence still needed

After AWS account activation: provision DynamoDB/table indexes, create and attach the IAM role, provision/configure SNS if required, deploy to EC2, run controlled functional checks, and capture genuine screenshots/resource details only after they exist.
