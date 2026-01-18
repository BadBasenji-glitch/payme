#!/usr/bin/env python3
"""Fetch and parse BIC database from Deutsche Bundesbank."""

import argparse
import io
import requests
import sys
import zipfile
from pathlib import Path

from config import BIC_DB_FILE, STORAGE_PATH
from storage import save_json, load_json

# Current Bundesbank BLZ download URL (ZIP containing TXT)
BUNDESBANK_BLZ_ZIP_URL = 'https://www.bundesbank.de/resource/blob/602678/latest/mL/blz-aktuell-txt-zip-data.zip'

# Bundesbank BLZ file format (fixed-width)
# Position 1-8:     Bankleitzahl (BLZ)
# Position 9:       Merkmal (1=Hauptstelle, 2=Nebenstelle)
# Position 10-67:   Bezeichnung (bank name)
# Position 73-107:  Ort (city)
# Position 140-150: BIC


def parse_blz_line(line: str) -> dict | None:
    """
    Parse a single line from the Bundesbank BLZ file.
    Returns None if line should be skipped.
    """
    if len(line) < 150:
        return None

    # Only include main branches (Merkmal = 1)
    merkmal = line[8:9]
    if merkmal != '1':
        return None

    blz = line[0:8].strip()
    if not blz or not blz.isdigit():
        return None

    name = line[9:67].strip()
    city = line[72:107].strip()
    bic = line[139:150].strip()

    if not name:
        return None

    return {
        'blz': blz,
        'name': name,
        'city': city,
        'bic': bic,
    }


def parse_blz_file(content: str) -> dict:
    """
    Parse Bundesbank BLZ file content.
    Returns dict mapping BLZ to bank info.
    """
    result = {}
    lines = content.split('\n')

    for line in lines:
        parsed = parse_blz_line(line)
        if parsed:
            blz = parsed['blz']
            result[blz] = {
                'name': parsed['name'],
                'city': parsed['city'],
                'bic': parsed['bic'],
            }

    return result


def download_blz_file() -> str:
    """Download BLZ ZIP file from Bundesbank and extract TXT. Returns content as string."""
    print('Downloading from Bundesbank...')
    print(f'URL: {BUNDESBANK_BLZ_ZIP_URL}')

    response = requests.get(BUNDESBANK_BLZ_ZIP_URL, timeout=30)
    response.raise_for_status()
    print(f'Downloaded {len(response.content):,} bytes')

    # Extract TXT file from ZIP
    print('Extracting ZIP...')
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        # Find the TXT file in the ZIP (case-insensitive)
        txt_files = [n for n in zf.namelist() if n.lower().endswith('.txt')]
        if not txt_files:
            raise ValueError('No TXT file found in ZIP archive')

        txt_filename = txt_files[0]
        print(f'Found: {txt_filename}')

        # Read and decode (Latin-1 encoding)
        content = zf.read(txt_filename).decode('latin-1')
        print(f'Extracted {len(content):,} characters')

    return content


def read_local_file(path: Path) -> str:
    """Read BLZ file from local path."""
    print(f'Reading from: {path}')

    # Try Latin-1 first (Bundesbank format), fall back to UTF-8
    try:
        content = path.read_text(encoding='latin-1')
    except UnicodeDecodeError:
        content = path.read_text(encoding='utf-8')

    print(f'Read {len(content):,} bytes')
    return content


def update_bic_db(content: str) -> int:
    """
    Parse BLZ content and update BIC database.
    Returns number of entries added.
    """
    print('Parsing BLZ data...')
    bic_data = parse_blz_file(content)
    count = len(bic_data)
    print(f'Found {count:,} banks')

    # Ensure storage directory exists
    STORAGE_PATH.mkdir(parents=True, exist_ok=True)

    # Save to database file
    save_json(BIC_DB_FILE, bic_data)
    print(f'Saved to: {BIC_DB_FILE}')

    return count


def show_stats() -> None:
    """Show statistics about current BIC database."""
    if not BIC_DB_FILE.exists():
        print('BIC database does not exist')
        return

    data = load_json(BIC_DB_FILE, {})
    print(f'BIC database: {BIC_DB_FILE}')
    print(f'Total entries: {len(data):,}')

    # Count entries with BIC
    with_bic = sum(1 for v in data.values() if v.get('bic'))
    print(f'Entries with BIC: {with_bic:,}')

    # Sample entries
    if data:
        print()
        print('Sample entries:')
        for i, (blz, info) in enumerate(list(data.items())[:3]):
            print(f'  {blz}: {info["name"]} ({info["city"]}) - {info["bic"]}')


def main():
    parser = argparse.ArgumentParser(
        description='Update BIC database from Deutsche Bundesbank'
    )
    parser.add_argument(
        '--from-file',
        type=Path,
        help='Read from local file instead of downloading'
    )
    parser.add_argument(
        '--stats',
        action='store_true',
        help='Show statistics about current database'
    )
    args = parser.parse_args()

    print('update_bic_db.py')
    print('=' * 40)

    if args.stats:
        show_stats()
        return

    try:
        if args.from_file:
            content = read_local_file(args.from_file)
        else:
            content = download_blz_file()

        count = update_bic_db(content)
        print('=' * 40)
        print(f'Success: {count:,} banks in database')

    except requests.RequestException as e:
        print(f'Download failed: {e}', file=sys.stderr)
        sys.exit(1)
    except (IOError, OSError) as e:
        print(f'File error: {e}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
