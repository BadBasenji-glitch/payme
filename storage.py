#!/usr/bin/env python3
"""Storage utilities for payme. All JSON file operations."""

import json
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from config import BACKUP_PATH, BACKUP_RETENTION_DAYS


def load_json(path: Path, default: Any = None) -> Any:
    """Load JSON file, return default if not found or invalid."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default if default is not None else {}


def save_json(path: Path, data: Any) -> None:
    """Save data to JSON file atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    
    with NamedTemporaryFile(
        mode='w',
        suffix='.json',
        dir=path.parent,
        delete=False,
        encoding='utf-8'
    ) as tmp:
        json.dump(data, tmp, indent=2, ensure_ascii=False)
        tmp_path = tmp.name
    
    os.replace(tmp_path, path)


def append_to_list(path: Path, item: Any) -> None:
    """Append item to JSON list file."""
    data = load_json(path, [])
    data.append(item)
    save_json(path, data)


def update_dict(path: Path, key: str, value: Any) -> None:
    """Update single key in JSON dict file."""
    data = load_json(path, {})
    data[key] = value
    save_json(path, data)


def remove_from_dict(path: Path, key: str) -> None:
    """Remove key from JSON dict file."""
    data = load_json(path, {})
    data.pop(key, None)
    save_json(path, data)


def backup_file(path: Path) -> Path:
    """Create timestamped backup of file. Returns backup path."""
    if not path.exists():
        return None
    
    BACKUP_PATH.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_name = f'{path.stem}_{timestamp}{path.suffix}'
    backup_path = BACKUP_PATH / backup_name
    
    shutil.copy2(path, backup_path)
    return backup_path


def cleanup_old_backups(prefix: str = None) -> int:
    """Remove backups older than retention period. Returns count removed."""
    if not BACKUP_PATH.exists():
        return 0
    
    cutoff = datetime.now() - timedelta(days=BACKUP_RETENTION_DAYS)
    removed = 0
    
    for backup_file in BACKUP_PATH.iterdir():
        if prefix and not backup_file.stem.startswith(prefix):
            continue
        
        try:
            mtime = datetime.fromtimestamp(backup_file.stat().st_mtime)
            if mtime < cutoff:
                backup_file.unlink()
                removed += 1
        except (OSError, ValueError):
            continue
    
    return removed


def file_exists(path: Path) -> bool:
    """Check if file exists."""
    return path.exists()


def delete_file(path: Path) -> bool:
    """Delete file if exists. Returns True if deleted."""
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


if __name__ == '__main__':
    # Test storage operations
    test_path = Path('/tmp/payme_test.json')
    
    print('Testing storage.py')
    print('=' * 40)
    
    # Test save/load
    test_data = {'key': 'value', 'number': 123, 'list': [1, 2, 3]}
    save_json(test_path, test_data)
    loaded = load_json(test_path)
    assert loaded == test_data, 'Save/load mismatch'
    print('✓ save_json / load_json')
    
    # Test append
    list_path = Path('/tmp/payme_list_test.json')
    delete_file(list_path)
    append_to_list(list_path, {'id': 1})
    append_to_list(list_path, {'id': 2})
    loaded = load_json(list_path)
    assert len(loaded) == 2, 'Append failed'
    print('✓ append_to_list')
    
    # Test update_dict
    dict_path = Path('/tmp/payme_dict_test.json')
    delete_file(dict_path)
    update_dict(dict_path, 'a', 1)
    update_dict(dict_path, 'b', 2)
    loaded = load_json(dict_path)
    assert loaded == {'a': 1, 'b': 2}, 'Update dict failed'
    print('✓ update_dict')
    
    # Test remove_from_dict
    remove_from_dict(dict_path, 'a')
    loaded = load_json(dict_path)
    assert loaded == {'b': 2}, 'Remove from dict failed'
    print('✓ remove_from_dict')
    
    # Test backup
    backup_path = backup_file(test_path)
    assert backup_path and backup_path.exists(), 'Backup failed'
    print(f'✓ backup_file → {backup_path}')
    
    # Test default on missing
    missing = load_json(Path('/tmp/nonexistent.json'), {'default': True})
    assert missing == {'default': True}, 'Default failed'
    print('✓ load_json default')
    
    # Cleanup
    delete_file(test_path)
    delete_file(list_path)
    delete_file(dict_path)
    delete_file(backup_path)
    
    print('=' * 40)
    print('All tests passed')
