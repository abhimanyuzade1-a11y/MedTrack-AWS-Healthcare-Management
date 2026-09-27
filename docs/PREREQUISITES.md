# MedTrack prerequisites

## Local application

- Python 3.10 or newer.
- `pip` for installing the dependencies in `requirements.txt`.
- Project dependencies: Flask and boto3. boto3 is used by the DynamoDB backend; the default local SQLite mode uses Python's standard-library `sqlite3`.
- A modern browser for the responsive HTML/Jinja interface. Bootstrap and Bootstrap Icons are loaded from CDNs by the current base template, so the browser needs internet access to retrieve those assets for the styled UI.
- No Node.js, React, Docker, DynamoDB Local, LocalStack, or AWS credentials are required for SQLite local development.

## AWS deployment (future)

- An activated AWS account with a selected region.
- A pre-provisioned DynamoDB table and indexes matching [DYNAMODB_DESIGN.md](DYNAMODB_DESIGN.md).
- An EC2 instance and attached least-privilege IAM role for runtime access.
- SNS topic/subscriptions only after notification publishing is implemented.
- Git and access to the GitHub repository are relevant for source checkout and the capstone repository workflow.
- A production WSGI server is required for hosting; Gunicorn is the documented intended choice but is not currently listed in `requirements.txt`.

AWS resources and deployment configuration are not prerequisites for local SQLite use. AWS account activation is currently the stated blocker for the cloud deployment phase.
