#!/usr/bin/env python3
"""Google Photos API client for payme."""

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from config import (
    GOOGLE_PHOTOS_API_BASE,
    GOOGLE_TOKENS_FILE,
    ALBUM_CACHE_FILE,
    PROCESSED_PHOTOS_FILE,
    PHOTO_GROUPING_MINUTES,
    get_env,
)
from storage import load_json, save_json, update_dict
from http_client import get, post, get_json, post_json, download, HttpError

# OAuth endpoints
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'


def load_tokens() -> dict:
    """Load OAuth tokens from storage."""
    return load_json(GOOGLE_TOKENS_FILE, {})


def save_tokens(tokens: dict) -> None:
    """Save OAuth tokens to storage."""
    save_json(GOOGLE_TOKENS_FILE, tokens)


def refresh_access_token(refresh_token: str, client_id: str, client_secret: str) -> dict:
    """
    Refresh OAuth access token.

    Returns dict with new access_token and expires_in.
    Raises HttpError on failure.
    """
    response = post_json(
        GOOGLE_TOKEN_URL,
        data={
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token,
            'client_id': client_id,
            'client_secret': client_secret,
        },
        timeout=30,
    )

    if 'access_token' not in response:
        raise HttpError(f'Token refresh failed: {response}')

    return response


def get_valid_access_token() -> str:
    """
    Get a valid access token, refreshing if necessary.

    Returns access token string.
    Raises HttpError if token refresh fails.
    """
    tokens = load_tokens()

    if not tokens:
        raise HttpError('No Google tokens found. Run authorize_google.py first.')

    access_token = tokens.get('access_token')
    refresh_token = tokens.get('refresh_token')
    expires_at = tokens.get('expires_at')
    client_id = tokens.get('client_id')
    client_secret = tokens.get('client_secret')

    if not refresh_token:
        raise HttpError('No refresh token found. Re-run authorize_google.py.')

    # Check if token needs refresh (with 5 min buffer)
    needs_refresh = True
    if expires_at and access_token:
        expires_dt = datetime.fromisoformat(expires_at)
        if datetime.now() < expires_dt - timedelta(minutes=5):
            needs_refresh = False

    if needs_refresh:
        if not client_id or not client_secret:
            raise HttpError('Missing client credentials. Re-run authorize_google.py.')

        new_tokens = refresh_access_token(refresh_token, client_id, client_secret)

        # Update stored tokens
        tokens['access_token'] = new_tokens['access_token']
        expires_in = new_tokens.get('expires_in', 3600)
        tokens['expires_at'] = (datetime.now() + timedelta(seconds=expires_in)).isoformat()

        # Refresh token might be rotated
        if 'refresh_token' in new_tokens:
            tokens['refresh_token'] = new_tokens['refresh_token']

        save_tokens(tokens)
        access_token = tokens['access_token']

    return access_token


def get_auth_headers() -> dict:
    """Get authorization headers for API requests."""
    access_token = get_valid_access_token()
    return {'Authorization': f'Bearer {access_token}'}


def check_token_health() -> dict:
    """
    Check OAuth token health.

    Returns dict with:
    - status: 'ok', 'expiring', 'expired', or 'missing'
    - expires_at: expiration datetime (if available)
    - message: human-readable status
    """
    tokens = load_tokens()

    if not tokens or not tokens.get('refresh_token'):
        return {
            'status': 'missing',
            'expires_at': None,
            'message': 'No tokens found. Run authorize_google.py.',
        }

    expires_at = tokens.get('expires_at')
    if not expires_at:
        return {
            'status': 'ok',
            'expires_at': None,
            'message': 'Token present, expiration unknown.',
        }

    expires_dt = datetime.fromisoformat(expires_at)
    now = datetime.now()

    if now > expires_dt:
        # Try to refresh
        try:
            get_valid_access_token()
            return {
                'status': 'ok',
                'expires_at': expires_at,
                'message': 'Token refreshed successfully.',
            }
        except HttpError as e:
            return {
                'status': 'expired',
                'expires_at': expires_at,
                'message': f'Token expired and refresh failed: {e}',
            }

    if now > expires_dt - timedelta(days=1):
        return {
            'status': 'expiring',
            'expires_at': expires_at,
            'message': 'Token expiring soon.',
        }

    return {
        'status': 'ok',
        'expires_at': expires_at,
        'message': 'Token valid.',
    }


