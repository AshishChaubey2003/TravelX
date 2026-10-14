"""
Event schemas and versioning (checklists G06 + G07).

Every Kafka event TravelX publishes is a JSON object that carries an integer
`schema_version` and (G07) a unique `event_id`. This module defines the
required fields per topic, how to validate an event, and how a producer
stamps the current version and a fresh event_id.

Versioning policy:
- Adding a new OPTIONAL field does not change the version. Unknown extra
  fields are accepted so consumers keep working when producers add fields.
  (`event_id` was added this way in G07, so it is still schema_version 1.)
- Removing, renaming, or changing the type/meaning of a field requires a new
  schema_version, and consumers must support both versions during rollout.
- Events published before versioning existed carry no `schema_version`. They
  are treated as LEGACY_SCHEMA_VERSION (1), which has the identical shape.
- Events published before G07 carry no `event_id`; the consumer identifies
  those by topic/partition/offset instead.
- An event with a version this code does not support is rejected.
"""
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation

from .topics import (
    TOPIC_BOOKING_CREATED,
    TOPIC_PAYMENT_SUCCESS,
    TOPIC_PAYMENT_FAILED,
    TOPIC_BOOKING_CANCELLED,
)

SCHEMA_VERSION = 1
SUPPORTED_SCHEMA_VERSIONS = frozenset({1})
LEGACY_SCHEMA_VERSION = 1


class EventValidationError(ValueError):
    """Raised when an event does not match its topic's schema."""


def _check_uuid(value):
    if not isinstance(value, str):
        raise ValueError("must be a UUID string")
    try:
        uuid.UUID(value)
    except ValueError:
        raise ValueError("must be a valid UUID string")


def _check_id(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("must be a non-empty string")


def _check_str(value):
    if not isinstance(value, str):
        raise ValueError("must be a string")


def _check_nullable_str(value):
    if value is not None and not isinstance(value, str):
        raise ValueError("must be a string or null")


def _check_decimal(value):
    if isinstance(value, bool) or not isinstance(value, str):
        raise ValueError("must be a decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError("must be a decimal string")
    if not number.is_finite():
        raise ValueError("must be a finite number")
    if number < 0:
        raise ValueError("must not be negative")


def _check_date(value):
    if not isinstance(value, str):
        raise ValueError("must be an ISO date string (YYYY-MM-DD)")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValueError("must be an ISO date string (YYYY-MM-DD)")


_FIELD_CHECKS = {
    "uuid": _check_uuid,
    "id": _check_id,
    "str": _check_str,
    "nullable_str": _check_nullable_str,
    "decimal": _check_decimal,
    "date": _check_date,
}

# Required fields per topic (version 1).
EVENT_SCHEMAS = {
    TOPIC_BOOKING_CREATED: {
        "booking_id": "uuid",
        "user_id": "id",
        "user_email": "str",
        "total_amount": "decimal",
        "status": "str",
        "check_in": "date",
        "check_out": "date",
    },
    TOPIC_PAYMENT_SUCCESS: {
        "booking_id": "uuid",
        "user_id": "id",
        "user_email": "str",
        "amount": "decimal",
    },
    TOPIC_PAYMENT_FAILED: {
        "booking_id": "uuid",
        "user_id": "id",
        "user_email": "str",
        "total_amount": "decimal",
    },
    TOPIC_BOOKING_CANCELLED: {
        "booking_id": "uuid",
        "user_id": "id",
        "user_email": "str",
        "total_amount": "decimal",
    },
}

# Optional on every topic: may be absent, but if present must have this type.
COMMON_OPTIONAL_FIELDS = {
    "event_id": "uuid",
}

OPTIONAL_FIELDS = {topic: dict(COMMON_OPTIONAL_FIELDS) for topic in EVENT_SCHEMAS}
OPTIONAL_FIELDS[TOPIC_PAYMENT_SUCCESS]["stripe_session_id"] = "nullable_str"


def validate_event(topic, payload):
    """
    Validate a decoded event against its topic schema.

    Returns a new dict (the input is not modified) with `schema_version`
    filled in. Raises EventValidationError listing every problem found.
    """
    schema = EVENT_SCHEMAS.get(topic)
    if schema is None:
        raise EventValidationError(f"no schema registered for topic {topic!r}")

    if not isinstance(payload, dict):
        raise EventValidationError(
            f"payload must be a JSON object, got {type(payload).__name__}"
        )

    version = payload.get("schema_version", LEGACY_SCHEMA_VERSION)
    if isinstance(version, bool) or not isinstance(version, int) or version not in SUPPORTED_SCHEMA_VERSIONS:
        raise EventValidationError(
            f"unsupported schema_version {version!r} "
            f"(supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)})"
        )

    problems = []

    for field, kind in schema.items():
        if field not in payload:
            problems.append(f"missing required field '{field}'")
            continue
        try:
            _FIELD_CHECKS[kind](payload[field])
        except ValueError as exc:
            problems.append(f"field '{field}' {exc}")

    for field, kind in OPTIONAL_FIELDS.get(topic, {}).items():
        if field in payload:
            try:
                _FIELD_CHECKS[kind](payload[field])
            except ValueError as exc:
                problems.append(f"field '{field}' {exc}")

    if problems:
        raise EventValidationError("; ".join(problems))

    return {**payload, "schema_version": version}


def prepare_event(topic, payload):
    """
    Producer side: stamp the current schema_version and a fresh event_id onto
    the payload and validate it, so we never publish an event our own
    consumer would reject. An event_id already present in the payload is kept.
    """
    if not isinstance(payload, dict):
        raise EventValidationError(
            f"payload must be a dict, got {type(payload).__name__}"
        )
    return validate_event(topic, {
        **payload,
        "schema_version": SCHEMA_VERSION,
        "event_id": payload.get("event_id") or str(uuid.uuid4()),
    })