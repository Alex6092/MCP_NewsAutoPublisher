# Règles par plateforme

## Discord (webhook)

- Limites :
  - `content` : 2000 caractères ;
  - titre d'embed : 256 caractères ;
  - description d'embed : 4096 caractères ;
  - fichiers : 10 Mo par défaut (ou `max_upload_mb` du canal).
- Markdown accepté : `**gras**`, `*italique*`, `` `code` ``, `[texte](https://lien)`, titres `##`
  et puces `-`.
- Structure qui marche :
  - titre : bénéfice ou nouveauté en moins de 8 mots, un emoji au maximum ;
  - accroche : une phrase sur ce qui change pour le joueur ou le développeur ;
  - 3 à 5 puces concrètes, avec des chiffres quand c'est possible ;
  - appel à l'action : tester, donner un avis, réagir, suivre le lien.
- Aucune mention `@everyone` dans le texte : les mentions sont réglées dans la config du canal.
- Le short (version allégée) est joint automatiquement. `image` sert à afficher une capture dans l'embed.

## X

- Limite de 280 caractères **pondérés** :
  - chaque URL compte 23 ;
  - les emoji et le CJK comptent 2 ;
  - le lien du champ `url` ajoute 24 (espace compris).
- La première ligne décide de tout : nouveauté ou bénéfice tout de suite, pas de « Bonjour à tous ».
- 1 ou 2 hashtags pertinents maximum, en fin de post, et 0 à 2 emoji.
- Pas de fil de plusieurs posts (non pris en charge en mode intent).
- Mode intent :
  - l'utilisateur voit l'éditeur prérempli et y glisse lui-même le short ou une image ;
  - le lien affiche une carte d'aperçu si la page cible a une image Open Graph.

## YouTube Shorts

- Format :
  - vidéo verticale 9:16 de 180 s maximum ;
  - viser 20 à 45 s, car la rétention prime ;
  - l'accroche visuelle et orale doit tomber dans les 2 premières secondes.
- Titre :
  - 100 caractères maximum, idéalement moins de 60 ;
  - les mots clés d'abord ;
  - `#Shorts` dans le titre ou la description ;
  - jamais de `<` ni de `>`.
- Description :
  - 1 ou 2 phrases de contexte ;
  - les liens (Discord, Fab, site) ;
  - 3 à 5 hashtags.
- Tags : 5 à 10 mots clés (nom du projet, moteur, genre), 500 caractères au total.
- Zone de sécurité : le bas de l'écran (environ 20 %) et la droite sont masqués par l'interface.
  Le gabarit place déjà les textes au bon endroit.

## Bilingue (plugins Unreal)

- Un brouillon par langue, chacun écrit nativement.
- En anglais : vocabulaire Unreal standard (Blueprint, Data Asset, Gameplay Tags…) et bénéfices
  pour le studio (temps gagné, intégration sans C++).
