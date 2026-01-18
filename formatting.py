#!/usr/bin/env python3
"""Formatting utilities for payme. Currency, dates, display."""

from datetime import datetime
from typing import Union


def format_currency(amount: Union[float, int], currency: str = 'EUR') -> str:
    """Format amount in German style: 1.234,56 €"""
    if currency == 'EUR':
        symbol = '€'
    else:
        symbol = currency
    
    # Format with German separators
    formatted = f'{amount:,.2f}'
    # Swap . and , for German format
    formatted = formatted.replace(',', 'X').replace('.', ',').replace('X', '.')
    
    return f'{formatted} {symbol}'


def parse_currency(text: str) -> tuple[float, str]:
    """Parse German or international currency string. Returns (amount, currency)."""
    text = text.strip()
    
    # Remove currency symbols and determine currency
    currency = 'EUR'
    for symbol, code in [('€', 'EUR'), ('$', 'USD'), ('£', 'GBP'), ('CHF', 'CHF')]:
        if symbol in text:
            currency = code
            text = text.replace(symbol, '')
            break
    
    text = text.strip()
    
    # Detect format by position of . and ,
    if ',' in text and '.' in text:
        if text.rfind(',') > text.rfind('.'):
            # German: 1.234,56
            text = text.replace('.', '').replace(',', '.')
        else:
            # International: 1,234.56
            text = text.replace(',', '')
    elif ',' in text:
        # Could be German decimal or international thousands
        # If exactly 2 digits after comma, treat as decimal
        parts = text.split(',')
        if len(parts) == 2 and len(parts[1]) == 2:
            text = text.replace(',', '.')
        else:
            text = text.replace(',', '')
    
    return float(text), currency


def format_date(dt: Union[datetime, str], include_time: bool = False) -> str:
    """Format datetime in German style: 18.01.2025 or 18.01.2025 14:30"""
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
    
    if include_time:
        return dt.strftime('%d.%m.%Y %H:%M')
    return dt.strftime('%d.%m.%Y')


def parse_date(text: str) -> datetime:
    """Parse common date formats. Returns datetime."""
    text = text.strip()
    
    formats = [
        '%d.%m.%Y',      # German: 18.01.2025
        '%d.%m.%y',      # German short: 18.01.25
        '%Y-%m-%d',      # ISO: 2025-01-18
        '%d/%m/%Y',      # European: 18/01/2025
        '%d-%m-%Y',      # Dash: 18-01-2025
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    
    raise ValueError(f'Cannot parse date: {text}')


def format_iban(iban: str) -> str:
    """Format IBAN with spaces every 4 characters."""
    iban = iban.replace(' ', '').upper()
    return ' '.join(iban[i:i+4] for i in range(0, len(iban), 4))


def truncate(text: str, max_length: int = 50) -> str:
    """Truncate text with ellipsis if too long."""
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + '...'


def format_confidence(score: float) -> str:
    """Format confidence score as percentage."""
    return f'{score * 100:.0f}%'


if __name__ == '__main__':
    print('Testing formatting.py')
    print('=' * 40)
    
    # Currency formatting
    assert format_currency(1234.56) == '1.234,56 €', 'Currency format failed'
    assert format_currency(1000) == '1.000,00 €', 'Currency format 1000 failed'
    assert format_currency(0.99) == '0,99 €', 'Currency format cents failed'
    print('✓ format_currency')
    
    # Currency parsing
    assert parse_currency('1.234,56 €') == (1234.56, 'EUR'), 'Parse German failed'
    assert parse_currency('€1,234.56') == (1234.56, 'EUR'), 'Parse intl failed'
    assert parse_currency('99,00') == (99.0, 'EUR'), 'Parse simple failed'
    print('✓ parse_currency')
    
    # Date formatting
    dt = datetime(2025, 1, 18, 14, 30)
    assert format_date(dt) == '18.01.2025', 'Date format failed'
    assert format_date(dt, include_time=True) == '18.01.2025 14:30', 'DateTime format failed'
    print('✓ format_date')
    
    # Date parsing
    assert parse_date('18.01.2025').day == 18, 'Parse German date failed'
    assert parse_date('2025-01-18').day == 18, 'Parse ISO date failed'
    print('✓ parse_date')
    
    # IBAN formatting
    assert format_iban('DE89370400440532013000') == 'DE89 3704 0044 0532 0130 00', 'IBAN format failed'
    print('✓ format_iban')
    
    # Truncate
    assert truncate('short') == 'short', 'Truncate short failed'
    assert truncate('a' * 60, 50) == 'a' * 47 + '...', 'Truncate long failed'
    print('✓ truncate')
    
    # Confidence
    assert format_confidence(0.95) == '95%', 'Confidence format failed'
    print('✓ format_confidence')
    
    print('=' * 40)
    print('All tests passed')