def list_albums() -> list[dict]:
    """
    List all albums in user's Google Photos.

    Returns list of album dicts with id, title, mediaItemsCount.
    """
    headers = get_auth_headers()
    albums = []
    page_token = None

    while True:
        params = {'pageSize': 50}
        if page_token:
            params['pageToken'] = page_token

        response = get_json(
            f'{GOOGLE_PHOTOS_API_BASE}/albums',
            headers=headers,
            params=params,
        )

        for album in response.get('albums', []):
            albums.append({
                'id': album.get('id'),
                'title': album.get('title', ''),
                'mediaItemsCount': int(album.get('mediaItemsCount', 0)),
            })

        page_token = response.get('nextPageToken')
        if not page_token:
            break

    return albums


def find_album(name: str = None, album_id: str = None) -> Optional[dict]:
    """
    Find album by name (fuzzy) or ID (exact).

    Album ID takes precedence if both provided.
    Name matching is case-insensitive with whitespace trimmed.

    Returns album dict or None if not found.
    """
    # If album ID provided, fetch directly
    if album_id:
        try:
            headers = get_auth_headers()
            response = get_json(
                f'{GOOGLE_PHOTOS_API_BASE}/albums/{album_id}',
                headers=headers,
            )
            return {
                'id': response.get('id'),
                'title': response.get('title', ''),
                'mediaItemsCount': int(response.get('mediaItemsCount', 0)),
            }
        except HttpError:
            return None

    # Search by name
    if not name:
        name = get_env('PAYME_ALBUM_NAME', 'bill-pay')

    name_normalized = name.strip().lower()
    albums = list_albums()

    for album in albums:
        title_normalized = album['title'].strip().lower()
        if title_normalized == name_normalized:
            return album

    # Fuzzy match: check if name is contained
    for album in albums:
        title_normalized = album['title'].strip().lower()
        if name_normalized in title_normalized or title_normalized in name_normalized:
            return album

    return None


def get_album_id() -> str:
    """
    Get configured album ID, finding by name if needed.

    Caches album ID for future calls.
    Raises HttpError if album not found.
    """
    # Check for configured album ID first
    album_id = get_env('PAYME_ALBUM_ID', '')
    if album_id:
        return album_id

    # Check cache
    cache = load_json(ALBUM_CACHE_FILE, {})
    if cache.get('album_id'):
        return cache['album_id']

    # Find album by name
    album_name = get_env('PAYME_ALBUM_NAME', 'bill-pay')
    album = find_album(name=album_name)

    if not album:
        raise HttpError(f'Album not found: {album_name}')

    # Cache for future
    cache['album_id'] = album['id']
    cache['album_title'] = album['title']
    cache['cached_at'] = datetime.now().isoformat()
    save_json(ALBUM_CACHE_FILE, cache)

    return album['id']


def list_album_photos(album_id: str = None) -> list[dict]:
    """
    List all photos in an album.

    Returns list of photo dicts with id, filename, mimeType, creationTime, baseUrl.
    Note: baseUrl expires after 60 minutes - do not cache!
    """
    if album_id is None:
        album_id = get_album_id()

    headers = get_auth_headers()
    photos = []
    page_token = None

    while True:
        body = {
            'albumId': album_id,
            'pageSize': 100,
        }
        if page_token:
            body['pageToken'] = page_token

        response = post_json(
            f'{GOOGLE_PHOTOS_API_BASE}/mediaItems:search',
            headers=headers,
            json=body,
        )

        for item in response.get('mediaItems', []):
            metadata = item.get('mediaMetadata', {})
            photos.append({
                'id': item.get('id'),
                'filename': item.get('filename', ''),
                'mimeType': item.get('mimeType', ''),
                'creationTime': metadata.get('creationTime', ''),
                'baseUrl': item.get('baseUrl'),
                'width': int(metadata.get('width', 0)),
                'height': int(metadata.get('height', 0)),
            })

        page_token = response.get('nextPageToken')
        if not page_token:
            break

    return photos


def get_processed_photos() -> set[str]:
    """Get set of already processed photo IDs."""
    data = load_json(PROCESSED_PHOTOS_FILE, {'processed': []})
    return set(data.get('processed', []))


def mark_photo_processed(photo_id: str) -> None:
    """Mark a photo as processed."""
    data = load_json(PROCESSED_PHOTOS_FILE, {'processed': []})
    if photo_id not in data['processed']:
        data['processed'].append(photo_id)
        save_json(PROCESSED_PHOTOS_FILE, data)


