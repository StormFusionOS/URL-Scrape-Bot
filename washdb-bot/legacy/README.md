# Legacy Code Archive

This directory contains deprecated code that has been replaced by newer implementations. These modules are kept for reference purposes only and are no longer actively maintained.

## Archived Components

### gui_backend/ (Deprecated: Nov 2024)

**Status**: DEPRECATED - DO NOT USE

**Replaced By**: `niceui/` module

**Reason for Deprecation**:
The Flask-based backend has been completely replaced by the NiceGUI unified web interface which provides:
- Better performance and responsiveness
- Unified frontend/backend in a single codebase
- Real-time updates without page refreshes
- Modern UI components
- Easier maintenance

**Original Purpose**:
Flask-based REST API backend that served the original GUI. It provided endpoints for:
- Scraper management
- Database queries
- Job scheduling
- Log viewing

**Migration Path**:
All functionality from `gui_backend/` has been reimplemented in `niceui/`:
- `gui_backend/app.py` → `niceui/main.py` (entry point)
- API endpoints → `niceui/backend_facade.py`  (facade pattern)
- Static frontend → `niceui/pages/*` (integrated UI)

**If You Need Reference**:
The code remains here for historical reference. If you need to understand how something worked in the old system, you can review the files here. However, **do not use this code in any new development**.

---

## Guidelines for Legacy Code

1. **Do Not Modify**: Legacy code should not be changed
2. **Do Not Import**: Never import from legacy modules in active code
3. **Reference Only**: Use only for understanding previous implementations
4. **Ask Before Removing**: Coordinate with the team before deleting legacy code

## Removal Schedule

Legacy code may be permanently removed when:
- All functionality has been verified in the replacement
- No open issues reference the legacy code
- Team consensus agrees it's safe to remove
- At least 6 months have passed since deprecation

---

**Last Updated**: 2025-11-23
