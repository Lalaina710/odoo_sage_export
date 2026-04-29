# Export Comptable Odoo → Sage 100c (Odoo 18)

Module Odoo 18 pour exporter les écritures comptables validées vers un fichier importable dans Sage 100c Cloud V8.

## Fonctionnalités

- Export des écritures comptables validées au format Sage 100c
- Filtrage par **période** (date début / date fin) et par **journaux**
- Gestion des **doublons** : les écritures exportées sont marquées et exclues des exports suivants
- Option de **ré-export** pour inclure les écritures déjà exportées
- Badge **"Exporté Sage"** visible sur chaque pièce comptable
- Colonne **"Export Sage"** dans la liste des pièces comptables
- Filtres de recherche : "Exporté vers Sage" / "Non exporté vers Sage"

## Format du fichier — Sage 100c (9 colonnes)

Format conforme à l'import standard "Écritures comptables" Sage 100c.

| # | Colonne | Description | Source Odoo | Exemple |
|---|---------|-------------|-------------|---------|
| 1 | Code journal | Code du journal comptable | `move.journal_id.code` | VE |
| 2 | Date de pièce | Date de l'écriture (JJ/MM/AAAA) | `move.date` | 02/04/2026 |
| 3 | N° pièce | Numéro interne Odoo (regroupement) | `move.name` | FC260001 |
| 4 | N° compte général | Numéro de compte (8 chiffres post-bascule TVA) | `line.account_id.code` | 41110000 |
| 5 | N° compte tiers | Référence partenaire (411/401 uniquement) | `partner.ref` | C00001 |
| 6 | Libellé écriture | Description (max ~35 char Sage) | `move.ref` ou fallback | Facture client X |
| 7 | Montant débit | Montant débit | `line.debit` | 1200,00 |
| 8 | Montant crédit | Montant crédit | `line.credit` | 0,00 |
| 9 | Numéro facture | Réf commerciale lettrage (factures/avoirs uniquement) | `move.name` | FC260001 |

**Spécifications techniques :**
- Séparateur : point-virgule (`;`)
- Encodage : ISO-8859-1 (Latin-1) — Sage Windows ANSI/CP1252 compatible
- Newline : Windows CRLF (`\r\n`)
- Format date : JJ/MM/AAAA (DD/MM/YYYY)
- Format montant : décimales avec virgule (`1200,00`)
- Pas de header (colonnes implicites par position)
- Pas de guillemets autour des champs
- Les `;` dans les libellés sont remplacés par des espaces

**Garde-fous (lignes ignorées avec log) :**
- Code journal manquant → warning + skip
- Code compte général manquant → warning + skip
- Date pièce manquante → error + skip

## Installation

1. Copier le dossier `odoo_sage_export` dans votre répertoire d'addons
2. Redémarrer Odoo
3. **Apps** → mettre à jour la liste → chercher **"Export Comptable vers Sage 100c"** → **Installer**

## Utilisation

### Exporter les écritures

1. Aller dans **Comptabilité → Export vers Sage**
2. Remplir les champs :
   - **Date début** : début de la période à exporter
   - **Date fin** : fin de la période à exporter
   - **Journaux** : sélectionner les journaux souhaités (laisser vide = tous les journaux)
   - **Ré-export** : cocher pour inclure les écritures déjà exportées
3. Cliquer sur **Exporter**
4. Télécharger le fichier `.txt` généré

### Importer dans Sage 100c

1. Ouvrir Sage 100c
2. **Fichier → Import d'écritures**
3. Sélectionner le fichier `.txt` exporté depuis Odoo
4. Vérifier et valider l'import

### Vérifier les écritures exportées

- Un badge vert **"Exporté Sage"** apparaît sur les pièces comptables exportées
- La **date d'export** est affichée sur la fiche de la pièce
- Une colonne **"Export Sage"** (case à cocher en lecture seule) est disponible dans la liste des pièces comptables — activez-la via le sélecteur de colonnes si elle n'est pas visible
- Utiliser les filtres dans la liste des écritures :
  - **"Exporté vers Sage"** : voir les écritures déjà envoyées
  - **"Non exporté vers Sage"** : voir ce qui reste à exporter

## Prérequis

- Les **numéros de comptes** doivent être identiques entre Odoo et Sage
- Les **codes journaux** doivent être identiques entre Odoo et Sage
- Les **références partenaires** (champ `ref` du contact) doivent correspondre aux codes tiers Sage
- Les écritures doivent être **validées** (état "Comptabilisé") avant export

## Dépendances

- `account`

## Droits d'accès

| Groupe | Accès |
|--------|-------|
| Responsable comptabilité | Complet (lecture, écriture, création, suppression) |
| Facturation | Lecture, écriture, création (pas de suppression) |

## Licence

LGPL-3
