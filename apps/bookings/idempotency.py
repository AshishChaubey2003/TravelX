"""
Request-level idempotency for booking creation (Stage 2).

The client supplies `Idempotency-Key: <UUID>`. The key is stored in
Booking.idempotency_key, whose UNIQUE constraint is what actually prevents
duplicates under concurrency; the fingerprint below is what distinguishes an
honest retry from a different request that reused the same key.

Deliberately NOT a hash of raw request JSON: field order, whitespace,
'2026-1-1' vs '2026-01-01', uppercase UUIDs and omitted-vs-explicit defaults
would all produce different hashes for identical requests. The fingerprint is
computed from serializer.validated_data, after DRF has coerced types and
filled defaults, so those variations normalise away before hashing.
"""
import hashlib
import json
import uuid

IDEMPOTENCY_KEY_META = 'HTTP_IDEMPOTENCY_KEY'
IDEMPOTENCY_KEY_HEADER = 'Idempotency-Key'
REPLAY_HEADER = 'Idempotent-Replay'

# Exactly the fields BookingCreateSerializer declares - nothing arbitrary, and
# no transport metadata (no auth token, no X-Request-ID, no timestamps).
_RESOURCE_FIELDS = ('hotel_id', 'adventure_id', 'vehicle_id')


def read_idempotency_key(request):
    """
    Return (key, error_message).

    absent header -> (None, None)   legacy behaviour, no deduplication
    valid UUID    -> (UUID, None)
    anything else -> (None, message) and the caller returns 400
    """
    raw = request.META.get(IDEMPOTENCY_KEY_META, '')
    if not isinstance(raw, str) or not raw.strip():
        return None, None
    try:
        return uuid.UUID(raw.strip()), None
    except (ValueError, AttributeError, TypeError):
        return None, 'Idempotency-Key must be a valid UUID.'


def booking_fingerprint(validated_data):
    """
    Deterministic SHA-256 over the canonicalised validated payload.

    Normalisation:
      - resource ids: absent or falsy -> None; otherwise str(UUID), which is
        lowercase hyphenated, so uppercase input matches lowercase input
      - dates: DateField has already parsed them; .isoformat() -> YYYY-MM-DD
      - quantities: int(); DRF has already applied default=1, so an omitted
        'nights' and an explicit 'nights': 1 produce the same fingerprint
      - key order fixed by sort_keys, whitespace removed by separators
    """
    canonical = {}
    for field in _RESOURCE_FIELDS:
        value = validated_data.get(field)
        canonical[field] = str(value) if value else None
    canonical['check_in'] = validated_data['check_in'].isoformat()
    canonical['check_out'] = validated_data['check_out'].isoformat()
    canonical['nights'] = int(validated_data.get('nights', 1))
    canonical['spots'] = int(validated_data.get('spots', 1))

    blob = json.dumps(canonical, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()
