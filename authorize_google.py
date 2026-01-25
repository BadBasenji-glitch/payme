#!/usr/bin/env python3
"""
One-time Google Photos OAuth authorization for payme.

Usage:
    python3 authorize_google.py /path/to/client_secret.json

This script:
1. Reads OAuth client credentials from the provided JSON file
2. Opens a browser for Google sign-in
3. Requests read-only access to Google Photos
4. Saves tokens to the configured storage location

After running, tokens will auto-refresh. Only re-run if tokens become invalid.
"""

import argparse
import json
import sys
import webbrowser
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs

from config import GOOGLE_TOKENS_FILE, STORAGE_PATH
from http_client import post_json, HttpError

# Google OAuth endpoints
GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'

# Scopes for Drive and Gmail access
SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',  # Read files from Drive
    'https://www.googleapis.com/auth/drive.file',      # Upload files to Drive
    'https://www.googleapis.com/auth/gmail.readonly',  # Read Gmail messages
    'https://www.googleapis.com/auth/gmail.modify',    # Mark messages as read
]

# Local callback server
REDIRECT_HOST = 'localhost'
REDIRECT_PORT = 8085
REDIRECT_URI = f'http://{REDIRECT_HOST}:{REDIRECT_PORT}/callback'


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler to receive OAuth callback."""

    authorization_code = None
    error = None

    def do_GET(self):
        """Handle OAuth callback."""
        parsed = urlparse(self.path)

        if parsed.path == '/callback':
            params = parse_qs(parsed.query)

            if 'code' in params:
                OAuthCallbackHandler.authorization_code = params['code'][0]
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                self.wfile.write(b'''
                    <html>
                    <head><title>payme Authorization</title></head>
                    <body style="font-family: sans-serif; text-align: center; padding: 50px;">
                        <h1>&#10004; Authorization Successful</h1>
                        <p>You can close this window and return to the terminal.</p>
                    </body>
                    </html>
                ''')
            elif 'error' in params:
                OAuthCallbackHandler.error = params.get('error_description', params['error'])[0]
                self.send_response(400)
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                error_msg = OAuthCallbackHandler.error
                self.wfile.write(f'''
                    <html>
                    <head><title>payme Authorization Failed</title></head>
                    <body style="font-family: sans-serif; text-align: center; padding: 50px;">
                        <h1>&#10008; Authorization Failed</h1>
                        <p>{error_msg}</p>
                    </body>
                    </html>
                '''.encode())
            else:
                self.send_response(400)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """Suppress HTTP logs."""
        pass


def load_client_credentials(credentials_path: Path) -> dict:
    """
    Load OAuth client credentials from Google Cloud Console JSON file.

    Returns dict with client_id, client_secret.
    """
    with open(credentials_path, 'r') as f:
        data = json.load(f)

    # Handle both "installed" and "web" application types
    if 'installed' in data:
        creds = data['installed']
    elif 'web' in data:
        creds = data['web']
    else:
        raise ValueError('Invalid credentials file format')

    return {
        'client_id': creds['client_id'],
        'client_secret': creds['client_secret'],
    }


def build_auth_url(client_id: str) -> str:
    """Build Google OAuth authorization URL."""
    params = {
        'client_id': client_id,
        'redirect_uri': REDIRECT_URI,
        'response_type': 'code',
        'scope': ' '.join(SCOPES),
        'access_type': 'offline',
        'prompt': 'consent',  # Force consent to get refresh token
    }
    return f'{GOOGLE_AUTH_URL}?{urlencode(params)}'


def exchange_code_for_tokens(code: str, client_id: str, client_secret: str) -> dict:
    """
    Exchange authorization code for access and refresh tokens.

    Returns dict with access_token, refresh_token, expires_in.
    """
    data = {
        'code': code,
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': REDIRECT_URI,
        'grant_type': 'authorization_code',
    }

    # Use requests directly to send form data
    import requests
    response = requests.post(GOOGLE_TOKEN_URL, data=data, timeout=30)
    response.raise_for_status()
    return response.json()


def save_tokens(tokens: dict, client_id: str, client_secret: str) -> Path:
    """
    Save tokens to storage.

    Returns path to saved file.
    """
    STORAGE_PATH.mkdir(parents=True, exist_ok=True)

    # Calculate expiration time
    expires_in = tokens.get('expires_in', 3600)
    expires_at = (datetime.now() + timedelta(seconds=expires_in)).isoformat()

    token_data = {
        'access_token': tokens['access_token'],
        'refresh_token': tokens['refresh_token'],
        'expires_at': expires_at,
        'client_id': client_id,
        'client_secret': client_secret,
        'scopes': SCOPES,
        'created_at': datetime.now().isoformat(),
    }

    with open(GOOGLE_TOKENS_FILE, 'w') as f:
        json.dump(token_data, f, indent=2)

    return GOOGLE_TOKENS_FILE


def run_oauth_flow(credentials_path: Path, manual: bool = False) -> bool:
    """
    Run complete OAuth flow.

    1. Load client credentials
    2. Start local callback server (or manual code entry)
    3. Open browser for authorization
    4. Wait for callback (or paste code)
    5. Exchange code for tokens
    6. Save tokens

    Returns True on success.
    """
    print('Loading client credentials...')
    creds = load_client_credentials(credentials_path)
    client_id = creds['client_id']
    client_secret = creds['client_secret']
    print(f'Client ID: {client_id[:20]}...')

    # Build authorization URL
    auth_url = build_auth_url(client_id)

    if manual:
        # Manual code entry mode
        print('\n' + '='*60)
        print('MANUAL AUTHORIZATION MODE')
        print('='*60)
        print('\n1. Visit this URL in your browser:\n')
        print(auth_url)
        print('\n2. Sign in and authorize the application')
        print('\n3. You will be redirected to a localhost URL that won\'t load.')
        print('   Copy the ENTIRE URL from your browser address bar.')
        print('\n4. Paste the URL here and press Enter:\n')

        redirect_url = input('Paste URL: ').strip()

        # Extract code from URL
        parsed = urlparse(redirect_url)
        params = parse_qs(parsed.query)

        if 'code' not in params:
            print('\nError: No authorization code found in URL')
            print('Make sure you copied the entire URL including ?code=...')
            return False

        code = params['code'][0]
        print('\nAuthorization code extracted!')
    else:
        # Callback server mode
        print(f'\nStarting callback server on {REDIRECT_URI}...')
        server = HTTPServer((REDIRECT_HOST, REDIRECT_PORT), OAuthCallbackHandler)
        server.timeout = 300  # 5 minute timeout

        # Open browser
        print('\nOpening browser for Google authorization...')
        print(f'If browser does not open, visit:\n{auth_url}\n')
        webbrowser.open(auth_url)

        print('Waiting for authorization...')

        # Wait for callback
        OAuthCallbackHandler.authorization_code = None
        OAuthCallbackHandler.error = None

        while OAuthCallbackHandler.authorization_code is None and OAuthCallbackHandler.error is None:
            server.handle_request()

        server.server_close()

        if OAuthCallbackHandler.error:
            print(f'\nAuthorization failed: {OAuthCallbackHandler.error}')
            return False

        code = OAuthCallbackHandler.authorization_code
        print('\nAuthorization code received!')

    # Exchange code for tokens
    print('Exchanging code for tokens...')
    try:
        tokens = exchange_code_for_tokens(code, client_id, client_secret)
    except Exception as e:
        print(f'Token exchange failed: {e}')
        return False

    if 'refresh_token' not in tokens:
        print('Warning: No refresh token received. You may need to revoke access and re-authorize.')
        print('Visit: https://myaccount.google.com/permissions')
        return False

    # Save tokens
    print('Saving tokens...')
    token_path = save_tokens(tokens, client_id, client_secret)

    print(f'\n✓ Authorization complete!')
    print(f'Tokens saved to: {token_path}')
    print('\npayme can now access your Google Photos.')
    print('Tokens will auto-refresh. Only re-run this script if access becomes invalid.')

    return True


def verify_tokens() -> bool:
    """Verify that saved tokens are valid."""
    if not GOOGLE_TOKENS_FILE.exists():
        print(f'No tokens found at: {GOOGLE_TOKENS_FILE}')
        return False

    with open(GOOGLE_TOKENS_FILE, 'r') as f:
        tokens = json.load(f)

    print(f'Token file: {GOOGLE_TOKENS_FILE}')
    print(f'Created: {tokens.get("created_at", "unknown")}')
    print(f'Expires: {tokens.get("expires_at", "unknown")}')
    print(f'Has refresh token: {"refresh_token" in tokens}')
    print(f'Scopes: {", ".join(tokens.get("scopes", []))}')

    # Check if expired
    expires_at = tokens.get('expires_at')
    if expires_at:
        expires_dt = datetime.fromisoformat(expires_at)
        if datetime.now() > expires_dt:
            print('\nAccess token expired (will auto-refresh on next use)')
        else:
            remaining = expires_dt - datetime.now()
            print(f'\nAccess token valid for: {remaining}')

    return 'refresh_token' in tokens


def main():
    parser = argparse.ArgumentParser(
        description='Authorize payme to access Google Photos',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  First-time setup:
    python3 authorize_google.py /path/to/client_secret.json

  Verify existing tokens:
    python3 authorize_google.py --verify

To get client_secret.json:
  1. Go to https://console.cloud.google.com/
  2. Create/select a project
  3. Enable "Photos Library API"
  4. Go to Credentials → Create Credentials → OAuth 2.0 Client ID
  5. Application type: Desktop app
  6. Download the JSON file
        '''
    )

    parser.add_argument(
        'credentials',
        nargs='?',
        type=Path,
        help='Path to client_secret.json from Google Cloud Console',
    )
    parser.add_argument(
        '--verify',
        action='store_true',
        help='Verify existing tokens without re-authorizing',
    )
    parser.add_argument(
        '--manual',
        action='store_true',
        help='Manual mode: paste the redirect URL instead of using callback server (use when running on remote machine like Home Assistant)',
    )

    args = parser.parse_args()

    if args.verify:
        success = verify_tokens()
        sys.exit(0 if success else 1)

    if not args.credentials:
        parser.print_help()
        print('\nError: credentials file required')
        sys.exit(1)

    if not args.credentials.exists():
        print(f'Error: File not found: {args.credentials}')
        sys.exit(1)

    success = run_oauth_flow(args.credentials, manual=args.manual)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
