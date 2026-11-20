---
title: Des textes plus lisibles, et un tableau de bord vide qui dit quoi faire
date: 2026-11-20
created: 2026-11-20T14:00+01:00
lots: [L19]
captures:
  - { file: captures/L19-etat-vide-telephone.png, alt: "Tableau de bord sans offre au téléphone : « Aucune offre pour l'instant », une phrase qui invite à lancer Nouveaux mails et le bouton Nouveaux mails" }
  - { file: captures/L19-regles-regex-telephone.png, alt: "Règles regex du nettoyeur au téléphone : une carte par règle, avec les champs Expéditeur et Objet l'un sous l'autre" }
---
Les plus petits textes de l'application (étiquettes, statuts, menus, boutons du nettoyeur) passent à 12 pixels au moins.

- Quand aucune offre n'est encore enregistrée, le tableau de bord le dit et propose le bouton « Nouveaux mails » ; quand ce sont les filtres qui ne gardent rien, il rappelle le nombre total d'offres et propose de tout afficher.
- Au téléphone, chaque règle regex du nettoyeur tient dans sa propre carte : plus besoin de faire défiler le tableau sur le côté.
- Les cases « Je confirme » du nettoyeur sont plus grandes, et leur phrase comme l'en-tête « Backups Thunderbird » se touchent plus facilement.
