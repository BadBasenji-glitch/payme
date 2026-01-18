#!/usr/bin/env python3
"""Gemini OCR and bill parsing for payme."""

import base64
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from config import GEMINI_API_BASE, CONFIDENCE_THRESHOLD, get_env
from http_client import post_json, HttpError

# Gemini model for vision tasks
GEMINI_MODEL = 'gemini-1.5-flash'

# Prompt for bill parsing
BILL_PARSE_PROMPT = '''Analyze this bill/invoice image and extract the payment details.

Return a JSON object with these fields:
{
  "recipient": "Name of the company/person to pay",
  "iban": "IBAN bank account number (format: DE89 3704 0044 0532 0130 00)",
  "bic": "BIC/SWIFT code if visible (optional)",
  "amount": 123.45,
  "currency": "EUR",
  "reference": "Payment reference/Verwendungszweck (invoice number, customer number, etc.)",
  "due_date": "Due date if visible (format: YYYY-MM-DD)",
  "invoice_number": "Invoice number if visible",
  "description": "Brief description of what this bill is for (e.g., 'Electricity bill for January 2025')",
  "original_text": "Key text from the bill in the original language",
  "english_translation": "English translation of the key bill content - translate recipient name, description, line items, and any important notes",
  "confidence": {
    "recipient": 0.95,
    "iban": 0.98,
    "amount": 0.99,
    "reference": 0.85
  }
}

Important:
- Extract the IBAN exactly as shown, preserving all digits
- Amount should be a number without currency symbol
- Currency is usually EUR for German bills
- Reference should include invoice number, customer number, or payment purpose
- Confidence scores should be 0.0-1.0 based on how clearly each field was visible
- If a field is not found, set it to null with confidence 0.0
- For German bills, look for "IBAN", "Betrag", "Verwendungszweck", "Rechnungsnummer"
- Provide a helpful English translation of the bill content for non-German speakers

Return ONLY the JSON object, no other text.'''

MULTI_PAGE_PROMPT = '''These images are pages from the same bill/invoice. Analyze all pages together and extract the complete payment details.

Return a JSON object with these fields:
{
  "recipient": "Name of the company/person to pay",
  "iban": "IBAN bank account number",
  "bic": "BIC/SWIFT code if visible (optional)",
  "amount": 123.45,
  "currency": "EUR",
  "reference": "Payment reference/Verwendungszweck",
  "due_date": "Due date if visible (format: YYYY-MM-DD)",
  "invoice_number": "Invoice number if visible",
  "description": "Brief description of what this bill is for",
  "original_text": "Key text from the bill in the original language",
  "english_translation": "English translation of the key bill content - translate recipient name, description, line items, and any important notes",
  "confidence": {
    "recipient": 0.95,
    "iban": 0.98,
    "amount": 0.99,
    "reference": 0.85
  }
}

The payment details (IBAN, amount) are often on the last page or payment slip.
Provide a helpful English translation of the bill content for non-German speakers.
Return ONLY the JSON object, no other text.'''


@dataclass
class ParsedBill:
    """Parsed bill data from Gemini OCR."""
    recipient: str = ''
    iban: str = ''
    bic: str = ''
    amount: float = 0.0
    currency: str = 'EUR'
    description: str = ''
    original_text: str = ''
    english_translation: str = ''
    reference: str = ''
    due_date: str = ''
    invoice_number: str = ''
    confidence: dict = field(default_factory=dict)
    overall_confidence: float = 0.0
    raw_response: str = ''

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            'recipient': self.recipient,
            'iban': self.iban,
            'bic': self.bic,
            'amount': self.amount,
            'currency': self.currency,
            'description': self.description,
            'original_text': self.original_text,
            'english_translation': self.english_translation,
            'reference': self.reference,
            'due_date': self.due_date,
            'invoice_number': self.invoice_number,
            'confidence': self.confidence,
            'overall_confidence': self.overall_confidence,
        }

    def is_high_confidence(self) -> bool:
        """Check if overall confidence meets threshold."""
        return self.overall_confidence >= CONFIDENCE_THRESHOLD

    def get_low_confidence_fields(self) -> list[str]:
        """Get list of fields below confidence threshold."""
        return [
            field for field, score in self.confidence.items()
            if score < CONFIDENCE_THRESHOLD
        ]


def get_api_key() -> str:
    """Get Gemini API key from environment."""
    return get_env('PAYME_GEMINI_API_KEY', required=True)


def encode_image(image_path: Path) -> tuple[str, str]:
    """
    Encode image file as base64.

    Returns (base64_data, mime_type).
    """
    image_path = Path(image_path)

    # Determine MIME type
    suffix = image_path.suffix.lower()
    mime_types = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
    }
    mime_type = mime_types.get(suffix, 'image/jpeg')

    # Read and encode
    with open(image_path, 'rb') as f:
        image_data = f.read()

    base64_data = base64.b64encode(image_data).decode('utf-8')
    return base64_data, mime_type


