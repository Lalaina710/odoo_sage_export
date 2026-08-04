"""Tests de l'export Sage 100c — col 3 (N° pièce) v1.4.x + non-régressions.

Lancement sur le serveur 45 :

    docker exec -it odoo-dev odoo -d <base> \\
        -u odoo_sage_export --test-enable \\
        --test-tags /odoo_sage_export --stop-after-init --log-level=test
"""

from unittest.mock import patch

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.odoo_sage_export.wizard.sage_export_wizard import (
    MAX_LEN_LIBELLE,
)
from odoo.tests import tagged
from odoo.tools import mute_logger

LOGGER_PATH = 'odoo.addons.odoo_sage_export.wizard.sage_export_wizard'

# Index 0-based des colonnes Sage (le fichier en compte 9).
COL_JOURNAL = 0
COL_DATE = 1
COL_PIECE = 2
COL_COMPTE_GENERAL = 3
COL_COMPTE_TIERS = 4
COL_LIBELLE = 5
COL_DEBIT = 6
COL_CREDIT = 7
COL_NUM_FACTURE = 8

# 37 caractères, dont un espace en 35e position : `[:35]` laisse un espace
# final, que le nettoyage CSV strippe (écart col 6 assumé, cf. CHANGELOG).
NOM_ESPACE_EN_35 = 'ETS RANDRIANARISOA FRERES ET SOEUR SA'
# 42 caractères, 35e position non blanche : troncature nette à 35.
NOM_LONG = 'SOCIETE MALGACHE DES PRODUITS DE LA MER SA'


class _PosConfigDouble:
    """Surface de `pos.config` réellement lue par le wizard."""

    def __init__(self, partner, name='PdV Test Sage'):
        self.default_partner_id = partner
        self.name = name


class _PosSessionDouble:
    """Double de `pos.session` limité à la surface lue par le wizard.

    `_get_pos_session_for_move` renvoie toujours un recordset `pos.session`
    (ses 5 chemins retournent tous un recordset, jamais un booléen) ; le
    double reproduit la seule surface consommée en aval :
    `config_id.default_partner_id` (fallback col 6) et la véracité de
    l'objet (branche col 9).

    On ne crée pas de vraie `pos.session` : `create()` enchaîne sur
    `action_pos_session_open()` et la contrainte `_check_pos_config`
    (« Another session is already opened for this point of sale »), dont
    le résultat dépend des sessions ouvertes de la base — inexploitable
    dans un test déterministe tournant sur une copie de production.
    """

    def __init__(self, partner):
        self.config_id = _PosConfigDouble(partner)


