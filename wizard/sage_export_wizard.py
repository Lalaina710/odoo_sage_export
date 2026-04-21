import base64
import logging
from datetime import datetime

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


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
    move_ids = fields.Many2many(
        'account.move',
        string='Ecritures exportées',
        readonly=True,
    )
    export_count = fields.Integer(
        string='Nombre écritures',
        readonly=True,
    )

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_from > rec.date_to:
                raise UserError(_('La date de début doit être antérieure à la date de fin.'))

    def _get_move_lines(self):
        """Retrieve account.move.lines to export."""
        self.ensure_one()
        domain = [
            ('move_id.state', '=', 'posted'),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
            ('company_id', '=', self.env.company.id),
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

    def _get_libelle(self, line):
        """Construit le libellé Sage: type-N°FACTURE-NOM CLIENT."""
        move = line.move_id
        # Facture POS: origin rempli + journal vente locale
        is_pos = bool(move.invoice_origin) and move.move_type == 'out_invoice' and not move.invoice_origin.startswith('BC')
        if is_pos:
            prefix = 'fact-pdv'
        elif move.move_type == 'out_refund':
            prefix = 'avoir'
        elif move.move_type == 'in_refund':
            prefix = 'avoir-f'
        elif move.move_type == 'in_invoice':
            prefix = 'fact-f'
        else:
            prefix = 'fact'
        # Nom client/fournisseur
        partner_name = (move.partner_id.name or '').replace(';', ' ')
        # Libellé: fact-G264398-NOVOTEL ou fact-pdv-VL/26-27/22540
        return '%s-%s-%s' % (prefix, move.name or '', partner_name)

    def _format_line(self, line):
        """Format a single account.move.line as a Sage-compatible row."""
        move = line.move_id
        fields_list = [
            move.journal_id.code or '',                # Code Journal
            self._format_date(move.date),              # Date
            move.name or '',                           # N° Pièce
            line.account_id.code or '',                # Compte Général
            self._get_compte_tiers(line),              # Compte Tiers
            self._get_libelle(line),                   # Libellé
            self._format_amount(line.debit),           # Débit
            self._format_amount(line.credit),          # Crédit
            (move.ref or '').replace(';', ' '),        # N° Référence
            self._format_date(line.date_maturity),     # Date d'échéance
        ]
        return ';'.join(fields_list)

    def action_export(self):
        """Generate the Sage export file (sans marquer les écritures)."""
        self.ensure_one()
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

        moves = lines.mapped('move_id')

        # Write file to wizard — NE PAS marquer les écritures ici
        self.write({
            'export_file': base64.b64encode(file_data),
            'export_filename': filename,
            'move_ids': [(6, 0, moves.ids)],
            'export_count': len(moves),
        })

        _logger.info(
            'Sage export genere: %d ecritures, %d lignes, periode %s-%s, user %s',
            len(moves), len(lines), self.date_from, self.date_to,
            self.env.user.login,
        )

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_confirm_export(self):
        """Marquer les écritures comme exportées APRES téléchargement."""
        self.ensure_one()
        if not self.move_ids:
            raise UserError(_('Aucune écriture à confirmer. Lancez d\'abord l\'export.'))

        self.move_ids.write({
            'sage_exported': True,
            'sage_export_date': fields.Datetime.now(),
        })

        _logger.info(
            'Sage export confirme: %d ecritures marquees, user %s',
            len(self.move_ids), self.env.user.login,
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Export confirmé'),
                'message': _('%d écritures marquées comme exportées.') % len(self.move_ids),
                'type': 'success',
                'sticky': False,
            },
        }
