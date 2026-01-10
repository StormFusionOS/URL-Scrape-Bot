"""
AI Copy Button component - copies formatted content to clipboard for AI troubleshooting.
"""

from nicegui import ui
from typing import Callable, Optional


def ai_copy_button(
    content_provider: Callable[[], str],
    label: str = "Copy for AI",
    icon: str = "content_copy",
    color: str = "primary",
    tooltip: str = "Copy formatted content for AI troubleshooting"
) -> ui.button:
    """
    Create a button that copies AI-friendly formatted content to clipboard.

    Args:
        content_provider: Callable that returns the content to copy
        label: Button label text
        icon: Material icon name
        color: Button color
        tooltip: Tooltip text

    Returns:
        NiceGUI button element
    """

    async def copy_to_clipboard():
        try:
            content = content_provider()
            if not content:
                ui.notify("No content to copy", type="warning")
                return

            # Escape backticks and backslashes for JavaScript
            escaped = content.replace('\\', '\\\\').replace('`', '\\`').replace('$', '\\$')

            # Use JavaScript clipboard API
            await ui.run_javascript(f'''
                navigator.clipboard.writeText(`{escaped}`).then(() => {{
                    // Success is handled by NiceGUI notify
                }}).catch(err => {{
                    console.error('Failed to copy:', err);
                }});
            ''')

            ui.notify("Copied to clipboard!", type="positive", position="top")

        except Exception as e:
            ui.notify(f"Copy failed: {str(e)}", type="negative")

    btn = ui.button(label, icon=icon, on_click=copy_to_clipboard, color=color)
    btn.props('outline dense')
    btn.tooltip(tooltip)

    return btn


def format_error_for_ai(
    error_id: int,
    timestamp: str,
    service_name: str,
    severity: str,
    error_code: Optional[str],
    message: str,
    error_type: Optional[str] = None,
    stack_trace: Optional[str] = None,
    context: Optional[dict] = None,
    system_state: Optional[dict] = None
) -> str:
    """
    Format an error record into AI-friendly markdown.

    Returns:
        Formatted markdown string ready for pasting into Claude/ChatGPT
    """
    lines = [
        f"## Error Report #{error_id}",
        "",
        f"**Time:** {timestamp}",
        f"**Service:** {service_name} | **Severity:** {severity.upper()} | **Code:** {error_code or 'N/A'}",
        f"**Type:** {error_type or 'Unknown'}",
        "",
        f"### Message",
        f"{message}",
        "",
    ]

    if stack_trace:
        lines.extend([
            "### Stack Trace",
            "```python",
            stack_trace[:3000] if len(stack_trace) > 3000 else stack_trace,
            "```",
            "",
        ])

    if context:
        lines.extend([
            "### Context",
            "```json",
        ])
        import json
        try:
            lines.append(json.dumps(context, indent=2, default=str))
        except:
            lines.append(str(context))
        lines.extend([
            "```",
            "",
        ])

    if system_state:
        lines.extend([
            "### System State at Error Time",
            "```json",
        ])
        import json
        try:
            lines.append(json.dumps(system_state, indent=2, default=str))
        except:
            lines.append(str(system_state))
        lines.extend([
            "```",
            "",
        ])

    lines.extend([
        "---",
        "*Exported from WashDB System Monitor*",
    ])

    return "\n".join(lines)