@tagged('post_install', '-at_install')
class TestSageExportNumeroPiece(AccountTestInvoicingCommon):
    """Col 3 = `move.ref` sur les achats, `move.name` ailleurs. Sans troncature."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.wizard = cls.env['sage.export.wizard'].create({
            'date_from': '2019-01-01',
            'date_to': '2019-12-31',
        })
        # Le compte tiers Sage (col 5) n'est alimenté que si le compte
        # commence par 401/411 : on aligne le plan de test sur SOPROMER.
        cls.company_data['default_account_payable'].code = '40110000'
        cls.company_data['default_account_receivable'].code = '41110000'

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _create_bill(self, ref=None, move_type='in_invoice', post=True):
        """Facture (ou avoir) fournisseur avec `ref` positionnée avant post."""
        bill = self.init_invoice(
            move_type, partner=self.partner_a, products=self.product_a,
            post=False,
        )
        bill.ref = ref
        if post:
            bill.action_post()
        return bill

    def _create_invoice(self):
        """Facture client postée."""
        return self.init_invoice(
            'out_invoice', partner=self.partner_a, products=self.product_a,
            post=True,
        )

    def _create_misc_entry(self):
        """OD équilibrée et postée (aucun `move_type` facture).

        Structure identique à une écriture de clôture POS côté wizard : un
        `account.move` de type `entry`, sans partner sur les AML.
        """
        entry = self.env['account.move'].create({
            'move_type': 'entry',
            'date': '2019-06-01',
            'journal_id': self.company_data['default_journal_misc'].id,
            'line_ids': [
                (0, 0, {
                    'name': 'test OD debit',
                    'account_id': self.company_data['default_account_expense'].id,
                    'debit': 100.0,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'name': 'test OD credit',
                    'account_id': self.company_data['default_account_revenue'].id,
                    'debit': 0.0,
                    'credit': 100.0,
                }),
            ],
        })
        entry.action_post()
        return entry

    def _row(self, move):
        """Ligne CSV complète (9 colonnes) de la 1re AML du move."""
        return self.wizard._format_line(move.line_ids[0])

    def _cols(self, move):
        return self._row(move).split(';')

    def _tiers_line(self, move, prefix):
        return move.line_ids.filtered(
            lambda aml: aml.account_id.code.startswith(prefix)
        )[:1]

    # ------------------------------------------------------------------
    # Col 3 — achats
    # ------------------------------------------------------------------
    def test_col3_achat_avec_ref(self):
        """Achat avec référence fournisseur -> col 3 = `move.ref`."""
        bill = self._create_bill(ref='FA0705RT26')
        cols = self._cols(bill)

        # Ligne complète : 9 colonnes, structure Sage conforme.
        self.assertEqual(len(cols), 9)
        self.assertEqual(cols[COL_PIECE], 'FA0705RT26')
        self.assertEqual(cols[COL_JOURNAL], bill.journal_id.code)
        self.assertEqual(cols[COL_DATE], bill.date.strftime('%d/%m/%Y'))
        self.assertNotEqual(cols[COL_PIECE], bill.name)
        # Montants au format français, séparateur virgule.
        self.assertRegex(cols[COL_DEBIT], r'^\d+,\d{2}$')
        self.assertRegex(cols[COL_CREDIT], r'^\d+,\d{2}$')

    def test_col3_achat_sans_ref_reste_vide(self):
        """Sans `ref` -> col 3 vide, PAS de repli sur `move.name`."""
        bill = self._create_bill(ref=False)
        cols = self._cols(bill)

        self.assertEqual(len(cols), 9)
        self.assertEqual(cols[COL_PIECE], '')

    def test_col3_achat_ref_longue_non_tronquee(self):
        """v1.4.1 : aucune troncature de la col 3, réf sortie intacte.

        La prod 43 exporte `GRS/26-27/0047` (14 car.) en col 3 depuis des
        mois sans rejet ni fusion de pièce : la zone « N° pièce » Sage
        n'est pas bornée à 13 caractères.
        """
        ref = 'FRAIS LOG FA42843'  # 17 caractères
        bill = self._create_bill(ref=ref)
        cols = self._cols(bill)

        self.assertEqual(cols[COL_PIECE], ref)
        self.assertEqual(len(cols[COL_PIECE]), 17)

    def test_col3_avoir_extourne_via_assistant_core(self):
        """Extourne via `account.move.reversal` -> col 3 = `ref` auto Odoo.

        Comportement **voulu** par le client : aucune remontée au BC, la
        référence d'extourne (« Annulation de : ... ») n'est pas
        neutralisée. L'assertion porte sur `refund.ref` et non sur le
        texte traduit, pour rester indépendante de la langue.
        """
        bill = self._create_bill(ref='FA0705RT26')
        reversal = self.env['account.move.reversal'].with_context(
            active_model='account.move', active_ids=bill.ids,
        ).create({
            'date': bill.date,
            'reason': 'erreur de saisie',
            'journal_id': bill.journal_id.id,
        })
        refund = self.env['account.move'].browse(
            reversal.reverse_moves()['res_id']
        )
        refund.action_post()

        self.assertEqual(refund.move_type, 'in_refund')
        self.assertEqual(refund.reversed_entry_id, bill)
        # `_prepare_default_reversal` remplit `ref` avec le texte auto.
        self.assertTrue(refund.ref)
        self.assertIn(bill.name, refund.ref)
        self.assertNotEqual(refund.ref, 'FA0705RT26')
        self.assertEqual(self._cols(refund)[COL_PIECE], refund.ref)

    def test_col3_ref_avec_point_virgule_ne_decale_pas(self):
        """Un `;` dans la réf ne doit jamais créer une 10e colonne."""
        bill = self._create_bill(ref='FA0705;RT26')
        row = self._row(bill)

        self.assertEqual(row.count(';'), 8)
        self.assertEqual(len(row.split(';')), 9)
        self.assertEqual(row.split(';')[COL_PIECE], 'FA0705 RT26')

    def test_col3_identique_entre_audit_et_fichier(self):
        """L'audit doit voir exactement la chaîne écrite dans le fichier.

        Le nettoyage est appliqué une fois dans `_get_numero_piece` puis
        une seconde fois à l'assemblage par `_format_line` : il doit être
        idempotent, sinon les clés de collision porteraient sur une valeur
        différente de celle importée dans Sage.
        """
        bill = self._create_bill(ref='  FA;0705  ')

        valeur_audit = self.wizard._get_numero_piece(bill.line_ids[0])
        valeur_fichier = self._cols(bill)[COL_PIECE]

        self.assertEqual(valeur_audit, 'FA 0705')
        self.assertEqual(valeur_audit, valeur_fichier)

    # ------------------------------------------------------------------
    # Col 5 — compte tiers (401 fournisseur / 411 client)
    # ------------------------------------------------------------------
    def test_col5_partner_ref_avec_point_virgule_ne_decale_pas(self):
        """M5 : `;` dans `res.partner.ref` (champ libre) -> col 5 nettoyée."""
        self.partner_a.ref = 'F0001;X'
        bill = self._create_bill(ref='FA0705RT26')
        row = self.wizard._format_line(self._tiers_line(bill, '401'))

        self.assertEqual(row.count(';'), 8)
        self.assertEqual(row.split(';')[COL_COMPTE_TIERS], 'F0001 X')

    def test_col5_compte_client_411(self):
        """Vente : col 5 = `partner.ref` sur la ligne 411."""
        self.partner_a.ref = 'C00001'
        invoice = self._create_invoice()
        line = self._tiers_line(invoice, '411')

        self.assertTrue(line, 'aucune ligne 411 sur la facture client')
        cols = self.wizard._format_line(line).split(';')
        self.assertEqual(cols[COL_COMPTE_TIERS], 'C00001')
        self.assertEqual(cols[COL_PIECE], invoice.name)

    # ------------------------------------------------------------------
    # Col 6 — libellé tiers (colonne la plus instable de l'historique)
    # ------------------------------------------------------------------
    def test_col6_libelle_court(self):
        """Nom court -> libellé restitué tel quel."""
        self.partner_a.name = 'SUSHI BOX'
        bill = self._create_bill(ref='FA0705RT26')

        self.assertEqual(self._cols(bill)[COL_LIBELLE], 'SUSHI BOX')

    def test_col6_libelle_tronque_a_35(self):
        """Nom > 35 caractères -> troncature nette à 35."""
        self.partner_a.name = NOM_LONG
        bill = self._create_bill(ref='FA0705RT26')
        libelle = self._cols(bill)[COL_LIBELLE]

        self.assertEqual(libelle, NOM_LONG[:MAX_LEN_LIBELLE])
        self.assertEqual(len(libelle), MAX_LEN_LIBELLE)

    def test_col6_espace_en_35e_position_est_strippe(self):
        """Écart v1.4.0 assumé : l'espace final du slice est strippé.

        Avant v1.4.0 : `clean(name)[:35]` gardait l'espace final (35 car.).
        Depuis : `_format_line` re-nettoie la valeur assemblée, qui est
        donc strippée (34 car.). Cosmétique — Sage trimme — mais à ne pas
        prendre pour une régression lors d'un diff byte à byte.
        """
        self.partner_a.name = NOM_ESPACE_EN_35
        bill = self._create_bill(ref='FA0705RT26')
        libelle = self._cols(bill)[COL_LIBELLE]

        self.assertEqual(libelle, NOM_ESPACE_EN_35[:MAX_LEN_LIBELLE].strip())
        self.assertEqual(len(libelle), 34)
        self.assertFalse(libelle.endswith(' '))

    # ------------------------------------------------------------------
    # Non-régression ventes / clôtures POS
    # ------------------------------------------------------------------
    def test_col3_vente_inchangee(self):
        """Vente : col 3 = `move.name`, restitué intégralement."""
        invoice = self._create_invoice()
        cols = self._cols(invoice)

        self.assertEqual(cols[COL_PIECE], invoice.name)
        self.assertEqual(len(cols[COL_PIECE]), len(invoice.name))

    def test_col3_col6_col9_cloture_pos(self):
        """Clôture POS : col 3 et col 9 = `move.name`, col 6 = PdV.

        La résolution de session (`_get_pos_session_for_move`, 4 chemins)
        est remplacée par un double : le test cible le mapping de colonnes
        et le fallback partner du PdV, pas la reconstitution d'une session
        POS complète.
        """
        self.partner_a.name = 'Comptoir SOPROMER'
        entry = self._create_misc_entry()
        # Une clôture POS n'a pas de partner sur ses AML : c'est ce qui
        # déclenche le fallback `pos_config.default_partner_id` en col 6.
        self.assertFalse(entry.line_ids[0].partner_id)

        session = _PosSessionDouble(self.partner_a)
        with patch.object(
            type(self.wizard), '_get_pos_session_for_move', return_value=session,
        ):
            cols = self._cols(entry)

        self.assertEqual(len(cols), 9)
        self.assertEqual(cols[COL_PIECE], entry.name)
        self.assertEqual(cols[COL_LIBELLE], 'Comptoir SOPROMER')
        self.assertEqual(cols[COL_NUM_FACTURE], entry.name)

    # ------------------------------------------------------------------
    # Col 9 — inchangée depuis v1.3.8
    # ------------------------------------------------------------------
    def test_col9_reste_le_numero_odoo(self):
        """Col 9 = `move.name` pour ventes ET achats, jamais la réf."""
        bill = self._create_bill(ref='FA0705RT26')
        invoice = self._create_invoice()

        self.assertEqual(self._cols(bill)[COL_NUM_FACTURE], bill.name)
        self.assertEqual(self._cols(invoice)[COL_NUM_FACTURE], invoice.name)

    def test_col9_vide_hors_facture_et_pos(self):
        """OD / banque : col 9 vide, col 3 = `move.name`."""
        entry = self._create_misc_entry()
        cols = self._cols(entry)

        self.assertEqual(cols[COL_NUM_FACTURE], '')
        self.assertEqual(cols[COL_PIECE], entry.name)

    # ------------------------------------------------------------------
    # Observabilité
    # ------------------------------------------------------------------
    @mute_logger(LOGGER_PATH)
    def test_audit_col3_vide_et_collisions(self):
        """`_audit_numero_piece` remonte les vides et les collisions."""
        sans_ref = self._create_bill(ref=False)
        doublon_1 = self._create_bill(ref='FA0705RT26')
        doublon_2 = self._create_bill(ref='FA0705RT26')

        lines = sans_ref.line_ids | doublon_1.line_ids | doublon_2.line_ids
        audit = self.wizard._audit_numero_piece(lines)

        self.assertEqual(audit['empty'], 1)
        # Même journal + même date + même col 3 -> Sage fusionne.
        self.assertEqual(audit['collisions'], 1)
        self.assertEqual(audit['non_latin1'], 0)

    @mute_logger(LOGGER_PATH)
    def test_audit_detecte_reference_non_encodable_iso8859_1(self):
        """m2 : apostrophe typographique -> `?` dans le fichier, warning."""
        bill = self._create_bill(ref='FA’26')
        audit = self.wizard._audit_numero_piece(bill.line_ids)

        self.assertEqual(audit['non_latin1'], 1)

    # ------------------------------------------------------------------
    # Multi-société
    # ------------------------------------------------------------------
    def test_multi_company_exclut_les_ecritures_dune_autre_societe(self):
        """`_get_move_lines` ne remonte que la société courante."""
        other_company = self.setup_other_company()['company']
        bill_other = self.init_invoice(
            'in_invoice', partner=self.partner_a, products=self.product_a,
            post=True, company=other_company,
        )

        wizard = self.env['sage.export.wizard'].create({
            'date_from': '2019-01-01',
            'date_to': '2019-12-31',
            # Évite le scan SQL de tous les tickets POS de la base.
            'exclude_pos_tickets': False,
        })
        lines = wizard._get_move_lines()

        self.assertNotIn(bill_other.id, lines.mapped('move_id').ids)
        self.assertFalse(lines.filtered(
            lambda aml: aml.company_id != self.env.company
        ))
