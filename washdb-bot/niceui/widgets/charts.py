"""
ECharts chart widgets tailored for dark theme.
"""

from nicegui import ui
from typing import List, Dict, Any
from ..theme import COLORS


def create_line_chart(chart_id: str, series_data: List[Dict[str, Any]], categories: List[str] = None):
    """
    Create a line chart using ECharts.

    Args:
        chart_id: Unique ID for the chart
        series_data: List of series dictionaries with 'name' and 'data' keys
        categories: X-axis categories (defaults to day numbers)
    """
    if categories is None:
        # Default to day numbers
        max_len = max(len(s['data']) for s in series_data) if series_data else 0
        categories = [f'Day {i+1}' for i in range(max_len)]

    options = {
        'backgroundColor': 'transparent',
        'textStyle': {
            'color': '#ffffff'
        },
        'tooltip': {
            'trigger': 'axis',
            'backgroundColor': 'rgba(0, 0, 0, 0.8)',
            'borderColor': COLORS['accent'],
            'textStyle': {'color': '#ffffff'}
        },
        'legend': {
            'data': [s['name'] for s in series_data],
            'textStyle': {'color': '#ffffff'}
        },
        'grid': {
            'left': '3%',
            'right': '4%',
            'bottom': '3%',
            'containLabel': True
        },
        'xAxis': {
            'type': 'category',
            'boundaryGap': False,
            'data': categories,
            'axisLine': {'lineStyle': {'color': COLORS['accent']}},
            'axisLabel': {'color': '#ffffff'}
        },
        'yAxis': {
            'type': 'value',
            'axisLine': {'lineStyle': {'color': COLORS['accent']}},
            'axisLabel': {'color': '#ffffff'},
            'splitLine': {'lineStyle': {'color': 'rgba(167, 139, 250, 0.2)'}}
        },
        'series': [
            {
                'name': s['name'],
                'type': 'line',
                'smooth': True,
                'data': s['data'],
                'lineStyle': {'width': 2},
                'itemStyle': {'color': COLORS['primary'] if i == 0 else COLORS['accent']}
            }
            for i, s in enumerate(series_data)
        ]
    }

    return ui.echart(options).classes('w-full h-64')


def create_bar_chart(chart_id: str, series_data: List[Dict[str, Any]], categories: List[str]):
    """
    Create a bar chart using ECharts.

    Args:
        chart_id: Unique ID for the chart
        series_data: List of series dictionaries with 'name' and 'data' keys
        categories: X-axis categories
    """
    options = {
        'backgroundColor': 'transparent',
        'textStyle': {
            'color': '#ffffff'
        },
        'tooltip': {
            'trigger': 'axis',
            'backgroundColor': 'rgba(0, 0, 0, 0.8)',
            'borderColor': COLORS['accent'],
            'textStyle': {'color': '#ffffff'}
        },
        'legend': {
            'data': [s['name'] for s in series_data],
            'textStyle': {'color': '#ffffff'}
        },
        'grid': {
            'left': '3%',
            'right': '4%',
            'bottom': '3%',
            'containLabel': True
        },
        'xAxis': {
            'type': 'category',
            'data': categories,
            'axisLine': {'lineStyle': {'color': COLORS['accent']}},
            'axisLabel': {'color': '#ffffff'}
        },
        'yAxis': {
            'type': 'value',
            'axisLine': {'lineStyle': {'color': COLORS['accent']}},
            'axisLabel': {'color': '#ffffff'},
            'splitLine': {'lineStyle': {'color': 'rgba(167, 139, 250, 0.2)'}}
        },
        'series': [
            {
                'name': s['name'],
                'type': 'bar',
                'data': s['data'],
                'itemStyle': {'color': COLORS['primary'] if i == 0 else COLORS['accent']}
            }
            for i, s in enumerate(series_data)
        ]
    }

    return ui.echart(options).classes('w-full h-64')


def create_donut_chart(chart_id: str, data: List[Dict[str, Any]]):
    """
    Create a donut chart using ECharts.

    Args:
        chart_id: Unique ID for the chart
        data: List of dictionaries with 'name' and 'value' keys
    """
    options = {
        'backgroundColor': 'transparent',
        'textStyle': {
            'color': '#ffffff'
        },
        'tooltip': {
            'trigger': 'item',
            'backgroundColor': 'rgba(0, 0, 0, 0.8)',
            'borderColor': COLORS['accent'],
            'textStyle': {'color': '#ffffff'}
        },
        'legend': {
            'orient': 'vertical',
            'left': 'left',
            'textStyle': {'color': '#ffffff'}
        },
        'series': [
            {
                'type': 'pie',
                'radius': ['40%', '70%'],
                'avoidLabelOverlap': False,
                'itemStyle': {
                    'borderRadius': 10,
                    'borderColor': '#1e1b4b',
                    'borderWidth': 2
                },
                'label': {
                    'show': True,
                    'color': '#ffffff'
                },
                'emphasis': {
                    'label': {
                        'show': True,
                        'fontSize': 20,
                        'fontWeight': 'bold'
                    }
                },
                'data': data,
                'color': [COLORS['positive'], COLORS['negative'], COLORS['warning'], COLORS['info']]
            }
        ]
    }

    return ui.echart(options).classes('w-full h-64')
