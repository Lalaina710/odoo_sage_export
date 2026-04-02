import base64
from datetime import datetime

from odoo import fields, models, _
from odoo.exceptions import UserError


class SageExportWizard(models.TransientModel):
    _name = 'sage.export.wizard'
    _description = 'Export Comptable vers Sage 100c'

    date_from = fields.Date(string='Date début', required=True)
    date_to = fields.Date(string='Date fin', required=True)
    journal_ids = fields.Many2many(
        'account.journal',
        string='Journaux',
        help='Laisser vide pour exporter tous les journaux.',
    )
    re_export = fields.Boolean(
        string='Ré-export',
        help='Inclure les écritures déjà exportées.',
    )
    export_file = fields.Binary(string='Fichier', readonly=True)
    export_filename = fields.Char(string='Nom du fichier', readonly=True)

    def _get_move_lines(self):
        """Retrieve account.move.lines to export."""
        domain = [
            ('move_id.state', '=', 'posted'),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
        ]
        if self.journal_ids:
            domain.append(('journal_id', 'in', self.journal_ids.ids))
        if not self.re_export:
            domain.append(('move_id.sage_exported', '=', False))

        lines = self.env['account.move.line'].search(
            domain,
            order='journal_id, date, move_id',
        )
        return lines

    def _format_date(self, date_value):
        """Format date to DD/MM/YYYY."""
        if not date_value:
            return ''
        if isinstance(date_value, str):
            date_value = datetime.strptime(date_value, '%Y-%m-%d').date()
        return date_value.strftime('%d/%m/%Y')

    def _format_amount(self, amount):
        """Format amount with comma decimal separator (French format)."""
        return '{:.2f}'.format(amount).replace('.', ',')

    def _get_compte_tiers(self, line):
        """Return partner ref if account is client (411) or supplier (401)."""
        account_code = line.account_id.code or ''
        if account_code.startswith(('411', '401')) and line.partner_id and line.partner_id.ref:
            return line.partner_id.ref
        return ''

    def _format_line(self, line):
        """Format a single account.move.line as a Sage-compatible row."""
        move = line.move_id
        fields_list = [
            move.journal_id.code or '',                # Code Journal
            self._format_date(move.date),              # Date
            move.name or '',                           # N° Pièce
            line.account_id.code or '',                # Compte Général
            self._get_compte_tiers(line),              # Compte Tiers
            (line.name or move.ref or '').replace(';', ' '),  # Libellé (escape ;)
            self._format_amount(line.debit),           # Débit
            self._format_amount(line.credit),          # Crédit
            (move.ref or '').replace(';', ' '),        # N° Référence
            self._format_date(line.date_maturity),     # Date d'échéance
        ]
        return ';'.join(fields_list)

    def action_export(self):
        """Generate the Sage export file."""
        lines = self._get_move_lines()
        if not lines:
            raise UserError(_('Aucune écriture à exporter pour la période et les journaux sélectionnés.'))

        # Generate file content
        rows = []
        for line in lines:
            rows.append(self._format_line(line))

        content = '\r\n'.join(rows)
        # Encode in ISO-8859-1 (Latin-1) for Sage compatibility
        file_data = content.encode('iso-8859-1', errors='replace')

        # Generate filename
        filename = 'SAGE_EXPORT_{}_au_{}.txt'.format(
            self.date_from.strftime('%Y%m%d'),
            self.date_to.strftime('%Y%m%d'),
        )

        # Write file to wizard for download first
        self.write({
            'export_file': base64.b64encode(file_data),
            'export_filename': filename,
        })

        # Mark moves as exported only after file is ready
        moves = lines.mapped('move_id')
        moves.write({
            'sage_exported': True,
            'sage_export_date': fields.Datetime.now(),
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
