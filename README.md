# Export Comptable Odoo → Sage 100c (Odoo 18)

**Version : 18.0.1.3.11**

Module Odoo 18 pour exporter les écritures comptables validées vers un fichier importable dans Sage 100c Cloud V8. Couvre les ventes normales, les achats fournisseurs et les **clôtures de session Point de Vente** (journal séparé `VEP` pour distinguer les tickets POS des ventes facturées).

## Fonctionnalités

- Export des écritures comptables validées au format Sage 100c (9 colonnes)
- Couverture complète des journaux SOPROMER :
  - **Ventes normales** (VL out_invoice / out_refund)
  - **Achats** (ACHL1, ACHL2 in_invoice / in_refund)
  - **Clôtures POS** (VL/POSS/CS*/EAE — écritures de session)
  - **OD diverses**, banques, caisses
- Filtrage par **période** (date début / date fin) et par **journaux**
- **Journal POS séparé `VEP`** : factures POS et clôtures de session injectées dans un journal dédié, distinct du `VL` standard, pour séparer les tickets PdV des ventes facturées en compta
- Gestion des **doublons** : les écritures exportées sont marquées et exclues des exports suivants
- Option de **ré-export** (réservé aux managers) pour inclure les écritures déjà exportées
- Badge **« Exporté Sage »** visible sur chaque pièce comptable
- Colonne **« Export Sage »** dans la liste des pièces comptables
- Filtres de recherche : « Exporté vers Sage » / « Non exporté vers Sage »
- **Groupement intelligent** : fusion automatique des lignes d'un même compte sur une même pièce (clé : move + journal + compte + tiers + sens débit/crédit), sans dépendance au libellé

## Format du fichier — Sage 100c (9 colonnes)

Format conforme à l'import standard « Écritures comptables » Sage 100c.

| # | Colonne | Description | Source Odoo | Exemple |
|---|---------|-------------|-------------|---------|
| 1 | Code journal | Code du journal comptable Sage | `move.journal_id.code` (avec mapping POS → `VEP`) | VEP |
| 2 | Date de pièce | Date de l'écriture (JJ/MM/AAAA) | `move.date` | 04/05/2026 |
| 3 | N° pièce | Numéro interne Odoo (clé de regroupement) | `move.name` | POS/00485 |
| 4 | N° compte général | Numéro de compte (8 chiffres post-bascule TVA) | `line.account_id.code` (catégorie produit ou property partner) | 70710000 |
| 5 | N° compte tiers | Référence partenaire (411/401 uniquement) | `partner.ref`, fallback `pos_config.default_partner_id.ref` pour clôtures POS sans partner sur AML | C00001 |
| 6 | Libellé écriture | Format unifié `ref - nom partner` tronqué à 35 chars (limite Sage 100c) | `partner.ref + " - " + partner.name`, fallback `move.name` | C00001 - SUSHI BOX |
| 7 | Montant débit | Montant débit | `line.debit` | 1200,00 |
| 8 | Montant crédit | Montant crédit | `line.credit` | 0,00 |
| 9 | Numéro facture | Réf commerciale lettrage (factures, avoirs et **clôtures POS**) | `move.name` | POS/00485 |

### Logique colonne par colonne

**Colonne 1 — Code journal**
- Mapping spécifique : les écritures issues de `pos.order` (factures tickets POS) et de `pos.session.move_id` (écritures de clôture) sont remappées vers le code journal **`VEP`** au lieu de `VL`.
- Permet de distinguer en compta Sage les ventes POS des ventes facturées classiques.

**Colonne 4 — N° compte général**
- Compte issu de `account.move.line.account_id.code`.
- Pour les ventes : alimenté par la **catégorie produit** (compte de revenu) ou par le **property account** du partenaire (411).
- Pour les achats : compte d'achat catégorie produit (60722000 etc.) ou compte fournisseur (40110000).
- Filtre `noupdate` : codes 8 chiffres post-bascule TVA (ex : `41110000`, `40110000`, `44566000`).

**Colonne 5 — N° compte tiers**
- Renseigné uniquement pour les comptes 411xxxxx et 401xxxxx.
- Source : `line.partner_id.ref` ou `move.partner_id.ref`.
- **Fallback POS** : pour les écritures de clôture de session sans partner sur l'AML, recherche du `pos_config.default_partner_id.ref` (ex : Comptoir).

