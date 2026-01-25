#!/usr/bin/env python3
"""Configuration loader for payme. All config from environment variables."""

import os
from pathlib import Path

# Paths
HA_CONFIG_PATH = Path('/config')
STORAGE_PATH = HA_CONFIG_PATH / '.storage' / 'payme'
BACKUP_PATH = HA_CONFIG_PATH / 'backups' / 'payme'
SCRIPTS_PATH = HA_CONFIG_PATH / 'scripts' / 'payme'

# Storage files
GOOGLE_TOKENS_FILE = STORAGE_PATH / 'google_tokens.json'
ALBUM_CACHE_FILE = STORAGE_PATH / 'album_cache.json'
PROCESSED_PHOTOS_FILE = STORAGE_PATH / 'processed_photos.json'
PROCESSED_EMAILS_FILE = STORAGE_PATH / 'processed_emails.json'
PAYMENT_HASHES_FILE = STORAGE_PATH / 'payment_hashes.json'
PAYMENT_HISTORY_FILE = STORAGE_PATH / 'payment_history.json'
BIC_DB_FILE = STORAGE_PATH / 'bic_db.json'
BIC_CACHE_FILE = STORAGE_PATH / 'bic_cache.json'

# Gmail settings
GMAIL_LABEL = 'bill-pay-HA'  # Label to filter emails for processing

# Constants
POLLING_INTERVAL_MINUTES = 30
BACKUP_RETENTION_DAYS = 7
DUPLICATE_WINDOW_DAYS = 90
PHOTO_GROUPING_MINUTES = 5
WISE_API_DELAY_SECONDS = 2
HTTP_TIMEOUT_SECONDS = 30
HTTP_RETRY_ATTEMPTS = 3
CONFIDENCE_THRESHOLD = 0.9

# API endpoints
WISE_API_BASE = 'https://api.wise.com'
GEMINI_API_BASE = 'https://generativelanguage.googleapis.com/v1beta'
GOOGLE_PHOTOS_API_BASE = 'https://photoslibrary.googleapis.com/v1'
OPENIBAN_API_BASE = 'https://openiban.com/validate'
BUNDESBANK_BLZ_URL = 'https://www.bundesbank.de/resource/blob/602848/bba34a4e629304a37cf9a553c47af782/mL/blz-2024-06-03-txt-data.txt'

# Wise status mapping: Wise API status -> payme internal status
# Wise statuses: incoming_payment_waiting, processing, waiting_for_authorization,
#                outgoing_payment_sent, funds_converted, cancelled, funds_refunded, bounced_back
WISE_STATUS_MAP = {
    'outgoing_payment_sent': 'paid',
    'funds_converted': 'paid',
    'waiting_for_authorization': 'awaiting_2fa',
    'cancelled': 'failed',
    'funds_refunded': 'failed',
    'bounced_back': 'failed',
    'incoming_payment_waiting': 'awaiting_funding',
    'processing': 'processing',
}

# Grouped status sets for Transfer class properties
WISE_COMPLETE_STATUSES = {'outgoing_payment_sent', 'funds_converted'}
WISE_PENDING_STATUSES = {'incoming_payment_waiting', 'processing', 'waiting_for_authorization'}
WISE_FAILED_STATUSES = {'cancelled', 'funds_refunded', 'bounced_back'}


def get_env(key: str, default: str = None, required: bool = False) -> str:
    """Get environment variable with optional default."""
    value = os.environ.get(key, default)
    if required and not value:
        raise EnvironmentError(f'Required environment variable {key} not set')
    return value


def get_secrets() -> dict:
    """Load all secrets from environment variables."""
    return {
        'gemini_api_key': get_env('PAYME_GEMINI_API_KEY', required=True),
        'wise_api_token': get_env('PAYME_WISE_API_TOKEN', required=True),
        'wise_profile_id': get_env('PAYME_WISE_PROFILE_ID', required=True),
        'album_name': get_env('PAYME_ALBUM_NAME', 'bill-pay'),
        'album_id': get_env('PAYME_ALBUM_ID', ''),
    }


def ensure_directories() -> None:
    """Create required directories if they don't exist."""
    STORAGE_PATH.mkdir(parents=True, exist_ok=True)
    BACKUP_PATH.mkdir(parents=True, exist_ok=True)


def print_config() -> None:
    """Print non-secret configuration for verification."""
    print('payme configuration')
    print('=' * 40)
    print(f'HA config path:     {HA_CONFIG_PATH}')
    print(f'Storage path:       {STORAGE_PATH}')
    print(f'Backup path:        {BACKUP_PATH}')
    print(f'Polling interval:   {POLLING_INTERVAL_MINUTES} minutes')
    print(f'Backup retention:   {BACKUP_RETENTION_DAYS} days')
    print(f'Duplicate window:   {DUPLICATE_WINDOW_DAYS} days')
    print(f'Photo grouping:     {PHOTO_GROUPING_MINUTES} minutes')
    print(f'Confidence threshold: {CONFIDENCE_THRESHOLD}')
    print('=' * 40)
    print('Storage files:')
    for name, path in [
        ('Google tokens', GOOGLE_TOKENS_FILE),
        ('Album cache', ALBUM_CACHE_FILE),
        ('Processed photos', PROCESSED_PHOTOS_FILE),
        ('Payment hashes', PAYMENT_HASHES_FILE),
        ('Payment history', PAYMENT_HISTORY_FILE),
        ('BIC database', BIC_DB_FILE),
        ('BIC cache', BIC_CACHE_FILE),
    ]:
        exists = '✓' if path.exists() else '✗'
        print(f'  {exists} {name}: {path}')


if __name__ == '__main__':
    print_config()
