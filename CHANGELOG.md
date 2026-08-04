## v18.0.1.4.1 (2026-07-27)

### Retrait de la troncature col 3 (arbitrage client)
- Suppression de `MAX_LEN_NUMERO_PIECE` et de toute troncature de la col 3, introduites en v1.4.0.
- Motif : la prod 43 exporte `GRS/26-27/0047` (14 caractères) en col 3 depuis des mois **sans rejet ni fusion de pièce**. Si la zone « N° pièce » Sage était bornée à 13, les ventes consécutives (`...0047` / `...0048`) collisionneraient déjà. La zone n'est donc pas bornée à 13.
- L'**import blanc côté Sage** reste la validation définitive de ce point.
- `_get_numero_piece` se réduit à `_clean_csv_value(move.ref)` (achats) / `_clean_csv_value(move.name)` (autres).
- Compteur et warning « tronquée » retirés de `_audit_numero_piece` et de la ligne INFO de synthèse. Les contrôles **col 3 vide**, **collision** et **non encodable ISO-8859-1** sont conservés.
- Ordre des opérations : le nettoyage est appliqué une seule fois dans `_get_numero_piece`, et il est idempotent — l'audit et le fichier voient donc strictement la même chaîne. Si une troncature revenait, elle devrait être la **dernière** opération, avant l'audit.

### Nettoyage code
- Suppression de `_is_tier_account` : code mort confirmé (aucun appelant dans `custom-addons/`, `third-party-addons/`, `custom-addons-oca/`).

### Tests
- 12 → 18 cas. Ajouts : réf longue **non tronquée**, cohérence audit ↔ fichier, col 6 (nom court / > 35 / espace en 35e position), compte tiers **411** client, filtre **multi-société**.
- Extourne : passe désormais par l'assistant `account.move.reversal` (vrai chemin core) au lieu d'injecter la `ref` à la main via `_reverse_moves`.
- Clôture POS : le mock renvoyait `True`, ce qui faisait échouer `_resolve_tiers_partner` (`True.config_id`) — artefact de test, pas un bug de production (`_get_pos_session_for_move` renvoie toujours un recordset). Remplacé par un double exposant `config_id.default_partner_id`, et le test asserte désormais les cols 3, 6 **et** 9.

## v18.0.1.4.0 (2026-07-27)

### Col 3 (N° pièce) — journal achat
- `in_invoice` / `in_refund` : la col 3 porte la **référence fournisseur** = `move.ref`, au lieu du n° interne Odoo.
- **Vide** si `move.ref` est vide : pas de repli sur `move.name`, **pas de remontée au bon de commande** (arbitrage client).
- Conséquences assumées, volontairement non contournées : avoir d'extourne → `Annulation de : BILL/..., motif` ; facture multi-BC → concaténation Odoo des refs ; `ref` vidée à la main sur une facture liée à un BC → col 3 vide.
- Ventes, clôtures POS, OD, banques, paiements : col 3 = `move.name`. Seule évolution sur ces journaux : passage par `_clean_csv_value` (no-op sur des n° de séquence, qui ne contiennent ni `;` ni espace de bord).

### Col 9 (numéro facture)
- **Inchangée** — toujours `move.name` (dernière évolution fonctionnelle : v1.3.8, extension aux clôtures POS). Passe désormais par `_clean_csv_value` au lieu d'un `.replace(';', ' ')` seul.

### Nettoyage CSV
- `_format_line` fait passer **les 9 colonnes** par `_clean_csv_value` (`;`, `\r`, `\n` → espace, puis `strip()`).
- Corrige un bug **pré-existant** : `res.partner.ref` est un champ libre ; un `;` saisi dedans produisait une ligne à 10 champs et décalait toutes les colonnes suivantes (montants importés dans la mauvaise zone Sage). Idem cols 1 et 4.

### ⚠️ Écart connu et accepté sur la col 6 — à ne pas prendre pour une régression
Lors d'un **diff byte à byte v1.3.16 / v1.4.x**, la colonne 6 (libellé tiers) peut différer d'un caractère sur certains partenaires. Ce n'est **pas** une régression, c'est une conséquence acceptée du nettoyage généralisé :

- avant : `clean(partner.name)[:35]` — le slice pouvait laisser un **espace final** ;
- depuis : `_format_line` re-nettoie la valeur assemblée, donc l'espace final est **strippé**.

L'écart n'apparaît que si le 35e caractère du nom est un espace. Exemple réel : `ETS RANDRIANARISOA FRERES ET SOEUR SA` → 35 caractères avant (`...ET SOEUR ` avec espace final), 34 après (`...ET SOEUR`). Purement cosmétique : Sage trimme les libellés à l'import. Couvert par le test `test_col6_espace_en_35e_position_est_strippe`.

### Observabilité
- Nouveau `_audit_numero_piece`, appelé par `action_export` : WARNING + compteurs sur les factures d'achat à col 3 vide, les **collisions** (même journal + date + col 3 sur deux pièces), et les valeurs non encodables en ISO-8859-1 (`’` → `?`).
- Compteurs repris dans le log INFO de synthèse de l'export.

### Nettoyage code
- Suppression de `_get_libelle` (aucun appelant : `_format_line` utilise `_get_libelle_tiers`) et, par ricochet, de `_eae_journal_name` (utilisé uniquement par `_get_libelle`). `_move_has_eae` conservé : utilisé par `_get_code_journal`.
- Constante `MAX_LEN_LIBELLE` (35).

### Tests
- Premiers tests du module : `tests/test_sage_export.py` (`AccountTestInvoicingCommon`, tag `post_install`).

## v18.0.1.3.16 (2026-05-22)
- Fix: col F libellé tiers = miroir col E avec fallback session POS pour AML anonymes.
- v1.3.15 cassait POS (partner_id NULL → col F vide pour 34/34 AML cash mai).

## v18.0.1.3.15 (2026-05-22)
- Col F (6) du XLSX = libellé tiers (partner.name) au lieu de l'ancien contenu.

## v18.0.1.3.14 (2026-05-22)
- Fix: v1.3.13 excluait tout le move avec une ligne 9*, perdant lignes tiers/charges.
- Now: retire UNIQUEMENT lignes 9* + contre-partie 5* du même move. Garde 411/6/7.

## v18.0.1.3.13 (2026-05-22)
- Fix: exclure écriture COMPLÈTE (toutes lignes) si au moins une ligne classe 9 — évite contre-partie orpheline déséquilibrant XLSX
