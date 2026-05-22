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
