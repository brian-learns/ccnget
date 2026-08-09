"""Tests for src/ccnget/retry.py — exponential backoff retry logic."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from ccnget.retry import retry_with_backoff


class TestRetrySuccess:
    """Happy path: call succeeds on first attempt."""

    @patch("ccnget.retry.time.sleep")
    def test_first_call_succeeds(self, mock_sleep):
        response = MagicMock(spec=requests.Response)
        response.status_code = 200

        result = retry_with_backoff(lambda: response)
        assert result is response
        mock_sleep.assert_not_called()


class TestRetryTransientErrors:
    """Retry is triggered on connection errors and timeouts."""

    @patch("ccnget.retry.time.sleep")
    def test_retry_on_connection_error(self, mock_sleep):
        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise requests.exceptions.ConnectionError("DNS failure")
            resp = MagicMock(spec=requests.Response)
            resp.status_code = 200
            return resp

        result = retry_with_backoff(fn, max_retries=5)
        assert result is not None
        assert call_count == 3

    @patch("ccnget.retry.time.sleep")
    def test_retry_on_timeout(self, mock_sleep):
        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise requests.exceptions.Timeout("timed out")
            resp = MagicMock(spec=requests.Response)
            resp.status_code = 200
            return resp

        result = retry_with_backoff(fn, max_retries=3)
        assert result is not None
        assert call_count == 2

    @patch("ccnget.retry.time.sleep")
    def test_exhausts_retries_raises_last_exception(self, mock_sleep):
        def fn():
            raise requests.exceptions.ConnectionError("permanent failure")

        with pytest.raises(requests.exceptions.ConnectionError, match="permanent failure"):
            retry_with_backoff(fn, max_retries=2)


class TestRetryHttp5xx:
    """Retry is triggered on 5xx HTTP responses."""

    @patch("ccnget.retry.time.sleep")
    def test_retry_on_503(self, mock_sleep):
        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                resp = MagicMock(spec=requests.Response)
                resp.status_code = 503
                return resp
            resp2 = MagicMock(spec=requests.Response)
            resp2.status_code = 200
            return resp2

        result = retry_with_backoff(fn, max_retries=3)
        assert result is not None
        assert call_count == 2

    @patch("ccnget.retry.time.sleep")
    def test_retry_on_502(self, mock_sleep):
        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                resp = MagicMock(spec=requests.Response)
                resp.status_code = 502
                return resp
            resp2 = MagicMock(spec=requests.Response)
            resp2.status_code = 200
            return resp2

        result = retry_with_backoff(fn, max_retries=3)
        assert result is not None
        assert call_count == 2

    @patch("ccnget.retry.time.sleep")
    def test_retry_on_500(self, mock_sleep):
        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                resp = MagicMock(spec=requests.Response)
                resp.status_code = 500
                return resp
            resp2 = MagicMock(spec=requests.Response)
            resp2.status_code = 200
            return resp2

        result = retry_with_backoff(fn, max_retries=3)
        assert call_count == 2


class TestNoRetryOn4xx:
    """Non-retryable HTTP errors (4xx) are not retried."""

    @patch("ccnget.retry.time.sleep")
    def test_no_retry_on_400(self, mock_sleep):
        resp = MagicMock(spec=requests.Response)
        resp.status_code = 400
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError("Bad Request")

        def fn():
            return resp

        with pytest.raises(requests.exceptions.HTTPError):
            retry_with_backoff(fn, max_retries=3)
        # Should only be called once — no retries
        mock_sleep.assert_not_called()

    @patch("ccnget.retry.time.sleep")
    def test_no_retry_on_401(self, mock_sleep):
        resp = MagicMock(spec=requests.Response)
        resp.status_code = 401
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError("Unauthorized")

        with pytest.raises(requests.exceptions.HTTPError):
            retry_with_backoff(lambda: resp, max_retries=3)
        mock_sleep.assert_not_called()


class TestBackoffTiming:
    """Verify backoff delays increase exponentially."""

    @patch("ccnget.retry.time.sleep")
    def test_delays_increase(self, mock_sleep):
        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1
            if call_count < 4:
                raise requests.exceptions.ConnectionError()
            resp = MagicMock(spec=requests.Response)
            resp.status_code = 200
            return resp

        retry_with_backoff(fn, max_retries=5, base_delay=1.0, jitter=0)
        # 3 retries = 3 sleeps: ~1s, ~2s, ~4s
        assert mock_sleep.call_count == 3
        delays = [c[0][0] for c in mock_sleep.call_args_list]
        # With jitter=0, delays should be exactly 1, 2, 4
        assert delays[0] == pytest.approx(1.0)
        assert delays[1] == pytest.approx(2.0)
        assert delays[2] == pytest.approx(4.0)

    @patch("ccnget.retry.time.sleep")
    def test_max_delay_cap(self, mock_sleep):
        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1
            if call_count < 5:
                raise requests.exceptions.ConnectionError()
            resp = MagicMock(spec=requests.Response)
            resp.status_code = 200
            return resp

        retry_with_backoff(fn, max_retries=10, base_delay=1.0, max_delay=5.0, jitter=0)
        delays = [c[0][0] for c in mock_sleep.call_args_list]
        # Delays: 1, 2, 4, 5 (capped), 5 (capped) — we only need 4 failures
        for d in delays:
            assert d <= 5.0
