#!/usr/bin/env python3
"""Google Drive API client for payme."""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from config import (
    GOOGLE_TOKENS_FILE,
    ALBUM_CACHE_FILE,
    PROCESSED_PHOTOS_FILE,
    PHOTO_GROUPING_MINUTES,
    get_env,
)
from storage import load_json, save_json
from http_client import get_json, HttpError

# Google Drive API base
GOOGLE_DRIVE_API_BASE = 'https://www.googleapis.com/drive/v3'

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
    import requests
    response = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token,
            'client_id': client_id,
            'client_secret': client_secret,
        },
        timeout=30,
    )

    if response.status_code != 200:
        raise HttpError(f'Token refresh failed: {response.text}')

    result = response.json()
    if 'access_token' not in result:
        raise HttpError(f'Token refresh failed: {result}')

    return result


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


def list_folders() -> list[dict]:
    """
    List all folders in user's Google Drive.

    Returns list of folder dicts with id, name.
    """
    headers = get_auth_headers()
    folders = []
    page_token = None

    while True:
        params = {
            'q': "mimeType='application/vnd.google-apps.folder' and trashed=false",
            'fields': 'nextPageToken, files(id, name)',
            'pageSize': 100,
        }
        if page_token:
            params['pageToken'] = page_token

        response = get_json(
            f'{GOOGLE_DRIVE_API_BASE}/files',
            headers=headers,
            params=params,
        )

        for folder in response.get('files', []):
            folders.append({
                'id': folder.get('id'),
                'title': folder.get('name', ''),
            })

        page_token = response.get('nextPageToken')
        if not page_token:
            break

    return folders


def find_folder(name: str = None, folder_id: str = None) -> Optional[dict]:
    """
    Find folder by name (fuzzy) or ID (exact).

    Folder ID takes precedence if both provided.
    Name matching is case-insensitive with whitespace trimmed.

    Returns folder dict or None if not found.
    """
    # If folder ID provided, fetch directly
    if folder_id:
        try:
            headers = get_auth_headers()
            response = get_json(
                f'{GOOGLE_DRIVE_API_BASE}/files/{folder_id}',
                headers=headers,
                params={'fields': 'id, name'},
            )
            return {
                'id': response.get('id'),
                'title': response.get('name', ''),
            }
        except HttpError:
            return None

    # Search by name
    if not name:
        name = get_env('PAYME_ALBUM_NAME', 'bill-pay')

    name_normalized = name.strip().lower()
    folders = list_folders()

    for folder in folders:
        title_normalized = folder['title'].strip().lower()
        if title_normalized == name_normalized:
            return folder

    # Fuzzy match: check if name is contained
    for folder in folders:
        title_normalized = folder['title'].strip().lower()
        if name_normalized in title_normalized or title_normalized in name_normalized:
            return folder

    return None


def get_folder_id() -> str:
    """
    Get configured folder ID, finding by name if needed.

    Caches folder ID for future calls.
    Raises HttpError if folder not found.
    """
    # Check for configured folder ID first
    folder_id = get_env('PAYME_ALBUM_ID', '')
    if folder_id:
        return folder_id

    # Check cache
    cache = load_json(ALBUM_CACHE_FILE, {})
    if cache.get('album_id'):
        return cache['album_id']

    # Find folder by name
    folder_name = get_env('PAYME_ALBUM_NAME', 'bill-pay')
    folder = find_folder(name=folder_name)

    if not folder:
        raise HttpError(f'Folder not found: {folder_name}. Create a folder named "{folder_name}" in Google Drive.')

    # Cache for future
    cache['album_id'] = folder['id']
    cache['album_title'] = folder['title']
    cache['cached_at'] = datetime.now().isoformat()
    save_json(ALBUM_CACHE_FILE, cache)

    return folder['id']


