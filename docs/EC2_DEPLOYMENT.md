# Intended EC2 deployment procedure

**Status: not deployed.** The AWS account is currently reported to show the account activation/setup page. The steps below describe a future procedure; no EC2 instance, IAM role, DynamoDB table, SNS topic, or deployment URL currently exists.

## 1. Activate and prepare AWS

After account activation, select the deployment region and provision the DynamoDB table/indexes documented in [DYNAMODB_DESIGN.md](DYNAMODB_DESIGN.md). Create and review a least-privilege EC2 application role as described in [IAM_DESIGN.md](IAM_DESIGN.md). SNS topic provisioning is optional; configure it only if notifications are wanted.

## 2. Create the EC2 host

Choose a supported Linux AMI and an instance size appropriate for the capstone demo. Attach the application IAM role at launch. Do not place AWS access keys on the instance. Use a key pair or another approved administrative access method and restrict SSH ingress to the operator's source address.

Configure the security group for the eventual HTTPS/HTTP front door (ports 443 and, if redirecting to HTTPS, 80). Do not expose Flask's development server or an arbitrary Gunicorn development port directly to the public internet. A reverse proxy or managed HTTPS front end should forward to a loopback-bound WSGI server.

## 3. Install the application

On the instance, install the distribution's supported Python 3 and pip packages, clone the approved GitHub repository, create a virtual environment, and install `requirements.txt`.

The requirements include Flask, boto3, and Gunicorn. `wsgi.py` exposes the Flask application as `application`. Do not use `python app.py` or Flask's development server as the production process.

An intended process command is:

```sh
gunicorn --workers 2 --bind 127.0.0.1:8000 wsgi:application
```

Run it under a restricted operating-system service account and a process manager such as systemd. Configure the HTTPS reverse proxy/front end separately, including TLS and forwarding to `127.0.0.1:8000`.

## 4. Configure the application

Supply configuration through a protected service environment file or deployment secret manager, not source control. At minimum:

```text
MEDTRACK_DATA_STORE=dynamodb
DYNAMODB_TABLE_NAME=<provisioned-table-name>
AWS_REGION=<deployment-region>
MEDTRACK_SECRET_KEY=<securely-generated-value>
MEDTRACK_COOKIE_SECURE=1
MEDTRACK_SNS_ENABLED=0
SNS_TOPIC_ARN=<provisioned-topic-arn>
```

`DYNAMODB_TABLE_NAME`, `AWS_REGION`, `SNS_TOPIC_ARN`, `MEDTRACK_SNS_ENABLED`, and session settings are app configuration. Enable SNS (`MEDTRACK_SNS_ENABLED=1`) only when a topic exists and the role can publish to it. `MEDTRACK_DATABASE_PATH` applies only to SQLite mode. Do not add AWS access key variables: boto3 should use the attached instance role. SNS remains disabled by default.

## 5. Start and verify service

Start the WSGI process through systemd, configure the reverse proxy, and verify the health of the process and HTTPS access. After the DynamoDB table and role are provisioned, perform controlled end-to-end checks for registration, login, booking/conflict handling, status updates, diagnosis transactions, and history reads. Add SNS checks only after the SNS topic, subscriptions, and publish permissions are configured.

Do not publish the demo URL or report a successful AWS deployment until the app has actually been launched and verified. This guide is preparation only; AWS resource setup and deployment remain blocked by account activation.
