#!/usr/bin/env python3
"""GiroCode (EPC QR) detection and parsing for payme."""

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    import cv2
    from pyzbar import pyzbar
    DEPENDENCIES_AVAILABLE = True
except ImportError:
    DEPENDENCIES_AVAILABLE = False


@dataclass
class GiroCodeData:
    """Parsed GiroCode payment data."""
    bic: str
    recipient: str
    iban: str
    amount: float
    currency: str
    reference: str
    text: str
    purpose: str
    raw: str

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            'bic': self.bic,
            'recipient': self.recipient,
            'iban': self.iban,
            'amount': self.amount,
            'currency': self.currency,
            'reference': self.reference,
            'text': self.text,
            'purpose': self.purpose,
        }


def check_dependencies() -> bool:
    """Check if required dependencies are available."""
    return DEPENDENCIES_AVAILABLE


def parse_girocode(data: str) -> Optional[GiroCodeData]:
    """
    Parse EPC QR Code (GiroCode) data.

    EPC QR Code format (lines separated by newline):
    1. Service Tag: BCD
    2. Version: 001 or 002
    3. Character Set: 1 (UTF-8)
    4. Identification: SCT (SEPA Credit Transfer)
    5. BIC (optional in version 002)
    6. Recipient Name
    7. IBAN
    8. Amount: EUR[0-9.]+ (e.g., EUR123.45)
    9. Purpose Code (4 chars, optional)
    10. Reference (structured, optional)
    11. Text (unstructured, optional)
    12. Information (optional)

    Returns GiroCodeData or None if not valid GiroCode.
    """
    if not data:
        return None

    lines = data.strip().split('\n')

    # Must have at least 8 lines for valid GiroCode
    if len(lines) < 8:
        return None

    # Check service tag
    if lines[0].strip() != 'BCD':
        return None

    # Check version (001 or 002)
    version = lines[1].strip()
    if version not in ('001', '002'):
        return None

    # Check character set (1 = UTF-8)
    if lines[2].strip() != '1':
        return None

    # Check identification (SCT = SEPA Credit Transfer)
    if lines[3].strip() != 'SCT':
        return None

    # Parse fields (pad list to avoid index errors)
    while len(lines) < 12:
        lines.append('')

    bic = lines[4].strip()
    recipient = lines[5].strip()
    iban = lines[6].strip().replace(' ', '').upper()

    # Parse amount (format: EUR123.45 or just EUR for zero)
    amount_str = lines[7].strip()
    amount = 0.0
    currency = 'EUR'

    amount_match = re.match(r'^([A-Z]{3})(\d+(?:\.\d{1,2})?)$', amount_str)
    if amount_match:
        currency = amount_match.group(1)
        amount = float(amount_match.group(2))
    elif amount_str.upper() in ('EUR', ''):
        amount = 0.0
    else:
        # Try to extract just numbers
        numbers = re.findall(r'[\d.]+', amount_str)
        if numbers:
            try:
                amount = float(numbers[0])
            except ValueError:
                pass

    purpose = lines[8].strip() if len(lines) > 8 else ''
    reference = lines[9].strip() if len(lines) > 9 else ''
    text = lines[10].strip() if len(lines) > 10 else ''

    # Validation: must have IBAN and recipient
    if not iban or not recipient:
        return None

    return GiroCodeData(
        bic=bic,
        recipient=recipient,
        iban=iban,
        amount=amount,
        currency=currency,
        reference=reference,
        text=text,
        purpose=purpose,
        raw=data,
    )


def decode_qr_codes(image_path: Path) -> list[str]:
    """
    Detect and decode all QR codes in an image.

    Returns list of decoded data strings.
    """
    if not DEPENDENCIES_AVAILABLE:
        raise RuntimeError(
            'QR detection requires pyzbar and opencv-python-headless. '
            'Install with: pip install pyzbar opencv-python-headless'
        )

    # Read image
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError(f'Could not read image: {image_path}')

    # Convert to grayscale for better detection
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Detect QR codes
    codes = pyzbar.decode(gray)

    # Extract data from QR codes only (not barcodes)
    results = []
    for code in codes:
        if code.type == 'QRCODE':
            try:
                data = code.data.decode('utf-8')
                results.append(data)
            except UnicodeDecodeError:
                # Try latin-1 as fallback
                try:
                    data = code.data.decode('latin-1')
                    results.append(data)
                except UnicodeDecodeError:
                    continue

    return results


