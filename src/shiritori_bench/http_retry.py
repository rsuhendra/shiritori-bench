"""Bounded retries of one HTTP request; never retries a completed model turn."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import http.client
import json
import logging
import math
import socket
import ssl
import time
import urllib.error
import urllib.request

RETRY_STATUSES = {408, 429, 500, 502, 503, 504}
LOGGER = logging.getLogger(__name__)


class RetryExhausted(RuntimeError):
    def __init__(self, metadata):
        self.transport_metadata = metadata
        last = metadata['failures'][-1]
        super().__init__(f"API request failed after {metadata['attempts']} attempts "
                         f"({last['error_type']}, HTTP {last['status']}); no game loss assigned")


def transient(error):
    if isinstance(error, urllib.error.HTTPError):
        return error.code in RETRY_STATUSES
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    if isinstance(reason, ssl.SSLError):
        return False  # Never hide certificate or TLS configuration problems.
    return (isinstance(reason, (TimeoutError, ConnectionError, http.client.IncompleteRead))
            or isinstance(reason, socket.gaierror) and reason.errno == socket.EAI_AGAIN)


def retry_after(error):
    if not isinstance(error, urllib.error.HTTPError) or not error.headers:
        return 0.0
    value = error.headers.get('Retry-After', '')
    try:
        seconds = float(value)
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            seconds = (date - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return 0.0
    return max(0.0, seconds) if math.isfinite(seconds) else 0.0


def post_json(request, *, timeout=120, max_retries=2):
    if isinstance(max_retries, bool) or not isinstance(max_retries, int) or not 0 <= max_retries <= 2:
        raise ValueError('max_retries must be an integer from 0 to 2')
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('timeout must be finite and positive')
    started = time.monotonic()
    failures = []
    for attempt in range(1, max_retries + 2):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = json.loads(response.read().decode('utf-8'))
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.IncompleteRead) as error:
            if not transient(error):
                raise
            delay = max(2.0 ** attempt, retry_after(error))
            retrying = attempt <= max_retries and delay <= 60
            failures.append(dict(attempt=attempt, error_type=type(error).__name__,
                status=getattr(error, 'code', None), delay_seconds=delay if retrying else None))
            if isinstance(error, urllib.error.HTTPError):
                error.close()
            if not retrying:
                raise RetryExhausted(dict(attempts=attempt, retries=attempt - 1,
                    max_retries=max_retries, failures=failures,
                    latency_seconds=time.monotonic() - started)) from error
            # No exception messages, headers, credentials, or response bodies in retry logs.
            LOGGER.warning('Temporary API failure (%s, HTTP %s); retry %d/%d in %.1fs',
                           type(error).__name__, getattr(error, 'code', None),
                           attempt, max_retries, delay)
            time.sleep(delay)
            continue
        raw['transport'] = dict(attempts=attempt, retries=attempt - 1,
            max_retries=max_retries, failures=failures,
            latency_seconds=time.monotonic() - started)
        return raw