def get_new_photos(album_id: str = None) -> list[dict]:
    """
    Get photos not yet processed.

    Returns list of new photo dicts, sorted by creation time.
    """
    all_photos = list_album_photos(album_id)
    processed = get_processed_photos()

    new_photos = [p for p in all_photos if p['id'] not in processed]

    # Sort by creation time
    new_photos.sort(key=lambda p: p.get('creationTime', ''))

    return new_photos


def group_photos_by_time(photos: list[dict]) -> list[list[dict]]:
    """
    Return each photo as its own group (grouping disabled).
    Each photo/file is treated as a separate bill.
    """
    if not photos:
        return []
    return [[photo] for photo in photos]


def download_photo(photo: dict, size: str = 'full') -> bytes:
    """
    Download photo content.

    Args:
        photo: Photo dict with baseUrl
        size: 'full', 'large' (1600px), 'medium' (800px), 'thumb' (256px)

    Returns:
        Image bytes
    """
    base_url = photo.get('baseUrl')
    if not base_url:
        raise ValueError('Photo has no baseUrl')

    # Add size parameters
    size_params = {
        'full': f'=w{photo.get("width", 4000)}-h{photo.get("height", 4000)}',
        'large': '=w1600-h1600',
        'medium': '=w800-h800',
        'thumb': '=w256-h256',
    }

    url = base_url + size_params.get(size, size_params['full'])
    return download(url, timeout=60)


def download_photo_to_file(photo: dict, output_path: Path, size: str = 'full') -> Path:
    """Download photo to file. Returns output path."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    image_data = download_photo(photo, size)

    with open(output_path, 'wb') as f:
        f.write(image_data)

    return output_path


if __name__ == '__main__':
    print('Testing google_photos.py')
    print('=' * 40)

    # Test photo grouping
    test_photos = [
        {'id': '1', 'creationTime': '2024-01-15T10:00:00Z'},
        {'id': '2', 'creationTime': '2024-01-15T10:02:00Z'},  # 2 min later
        {'id': '3', 'creationTime': '2024-01-15T10:03:00Z'},  # 3 min later
        {'id': '4', 'creationTime': '2024-01-15T11:00:00Z'},  # 1 hour later
        {'id': '5', 'creationTime': '2024-01-15T11:01:00Z'},  # 1 min later
    ]

    groups = group_photos_by_time(test_photos)
    assert len(groups) == 2, f'Expected 2 groups, got {len(groups)}'
    assert len(groups[0]) == 3, f'First group should have 3 photos, got {len(groups[0])}'
    assert len(groups[1]) == 2, f'Second group should have 2 photos, got {len(groups[1])}'
    print('[OK] Photo grouping by time')

    # Test empty grouping
    empty_groups = group_photos_by_time([])
    assert len(empty_groups) == 0, 'Empty input should return empty groups'
    print('[OK] Empty photo grouping')

    # Test single photo grouping
    single_groups = group_photos_by_time([{'id': '1', 'creationTime': '2024-01-15T10:00:00Z'}])
    assert len(single_groups) == 1, 'Single photo should be one group'
    print('[OK] Single photo grouping')

    # Test processed photos tracking
    from storage import delete_file
    test_processed_file = PROCESSED_PHOTOS_FILE

    # Clean state
    delete_file(test_processed_file)

    processed = get_processed_photos()
    assert len(processed) == 0, 'Should start empty'

    mark_photo_processed('test-photo-1')
    mark_photo_processed('test-photo-2')

    processed = get_processed_photos()
    assert 'test-photo-1' in processed, 'Should contain marked photo'
    assert 'test-photo-2' in processed, 'Should contain second photo'
    assert len(processed) == 2, 'Should have 2 processed photos'

    # Mark same photo again (should not duplicate)
    mark_photo_processed('test-photo-1')
    processed = get_processed_photos()
    assert len(processed) == 2, 'Should not duplicate'

    # Cleanup
    delete_file(test_processed_file)
    print('[OK] Processed photos tracking')

    # Test token health check (without actual tokens)
    health = check_token_health()
    assert health['status'] == 'missing', 'Should be missing without tokens'
    print(f'[OK] Token health check: {health["status"]}')

    print()
    print('API tests require Google OAuth tokens.')
    print('Run authorize_google.py to set up authentication.')

    print('=' * 40)
    print('All tests passed')
