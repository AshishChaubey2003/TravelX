"""
F-001: login throttling.

The stock simplejwt `TokenObtainPairView` has no throttle, so an attacker
can run unlimited password guesses from a single IP (and, worse, from a
botnet distributed across many IPs targeting the same account).

Two throttles cover both cases:

- `LoginIPThrottle` keys on the client IP. ScopedRateThrottle's default IP
  keying is fine here. Rate is `login` in DEFAULT_THROTTLE_RATES.

- `LoginAccountThrottle` keys on the submitted username, so password-spraying
  against one account from many IPs is rate-limited independently of IP.
  Rate is `login_account` in DEFAULT_THROTTLE_RATES.

Throttle state lives in the configured Django cache. In the dev default
(LocMemCache) throttle state is per-process; in production with Redis the
state is shared across all workers (that is one reason a shared cache is
listed as a prerequisite in the audit docs).

Design notes
------------
- The username is NOT normalised (lowercased / trimmed) before use as a key.
  Doing so would let an attacker evade the throttle by alternating cases.
  simplejwt itself is also case-sensitive on the authentication side; the
  throttle key reflects what the attacker is actually trying.
- The throttle fires on BOTH successful and failed login attempts, which is
  how DRF's `ScopedRateThrottle` already behaves. For a login endpoint this
  is intentional: an attacker who guesses right still shouldn't get free
  turns against the same account.
- The throttle only fires on POST — DRF's throttle machinery already scopes
  it to the view that declares it, and `TokenObtainPairView` only accepts
  POST.
"""
import re

from rest_framework.throttling import ScopedRateThrottle

# M17 deployment-blocker fix: DRF's SimpleRateThrottle.parse_rate reads only
# the FIRST character after the slash ('m' in '10/min'), so the configured
# 'login_account': '10/5min' rate raised KeyError('5') on EVERY request to
# the login endpoint — a 500 on all logins in any real deployment. The unit
# suite never saw it because every throttle test patches THROTTLE_RATES; the
# M17 live smoke run against the real settings caught it.
_RATE_RE = re.compile(r'^(\d+)/(\d*)(s|m|h|d)\w*$')
_UNIT_SECONDS = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}


def parse_extended_rate(rate):
    """
    Parse '<count>/<multiplier?><unit>' rates, e.g. '10/5min' -> (10, 300).

    Superset of DRF's own format: a plain '20/min' or '100/day' parses
    identically to stock DRF. Raises ValueError for anything unparseable so a
    bad rate fails LOUDLY at test/startup time, never as a per-request 500.
    """
    if rate is None:
        return (None, None)
    match = _RATE_RE.match(rate)
    if not match:
        raise ValueError(f'Unparseable throttle rate: {rate!r}')
    count, multiplier, unit = match.groups()
    return int(count), _UNIT_SECONDS[unit] * (int(multiplier) if multiplier else 1)


class LoginIPThrottle(ScopedRateThrottle):
    """Per-IP throttle for login attempts. Uses the standard IP-keying."""
    scope_attr = 'login_ip_scope'

    def parse_rate(self, rate):
        return parse_extended_rate(rate)


class LoginAccountThrottle(ScopedRateThrottle):
    """
    Per-account throttle: key is the submitted username, so password-spraying
    the same account from many IPs is limited independently of IP throttling.
    """
    scope_attr = 'login_account_scope'

    def parse_rate(self, rate):
        return parse_extended_rate(rate)

    def get_cache_key(self, request, view):
        # ScopedRateThrottle normally returns None (which means "don't
        # throttle") when `scope` is unset; we always use the fixed scope
        # 'login_account' declared on the view below.
        self.scope = getattr(view, 'login_account_scope', 'login_account')
        self.rate = self.get_rate()
        if not self.rate:
            return None
        self.num_requests, self.duration = self.parse_rate(self.rate)

        username = ''
        try:
            data = request.data
        except Exception:
            data = {}
        if isinstance(data, dict):
            raw = data.get('username') or data.get('email') or ''
            if isinstance(raw, str):
                username = raw.strip()[:150]
        if not username:
            # No username in payload: fall back to IP so an attacker can't
            # evade this by omitting the username field.
            ident = self.get_ident(request)
        else:
            ident = f'u:{username}'

        return f'throttle_login_account_{ident}'
