#!/usr/bin/env python3
"""
Category Manager - Manage Google Maps search categories.

Manages the categories.csv file that defines what categories Google Maps
crawler will search for.
"""

import csv
import shutil
from pathlib import Path
from typing import List, Dict, Tuple
from datetime import datetime
from threading import Lock


class CategoryManager:
    """
    Manager for Google Maps search categories (categories.csv).
    """

    def __init__(self, csv_path: str = 'scrape_google/categories.csv'):
        """
        Initialize CategoryManager.

        Args:
            csv_path: Path to categories CSV file
        """
        self.csv_path = Path(csv_path)
        self.backup_dir = self.csv_path.parent / 'backups'
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        # Thread safety
        self._lock = Lock()

        # Loaded categories
        self.categories: List[Dict[str, str]] = []

        # Load categories
        self.load()

    def load(self) -> None:
        """Load categories from CSV file."""
        with self._lock:
            self.categories = []

            if not self.csv_path.exists():
                return

            try:
                with open(self.csv_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if row.get('label'):  # Skip empty rows
                            self.categories.append({
                                'label': row['label'].strip(),
                                'keyword': row['keyword'].strip(),
                                'source': row.get('source', 'google').strip()
                            })
            except Exception as e:
                print(f"Error loading categories: {e}")
                self.categories = []

    def save(self, create_backup: bool = True) -> Tuple[bool, str]:
        """
        Save categories to CSV file.

        Args:
            create_backup: Whether to create a backup before saving

        Returns:
            Tuple of (success, message)
        """
        with self._lock:
            try:
                # Create backup
                if create_backup and self.csv_path.exists():
                    self._create_backup()

                # Write to temp file first
                temp_path = self.csv_path.with_suffix('.tmp')
                with open(temp_path, 'w', encoding='utf-8', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=['label', 'keyword', 'source'])
                    writer.writeheader()

                    # Sort by source, then label
                    sorted_cats = sorted(self.categories, key=lambda x: (x['source'], x['label']))
                    writer.writerows(sorted_cats)

                # Move temp to actual file (atomic)
                temp_path.replace(self.csv_path)

                return True, "Categories saved successfully"

            except Exception as e:
                return False, f"Failed to save: {str(e)}"

    def _create_backup(self) -> None:
        """Create a timestamped backup of the CSV file."""
        if not self.csv_path.exists():
            return

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f"{self.csv_path.stem}_{timestamp}{self.csv_path.suffix}"
        backup_path = self.backup_dir / backup_name

        try:
            shutil.copy2(self.csv_path, backup_path)

            # Keep only last 10 backups
            self._cleanup_old_backups(keep=10)

        except Exception as e:
            print(f"Error creating backup: {e}")

    def _cleanup_old_backups(self, keep: int = 10) -> None:
        """Remove old backup files."""
        pattern = f"{self.csv_path.stem}_*.csv"
        backups = sorted(self.backup_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)

        for backup in backups[keep:]:
            try:
                backup.unlink()
            except Exception as e:
                print(f"Error removing backup {backup}: {e}")

    def get_categories(self, source: str = None) -> List[Dict[str, str]]:
        """
        Get categories, optionally filtered by source.

        Args:
            source: Filter by source ('google', 'yp', or None for all)

        Returns:
            List of category dicts
        """
        if source:
            return [cat for cat in self.categories if cat['source'] == source]
        return self.categories.copy()

    def add_category(self, label: str, keyword: str, source: str = 'google') -> Tuple[bool, str]:
        """
        Add a new category.

        Args:
            label: Category label
            keyword: Search keyword
            source: Source ('google' or 'yp')

        Returns:
            Tuple of (success, message)
        """
        label = label.strip()
        keyword = keyword.strip()
        source = source.strip().lower()

        # Validation
        if not label or not keyword:
            return False, "Label and keyword cannot be empty"

        if source not in ['google', 'yp']:
            return False, "Source must be 'google' or 'yp'"

        # Check for duplicate label
        if any(cat['label'].lower() == label.lower() for cat in self.categories):
            return False, f"Category '{label}' already exists"

        # Add category
        self.categories.append({
            'label': label,
            'keyword': keyword,
            'source': source
        })

        # Save
        success, msg = self.save()
        if success:
            return True, f"Added category '{label}'"
        else:
            # Rollback
            self.categories.pop()
            return False, msg

    def remove_category(self, label: str) -> Tuple[bool, str]:
        """
        Remove a category by label.

        Args:
            label: Category label to remove

        Returns:
            Tuple of (success, message)
        """
        # Find category
        for i, cat in enumerate(self.categories):
            if cat['label'] == label:
                # Remove
                removed = self.categories.pop(i)

                # Save
                success, msg = self.save()
                if success:
                    return True, f"Removed category '{label}'"
                else:
                    # Rollback
                    self.categories.insert(i, removed)
                    return False, msg

        return False, f"Category '{label}' not found"

    def update_category(self, old_label: str, new_label: str, keyword: str, source: str) -> Tuple[bool, str]:
        """
        Update an existing category.

        Args:
            old_label: Current label
            new_label: New label
            keyword: New keyword
            source: New source

        Returns:
            Tuple of (success, message)
        """
        # Find category
        for cat in self.categories:
            if cat['label'] == old_label:
                # Backup old values
                old_values = cat.copy()

                # Update
                cat['label'] = new_label.strip()
                cat['keyword'] = keyword.strip()
                cat['source'] = source.strip().lower()

                # Save
                success, msg = self.save()
                if success:
                    return True, f"Updated category '{old_label}'"
                else:
                    # Rollback
                    cat.update(old_values)
                    return False, msg

        return False, f"Category '{old_label}' not found"

    def get_stats(self) -> Dict:
        """
        Get statistics about categories.

        Returns:
            Dictionary with stats
        """
        google_cats = [c for c in self.categories if c['source'] == 'google']
        yp_cats = [c for c in self.categories if c['source'] == 'yp']

        return {
            'total': len(self.categories),
            'google': len(google_cats),
            'yp': len(yp_cats),
            'avg_keyword_length': sum(len(c['keyword']) for c in self.categories) / len(self.categories) if self.categories else 0
        }

    def export_to_list(self) -> List[List[str]]:
        """
        Export categories as list of lists (for table display).

        Returns:
            List of [label, keyword, source] rows
        """
        return [[cat['label'], cat['keyword'], cat['source']] for cat in self.categories]

    def import_from_csv_text(self, csv_text: str, merge: bool = False) -> Tuple[bool, str]:
        """
        Import categories from CSV text.

        Args:
            csv_text: CSV formatted text
            merge: If True, merge; if False, replace

        Returns:
            Tuple of (success, message)
        """
        try:
            # Parse CSV
            lines = csv_text.strip().split('\n')
            reader = csv.DictReader(lines)

            new_categories = []
            for row in reader:
                if row.get('label'):
                    new_categories.append({
                        'label': row['label'].strip(),
                        'keyword': row['keyword'].strip(),
                        'source': row.get('source', 'google').strip()
                    })

            if not new_categories:
                return False, "No valid categories found in CSV"

            if merge:
                # Add to existing
                added = 0
                for new_cat in new_categories:
                    # Check for duplicates
                    if not any(cat['label'] == new_cat['label'] for cat in self.categories):
                        self.categories.append(new_cat)
                        added += 1

                success, msg = self.save()
                if success:
                    return True, f"Added {added} new categories (total: {len(self.categories)})"
                return False, msg
            else:
                # Replace all
                old_categories = self.categories.copy()
                self.categories = new_categories

                success, msg = self.save()
                if success:
                    return True, f"Replaced with {len(new_categories)} categories"
                else:
                    # Rollback
                    self.categories = old_categories
                    return False, msg

        except Exception as e:
            return False, f"Failed to parse CSV: {str(e)}"


# Global instance
category_manager = CategoryManager()


if __name__ == "__main__":
    # Quick test
    manager = CategoryManager()

    print("\n=== Google Categories ===")
    print(f"Total: {len(manager.categories)}")

    stats = manager.get_stats()
    print(f"\nGoogle: {stats['google']} categories")
    print(f"YP: {stats['yp']} categories")

    print("\nFirst 5 categories:")
    for cat in manager.categories[:5]:
        print(f"  {cat['label']} → {cat['keyword']} ({cat['source']})")