def encode_image_bytes(image_data: bytes, mime_type: str = 'image/jpeg') -> str:
    """Encode image bytes as base64."""
    return base64.b64encode(image_data).decode('utf-8')


def build_request_body(
    images: list[tuple[str, str]],
    prompt: str,
) -> dict:
    """
    Build Gemini API request body.

    Args:
        images: List of (base64_data, mime_type) tuples
        prompt: Text prompt

    Returns:
        Request body dict
    """
    parts = []

    # Add images
    for base64_data, mime_type in images:
        parts.append({
            'inline_data': {
                'mime_type': mime_type,
                'data': base64_data,
            }
        })

    # Add text prompt
    parts.append({'text': prompt})

    return {
        'contents': [{'parts': parts}],
        'generationConfig': {
            'temperature': 0.1,  # Low temperature for consistent extraction
            'topP': 0.8,
            'maxOutputTokens': 1024,
        }
    }


def call_gemini_api(request_body: dict, api_key: str) -> str:
    """
    Call Gemini API and return response text.

    Raises HttpError on API failure.
    """
    url = f'{GEMINI_API_BASE}/models/{GEMINI_MODEL}:generateContent'

    response = post_json(
        url,
        headers={'Content-Type': 'application/json'},
        json={**request_body, 'key': api_key},
        timeout=60,  # Longer timeout for vision tasks
    )

    # Extract text from response
    try:
        candidates = response.get('candidates', [])
        if not candidates:
            raise HttpError('No response from Gemini')

        content = candidates[0].get('content', {})
        parts = content.get('parts', [])
        if not parts:
            raise HttpError('Empty response from Gemini')

        return parts[0].get('text', '')
    except (KeyError, IndexError) as e:
        raise HttpError(f'Invalid Gemini response format: {e}')


def parse_gemini_response(response_text: str) -> ParsedBill:
    """
    Parse Gemini response text into ParsedBill.

    Handles JSON extraction from potentially messy response.
    """
    result = ParsedBill(raw_response=response_text)

    # Try to extract JSON from response
    json_match = re.search(r'\{[\s\S]*\}', response_text)
    if not json_match:
        return result

    try:
        data = json.loads(json_match.group())
    except json.JSONDecodeError:
        return result

    # Extract fields
    result.recipient = str(data.get('recipient', '') or '')
    result.iban = str(data.get('iban', '') or '').replace(' ', '').upper()
    result.bic = str(data.get('bic', '') or '').upper()
    result.reference = str(data.get('reference', '') or '')
    result.due_date = str(data.get('due_date', '') or '')
    result.invoice_number = str(data.get('invoice_number', '') or '')
    result.currency = str(data.get('currency', 'EUR') or 'EUR').upper()
    result.description = str(data.get('description', '') or '')
    result.original_text = str(data.get('original_text', '') or '')
    result.english_translation = str(data.get('english_translation', '') or '')

    # Parse amount
    amount = data.get('amount')
    if amount is not None:
        try:
            result.amount = float(amount)
        except (ValueError, TypeError):
            result.amount = 0.0

    # Parse confidence scores
    confidence = data.get('confidence', {})
    if isinstance(confidence, dict):
        result.confidence = {
            k: float(v) for k, v in confidence.items()
            if isinstance(v, (int, float))
        }

    # Calculate overall confidence (average of key fields)
    key_fields = ['recipient', 'iban', 'amount', 'reference']
    scores = [result.confidence.get(f, 0.0) for f in key_fields]
    if scores:
        result.overall_confidence = sum(scores) / len(scores)

    return result


def parse_bill_image(image_path: Path, api_key: str = None) -> ParsedBill:
    """
    Parse a single bill image using Gemini OCR.

    Args:
        image_path: Path to bill image
        api_key: Optional API key (uses env if not provided)

    Returns:
        ParsedBill with extracted data
    """
    if api_key is None:
        api_key = get_api_key()

    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f'Image not found: {image_path}')

    # Encode image
    base64_data, mime_type = encode_image(image_path)

    # Build and send request
    request_body = build_request_body(
        images=[(base64_data, mime_type)],
        prompt=BILL_PARSE_PROMPT,
    )

    response_text = call_gemini_api(request_body, api_key)
    return parse_gemini_response(response_text)


