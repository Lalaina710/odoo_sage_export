import base64
import logging
from datetime import datetime

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Longueur des zones libellé Sage 100c (col 6).
MAX_LEN_LIBELLE = 35
# Nombre max de valeurs détaillées dans un warning d'audit.
AUDIT_LOG_SAMPLE = 50


def _sample(values, limit=AUDIT_LOG_SAMPLE):
    """Formate une liste pour un log : N premières valeurs + reste compté."""
    head = ', '.join(values[:limit])
    if len(values) > limit:
        return '%s ... (+%d)' % (head, len(values) - limit)
    return head


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
    exclude_pos_tickets = fields.Boolean(
        string='Exclure tickets POS',
        help='Exclure les factures par ticket POS (pos_order.account_move). '
             'Les clôtures de session (pos_session.move_id) restent exportées.',
        default=True,
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
        # Filtres de base (période / journal / company / état) — réutilisés
        # pour borner le scan des moves classe 9.
        base_domain = [
            ('move_id.state', '=', 'posted'),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
            ('company_id', '=', self.env.company.id),
        ]
        if self.journal_ids:
            base_domain.append(('journal_id', 'in', self.journal_ids.ids))

        # v1.3.14: retirer UNIQUEMENT les lignes 9* + leur contre-partie 5*
        # dans le MEME move. Cible reelle = paires ecarts caisse
        # (999001/999002 <-> 51150000). v1.3.13 excluait tout le move des
        # qu'une ligne 9* etait presente -> perdait les lignes tiers (411),
        # charges (6xxx) et produits (7xxx) sur ecritures mixtes.
        moves_with_class9_ids = set(self.env['account.move.line'].search(
            base_domain + [('account_id.code', '=like', '9%')],
        ).mapped('move_id.id'))

        domain = list(base_domain)
        if not self.re_export:
            domain.append(('move_id.sage_exported', '=', False))

        if self.exclude_pos_tickets:
            ticket_move_ids = self._get_pos_ticket_move_ids()
            if ticket_move_ids:
                domain.append(('move_id', 'not in', ticket_move_ids))

        lines = self.env['account.move.line'].search(
            domain,
            order='journal_id, date, move_id',
        )

        # Filtre par ligne (pas par move) : seules les lignes 9* et leur
        # contre-partie 5* sur un move classe 9 sont retirees.
        def _keep(aml):
            code = aml.account_id.code or ''
            if code.startswith('9'):
                return False
            if code.startswith('5') and aml.move_id.id in moves_with_class9_ids:
                return False
            return True

        return lines.filtered(_keep)

    def _get_pos_ticket_move_ids(self):
        """IDs des account.move correspondant aux factures par ticket POS.

        Un ticket POS génère une account.move via `pos_order.account_move`
        quand `to_invoice=True`. Ces moves font doublon avec la clôture de
        session (`pos_session.move_id`) — l'export Sage ne doit garder que
        la clôture.
        """
        self.env.cr.execute(
            """
            SELECT account_move
              FROM pos_order
             WHERE account_move IS NOT NULL
            """,
        )
        return [row[0] for row in self.env.cr.fetchall()]

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

    def _clean_csv_value(self, value):
        """Neutralise les caractères incompatibles avec le CSV Sage 100c.

        Le fichier est un CSV `;` en ISO-8859-1 sans guillemets : un `;`
        ou un saut de ligne dans une valeur décalerait toutes les colonnes
        suivantes. Ils sont remplacés par un espace, puis la valeur est
        strippée.
        """
        return (value or '').replace(';', ' ').replace('\r', ' ').replace('\n', ' ').strip()

    def _get_compte_general(self, line):
        """Compte general Sage pour la ligne.

        Priorite (Sage 8 chiffres) :

        1. Ligne produit sur facture vente/achat -> compte de la **categorie
           du produit** :
             - out_invoice / out_refund -> property_account_income_categ_id
             - in_invoice  / in_refund  -> property_account_expense_categ_id
        2. Ligne tiers (compte 411* ou 401* sur l'AML) -> compte du
           **partner** :
             - 411* -> partner.property_account_receivable_id
             - 401* -> partner.property_account_payable_id
           Corrige les AML obsoletes pointant des comptes 6 chiffres
           heritees des imports Sage (ex: 401100 -> 40110000).
        3. Fallback line.account_id.code (TVA, OD, banque, payments).

        Tous les fallbacks restent toleres : si la categ ou le partner
        n'a pas de property compte definie, on garde l'AML actuel.
        """
        move = line.move_id

        # 1. Ligne produit -> categorie produit
        if line.product_id and move.move_type in (
            'out_invoice', 'out_refund', 'in_invoice', 'in_refund',
        ):
            categ = line.product_id.categ_id
            if move.move_type in ('out_invoice', 'out_refund'):
                acc = categ.property_account_income_categ_id
            else:
                acc = categ.property_account_expense_categ_id
            if acc and acc.code:
                return acc.code

        # 2. Ligne tiers -> partner property
        aml_code = line.account_id.code or ''
        if line.partner_id and aml_code:
            partner = line.partner_id
            if aml_code.startswith('411'):
                new = partner.property_account_receivable_id.code
                if new:
                    return new
            elif aml_code.startswith('401'):
                new = partner.property_account_payable_id.code
                if new:
                    return new

        # 3. Fallback
        return aml_code

    def _resolve_tiers_partner(self, line):
        """Résout le partner tiers pour une AML (DRY pour col E + col F).

        Ordre : line.partner_id -> move.partner_id -> default_partner
        de la pos.config (clôtures POS / cash anonyme / TPE).
        Retourne un recordset (vide ou 1 partner).
        """
        partner = line.partner_id or line.move_id.partner_id
        if not partner:
            session = self._get_pos_session_for_move(line.move_id)
            if session and session.config_id:
                partner = session.config_id.default_partner_id
        return partner or self.env['res.partner']

    def _get_compte_tiers(self, line):
        """Return partner ref if account is client (411) or supplier (401).

        Pour les clôtures POS sans partner_id sur l'AML (vente personnel
        anonyme), fallback sur le default_partner du pos_config.
        """
        account_code = line.account_id.code or ''
        if not account_code.startswith(('411', '401')):
            return ''
        partner = self._resolve_tiers_partner(line)
        return partner.ref or ''

    def _get_libelle_tiers(self, line):
        """Libellé tiers (col F) — miroir de _get_compte_tiers (col E).

        Retourne `.name` du même partner résolu pour la col E, avec le
        même fallback session POS (cash / TPE anonyme). Strippe les
        caractères CSV (`;`, `\\r`, `\\n`) et tronque à 35 chars
        (limite Sage 100c).

        v1.3.16 : remplace la lecture directe `line.partner_id.name`
        introduite en v1.3.15 qui retournait vide pour 34/34 AML cash
        POS mai (partner_id NULL natif POS).
        """
        partner = self._resolve_tiers_partner(line)
        name = (partner.name or '') if partner else ''
        return self._clean_csv_value(name)[:MAX_LEN_LIBELLE]

    def _move_has_eae(self, move):
        """True si le move contient au moins une ligne sur compte 51150000.
        Toutes les lignes d'un meme move doivent alors etre routees vers
        le journal EAE cote Sage (debit + contrepartie credit)."""
        return any(
            aml.account_id and aml.account_id.code == '51150000'
            for aml in move.line_ids
        )

    def _get_code_journal(self, line):
        """Code journal Sage pour la ligne.

        Si le move contient une ligne sur compte `51150000` (ESPECES A
        ENCAISSER), force `EAE` pour TOUTES les lignes du move : Odoo poste
        ces ecritures sur les journaux de caisse PdV (CSE8, CSTOM, CSSY,
        etc.) mais en Sage la piece complete (debit caisse + credit tiers)
        doit atterrir dans le journal de centralisation `EAE`.
        """
        if self._move_has_eae(line.move_id):
            return 'EAE'
        return line.move_id.journal_id.code or ''

    def _get_pos_session_for_move(self, move):
        """Retourne pos.session si move est lié à une session POS, sinon False.

        Chemins testés par ordre de priorité :
        1. move.pos_session_ids (champ inverse natif si présent).
        2. pos.session.move_id = move (clôture POS classique facturée).
        3. account.bank.statement.line.pos_session_id (cash POS → EAE).
        4. account.payment.pos_session_id (TPE/carte POS → BNK1).
        """
        # 1. Champ inverse natif
        if 'pos_session_ids' in move._fields:
            sessions = move.pos_session_ids
            if sessions:
                return sessions[:1]
        # 2. Clôture POS classique
        session = self.env['pos.session'].search([('move_id', '=', move.id)], limit=1)
        if session:
            return session
        # 3. Cash POS via account.bank.statement.line
        if 'statement_line_ids' in move._fields and move.statement_line_ids:
            stmt_lines = move.statement_line_ids.filtered(
                lambda s: 'pos_session_id' in s._fields and s.pos_session_id
            )
            if stmt_lines:
                return stmt_lines[:1].pos_session_id
        # 4. TPE/carte POS via account.payment
        Payment = self.env['account.payment']
        if 'pos_session_id' in Payment._fields:
            payment = Payment.search([('move_id', '=', move.id)], limit=1)
            if payment and payment.pos_session_id:
                return payment.pos_session_id
        return self.env['pos.session']

    def _get_numero_piece(self, line):
        """N° pièce Sage 100c (3e colonne).

        - **Journal achat uniquement** (`in_invoice` / `in_refund`) :
          **référence fournisseur** (v1.4.0) au lieu du n° interne Odoo,
          soit `move.ref` — le champ « Référence » de la facture
          fournisseur, qu'Odoo pré-remplit avec le `partner_ref` du BC
          (`purchase.order._prepare_invoice`). **Vide** si `move.ref` est
          vide : pas de repli sur `move.name` (arbitrage client).

          Conséquences assumées côté client — volontairement **non**
          contournées ici :
          * avoir d'extourne → `move.ref` contient le texte auto d'Odoo
            (« Annulation de : BILL/..., motif ») ;
          * facture multi-BC → `move.ref` est la concaténation des refs
            (`purchase.order._create_invoices`) ;
          * facture rattachée à un BC mais `ref` vidée à la main →
            col 3 vide (aucune remontée au BC).

        - Tous les autres cas (ventes, clôtures POS, OD, banques,
          paiements) : `move.name`.

        **Aucune troncature** (v1.4.1) : la prod 43 exporte `GRS/26-27/0047`
        (14 caractères) en col 3 depuis des mois sans rejet ni fusion de
        pièce à l'import — la zone « N° pièce » Sage n'est donc pas bornée
        à 13. Seul le nettoyage CSV est appliqué.

        Les anomalies (col 3 vide, collisions, encodage) sont journalisées
        par `_audit_numero_piece` au moment de l'export.
        """
        move = line.move_id
        if move.move_type in ('in_invoice', 'in_refund'):
            return self._clean_csv_value(move.ref)
        return self._clean_csv_value(move.name)

    def _audit_numero_piece(self, lines):
        """Journalise les anomalies col 3 (N° pièce) avant écriture fichier.

        Trois contrôles, dans le style de `_is_line_exportable` (warning
        + poursuite de l'export, la décision revient au comptable) :

        - factures/avoirs d'**achat** sortant avec une col 3 **vide** :
          elles partagent toutes le même n° de pièce vide côté Sage ;
        - **collisions** (même journal Sage + date + col 3 sur deux moves
          distincts) : Sage fusionne ces pièces à l'import. Cas nominal :
          les avoirs d'extourne, dont la `ref` auto commence tous par
          « Annulation de : » ;
        - valeurs **non encodables en ISO-8859-1** (ex apostrophe
          typographique U+2019 collée depuis Word/PDF) : le fichier est
          écrit avec `errors='replace'`, ces caractères deviennent `?` et
          deux réfs distinctes peuvent produire la même clé de pièce.

        Les clés sont calculées sur la valeur **réellement écrite dans le
        fichier** : `_get_numero_piece` est la seule source, et le
        nettoyage appliqué à l'assemblage par `_format_line` est
        idempotent — l'audit et le fichier voient donc la même chaîne.

        Retourne un dict de compteurs pour le log de synthèse.
        """
        # Une seule ligne représentative par pièce : la col 3 ne dépend
        # que du move.
        reps = {}
        for line in lines:
            reps.setdefault(line.move_id.id, line)

        empty, non_latin1, collisions = [], [], []
        seen = {}
        for line in reps.values():
            move = line.move_id
            value = self._get_numero_piece(line)
            label = move.name or str(move.id)

            if move.move_type in ('in_invoice', 'in_refund') and not value:
                empty.append(label)

            if not value:
                continue
            try:
                value.encode('iso-8859-1')
            except UnicodeEncodeError:
                non_latin1.append('%s (%s)' % (label, value))
            key = (self._get_code_journal(line), move.date, value)
            if key in seen:
                collisions.append('%s <-> %s (%s)' % (seen[key], label, value))
            else:
                seen[key] = label

        if empty:
            _logger.warning(
                'Sage export: %d facture(s)/avoir(s) achat sans reference '
                'fournisseur -> col 3 vide, pieces fusionnables a l import '
                'Sage: %s', len(empty), _sample(empty),
            )
        if non_latin1:
            _logger.warning(
                'Sage export: %d n° de piece non encodable(s) en ISO-8859-1 '
                '(caracteres remplaces par ? dans le fichier): %s',
                len(non_latin1), _sample(non_latin1),
            )
        if collisions:
            _logger.warning(
                'Sage export: %d collision(s) de n° de piece (meme journal + '
                'date + col 3) -> Sage fusionnera ces pieces: %s',
                len(collisions), _sample(collisions),
            )

        return {
            'empty': len(empty),
            'non_latin1': len(non_latin1),
            'collisions': len(collisions),
        }

    def _get_numero_facture(self, line):
        """Numéro facture pour la 9e colonne Sage 100c.

        Renseigné pour :
        - factures et avoirs clients/fournisseurs (out/in_invoice/refund),
        - clôtures POS (pos_session.move_id) — alignées sur ventes normales.
        Vide pour les autres écritures (OD, banque, paiements simples).

        Inchangé depuis v1.3.16 : la référence fournisseur demandée par le
        client alimente la **col 3** (`_get_numero_piece`), pas cette
        colonne.
        """
        move = line.move_id
        if move.move_type in ('out_invoice', 'in_invoice', 'out_refund', 'in_refund'):
            return (move.name or '').replace(';', ' ')
        if self._get_pos_session_for_move(move):
            return (move.name or '').replace(';', ' ')
        return ''

    def _format_line(self, line, debit=None, credit=None):
        """Format a single account.move.line as a Sage 100c-compatible row.

        9 colonnes (format strict Sage 100c) :
        1. Code journal
        2. Date pièce (JJ/MM/AAAA)
        3. N° pièce (achats : référence fournisseur, sinon move.name)
        4. N° compte général
        5. N° compte tiers (411*/401* uniquement)
        6. Libellé écriture
        7. Montant débit
        8. Montant crédit
        9. Numéro facture (uniquement pour factures/avoirs)

        `debit` et `credit` overridables pour lignes groupées (somme).

        v1.4.0 : **toutes** les colonnes passent par `_clean_csv_value`
        avant assemblage. Les cols 1, 4, 5 et 9 ne l'étaient pas : un `;`
        dans `res.partner.ref` (champ libre, col 5) produisait une ligne à
        10 champs, décalant toutes les colonnes suivantes — les montants
        atterrissaient dans la mauvaise zone Sage. Le nettoyage est
        idempotent : les colonnes déjà nettoyées (3, 6) ne changent pas.
        """
        move = line.move_id
        fields_list = [
            self._get_code_journal(line),              # 1. Code Journal
            self._format_date(move.date),              # 2. Date pièce
            self._get_numero_piece(line),              # 3. N° Pièce (v1.4.0)
            self._get_compte_general(line),            # 4. Compte Général
            self._get_compte_tiers(line),              # 5. Compte Tiers
            self._get_libelle_tiers(line),             # 6. Libellé tiers (v1.3.16)
            self._format_amount(line.debit if debit is None else debit),
            self._format_amount(line.credit if credit is None else credit),
            self._get_numero_facture(line),            # 9. Numéro facture
        ]
        return ';'.join(self._clean_csv_value(value) for value in fields_list)

    def _group_lines(self, lines):
        """Regrouper AML par (move, journal Sage, compte general, compte tiers,
        side D/C) — somme debit/credit. Fusion globale TOUS comptes.

        Sur un même move, lignes ayant même compte général / même compte
        tiers / même sens fusionnent en 1 ligne unique, peu importe
        `aml.name`. Cas couverts :
        - 411/401 : Comptoir TPE+Espèces → 1 ligne (ex APYIIII 3→1).
        - 70xxx/44xxx : 2 lignes même compte avec aml.name distincts
          ('20% G' + 'Ventes avec 20% G') → 1 ligne synthétisée.
        - Comptes différents (70710000 vs 70722000) restent séparés (la
          clé inclut le compte général).
        """
        groups = {}
        order = []
        for aml in lines:
            key = (
                aml.move_id.id,
                self._get_code_journal(aml),
                self._get_compte_general(aml),
                self._get_compte_tiers(aml),
                'D' if aml.debit > 0 else 'C',
            )
            if key not in groups:
                groups[key] = {'rep': aml, 'debit': 0.0, 'credit': 0.0}
                order.append(key)
            groups[key]['debit'] += aml.debit
            groups[key]['credit'] += aml.credit
        return [groups[k] for k in order]

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
        if not self._get_compte_general(line):
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

        # Filtrer lignes invalides (garde-fous Sage), puis grouper
        exported_lines = self.env['account.move.line']
        valid_lines = self.env['account.move.line']
        skipped = 0
        for line in lines:
            if not self._is_line_exportable(line):
                skipped += 1
                continue
            valid_lines |= line
            exported_lines |= line

        # Observabilité col 3 (N° pièce) : vides, troncatures, collisions,
        # encodage. N'interrompt jamais l'export.
        audit = self._audit_numero_piece(valid_lines)

        rows = []
        for grp in self._group_lines(valid_lines):
            rows.append(self._format_line(grp['rep'], debit=grp['debit'], credit=grp['credit']))

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
            'Sage export genere: %d ecritures, %d lignes (skipped %d), periode %s-%s, '
            'user %s | col 3: %d vide(s), %d collision(s), %d non-latin1',
            len(moves), len(exported_lines), skipped, self.date_from, self.date_to,
            self.env.user.login, audit['empty'], audit['collisions'],
            audit['non_latin1'],
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