def extract_girocode(image_path: Path) -> Optional[GiroCodeData]:
    """
    Extract GiroCode payment data from an image.

    Scans image for QR codes and attempts to parse each as GiroCode.
    Returns first valid GiroCode found, or None if none found.
    """
    image_path = Path(image_path)

    if not image_path.exists():
        raise FileNotFoundError(f'Image not found: {image_path}')

    qr_codes = decode_qr_codes(image_path)

    for qr_data in qr_codes:
        girocode = parse_girocode(qr_data)
        if girocode:
            return girocode

    return None


def extract_girocode_from_bytes(image_data: bytes) -> Optional[GiroCodeData]:
    """
    Extract GiroCode from image bytes (for API responses).

    Returns first valid GiroCode found, or None.
    """
    if not DEPENDENCIES_AVAILABLE:
        raise RuntimeError(
            'QR detection requires pyzbar and opencv-python-headless. '
            'Install with: pip install pyzbar opencv-python-headless'
        )

    import numpy as np

    # Decode image from bytes
    image_array = np.frombuffer(image_data, dtype=np.uint8)
    image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)

    if image is None:
        raise ValueError('Could not decode image data')

    # Convert to grayscale
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Detect QR codes
    codes = pyzbar.decode(gray)

    for code in codes:
        if code.type == 'QRCODE':
            try:
                data = code.data.decode('utf-8')
                girocode = parse_girocode(data)
                if girocode:
                    return girocode
            except UnicodeDecodeError:
                continue

    return None


# Sample GiroCode for testing
SAMPLE_GIROCODE = """BCD
002
1
SCT
COBADEFFXXX
Max Mustermann
DE89370400440532013000
EUR123.45

Invoice 12345
Payment for services"""


if __name__ == '__main__':
    print('Testing girocode.py')
    print('=' * 40)

    # Test parsing
    result = parse_girocode(SAMPLE_GIROCODE)
    assert result is not None, 'Failed to parse sample GiroCode'
    assert result.bic == 'COBADEFFXXX', f'Wrong BIC: {result.bic}'
    assert result.recipient == 'Max Mustermann', f'Wrong recipient: {result.recipient}'
    assert result.iban == 'DE89370400440532013000', f'Wrong IBAN: {result.iban}'
    assert result.amount == 123.45, f'Wrong amount: {result.amount}'
    assert result.currency == 'EUR', f'Wrong currency: {result.currency}'
    assert result.reference == 'Invoice 12345', f'Wrong reference: {result.reference}'
    print('[OK] GiroCode parsing')

    # Test to_dict
    data_dict = result.to_dict()
    assert data_dict['iban'] == 'DE89370400440532013000', 'to_dict failed'
    print('[OK] to_dict conversion')

    # Test invalid data
    assert parse_girocode('') is None, 'Empty should return None'
    assert parse_girocode('not a girocode') is None, 'Invalid should return None'
    assert parse_girocode('BCD\n001\n1\nXXX') is None, 'Wrong ID should return None'
    print('[OK] Invalid data handling')

    # Test amount parsing variants
    test_cases = [
        ('EUR100', 100.0),
        ('EUR99.99', 99.99),
        ('EUR0.01', 0.01),
        ('EUR', 0.0),
    ]
    for amount_str, expected in test_cases:
        test_data = f'BCD\n002\n1\nSCT\nBIC\nName\nDE89370400440532013000\n{amount_str}\n\n\n'
        parsed = parse_girocode(test_data)
        assert parsed is not None, f'Failed to parse with amount: {amount_str}'
        assert parsed.amount == expected, f'Wrong amount for {amount_str}: {parsed.amount}'
    print('[OK] Amount parsing variants')

    # Test dependency check
    print(f'[OK] Dependencies available: {check_dependencies()}')

    # Test image extraction if file provided
    if len(sys.argv) > 1:
        image_path = Path(sys.argv[1])
        print()
        print(f'Scanning image: {image_path}')
        print('=' * 40)

        if not check_dependencies():
            print('[ERROR] pyzbar/opencv not installed')
            sys.exit(1)

        try:
            girocode = extract_girocode(image_path)
            if girocode:
                print('GiroCode found:')
                print(f'  Recipient: {girocode.recipient}')
                print(f'  IBAN:      {girocode.iban}')
                print(f'  BIC:       {girocode.bic}')
                print(f'  Amount:    {girocode.amount} {girocode.currency}')
                print(f'  Reference: {girocode.reference}')
                print(f'  Text:      {girocode.text}')
            else:
                print('No GiroCode found in image')
        except Exception as e:
            print(f'[ERROR] {e}')
            sys.exit(1)
    else:
        print()
        print('Usage: python3 girocode.py <image_path>')
        print('  Scans image for GiroCode QR and extracts payment data')

    print('=' * 40)
    print('All tests passed')
