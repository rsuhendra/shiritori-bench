"""Offline fault injection: no provider calls and no actual backoff sleeps."""
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import http.client
import io
import json
import ssl
import unittest
from unittest.mock import MagicMock, patch
import urllib.error
import urllib.request

from shiritori_bench.http_retry import post_json, RetryExhausted
from shiritori_bench.deepseek import DeepSeekClient
from shiritori_bench.openrouter import OpenRouterClient


def http_error(status, retry_after=None):
    return urllib.error.HTTPError('https://example.invalid', status, 'not logged',
        {'Retry-After': retry_after} if retry_after else {}, io.BytesIO(b'private body'))


class RetryTests(unittest.TestCase):
    def run_request(self, effects, **options):
        good = MagicMock()
        good.__enter__.return_value.read.return_value = b'{"choices": []}'
        request = urllib.request.Request('https://example.invalid', data=b'unchanged')
        with patch('urllib.request.urlopen', side_effect=[*effects, good]) as send, \
                patch('shiritori_bench.http_retry.time.sleep') as sleep, \
                self.assertLogs('shiritori_bench.http_retry', level='WARNING'):
            result = post_json(request, **options)
        self.assertTrue(all(call.args[0] is request for call in send.call_args_list))
        return result, send.call_count, sleep

    def test_disconnect_and_timeout_retry_only_same_request(self):
        result, calls, sleep = self.run_request([
            http.client.RemoteDisconnected('closed'), urllib.error.URLError(TimeoutError())])
        self.assertEqual(calls, 3)
        self.assertEqual(result['transport']['retries'], 2)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [2, 4])

    def test_retryable_statuses(self):
        for status in (408, 429, 500, 502, 503, 504):
            with self.subTest(status=status):
                result, calls, _ = self.run_request([http_error(status)])
                self.assertEqual(calls, 2)
                self.assertEqual(result['transport']['failures'][0]['status'], status)

    def test_retry_after_seconds_and_date(self):
        for value in ('9', format_datetime(datetime.now(timezone.utc) + timedelta(seconds=12), usegmt=True)):
            _, _, sleep = self.run_request([http_error(429, value)])
            self.assertGreaterEqual(sleep.call_args.args[0], 9)

    def test_long_retry_after_stops_instead_of_retrying_early(self):
        with patch('urllib.request.urlopen', side_effect=http_error(429, '120')) as send, \
                patch('shiritori_bench.http_retry.time.sleep') as sleep:
            with self.assertRaises(RetryExhausted) as caught:
                post_json(None)
        self.assertEqual(send.call_count, 1)
        sleep.assert_not_called()
        self.assertEqual(caught.exception.transport_metadata['retries'], 0)

    def test_exhaustion_records_three_attempts_without_private_error_text(self):
        with patch('urllib.request.urlopen', side_effect=TimeoutError('secret')) as send, \
                patch('shiritori_bench.http_retry.time.sleep') as sleep, \
                self.assertLogs('shiritori_bench.http_retry'):
            with self.assertRaises(RetryExhausted) as caught:
                post_json(None)
        self.assertEqual(send.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(len(caught.exception.transport_metadata['failures']), 3)
        self.assertNotIn('secret', str(caught.exception))

    def test_permanent_errors_do_not_retry(self):
        for error in (http_error(400), http_error(401), http_error(403), http_error(404),
                      urllib.error.URLError(ssl.SSLCertVerificationError('bad certificate')),
                      urllib.error.URLError('invalid URL')):
            with self.subTest(error=type(error).__name__), \
                    patch('urllib.request.urlopen', side_effect=error) as send, \
                    patch('shiritori_bench.http_retry.time.sleep') as sleep:
                with self.assertRaises(type(error)):
                    post_json(None)
                self.assertEqual(send.call_count, 1)
                sleep.assert_not_called()

    def test_invalid_json_is_not_retried(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'not json'
        with patch('urllib.request.urlopen', return_value=response) as send:
            with self.assertRaises(json.JSONDecodeError):
                post_json(None)
        self.assertEqual(send.call_count, 1)

    def test_zero_disables_retries(self):
        with patch('urllib.request.urlopen', side_effect=TimeoutError()) as send:
            with self.assertRaises(RetryExhausted):
                post_json(None, max_retries=0)
        self.assertEqual(send.call_count, 1)

    def test_invalid_retry_count_rejected_before_request(self):
        for value in (-1, 3, 1.5, True):
            with self.subTest(value=value), patch('urllib.request.urlopen') as send:
                with self.assertRaises(ValueError):
                    post_json(None, max_retries=value)
                send.assert_not_called()

    def test_both_provider_adapters_use_retry_transport(self):
        for client in (DeepSeekClient('test'), OpenRouterClient('test')):
            response = MagicMock()
            response.__enter__.return_value.read.return_value = b'{"choices": []}'
            with patch('urllib.request.urlopen', side_effect=[ConnectionResetError(), response]) as send, \
                    patch('shiritori_bench.http_retry.time.sleep'), \
                    self.assertLogs('shiritori_bench.http_retry'):
                result = client.complete(model='test', messages=[])
            self.assertEqual(send.call_count, 2)
            self.assertEqual(result['transport']['attempts'], 2)
