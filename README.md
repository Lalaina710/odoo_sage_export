# Export Comptable Odoo → Sage 100c (Odoo 18)

**Version : 18.0.1.4.1** — dernière modification 2026-07-27

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
| 3 | N° pièce | Numéro interne Odoo (clé de regroupement / lettrage Sage).<br>**Achats** (`in_invoice`/`in_refund`) : **référence fournisseur**, vide si absente | Achats : `move.ref`.<br>Ventes / POS / OD / banques : `move.name` | Achat : `FA0705RT26`<br>Vente : `POS/00485` |
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

**Colonne 3 — N° pièce**
- **Ventes, clôtures POS, OD, banques, paiements** : `move.name` (n° interne Odoo), **non tronqué** — comportement inchangé, au nettoyage CSV près (voir « Nettoyage »).
- **Achats uniquement** (`in_invoice`, `in_refund`) — depuis **v1.4.0** : **référence fournisseur**, c'est-à-dire `move.ref`, le champ « Référence » de la facture fournisseur, qu'Odoo pré-remplit avec le `partner_ref` du bon de commande (`purchase.order._prepare_invoice`). C'est la valeur affichée dans la colonne « Référence fournisseur » de la liste des BC (ex `FA0705RT26`, `BL43214`, `FRAIS LOG FA42843`, `FAC N°047/RO/26`).
  - **Vide si `move.ref` est vide** — pas de repli sur `move.name`.
  - **Aucune remontée au bon de commande** : le module ne lit ni `purchase.order.partner_ref` ni `move.line_ids.purchase_line_id`. Décision client assumée, avec trois conséquences connues et **volontairement non contournées** :

    | Cas | Col 3 obtenue |
    |-----|---------------|
    | Avoir d'extourne | `Annulation de : BILL/..., motif` — `move.ref` contient le texte auto d'Odoo (`account.move.reversal`) |
    | Facture multi-BC | `FA0705RT26, BL43214` — `move.ref` est la concaténation des refs (`purchase.order._create_invoices`) |
    | Facture liée à un BC mais `ref` vidée à la main | *(vide)* |

- **Aucune troncature** (v1.4.1). Constat empirique : la prod 43 exporte `GRS/26-27/0047` (14 caractères) en col 3 **depuis des mois sans rejet ni fusion de pièce** — si la zone « N° pièce » Sage était bornée à 13, les ventes consécutives (`...0047` / `...0048`) collisionneraient déjà. La zone n'est donc pas bornée à 13. Seul le nettoyage CSV est appliqué. **L'import blanc côté Sage reste la validation définitive** de ce point.
- ⚠️ **Impact côté Sage** : la col 3 sert de n° de pièce (regroupement / lettrage). Partagent le même n° de pièce à l'import Sage — donc risquent d'être fusionnées :
  - deux factures d'achat portant la **même** référence fournisseur (BC facturé en deux fois, avoir reprenant la réf de la facture d'origine) ;
  - **tous les avoirs d'extourne** d'une même date/journal (tous préfixés `Annulation de : `) — cas nominal, pas une exception ;
  - toutes les factures d'achat **sans** `ref` (col 3 vide).

  Le regroupement **interne** au module n'est pas affecté (clé `move_id` base, cf. « Logique de groupement ») : seule la reconstitution des pièces côté Sage l'est. Ces trois cas sont comptés et détaillés dans les logs à chaque export (voir « Observabilité »).

**Colonne 4 — N° compte général**
- Compte issu de `account.move.line.account_id.code`.
- Pour les ventes : alimenté par la **catégorie produit** (compte de revenu) ou par le **property account** du partenaire (411).
- Pour les achats : compte d'achat catégorie produit (60722000 etc.) ou compte fournisseur (40110000).
- Filtre `noupdate` : codes 8 chiffres post-bascule TVA (ex : `41110000`, `40110000`, `44566000`).

**Colonne 5 — N° compte tiers**
- Renseigné uniquement pour les comptes 411xxxxx et 401xxxxx.
- Source : `line.partner_id.ref` ou `move.partner_id.ref`.
- **Fallback POS** : pour les écritures de clôture de session sans partner sur l'AML, recherche du `pos_config.default_partner_id.ref` (ex : Comptoir).
- Depuis v1.4.0 : nettoyée par `_clean_csv_value`. `res.partner.ref` est un champ **libre** — un `;` saisi dedans produisait une ligne à 10 champs, décalant toutes les colonnes suivantes (les montants atterrissaient dans la mauvaise zone Sage).

**Colonne 6 — Libellé écriture**
- Format unifié sur **toutes** les natures d'écritures (TVA, ventes 70xxx, comptes 411/401, achats 60xxx) : `ref - nom partner` tronqué à 35 caractères.
- Fallback en cascade : `partner` ligne → `partner` move → `default_partner` PdV (clôtures POS anonymes) → `move.name`.

**Colonne 9 — Numéro facture**
- Renseigné pour les factures (`out_invoice`, `out_refund`, `in_invoice`, `in_refund`) et les clôtures POS. Vide pour les OD, banques et paiements simples.
- Alimenté par `move.name` dans **tous** les cas — **inchangé depuis v1.3.8**. La référence fournisseur demandée par le client alimente la **col 3**, pas celle-ci.
- v1.4.0 : passe désormais par `_clean_csv_value` comme les autres colonnes (auparavant `.replace(';', ' ')` seul, sans `\r`/`\n` ni `strip()`).

### Nettoyage CSV