def list_folder_photos(folder_id: str = None) -> list[dict]:
    """
    List all image files in a folder.

    Returns list of photo dicts with id, filename, mimeType, creationTime.
    """
    if folder_id is None:
        folder_id = get_folder_id()

    headers = get_auth_headers()
    photos = []
    page_token = None

    while True:
        # Query for image files in the folder
        query = f"'{folder_id}' in parents and mimeType contains 'image/' and trashed=false"
        params = {
            'q': query,
            'fields': 'nextPageToken, files(id, name, mimeType, createdTime, imageMediaMetadata)',
            'pageSize': 100,
            'orderBy': 'createdTime',
        }
        if page_token:
            params['pageToken'] = page_token

        response = get_json(
            f'{GOOGLE_DRIVE_API_BASE}/files',
            headers=headers,
            params=params,
        )

        for item in response.get('files', []):
            metadata = item.get('imageMediaMetadata', {})
            photos.append({
                'id': item.get('id'),
                'filename': item.get('name', ''),
                'mimeType': item.get('mimeType', ''),
                'creationTime': item.get('createdTime', ''),
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


def get_new_photos(folder_id: str = None) -> list[dict]:
    """
    Get photos not yet processed.

    Returns list of new photo dicts, sorted by creation time.
    """
    all_photos = list_folder_photos(folder_id)
    processed = get_processed_photos()

    new_photos = [p for p in all_photos if p['id'] not in processed]

    # Sort by creation time
    new_photos.sort(key=lambda p: p.get('creationTime', ''))

    return new_photos


def group_photos_by_time(photos: list[dict]) -> list[list[dict]]:
    """
    Group photos taken within PHOTO_GROUPING_MINUTES of each other.

    Used to combine multi-page bill photos.
    Returns list of photo groups (each group is a list of photos).
    """
    if not photos:
        return []

    # Sort by creation time
    sorted_photos = sorted(photos, key=lambda p: p.get('creationTime', ''))

    groups = []
    current_group = [sorted_photos[0]]

    for photo in sorted_photos[1:]:
        prev_time = current_group[-1].get('creationTime', '')
        curr_time = photo.get('creationTime', '')

        if prev_time and curr_time:
            try:
                prev_dt = datetime.fromisoformat(prev_time.replace('Z', '+00:00'))
                curr_dt = datetime.fromisoformat(curr_time.replace('Z', '+00:00'))
                diff = (curr_dt - prev_dt).total_seconds() / 60

                if diff <= PHOTO_GROUPING_MINUTES:
                    current_group.append(photo)
                    continue
            except (ValueError, TypeError):
                pass

        # Start new group
        groups.append(current_group)
        current_group = [photo]

    # Don't forget last group
    groups.append(current_group)

    return groups


def download_photo(photo: dict, size: str = 'full') -> bytes:
    """
    Download photo content from Google Drive.

    Args:
        photo: Photo dict with id
        size: Not used for Drive (always downloads full file)

    Returns:
        Image bytes
    """
    import requests

    file_id = photo.get('id')
    if not file_id:
        raise ValueError('Photo has no id')

    headers = get_auth_headers()

    # Use alt=media to download file content
    url = f'{GOOGLE_DRIVE_API_BASE}/files/{file_id}?alt=media'

    response = requests.get(url, headers=headers, timeout=60)

    if response.status_code != 200:
        raise HttpError(f'Failed to download file: HTTP {response.status_code}')

    return response.content


def download_photo_to_file(photo: dict, output_path: Path, size: str = 'full') -> Path:
    """Download photo to file. Returns output path."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    image_data = download_photo(photo, size)

    with open(output_path, 'wb') as f:
        f.write(image_data)

    return output_path


# Aliases for compatibility with existing code expecting google_photos interface
list_albums = list_folders
find_album = find_folder
get_album_id = get_folder_id
list_album_photos = list_folder_photos


if __name__ == '__main__':
    print('Testing google_drive.py')
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

    # Test token health check (without actual tokens)
    health = check_token_health()
    assert health['status'] == 'missing', 'Should be missing without tokens'
    print(f'[OK] Token health check: {health["status"]}')

    print()
    print('API tests require Google OAuth tokens.')
    print('Run authorize_google.py to set up authentication.')

    print('=' * 40)
    print('All tests passed')
