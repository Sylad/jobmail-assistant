# Carte — jobmail-assistant

## Écran /cleaner (nettoyeur de boîte, L4)
- Flux unique « Scanner le nettoyage » : phases Pubs anciennes → Règles regex → Offres déjà traitées → Doublons ; puis un seul bouton Déplacer pour toutes les phases, derrière deux confirmations (sauvegarde + Thunderbird fermé).
- Logique pure dans `frontend/src/cleaner/cleaner-core.ts` (testée par `tests/js/cleaner-core.test.mjs`, Node lit le TS en effaçant les types ; syntaxe effaçable seulement) : UID à déplacer par phase (`planPhaseMoves`, dédup par UID dans l'ordre des phases), total annoncé (`countPlannedMoves`, même calcul), retrait du panneau de scan, message vide.
- Décision L4/t1 (2026-11-17) : la phase Règles regex envoie sa sélection comme les autres (exclusions par expéditeur respectées) ; une phase dont la sélection est vide n'est jamais envoyée, car pour regex le serveur lit une liste vide comme « tout le scan ».
- Le panneau de scan se retire seulement si les quatre phases sont « Terminé » ; en cas d'erreur ou d'arrêt il reste avec le message.
- Le bundle `jobmail/web/static/assets/cleaner.js` est commité : `cd frontend && npx vite build` après toute modification des sources.
