# Error tracking and alerting (H03)

## Enable
Set in your ignored `.env` (never commit the DSN):

    SENTRY_DSN=<project DSN from Sentry>
    SENTRY_ENVIRONMENT=production      # or staging / development
    SENTRY_RELEASE=<git sha or version>
    SENTRY_TRACES_SAMPLE_RATE=0.0

Run `python manage.py sentry_check` once per environment. One test event
("TravelX Sentry test event") must appear in Sentry.

## What is captured
- Unhandled exceptions in Django views (500s) and in Celery tasks.
- `logger.exception(...)` / ERROR logs from any logger EXCEPT
  `travelx.request` (duplicate of the view exception) and `travelx.health`
  (dependency-outage alerting belongs to H04).
- Every event carries the tag `request_id` (H01). Search it in the JSON logs.

## What is never sent
Cookies, auth headers, signatures, query strings, request bodies, user
identity, local variables.

## Alert rules to create in the Sentry UI (not code)
1. New issue in `production` -> notify the on-call channel/email.
2. Issue seen > 10 times in 5 minutes -> notify (spike).
3. Issue regressed (reopened after resolve) -> notify.
Tag payment/booking issues via `request_id` + logger name when triaging.

## Rotating a leaked DSN
Revoke the key in Sentry project settings, create a new one, update `.env`.