# JobMail Assistant pour Thunderbird

Extension experimentale qui lit les messages selectionnes dans Thunderbird et
les envoie au serveur local JobMail (`http://127.0.0.1:8765`). Elle ne modifie
pas les fichiers MBOX et ne deplace aucun mail.

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

## Intention

Thunderbird reste responsable de la lecture des messages. JobMail reste le
moteur local de filtrage, extraction et stockage. Cela evite de modifier les
boites MBOX pendant que Thunderbird les utilise.
