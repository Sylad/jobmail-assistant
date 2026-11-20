# L19 — Revue UX : bonnes pratiques d'une appli web standard

Date : 2026-11-20. Référentiels : WCAG 2.2 AA, heuristiques de Nielsen, skill `interface-utilisable`
(texte en rem ≥ 12 px, cibles ≥ 24 px, 44 px visés, contrastes, focus visible, états vides et d'erreur).

## Méthode

- Google Chrome piloté par Playwright 1.55, axe-core 4.10.3 (tags `wcag2a`, `wcag2aa`, `wcag21a`,
  `wcag21aa`, `wcag22aa` — donc `target-size` — et `best-practice`).
- Deux instances de démonstration hors dépôt : une base vide, et une base de 4 offres fictives
  (`Exemple SA`, `Démo SARL`…). Aucun vrai mail.
- 9 pages : tableau de bord (vide et rempli), Nettoyeur, Nouveautés, Plan de travail, deux fiches
  offre, offre inexistante (`/offers/999`), adresse inconnue (`/nexiste`).
- 7 tailles : 320×700, 390×844, 600×900, 840×900, 1280×900, 1440×900 et paysage 844×390.
- Par page et taille : violations axe, `scrollWidth` du document, boîtes des éléments
  interactifs (`getBoundingClientRect`, < 24 px), taille calculée de chaque nœud texte (< 12 px).
- Au clavier (390 et 1440 px) : Tab jusqu'à 60 fois ; pour chaque élément focalisé, contour
  (`outline`) ou ombre (`box-shadow`) non nul.
- Captures pleine page à 390 et 1440 px, regardées une à une (hors dépôt, dossier `.captures`
  du run, `avant/` et `apres/`).
- Code : recherche de `100vh` et `user-scalable` (aucun `user-scalable` ; 4 `100vh`, voir C8).

## Ce qui tient déjà

- Aucun défilement horizontal du document, de 320 à 1440 px et en paysage, sur les 9 pages.
- Focus visible sur chaque élément atteint au clavier (0 élément sans contour ni ombre, 6 à 39
  éléments selon la page), ordre de tabulation conforme au DOM.
- Boutons à icône seule (actions rapides des offres) nommés : axe `button-name` sans violation.
- Texte agrandi à 200 % : déjà couvert par `tests/test_texte_agrandi.py` (L8, L20, L21).
- Offre inexistante : page en français avec chemin de retour (L3).

## Écarts corrigés dans ce lot (simples et sûrs)

| # | Écart mesuré (avant) | Règle | Correction | Après |
|---|---|---|---|---|
| C1 | Adresse inconnue : JSON brut `{"detail":"Not Found"}`, sans `lang`, titre, h1 ni retour (axe `html-has-lang`, `document-title`, `page-has-heading-one`, `landmark-one-main`, `region`) | Nielsen 9, WCAG 3.1.1, 2.4.2 | Gestionnaire 404 : une requête GET qui demande du HTML hors `/api/` et `/static/` reçoit `not_found.html` (« Page introuvable », bouton Retour) ; les API et clients JSON gardent le JSON | 0 violation |
| C2 | Étiquettes « score ≥ 8 » et « total » des cartes : `#64748B` sur `#1B2335`, 3,29:1 | WCAG 1.4.3 | `--fg-mute` | 6,12:1 |
| C3 | Raccourcis du filtre (`.chip-link`) : 3,49:1 sur `#161E30` | WCAG 1.4.3 | `--fg-mute` | 6,49:1 |
| C4 | Texte gris `.muted` (état vide « Aucune offre… ») : 3,57:1 sur `#141C2E` | WCAG 1.4.3 | `.muted` en `--fg-mute` (le nettoyeur l'avait déjà, L4) | 6,63:1 |
| C5 | Lien « Tout afficher » dans une phrase grise, distingué par la seule couleur : 1,74:1 avec le texte | WCAG 1.4.1 (axe `link-in-text-block`) | `p.muted a` souligné | 0 violation |
| C6 | « Retour au tableau de bord » (fiche offre) : 172 × 15 px | WCAG 2.5.8 (24 px) | `min-height: 24px` | 172 × 24 px |
| C7 | Fiche offre ≥ 1280 px : deux `<aside>` sans nom (axe `landmark-unique`) | WCAG 1.3.1 | `aria-label` « Menu de l'application » et « Score et technos » | 0 violation |
| C8 | 4 hauteurs en `100vh` (coque, barre latérale, capture agrandie des Nouveautés) : au téléphone, `100vh` passe sous la barre du navigateur | skill interface-utilisable §5 | Ligne `100dvh` après chaque `100vh` (gardé en repli) | test |

Après correction : **0 violation axe sur les 63 couples page × taille**. Tests :
`tests/test_revue_l19.py` (9 tests ; le test de contraste vérifie aussi que l'ancien jeton échoue).

## Écarts laissés, proposés en sous-lots

| Sous-lot proposé | Mesure | Règle | Pourquoi pas ici |
|---|---|---|---|
| **L19/t1 — Texte d'au moins 12 px partout** | 33 déclarations CSS entre 0,625 et 0,744 rem (10 à 11,9 px) : libellés de navigation 11 px, étiquettes de champ 10 px, `kpi-tag` 10,5 px, statuts et score 11 px, `dt` de la fiche 10,5 px, sous-titres de la barre latérale 10-11 px ; nettoyeur Vue : boutons `text-xs` 10,5 px | skill interface-utilisable (≥ 12 px) | Touche toute la typographie : à revoir écran par écran (largeurs de la barre latérale, des cartes, des tableaux) avec captures, et `test_tailles_rem.py` à étendre |
| **L19/t2 — Filtres repliés au téléphone** | À 390 px, le titre « Offres détectées » commence à 1 129 px (écran de 844 px) : 6 champs, 2 boutons et 7 raccourcis passent avant la liste | Nielsen 8, divulgation progressive (skill §6) | Changement de parcours, demande une maquette et un avis de Sylvain |
| **L19/t3 — État vide qui dit pourquoi** | Base vide et aucun filtre : « Aucune offre ne matche ce filtre. » ; anglicisme « matche » ; « triées par score · desc » en jargon | Nielsen 2 et 9 | Texte et logique à choisir (base vide vs filtre trop strict, renvoi vers « Nouveaux mails ») |
| **L19/t4 — Règles regex lisibles au téléphone** | À 390 px, le tableau des règles défile en largeur dans son cadre (318 / 370 px), colonne Expéditeur coupée | WCAG 1.4.10 (recommandé), skill §5 | Mise en page du tableau à repenser (une règle par carte sous 600 px) |
| **L19/t5 — Cibles du nettoyeur** | Cases « Je confirme » (`confirm_cleanup`, `confirm_temp_cleanup`) 13 × 13 px ; résumé « Backups Thunderbird » 17 px de haut. axe `target-size` passe (exception d'espacement) mais sous les 44 px visés | WCAG 2.5.5 (AAA, visé par la skill) | Petit, mais touche le parcours de confirmation : à faire avec L19/t4 |

## Non contrôlé

- Lecteur d'écran réel (NVDA, VoiceOver) : seules les règles axe et les noms accessibles.
- Espacements de texte élargis (WCAG 1.4.12) et zoom de page à 400 %.
- États en cours (scan du nettoyeur, ré-analyse Ollama, import) et erreurs réseau : l'instance
  de démonstration n'a ni MBOX ni IMAP ni modèle.
- Mode clair : l'application n'a qu'un thème sombre.

## Sous-lots t1, t3, t4, t5 faits ; maquette t2 (2026-11-20)

Mesures dans Chromium sur deux instances de démonstration (base vide ; 4 offres fictives),
8 pages × 390 et 1440 px. Tests : `tests/test_revue_l19_suite.py` (12 tests, tous en échec sur
le code d'avant).

| Sous-lot | Avant | Après |
|---|---|---|
| t1 | Nœuds texte sous 12 px : 8 à 84 par page (10 à 11,9 px) ; `text-xs` Tailwind 10,5 px | 0 sur les 16 couples page × largeur ; plus aucune taille sous `0.75rem`, `code` en `max(0.75rem, 0.85em)`, `text-xs` à 12 px |
| t3 | Base vide : « Aucune offre ne matche ce filtre. » ; « triées par score · desc » | Base vide : « Aucune offre pour l'instant. » et un bouton « Nouveaux mails » (même formulaire que celui du haut, suivi affiché sous le bouton) ; filtre trop strict : « Aucune offre ne correspond à ces filtres, sur N offres en tout. Tout afficher » ; « triées par score décroissant » |
| t4 | 390 px : tableau de 370 px dans un cadre de 318, colonne Expéditeur coupée ; 1440 px : tableau borné à 760 px dans un cadre de 1092 | Sous 600 px, une carte par règle (« Règle n », Expéditeur puis Objet), 320 / 320 px ; 1440 px : 1092 / 1092 px |
| t5 | Cases « Je confirme » 13 × 13 px ; en-tête « Backups Thunderbird » 17 px de haut (et titre centré par le marqueur ▸) | Lignes de confirmation de 44 px de haut (libellé compris), case de 20 px ; en-tête de 44 px, titre à gauche |

**t2, maquette seulement** : `docs/maquettes/L19-t2-filtres-replies.html` (page du tableau de bord
figée, données fictives, styles proposés dans la page). Au téléphone (≤ 600 px de large, ou
≤ 500 px de haut en paysage), formulaire et raccourcis passent derrière un en-tête « Filtres »
replié, qui dit combien de filtres sont actifs. Début de la liste : 390 × 844, 1 406 → 804 px
(note de maquette comprise) ; 844 × 390, 1 226 → 688 px. Questions pour Sylvain : replier aussi
en paysage ? garder les raccourcis visibles hors du repli ? À 390 px, les 4 cartes de compteurs
occupent encore ~340 px avant la liste : les compacter serait un autre sous-lot.

Non vérifié ici : lecteur d'écran réel, texte agrandi à 200 % sur les nouveaux écrans (couvert
seulement pour la barre latérale par `tests/test_texte_agrandi.py`), relève réelle lancée depuis
le bouton de l'état vide (instance sans MBOX).