def parse_bill_images(image_paths: list[Path], api_key: str = None) -> ParsedBill:
    """
    Parse multiple bill images (multi-page bill) using Gemini OCR.

    Args:
        image_paths: List of paths to bill images
        api_key: Optional API key (uses env if not provided)

    Returns:
        ParsedBill with extracted data from all pages
    """
    if api_key is None:
        api_key = get_api_key()

    if not image_paths:
        raise ValueError('No images provided')

    if len(image_paths) == 1:
        return parse_bill_image(image_paths[0], api_key)

    # Encode all images
    images = []
    for path in image_paths:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f'Image not found: {path}')
        images.append(encode_image(path))

    # Build and send request
    request_body = build_request_body(
        images=images,
        prompt=MULTI_PAGE_PROMPT,
    )

    response_text = call_gemini_api(request_body, api_key)
    return parse_gemini_response(response_text)


def parse_bill_bytes(
    image_data: bytes,
    mime_type: str = 'image/jpeg',
    api_key: str = None,
) -> ParsedBill:
    """
    Parse bill from image bytes.

    Args:
        image_data: Raw image bytes
        mime_type: Image MIME type
        api_key: Optional API key

    Returns:
        ParsedBill with extracted data
    """
    if api_key is None:
        api_key = get_api_key()

    base64_data = encode_image_bytes(image_data, mime_type)

    request_body = build_request_body(
        images=[(base64_data, mime_type)],
        prompt=BILL_PARSE_PROMPT,
    )

    response_text = call_gemini_api(request_body, api_key)
    return parse_gemini_response(response_text)


if __name__ == '__main__':
    import sys

    print('Testing gemini.py')
    print('=' * 40)

    # Test response parsing
    sample_response = '''```json
{
  "recipient": "Stadtwerke München",
  "iban": "DE89 3704 0044 0532 0130 00",
  "bic": "COBADEFFXXX",
  "amount": 156.78,
  "currency": "EUR",
  "reference": "Kundennr. 12345678 Rechnungsnr. 2024-001",
  "due_date": "2024-02-15",
  "invoice_number": "2024-001",
  "confidence": {
    "recipient": 0.95,
    "iban": 0.98,
    "amount": 0.99,
    "reference": 0.88
  }
}
```'''

    result = parse_gemini_response(sample_response)
    assert result.recipient == 'Stadtwerke München', f'Wrong recipient: {result.recipient}'
    assert result.iban == 'DE89370400440532013000', f'Wrong IBAN: {result.iban}'
    assert result.amount == 156.78, f'Wrong amount: {result.amount}'
    assert result.currency == 'EUR', f'Wrong currency: {result.currency}'
    assert result.bic == 'COBADEFFXXX', f'Wrong BIC: {result.bic}'
    assert 0.9 < result.overall_confidence < 1.0, f'Wrong confidence: {result.overall_confidence}'
    print('[OK] Response parsing')

    # Test to_dict
    data_dict = result.to_dict()
    assert data_dict['iban'] == 'DE89370400440532013000', 'to_dict failed'
    print('[OK] to_dict conversion')

    # Test confidence methods
    assert result.is_high_confidence(), 'Should be high confidence'
    low_fields = result.get_low_confidence_fields()
    assert 'reference' in low_fields, 'Reference should be low confidence'
    print('[OK] Confidence methods')

    # Test empty/invalid response handling
    empty_result = parse_gemini_response('')
    assert empty_result.recipient == '', 'Empty should return empty fields'
    assert empty_result.overall_confidence == 0.0, 'Empty should have 0 confidence'
    print('[OK] Empty response handling')

    invalid_result = parse_gemini_response('This is not JSON at all')
    assert invalid_result.amount == 0.0, 'Invalid should return defaults'
    print('[OK] Invalid response handling')

    # Test image encoding (if file provided)
    if len(sys.argv) > 1:
        image_path = Path(sys.argv[1])
        print()
        print(f'Parsing bill: {image_path}')
        print('=' * 40)

        try:
            bill = parse_bill_image(image_path)
            print(f'Recipient:   {bill.recipient}')
            print(f'IBAN:        {bill.iban}')
            print(f'BIC:         {bill.bic}')
            print(f'Amount:      {bill.amount} {bill.currency}')
            print(f'Reference:   {bill.reference}')
            print(f'Due date:    {bill.due_date}')
            print(f'Invoice #:   {bill.invoice_number}')
            print(f'Confidence:  {bill.overall_confidence:.0%}')
            if not bill.is_high_confidence():
                print(f'Low fields:  {", ".join(bill.get_low_confidence_fields())}')
        except Exception as e:
            print(f'[ERROR] {e}')
    else:
        print()
        print('Usage: python3 gemini.py <image_path>')
        print('  Parses bill image using Gemini OCR')
        print('  Requires PAYME_GEMINI_API_KEY environment variable')

    print('=' * 40)
    print('All tests passed')
