#!/usr/bin/env python3
"""
Keyword Manager - Centralized management for all discovery source keywords.

Manages keyword files for filtering across all discovery sources:
- Shared keywords (anti-keywords, positive hints)
- Source-specific keywords (YP categories, Google domains, etc.)

Features:
- Thread-safe file operations
- Automatic backups before changes
- Validation and duplicate detection
- Change history tracking
- Hot reload support
"""

import os
import shutil
from pathlib import Path
from typing import List, Set, Dict, Optional, Tuple
from datetime import datetime
from threading import Lock
from dataclasses import dataclass, field


@dataclass
class KeywordFile:
    """Represents a keyword file configuration."""
    name: str
    path: str
    description: str
    source: str  # 'shared', 'google', 'yp', 'bing'
    file_type: str  # 'anti_keywords', 'positive_hints', 'allowlist', 'blocklist', 'domains'
    editable: bool = True
    keywords: Set[str] = field(default_factory=set)
    last_modified: Optional[datetime] = None
    line_count: int = 0


class KeywordManager:
    """
    Centralized manager for all keyword files used in discovery source filtering.
    """

    def __init__(self, data_dir: str = 'data'):
        """
        Initialize KeywordManager.

        Args:
            data_dir: Base directory for keyword files
        """
        self.data_dir = Path(data_dir)
        self.backup_dir = self.data_dir / 'backups'
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        # Thread safety for file operations
        self._lock = Lock()

        # Define all keyword files
        self.files: Dict[str, KeywordFile] = {
            # Shared keywords (used by all sources)
            'shared_anti_keywords': KeywordFile(
                name='Anti-Keywords (Shared)',
                path=str(self.data_dir / 'anti_keywords.txt'),
                description='Keywords that filter out unwanted businesses (equipment sellers, training, franchises, etc.)',
                source='shared',
                file_type='anti_keywords'
            ),
            'shared_positive_hints': KeywordFile(
                name='Positive Hints (Shared)',
                path=str(self.data_dir / 'yp_positive_hints.txt'),
                description='Keywords that boost confidence for target businesses (pressure washing, soft wash, etc.)',
                source='shared',
                file_type='positive_hints'
            ),

            # YP-specific keywords
            'yp_category_allowlist': KeywordFile(
                name='YP Category Allowlist',
                path=str(self.data_dir / 'yp_category_allowlist.txt'),
                description='Yellow Pages categories to include in results',
                source='yp',
                file_type='allowlist'
            ),
            'yp_category_blocklist': KeywordFile(
                name='YP Category Blocklist',
                path=str(self.data_dir / 'yp_category_blocklist.txt'),
                description='Yellow Pages categories to exclude from results',
                source='yp',
                file_type='blocklist'
            ),
            'yp_anti_keywords': KeywordFile(
                name='YP Anti-Keywords',
                path=str(self.data_dir / 'yp_anti_keywords.txt'),
                description='YP-specific anti-keywords (currently unused)',
                source='yp',
                file_type='anti_keywords',
                editable=True
            ),
        }

        # Load all files
        self.load_all()

    def load_all(self) -> None:
        """Load all keyword files from disk."""
        for file_id, kw_file in self.files.items():
            self._load_file(kw_file)

    def _load_file(self, kw_file: KeywordFile) -> None:
        """
        Load a single keyword file.

        Args:
            kw_file: KeywordFile to load
        """
        path = Path(kw_file.path)

        if not path.exists():
            kw_file.keywords = set()
            kw_file.line_count = 0
            kw_file.last_modified = None
            return

        with self._lock:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    lines = [line.strip() for line in f if line.strip()]
                    kw_file.keywords = set(lines)
                    kw_file.line_count = len(lines)

                # Get file modification time
                stat = path.stat()
                kw_file.last_modified = datetime.fromtimestamp(stat.st_mtime)

            except Exception as e:
                print(f"Error loading {kw_file.name}: {e}")
                kw_file.keywords = set()
                kw_file.line_count = 0

    def _save_file(self, kw_file: KeywordFile, create_backup: bool = True) -> bool:
        """
        Save a keyword file to disk.

        Args:
            kw_file: KeywordFile to save
            create_backup: Whether to create a backup before saving

        Returns:
            True if successful, False otherwise
        """
        path = Path(kw_file.path)

        with self._lock:
            try:
                # Create backup if file exists
                if create_backup and path.exists():
                    self._create_backup(kw_file)

                # Sort keywords for consistency
                sorted_keywords = sorted(kw_file.keywords, key=str.lower)

                # Write to temporary file first (atomic write)
                temp_path = path.with_suffix('.tmp')
                with open(temp_path, 'w', encoding='utf-8') as f:
                    for keyword in sorted_keywords:
                        f.write(f"{keyword}\n")

                # Move temp file to actual file (atomic operation)
                temp_path.replace(path)

                # Update metadata
                kw_file.line_count = len(sorted_keywords)
                stat = path.stat()
                kw_file.last_modified = datetime.fromtimestamp(stat.st_mtime)

                return True

            except Exception as e:
                print(f"Error saving {kw_file.name}: {e}")
                return False

    def _create_backup(self, kw_file: KeywordFile) -> None:
        """
        Create a timestamped backup of a keyword file.

        Args:
            kw_file: KeywordFile to backup
        """
        path = Path(kw_file.path)
        if not path.exists():
            return

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f"{path.stem}_{timestamp}{path.suffix}"
        backup_path = self.backup_dir / backup_name

        try:
            shutil.copy2(path, backup_path)

            # Keep only last 10 backups per file
            self._cleanup_old_backups(path.stem, keep=10)

        except Exception as e:
            print(f"Error creating backup for {kw_file.name}: {e}")

    def _cleanup_old_backups(self, file_stem: str, keep: int = 10) -> None:
        """
        Remove old backup files, keeping only the most recent ones.

        Args:
            file_stem: Base filename to match backups
            keep: Number of backups to keep
        """
        pattern = f"{file_stem}_*.txt"
        backups = sorted(self.backup_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)

        # Remove old backups
        for backup in backups[keep:]:
            try:
                backup.unlink()
            except Exception as e:
                print(f"Error removing old backup {backup}: {e}")

    def get_keywords(self, file_id: str) -> List[str]:
        """
        Get keywords from a file.

        Args:
            file_id: File identifier

        Returns:
            Sorted list of keywords
        """
        if file_id not in self.files:
            return []

        return sorted(self.files[file_id].keywords, key=str.lower)

    def add_keyword(self, file_id: str, keyword: str) -> Tuple[bool, str]:
        """
        Add a keyword to a file.

        Args:
            file_id: File identifier
            keyword: Keyword to add

        Returns:
            Tuple of (success, message)
        """
        if file_id not in self.files:
            return False, f"File '{file_id}' not found"

        kw_file = self.files[file_id]

        if not kw_file.editable:
            return False, f"{kw_file.name} is not editable"

        # Normalize keyword
        keyword = keyword.strip().lower()

        if not keyword:
            return False, "Keyword cannot be empty"

        if keyword in kw_file.keywords:
            return False, f"Keyword '{keyword}' already exists"

        # Add keyword
        kw_file.keywords.add(keyword)

        # Save to file
        if self._save_file(kw_file):
            return True, f"Added '{keyword}' to {kw_file.name}"
        else:
            kw_file.keywords.remove(keyword)  # Rollback
            return False, "Failed to save file"

    def remove_keyword(self, file_id: str, keyword: str) -> Tuple[bool, str]:
        """
        Remove a keyword from a file.

        Args:
            file_id: File identifier
            keyword: Keyword to remove

        Returns:
            Tuple of (success, message)
        """
        if file_id not in self.files:
            return False, f"File '{file_id}' not found"

        kw_file = self.files[file_id]

        if not kw_file.editable:
            return False, f"{kw_file.name} is not editable"

        keyword = keyword.strip().lower()

        if keyword not in kw_file.keywords:
            return False, f"Keyword '{keyword}' not found"

        # Remove keyword
        kw_file.keywords.remove(keyword)

        # Save to file
        if self._save_file(kw_file):
            return True, f"Removed '{keyword}' from {kw_file.name}"
        else:
            kw_file.keywords.add(keyword)  # Rollback
            return False, "Failed to save file"

    def update_keywords(self, file_id: str, keywords: List[str]) -> Tuple[bool, str]:
        """
        Replace all keywords in a file.

        Args:
            file_id: File identifier
            keywords: New list of keywords

        Returns:
            Tuple of (success, message)
        """
        if file_id not in self.files:
            return False, f"File '{file_id}' not found"

        kw_file = self.files[file_id]

        if not kw_file.editable:
            return False, f"{kw_file.name} is not editable"

        # Normalize and validate
        normalized = set()
        for kw in keywords:
            kw = kw.strip().lower()
            if kw:
                normalized.add(kw)

        # Backup current keywords
        old_keywords = kw_file.keywords.copy()

        # Update keywords
        kw_file.keywords = normalized

        # Save to file
        if self._save_file(kw_file):
            return True, f"Updated {kw_file.name} with {len(normalized)} keywords"
        else:
            kw_file.keywords = old_keywords  # Rollback
            return False, "Failed to save file"

    def search_keywords(self, file_id: str, query: str) -> List[str]:
        """
        Search for keywords matching a query.

        Args:
            file_id: File identifier
            query: Search query

        Returns:
            List of matching keywords
        """
        if file_id not in self.files:
            return []

        query_lower = query.lower()
        keywords = self.files[file_id].keywords

        return sorted([kw for kw in keywords if query_lower in kw], key=str.lower)

    def get_file_info(self, file_id: str) -> Optional[Dict]:
        """
        Get metadata about a keyword file.

        Args:
            file_id: File identifier

        Returns:
            Dictionary with file information
        """
        if file_id not in self.files:
            return None

        kw_file = self.files[file_id]

        return {
            'name': kw_file.name,
            'description': kw_file.description,
            'source': kw_file.source,
            'file_type': kw_file.file_type,
            'path': kw_file.path,
            'editable': kw_file.editable,
            'count': len(kw_file.keywords),
            'last_modified': kw_file.last_modified.isoformat() if kw_file.last_modified else None
        }

    def get_all_files_by_source(self) -> Dict[str, List[Dict]]:
        """
        Get all keyword files grouped by source.

        Returns:
            Dictionary mapping source to list of file info
        """
        by_source = {'shared': [], 'google': [], 'yp': [], 'bing': []}

        for file_id, kw_file in self.files.items():
            info = self.get_file_info(file_id)
            if info:
                by_source[kw_file.source].append({**info, 'file_id': file_id})

        return by_source

    def reload_all(self) -> None:
        """Reload all keyword files from disk (for hot reload)."""
        self.load_all()

    def export_to_dict(self, file_id: str) -> Optional[Dict]:
        """
        Export keyword file data as dictionary.

        Args:
            file_id: File identifier

        Returns:
            Dictionary with file data
        """
        if file_id not in self.files:
            return None

        kw_file = self.files[file_id]

        return {
            'metadata': self.get_file_info(file_id),
            'keywords': sorted(kw_file.keywords, key=str.lower)
        }

    def import_from_text(self, file_id: str, text: str, merge: bool = False) -> Tuple[bool, str]:
        """
        Import keywords from text (one per line).

        Args:
            file_id: File identifier
            text: Text containing keywords (one per line)
            merge: If True, merge with existing keywords; if False, replace

        Returns:
            Tuple of (success, message)
        """
        if file_id not in self.files:
            return False, f"File '{file_id}' not found"

        # Parse keywords from text
        new_keywords = set()
        for line in text.split('\n'):
            kw = line.strip().lower()
            if kw:
                new_keywords.add(kw)

        if not new_keywords:
            return False, "No valid keywords found in text"

        if merge:
            # Merge with existing
            existing = self.files[file_id].keywords
            combined = existing | new_keywords
            added = len(combined) - len(existing)

            success, msg = self.update_keywords(file_id, list(combined))
            if success:
                return True, f"Added {added} new keywords (total: {len(combined)})"
            return False, msg
        else:
            # Replace all
            return self.update_keywords(file_id, list(new_keywords))


# Global instance
keyword_manager = KeywordManager()


if __name__ == "__main__":
    # Quick test
    manager = KeywordManager()

    print("\n=== Keyword Files by Source ===")
    by_source = manager.get_all_files_by_source()

    for source, files in by_source.items():
        if files:
            print(f"\n{source.upper()}:")
            for file_info in files:
                print(f"  - {file_info['name']}: {file_info['count']} keywords")

    print("\n=== Shared Anti-Keywords (first 10) ===")
    anti_keywords = manager.get_keywords('shared_anti_keywords')[:10]
    for kw in anti_keywords:
        print(f"  - {kw}")