**Colonne 6 — Libellé écriture**
- Format unifié sur **toutes** les natures d'écritures (TVA, ventes 70xxx, comptes 411/401, achats 60xxx) : `ref - nom partner` tronqué à 35 caractères.
- Fallback en cascade : `partner` ligne → `partner` move → `default_partner` PdV (clôtures POS anonymes) → `move.name`.

**Colonne 9 — Numéro facture**
- Renseigné pour les factures (`out_invoice`, `out_refund`, `in_invoice`, `in_refund`).
- **Étendu aux clôtures POS** : utilise `move.name` pour les écritures `pos.session.move_id` afin d'identifier la pièce de clôture côté Sage.

### Logique de groupement

Pour éviter la multiplication des lignes par compte, les AML d'une même pièce sont **fusionnées** sur la clé suivante :

```
(move_id, journal_code, account_code, partner_ref, side_debit_or_credit)
```

- Avant v1.3.6 : groupement plus restrictif (incluait `aml.name`) → 3 lignes 411 distinctes pour la facture APYIIII, plusieurs lignes 70xxx par produit.
- Depuis v1.3.6 : 1 seule ligne par compte sur une même pièce — APYIIII → 1 ligne 411, ventes 70xxx multi-produits → 1 ligne par compte de revenu.
- Validé sur :
  - Achat ACHL1/26-27/04/0001 → 3 lignes (60722000, 44566000 TVA, 40110000 tier)
  - Vente GRS/26-27/0047 → fusion correcte
  - Clôture POS SOPR/45 du 04/05/2026 → 485 lignes propres

### Spécifications techniques

- Séparateur : point-virgule (`;`)
- Encodage : ISO-8859-1 (Latin-1) — Sage Windows ANSI/CP1252 compatible
- Newline : Windows CRLF (`\r\n`)
- Format date : JJ/MM/AAAA (DD/MM/YYYY)
- Format montant : décimales avec virgule (`1200,00`)
- Pas de header (colonnes implicites par position)
- Pas de guillemets autour des champs
- Les `;` dans les libellés sont remplacés par des espaces

### Garde-fous (lignes ignorées avec log)

- Code journal manquant → warning + skip
- Code compte général manquant → warning + skip
- Date pièce manquante → error + skip
- Partner sans `ref` sur compte 411/401 → warning (ligne incluse, col 5 vide)

## Configuration requise

### Plan comptable

- Les **numéros de comptes** doivent être identiques entre Odoo et Sage (8 chiffres post-bascule TVA).
- Les **codes journaux** doivent être identiques entre Odoo et Sage.
- Un **journal `VEP`** doit être créé côté Sage pour recevoir les écritures POS.

### Partenaires

- Les **références partenaires** (champ `ref` du contact) doivent correspondre aux codes tiers Sage (ex : `C00001`, `F00012`).
- Pour chaque **PdV utilisant la facturation tickets ou la clôture compta**, le `pos.config.default_partner_id` doit être renseigné avec un partner ayant un `ref` valide (utilisé comme fallback col 5 pour clôtures sans partner).

### Catégories produits

- Comptes de revenu et d'achat configurés sur `product.category` (alimente la col 4).
- Comptes 411/401 configurés sur `res.partner` (`property_account_receivable_id`, `property_account_payable_id`).

## Wizard d'export

Menu : **Comptabilité → Export vers Sage**

| Champ | Type | Description | Défaut |
|-------|------|-------------|--------|
| `date_from` | Date | Début de période | — |
| `date_to` | Date | Fin de période | — |
| `journal_ids` | Many2many `account.journal` | Journaux à exporter (vide = tous) | vide |
| `exclude_pos_tickets` | Boolean | Exclut les `account.move` issus de `pos.order` (tickets POS individuels facturés) | **True** |
| `re_export` | Boolean | Réinclut les écritures déjà marquées exportées | False (managers uniquement) |

### Comportement `exclude_pos_tickets`

- **True** (défaut) : exclut les factures de tickets POS (`pos_order.account_move`) du domaine. Les écritures de **clôture de session** (`pos.session.move_id`) restent incluses → c'est ce qui alimente Sage.
- **False** : inclut tous les `account.move`, y compris les factures POS individuelles.

## Installation