Le fichier est un CSV `;` **sans guillemets** : toute valeur contenant `;`, `\r` ou `\n` décalerait les colonnes suivantes. Depuis **v1.4.0**, `_format_line` fait passer **les 9 colonnes** par `_clean_csv_value` (remplacement par un espace + `strip()`) avant assemblage. Auparavant seules les colonnes 3 et 6 l'étaient ; les colonnes 1, 4, 5 et 9 ne l'étaient pas ou partiellement.

Le nettoyage est **idempotent** : les colonnes déjà nettoyées en interne (3 et 6, qui doivent l'être avant troncature) sont inchangées.

### Observabilité (logs col 3)

À chaque export, `_audit_numero_piece` compte et journalise (`WARNING`, échantillon de 50 valeurs + total, sans jamais interrompre l'export) :

| Contrôle | Pourquoi |
|----------|----------|
| Factures/avoirs d'achat à **col 3 vide** | partagent toutes le même n° de pièce vide côté Sage |
| **Collisions** : même (journal Sage, date, col 3) sur deux pièces distinctes | Sage fusionne ces pièces à l'import — inclut le cas nominal des avoirs d'extourne, tous préfixés `Annulation de : ` |
| Valeurs **non encodables en ISO-8859-1** | le fichier est écrit avec `errors='replace'` : `’` (U+2019, arrive par copier-coller Word/PDF) devient `?`, deux réfs distinctes peuvent alors produire la même clé de pièce |

Les compteurs sont repris dans la ligne `INFO` de synthèse de l'export.

Les clés de collision sont calculées sur la valeur **réellement écrite dans le fichier** : `_get_numero_piece` est l'unique source, et le nettoyage réappliqué à l'assemblage par `_format_line` est idempotent. Si une troncature devait revenir un jour, elle devrait être la **dernière** opération, avant l'audit.

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

- Format fichier : **CSV `.txt`** (pas XLSX) — import natif Sage 100c
- Séparateur : point-virgule (`;`)
- Encodage : ISO-8859-1 (Latin-1) — Sage Windows ANSI/CP1252 compatible
- Newline : Windows CRLF (`\r\n`)
- Format date : JJ/MM/AAAA (DD/MM/YYYY)
- Format montant : décimales avec virgule (`1200,00`)
- Pas de header (colonnes implicites par position)
- Pas de guillemets autour des champs
- Les `;`, `\r` et `\n` sont remplacés par des espaces sur **toutes** les colonnes (v1.4.0)
- Seule longueur Sage 100c appliquée : col 6 = 35 chars. La col 3 n'est **pas** tronquée (v1.4.1)

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

## Tests

Le module embarque `tests/test_sage_export.py` (18 cas, `AccountTestInvoicingCommon`, tag `post_install`) : col 3 (achat avec/sans réf, réf longue non tronquée, avoir d'extourne via l'assistant core, `;` dans la réf, cohérence audit ↔ fichier), col 5 (401 avec `;`, 411 client), col 6 (nom court, > 35, espace en 35e position), non-régressions ventes / clôture POS / col 9, audit d'observabilité, et filtre multi-société.

Lancement sur le **serveur 45** (jamais sur 43) :

```bash
docker exec -it odoo-dev odoo -d <base> \
    -u odoo_sage_export --test-enable \
    --test-tags /odoo_sage_export --stop-after-init --log-level=test
```

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
| **18.0.1.4.1** | Retrait de la troncature col 3 à 13 caractères introduite en v1.4.0 : la prod 43 exporte des n° de pièce de 14 caractères sans rejet Sage. Suppression du compteur d'audit « tronquée ». Suppression du code mort `_is_tier_account`. Tests portés à 18 cas (col 6, 411, multi-société, extourne via assistant core). |
| **18.0.1.4.0** | Col 3 (N° pièce) sur le **journal achat uniquement** (`in_invoice`/`in_refund`) = **référence fournisseur** (`move.ref`), **vide** si `move.ref` est vide (pas de repli sur `move.name`, pas de remontée au BC). Ventes/POS/OD/banques : `move.name`. **Col 9 inchangée** (`move.name`, cf. v1.3.8). Nettoyage CSV généralisé aux **9 colonnes** (fix `;` dans `res.partner.ref` → décalage de colonnes). Nouvel audit `_audit_numero_piece` (col 3 vide / collisions / non-ISO-8859-1). Suppression du code mort `_get_libelle` + `_eae_journal_name`. **Premiers tests** du module. |
| **18.0.1.3.16** | Fix col F : libellé miroir col E via méthode factorisée `_resolve_tiers_partner` (résout régression v1.3.15). Col F = `partner.ref + " - " + partner.name` cohérent avec col E, fallback identique (line.partner → move.partner → POS default_partner). |
| **18.0.1.3.15** | Régression : col F basculée vers libellé tiers direct sans factorisation → désaccord col E/F sur clôtures POS. Corrigée par v1.3.16. |
| **18.0.1.3.14** | Filter affiné classe 9 : exclusion **ciblée des lignes** `9*` + paire correspondante `5*` (au lieu d'exclure le `account.move` entier). Préserve les pièces mixtes contenant ventes 70xxx + engagements 9xxx. |
| **18.0.1.3.13** | Itération interne — voir v1.3.14. |
| **18.0.1.3.12** | Filter : exclure comptes classe 9 (`9*`) de l'export Sage (analytique / engagements non transférés Sage 100c SOPROMER). Domaine `_get_move_lines` : `('account_id.code', 'not like', '9%')`. |
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
