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
6. Si le scan a deja ete lance dans l'interface JobMail, utiliser
   `Corbeille scan JobMail`. L'extension recupere le dernier rapport cleaner,
   retrouve les messages dans Thunderbird par `Message-Id`, puis deplace ceux
   qui sont resolus.

## Intention

Thunderbird reste responsable de la lecture des messages. JobMail reste le
moteur local de filtrage, extraction et stockage. Cela evite de modifier les
boites MBOX pendant que Thunderbird les utilise.

## Limites connues

- La resolution des candidats JobMail depend d'abord du `Message-Id`; si un
  message a ete deplace, supprime ou si le `Message-Id` differe, l'extension le
  signale comme introuvable.
- `Corbeille candidats` agit sur le dernier scan lance depuis l'extension.
  `Corbeille scan JobMail` agit sur le dernier scan lance depuis l'interface
  JobMail.
- Le nettoyage reste toujours manuel et demande confirmation.
