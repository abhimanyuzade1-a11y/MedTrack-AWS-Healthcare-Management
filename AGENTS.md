# MedTrack Project Instructions

MedTrack is an AWS Cloud-Enabled Healthcare Management System for the SkillWallet AWS Cloud Practitioner capstone.

## Project rules

- Build and verify locally before integrating AWS.
- Do not create or modify AWS resources, deploy, or assume AWS resources exist unless explicitly approved in a later phase.
- Required stack: Python, Flask, HTML/CSS/JavaScript, Jinja2, Bootstrap 5, AWS DynamoDB, AWS SNS, AWS IAM, and AWS EC2.
- Do not use Next.js, React, Supabase, MongoDB, Firebase, or another backend.
- Keep the application suitable for deployment on an AWS EC2 Linux server.
- Keep implementation straightforward and avoid unnecessary dependencies.
- Never hard-code AWS credentials, passwords, API keys, or other secrets.
- Preserve working code; do not delete or overwrite it unless necessary.
- Run checks only at meaningful milestones; do not repeat tests after every small change.
- Do not begin a later development phase until the user approves it.

## Planned capabilities

- Patient registration and login
- Doctor login
- Patient and doctor dashboards
- Appointment booking and management
- Medical history
- Diagnosis submission
- Patient/doctor interaction
- DynamoDB for application data
- SNS for notifications
- IAM for AWS permissions
- EC2 for hosting
- GitHub repository and final live demo

## Initial architecture

- Flask application with server-rendered Jinja2 templates.
- Keep routes, service logic, configuration, templates, and static assets in separate folders.
- Start with a minimal app factory and health/home route; add domain features incrementally.
- Keep AWS integration behind service/config boundaries and defer it until a later, explicitly approved phase.
- Use environment-based configuration for future secrets and deployment settings.
- Bootstrap 5 is the planned UI framework; add it to pages when the UI is introduced.
