{
    'name': 'Export Comptable vers Sage 100c',
    'version': '18.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Export des écritures comptables au format Sage 100c',
    'description': 'Exporte les écritures comptables validées vers un fichier texte importable dans Sage 100c Cloud V8.',
    'author': 'Lalaina710',
    'license': 'LGPL-3',
    'depends': ['account'],
    'data': [
        'security/ir.model.access.csv',
        'views/account_move_views.xml',
        'views/sage_export_wizard_views.xml',
    ],
    'installable': True,
    'application': False,
}
