#!/usr/bin/env python3
"""HTTP client with retry and timeout for payme."""

import time
from typing import Any, Optional

import requests
from requests.exceptions import RequestException, Timeout, ConnectionError, HTTPError

from config import HTTP_TIMEOUT_SECONDS, HTTP_RETRY_ATTEMPTS


class HttpError(Exception):
    """HTTP request failed after all retries."""

    def __init__(self, message: str, status_code: int = None, response: str = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


def _calculate_backoff(attempt: int, base: float = 1.0, max_delay: float = 30.0) -> float:
    """Calculate exponential backoff delay. Returns seconds to wait."""
    delay = base * (2 ** attempt)
    return min(delay, max_delay)


def _should_retry(status_code: int) -> bool:
    """Determine if request should be retried based on status code."""
    # Retry on server errors and rate limiting
    return status_code >= 500 or status_code == 429


def request(
    method: str,
    url: str,
    headers: dict = None,
    params: dict = None,
    json: dict = None,
    data: Any = None,
    timeout: float = None,
    retries: int = None,
    raise_for_status: bool = True,
) -> requests.Response:
    """
    Make HTTP request with retry and exponential backoff.

    Args:
        method: HTTP method (GET, POST, PUT, DELETE, etc.)
        url: Request URL
        headers: Optional request headers
        params: Optional query parameters
        json: Optional JSON body (sets Content-Type automatically)
        data: Optional form data or raw body
        timeout: Request timeout in seconds (default: HTTP_TIMEOUT_SECONDS)
        retries: Number of retry attempts (default: HTTP_RETRY_ATTEMPTS)
        raise_for_status: Raise HttpError on 4xx/5xx responses (default: True)

    Returns:
        requests.Response object

    Raises:
        HttpError: On request failure after all retries
    """
    if timeout is None:
        timeout = HTTP_TIMEOUT_SECONDS
    if retries is None:
        retries = HTTP_RETRY_ATTEMPTS

    last_exception = None
    last_response = None

    for attempt in range(retries):
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json,
                data=data,
                timeout=timeout,
            )

            # Check if we should retry based on status code
            if response.status_code >= 400 and _should_retry(response.status_code):
                last_response = response
                if attempt < retries - 1:
                    delay = _calculate_backoff(attempt)
                    time.sleep(delay)
                    continue

            # Raise on client/server errors if requested
            if raise_for_status and response.status_code >= 400:
                raise HttpError(
                    f'HTTP {response.status_code}: {response.reason}',
                    status_code=response.status_code,
                    response=response.text[:500] if response.text else None,
                )

            return response

        except (Timeout, ConnectionError) as e:
            last_exception = e
            if attempt < retries - 1:
                delay = _calculate_backoff(attempt)
                time.sleep(delay)
                continue

        except RequestException as e:
            # Non-retryable request error
            raise HttpError(f'Request failed: {e}')

    # All retries exhausted
    if last_response is not None:
        raise HttpError(
            f'HTTP {last_response.status_code} after {retries} attempts',
            status_code=last_response.status_code,
            response=last_response.text[:500] if last_response.text else None,
        )

    raise HttpError(f'Request failed after {retries} attempts: {last_exception}')


def get(
    url: str,
    headers: dict = None,
    params: dict = None,
    timeout: float = None,
    retries: int = None,
) -> requests.Response:
    """Make GET request with retry."""
    return request('GET', url, headers=headers, params=params, timeout=timeout, retries=retries)


def post(
    url: str,
    headers: dict = None,
    json: dict = None,
    data: Any = None,
    timeout: float = None,
    retries: int = None,
) -> requests.Response:
    """Make POST request with retry."""
    return request('POST', url, headers=headers, json=json, data=data, timeout=timeout, retries=retries)


def put(
    url: str,
    headers: dict = None,
    json: dict = None,
    data: Any = None,
    timeout: float = None,
    retries: int = None,
) -> requests.Response:
    """Make PUT request with retry."""
    return request('PUT', url, headers=headers, json=json, data=data, timeout=timeout, retries=retries)


def delete(
    url: str,
    headers: dict = None,
    timeout: float = None,
    retries: int = None,
) -> requests.Response:
    """Make DELETE request with retry."""
    return request('DELETE', url, headers=headers, timeout=timeout, retries=retries)


def get_json(
    url: str,
    headers: dict = None,
    params: dict = None,
    timeout: float = None,
    retries: int = None,
) -> Any:
    """Make GET request and return JSON response."""
    response = get(url, headers=headers, params=params, timeout=timeout, retries=retries)
    try:
        return response.json()
    except ValueError as e:
        raise HttpError(f'Invalid JSON response: {e}', response=response.text[:500])


def post_json(
    url: str,
    headers: dict = None,
    json: dict = None,
    timeout: float = None,
    retries: int = None,
) -> Any:
    """Make POST request with JSON body and return JSON response."""
    response = post(url, headers=headers, json=json, timeout=timeout, retries=retries)
    try:
        return response.json()
    except ValueError as e:
        raise HttpError(f'Invalid JSON response: {e}', response=response.text[:500])


def download(
    url: str,
    headers: dict = None,
    timeout: float = None,
    retries: int = None,
) -> bytes:
    """Download binary content from URL."""
    response = get(url, headers=headers, timeout=timeout, retries=retries)
    return response.content


if __name__ == '__main__':
    print('Testing http_client.py')
    print('=' * 40)

    # Test successful GET
    try:
        response = get('https://httpbin.org/get', timeout=10)
        assert response.status_code == 200, 'GET failed'
        print('[OK] GET request')
    except HttpError as e:
        print(f'[FAIL] GET request: {e}')

    # Test GET with JSON response
    try:
        data = get_json('https://httpbin.org/json', timeout=10)
        assert 'slideshow' in data, 'JSON parsing failed'
        print('[OK] GET JSON')
    except HttpError as e:
        print(f'[FAIL] GET JSON: {e}')

    # Test POST with JSON
    try:
        response = post(
            'https://httpbin.org/post',
            json={'test': 'data'},
            timeout=10
        )
        assert response.status_code == 200, 'POST failed'
        print('[OK] POST JSON')
    except HttpError as e:
        print(f'[FAIL] POST JSON: {e}')

    # Test 404 error handling
    try:
        get('https://httpbin.org/status/404', timeout=10)
        print('[FAIL] 404 should raise HttpError')
    except HttpError as e:
        assert e.status_code == 404, 'Wrong status code'
        print('[OK] 404 error handling')

    # Test timeout handling (with short timeout)
    try:
        get('https://httpbin.org/delay/5', timeout=1, retries=1)
        print('[FAIL] Timeout should raise HttpError')
    except HttpError as e:
        assert 'failed' in str(e).lower(), 'Wrong error message'
        print('[OK] Timeout handling')

    # Test backoff calculation
    assert _calculate_backoff(0) == 1.0, 'Backoff 0 failed'
    assert _calculate_backoff(1) == 2.0, 'Backoff 1 failed'
    assert _calculate_backoff(2) == 4.0, 'Backoff 2 failed'
    assert _calculate_backoff(10) == 30.0, 'Backoff max failed'
    print('[OK] Backoff calculation')

    print('=' * 40)
    print('All tests passed')
