---
title: Le tableau de bord corrige quelques détails
date: 2026-11-01
created: 2026-11-01T12:00+01:00
lots: [L15]
captures:
  - { file: captures/L15-carte-avec-libelle-score.png, alt: "Liste des offres au téléphone : chaque carte commence par le libellé « Score » au-dessus de la note" }
---
Suites de la revue du tableau de bord.

- Une adresse avec un statut qui n'existe pas (`/?status=…`) est refusée proprement au lieu d'afficher une erreur serveur.
- Le pluriel est respecté : « 1 offre détectée », « 1 offre ».
- Au téléphone, la note de chaque offre porte maintenant son libellé « Score », comme les autres informations de la carte.
- Les scores faibles et les textes secondaires sont plus lisibles (contraste d'au moins 4,5 contre 1).
- Les captures de l'entrée précédente ont été reprises avec l'écran actuel.
