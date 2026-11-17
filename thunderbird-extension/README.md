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
5. Pour le nettoyage, utiliser d'abord `Scanner nettoyage`. JobMail renvoie les
   candidats, puis `Corbeille candidats` demande confirmation et laisse
   Thunderbird effectuer le deplacement. Le nettoyage n'est jamais automatique ;
   l'anciennete et la limite de scan viennent de la configuration JobMail.
6. Si le scan a deja ete lance dans l'interface JobMail : dans `/cleaner`,
   cocher les mails voulus, cocher `Rapport relu`, puis cliquer
   `Confier la sélection à l'extension Thunderbird`. Ensuite seulement,
   `Corbeille scan JobMail` recupere cette selection confirmee, retrouve les
   messages dans Thunderbird par `Message-Id`, puis deplace ceux qui sont
   resolus. Sans selection confirmee, le bouton ne deplace rien. La demande
   sert une seule fois ; un nouveau scan l'annule.

## Intention

Thunderbird reste responsable de la lecture des messages. JobMail reste le
moteur local de filtrage, extraction et stockage. Cela evite de modifier les
boites MBOX pendant que Thunderbird les utilise.

## Limites connues

- La resolution des candidats JobMail depend d'abord du `Message-Id`; si un
  message a ete deplace, supprime ou si le `Message-Id` differe, l'extension le
  signale comme introuvable.
- `Corbeille candidats` agit sur le dernier scan lance depuis l'extension.
  `Corbeille scan JobMail` agit seulement sur la selection confirmee dans
  l'ecran `/cleaner` de JobMail (jamais sur tous les candidats des scans) ;
  les exclusions et les cases decochees sont respectees.
- Ce chemin ne cree pas de sauvegarde `.mbox` : c'est Thunderbird qui deplace
  vers sa corbeille.
- Le nettoyage reste toujours manuel et demande confirmation.
