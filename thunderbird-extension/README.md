# JobMail Assistant pour Thunderbird

Extension experimentale qui lit les messages selectionnes dans Thunderbird et
les envoie au serveur local JobMail (`http://127.0.0.1:8765`). Elle evite les
modifications MBOX directes : Thunderbird lit et deplace les messages via ses
propres API, JobMail decide quoi importer ou nettoyer.

## Utilisation

1. Lancer JobMail local :

   ```bash
   cd /home/sylvain_ladoire/projects/developpeur/jobmail-assistant
   .venv/bin/python -m jobmail serve
   ```

2. Dans Thunderbird, charger temporairement le dossier `thunderbird-extension`
   comme extension de developpement.
3. Selectionner un ou plusieurs mails, puis utiliser le bouton JobMail ou le
   menu contextuel `Envoyer vers JobMail`.
4. Pour automatiser doucement, utiliser `Importer les non lus`, ou activer
   `Import auto`. L'extension cherchera seulement les mails non lus recents et
   laissera JobMail dedupliquer cote serveur.
5. `Aperçu nettoyage` donne une idee du nettoyage possible : JobMail renvoie le
   nombre de candidats et la fenetre en affiche un extrait (8 au plus). C'est
   un apercu seulement : il ne deplace rien et ne prepare aucun deplacement.
   L'anciennete et la limite de scan viennent de la configuration JobMail.
6. Pour deplacer des mails, passer par l'interface JobMail : dans `/cleaner`,
   lancer le scan, cocher les mails voulus, cocher `Rapport relu`, puis cliquer
   `Confier la sélection à l'extension Thunderbird`. Ensuite seulement,
   `Corbeille scan JobMail` recupere cette selection confirmee, retrouve les
   messages dans Thunderbird par `Message-Id` seulement, puis deplace ceux qui
   sont resolus. Sans selection confirmee, le bouton ne deplace rien. La demande
   sert une seule fois : JobMail l'oublie des qu'il l'a remise a l'extension
   (pour rejouer, confirmer a nouveau dans `/cleaner`) ; un nouveau scan
   l'annule aussi.

## Intention

Thunderbird reste responsable de la lecture des messages. JobMail reste le
moteur local de filtrage, extraction et stockage. Cela evite de modifier les
boites MBOX pendant que Thunderbird les utilise.

## Limites connues

- La resolution des candidats JobMail ne passe que par le `Message-Id` : si un
  message a ete deplace, supprime, n'a pas de `Message-Id` ou si celui-ci
  differe, l'extension le signale comme introuvable et ne le remplace jamais
  par un autre mail (aucun repli par sujet, expediteur ou date).
- L'ancien bouton `Corbeille candidats` est retire : il envoyait a la corbeille
  tous les candidats du scan de l'extension (jusqu'a 500, dont 8 affiches), sans
  selection mail par mail. Seuls partent des mails vus et confirmes.
- `Corbeille scan JobMail` est le seul bouton qui deplace ; il agit seulement sur la selection confirmee dans
  l'ecran `/cleaner` de JobMail (jamais sur tous les candidats des scans) ;
  les exclusions et les cases decochees sont respectees.
- Ce chemin ne cree pas de sauvegarde `.mbox` : c'est Thunderbird qui deplace
  vers sa corbeille.
- Le nettoyage reste toujours manuel et demande confirmation.
