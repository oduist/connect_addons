# -*- coding: utf-8 -*-

{
    'name': 'Connect CrewAI',
    'version': '1.0.0',
    'author': 'Oduist',
    'maintainer': 'Oduist',
    'price': 0,
    'currency': 'EUR',
    'support': 'support@oduist.com',
    'license': 'Other proprietary',
    'category': 'Phone',
    'summary': 'Connect CrewAI integration module - Multi-agent AI orchestration',
    'description': """
        CrewAI Integration for Odoo
        ============================
        
        This module integrates CrewAI multi-agent framework with Odoo, allowing you to:
        - Create and manage AI Agents with specific roles and goals
        - Define Tasks for agents to complete
        - Organize Agents into Crews for collaborative work
        - Execute Crews and track results
        - View execution logs and outputs
    """,
    'depends': ['connect', 'mail'],
    'external_dependencies': {
        'python': ['crewai'],
    },
    'data': [
        # Security
        'security/admin.xml',
        'security/user.xml',
        # Data
        'data/process_type.xml',
        # Views
        'views/menu.xml',
        'views/agent.xml',
        'views/task.xml',
        'views/crew.xml',
        'views/execution.xml',
    ],
    'demo': [
        'data/demo_data.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'images': ['static/description/logo.png'],
    'assets': {
        'web.assets_backend': [],
    }
}
