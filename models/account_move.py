from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    sage_exported = fields.Boolean(
        string='Exporté vers Sage',
        default=False,
        copy=False,
    )
    sage_export_date = fields.Datetime(
        string='Date export Sage',
        copy=False,
    )
