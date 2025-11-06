{
    'name': 'NLP Query Assistant (Local LLM)',
    'version': '1.0',
    'summary': 'Ask questions in natural language and fetch Odoo data via local LLM',
    'author': 'ChatGPT Assistant',
    'category': 'AI Integration',
    'depends': ['base', 'web', 'sale', 'account'],
    'data': [
        'views/nlp_query_view.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'nlp_query_assistant/static/src/css/template.css',
        ],
    },
    'installable': True,
    'application': True,
}
