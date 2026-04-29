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
        help='Inclure les écritures déjà exportées (réservé aux responsables comptables).',
        default=False,
        groups='account.group_account_manager',
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
        """Utilise le champ Référence (ref) de la pièce comptable comme libellé Sage."""
        move = line.move_id
        ref = (move.ref or '').replace(';', ' ')
        if ref:
            return ref
        # Fallback si ref vide: type-N°FACTURE-NOM CLIENT
        if move.move_type == 'out_refund':
            prefix = 'avoir'
        elif move.move_type == 'in_refund':
            prefix = 'avoir-f'
        elif move.move_type == 'in_invoice':
            prefix = 'fact-f'
        else:
            prefix = 'fact'
        partner_name = (move.partner_id.name or '').replace(';', ' ')
        return '%s-%s-%s' % (prefix, move.name or '', partner_name)

    def _get_numero_facture(self, line):
        """Numéro facture pour la 9e colonne Sage 100c.

        Renseigné uniquement pour les factures et avoirs (clients/fournisseurs),
        vide pour les autres écritures (OD, banque, etc.).
        """
        move = line.move_id
        if move.move_type in ('out_invoice', 'in_invoice', 'out_refund', 'in_refund'):
            return (move.name or '').replace(';', ' ')
        return ''

    def _format_line(self, line):
        """Format a single account.move.line as a Sage 100c-compatible row.

        9 colonnes (format strict Sage 100c) :
        1. Code journal
        2. Date pièce (JJ/MM/AAAA)
        3. N° pièce
        4. N° compte général
        5. N° compte tiers (411*/401* uniquement)
        6. Libellé écriture
        7. Montant débit
        8. Montant crédit
        9. Numéro facture (uniquement pour factures/avoirs)
        """
        move = line.move_id
        fields_list = [
            move.journal_id.code or '',                # 1. Code Journal
            self._format_date(move.date),              # 2. Date pièce
            move.name or '',                           # 3. N° Pièce
            line.account_id.code or '',                # 4. Compte Général
            self._get_compte_tiers(line),              # 5. Compte Tiers
            self._get_libelle(line),                   # 6. Libellé
            self._format_amount(line.debit),           # 7. Débit
            self._format_amount(line.credit),          # 8. Crédit
            self._get_numero_facture(line),            # 9. Numéro facture
        ]
        return ';'.join(fields_list)

    def _is_line_exportable(self, line):
        """Garde-fous Sage 100c : valide les champs obligatoires.

        Retourne True si la ligne peut être exportée, False sinon (avec log warning).
        Champs obligatoires Sage : code journal, code compte général, date pièce.
        """
        move = line.move_id
        if not (move.journal_id and move.journal_id.code):
            _logger.warning(
                'Sage export: ligne %s ignoree - code journal manquant (move %s)',
                line.id, move.name or move.id,
            )
            return False
        if not (line.account_id and line.account_id.code):
            _logger.warning(
                'Sage export: ligne %s ignoree - code compte general manquant (move %s)',
                line.id, move.name or move.id,
            )
            return False
        if not move.date:
            _logger.error(
                'Sage export: ligne %s ignoree - date piece manquante (move %s)',
                line.id, move.name or move.id,
            )
            return False
        return True

    def action_export(self):
        """Generate the Sage export file (sans marquer les écritures)."""
        self.ensure_one()
        lines = self._get_move_lines()
        if not lines:
            raise UserError(_('Aucune écriture à exporter pour la période et les journaux sélectionnés.'))

        # Generate file content (skip lignes invalides - garde-fous Sage)
        rows = []
        exported_lines = self.env['account.move.line']
        skipped = 0
        for line in lines:
            if not self._is_line_exportable(line):
                skipped += 1
                continue
            rows.append(self._format_line(line))
            exported_lines |= line

        if not rows:
            raise UserError(_(
                'Aucune ligne valide à exporter (toutes ignorées par les garde-fous Sage). '
                'Consultez les logs pour le détail.'
            ))

        content = '\r\n'.join(rows)
        # Encode in ISO-8859-1 (Latin-1) for Sage compatibility
        file_data = content.encode('iso-8859-1', errors='replace')

        # Generate filename
        filename = 'SAGE_EXPORT_{}_au_{}.txt'.format(
            self.date_from.strftime('%Y%m%d'),
            self.date_to.strftime('%Y%m%d'),
        )

        moves = exported_lines.mapped('move_id')

        # Write file to wizard — NE PAS marquer les écritures ici
        self.write({
            'export_file': base64.b64encode(file_data),
            'export_filename': filename,
            'move_ids': [(6, 0, moves.ids)],
            'export_count': len(moves),
        })

        _logger.info(
            'Sage export genere: %d ecritures, %d lignes (skipped %d), periode %s-%s, user %s',
            len(moves), len(exported_lines), skipped, self.date_from, self.date_to,
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