1. Copier le dossier `odoo_sage_export` dans votre répertoire d'addons
2. Redémarrer Odoo
3. **Apps** → mettre à jour la liste → chercher **« Export Comptable vers Sage 100c »** → **Installer**

## Utilisation

### Exporter les écritures

1. Aller dans **Comptabilité → Export vers Sage**
2. Remplir les champs :
   - **Date début** / **Date fin** : période à exporter
   - **Journaux** : laisser vide pour tous, ou sélectionner spécifiquement (`VL`, `VEP`, `ACHL1`, etc.)
   - **Exclure tickets POS** : laisser coché (défaut)
   - **Ré-export** : cocher uniquement pour ré-injecter des écritures déjà exportées
3. Cliquer sur **Exporter**
4. Télécharger le fichier `.txt` généré

### Importer dans Sage 100c

1. Ouvrir Sage 100c
2. **Fichier → Import d'écritures**
3. Sélectionner le fichier `.txt` exporté depuis Odoo
4. Vérifier et valider l'import

### Vérifier les écritures exportées

- Un badge vert **« Exporté Sage »** apparaît sur les pièces comptables exportées
- La **date d'export** est affichée sur la fiche de la pièce
- Une colonne **« Export Sage »** (case à cocher en lecture seule) est disponible dans la liste — activez-la via le sélecteur de colonnes si nécessaire
- Filtres dans la liste des écritures :
  - **« Exporté vers Sage »** : voir les écritures déjà envoyées
  - **« Non exporté vers Sage »** : voir ce qui reste à exporter

## Workflow de déploiement (SOPROMER)

1. Modifier le code en local (`C:\odoo18\custom-addons\odoo_sage_export`).
2. Déployer sur **serveur 45 (test)** via `odoo-devops` + skill `sopromer-deploy`.
3. Tester un export sur la base SOPR du 45 :
   - Vente : `GRS/26-27/0047`
   - Achat : `ACHL1/26-27/04/0001`
   - Clôture POS : `POS/00485` (485 lignes)
4. Valider format Sage côté comptable.
5. Commit + push GitHub `Lalaina710/odoo_sage_export`.
6. Déployer sur **serveur 43 (prod)** **le soir uniquement** (115 users + 40 PdV).

## Dépendances

- `account`
- `point_of_sale` (pour le mapping POS → VEP et le fallback `default_partner_id`)

## Droits d'accès

| Groupe | Accès |
|--------|-------|
| Responsable comptabilité | Complet (lecture, écriture, création, suppression, ré-export) |
| Facturation | Lecture, écriture, création (pas de suppression, pas de ré-export) |

## Changelog

| Version | Changement |
|---------|------------|
| **18.0.1.3.11** | Fix : `_get_pos_session_for_move` étendue à `bank_statement_line.pos_session_id` (cash POS → EAE) + `account.payment.pos_session_id` (TPE/carte POS → BNK1). Résout 564 lignes AML 411xxx export Sage sans compte tiers (44% des 411). Diag : `sopromer-rapports/04_compta_clients/diag_export_sage_tiers_manquants_220526.html`. |
| **18.0.1.3.8** | Col 9 (numéro facture) étendue aux clôtures POS via `move.name` pour `pos_session.move_id`. |
| **18.0.1.3.7** | Libellé col 6 unifié `ref - nom partner` partout (TVA, ventes, 411, achats), fallback `default_partner` PdV pour clôtures POS anonymes. |
| **18.0.1.3.6** | Groupement étendu à TOUS les comptes (clé sans `aml.name`) : APYIIII 3 lignes 411 → 1 ligne ; ventes 70xxx multi-aml.name → 1 ligne. |
| **18.0.1.3.5** | Col 5 (compte tiers) avec fallback `pos_config.default_partner_id.ref` pour clôtures POS sans partner sur AML. |
| **18.0.1.3.0** | Journal `VEP` séparé pour factures POS / clôtures sessions. Champ wizard `exclude_pos_tickets` (default=True), filtre `pos_order.account_move`. |
| **18.0.1.2.4** | Compte général depuis catégorie produit (vente/achat) + property partner (411/401), résout 401100 tronqué. |
| **18.0.1.2.1** | Filtre `company_id`, séparation export/marquage, logging détaillé. |
| **18.0.1.0.0** | Version initiale : export 9 colonnes, marquage anti-doublon, filtres. |

## Licence

LGPL-3
