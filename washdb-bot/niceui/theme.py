"""
Theme configuration for NiceGUI dashboard.
Dark mode with charcoal grey theme.
"""

from nicegui import ui

# Charcoal grey color scheme
COLORS = {
    'primary': '#374151',      # Charcoal grey
    'secondary': '#4B5563',    # Medium grey
    'accent': '#6B7280',       # Light grey
    'dark': '#1F2937',         # Dark charcoal background
    'positive': '#10b981',     # Green for success
    'negative': '#ef4444',     # Red for errors
    'info': '#3b82f6',         # Blue for info
    'warning': '#f59e0b',      # Orange for warnings
}


def apply_theme():
    """Apply dark mode and custom charcoal grey theme."""
    # Enable dark mode
    ui.dark_mode().enable()

    # Apply custom colors
    ui.colors(
        primary=COLORS['primary'],
        secondary=COLORS['secondary'],
        accent=COLORS['accent'],
        positive=COLORS['positive'],
        negative=COLORS['negative'],
        info=COLORS['info'],
        warning=COLORS['warning']
    )

    # Add custom CSS for enhanced styling
    ui.add_head_html('''
        <style>
            :root {
                --color-primary: #374151;
                --color-secondary: #4B5563;
                --color-accent: #6B7280;
            }

            .q-page {
                background: linear-gradient(135deg, #111827 0%, #1F2937 100%);
            }

            .stat-card {
                background: rgba(55, 65, 81, 0.2);
                border: 1px solid #6B7280;
                border-radius: 8px;
                transition: transform 0.2s;
            }

            .stat-card:hover {
                transform: translateY(-2px);
                box-shadow: 0 4px 12px rgba(55, 65, 81, 0.5);
            }

            .nav-item-active {
                background-color: rgba(55, 65, 81, 0.4);
                border-left: 3px solid #6B7280;
            }
        </style>
    ''')
