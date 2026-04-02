# Export Comptable Odoo → Sage 100c (Odoo 18)

Module Odoo 18 pour exporter les écritures comptables validées vers un fichier importable dans Sage 100c Cloud V8.

## Fonctionnalités

- Export des écritures comptables validées au format Sage 100c
- Filtrage par **période** (date début / date fin) et par **journaux**
- Gestion des **doublons** : les écritures exportées sont marquées et exclues des exports suivants
- Option de **ré-export** pour inclure les écritures déjà exportées
- Badge **"Exporté Sage"** visible sur chaque pièce comptable
- Filtres de recherche : "Exporté vers Sage" / "Non exporté vers Sage"

## Format du fichier

| Colonne | Description | Exemple |
|---------|-------------|---------|
| Code Journal | Code du journal comptable | GR |
| Date | Date de l'écriture | 02/04/2026 |
| N° Pièce | Numéro de la pièce | FC260001 |
| Compte Général | Numéro de compte | 411000 |
| Compte Tiers | Référence partenaire (411/401 uniquement) | C00001 |
| Libellé | Description de la ligne | Facture client X |
| Débit | Montant débit | 1200,00 |
| Crédit | Montant crédit | 0,00 |
| Référence | Référence de la pièce | BL-2026-001 |
| Date d'échéance | Échéance de paiement | 02/05/2026 |

**Spécifications techniques :**
- Séparateur : point-virgule (`;`)
- Encodage : ISO-8859-1 (Latin-1)
- Format date : DD/MM/YYYY
- Format montant : décimales avec virgule (`1200,00`)

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
