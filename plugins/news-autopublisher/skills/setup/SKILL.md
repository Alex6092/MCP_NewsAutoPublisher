---
name: setup
description: Assistant d'installation et de configuration de NewsAutoPublisher. Détecte les projets de l'utilisateur, pré-remplit config.yaml, aide à brancher Discord / X / YouTube, prépare Unity et Unreal pour les captures, et fait un premier test. À utiliser pour « installe / configure NewsAutoPublisher », « ajoute un projet », « branche mon Discord », ou quand status signale une configuration absente ou incomplète.
argument-hint: "[projet ou plateforme à configurer]"
---

# Installer et configurer NewsAutoPublisher

Demande : $ARGUMENTS

Objectif : que l'utilisateur ait le moins possible à taper. Tu détectes, tu proposes des valeurs, il
confirme. Pose tes questions avec l'outil de questions à choix quand il est disponible : deux à
quatre options, ta recommandation en premier.

## 0. État des lieux

`status`. S'il n'y a pas de configuration, `init_config`, puis continue : ne laisse pas
l'utilisateur remplir le fichier à la main. Si l'utilisateur ne demande qu'un ajout précis (un
projet, un canal), va directement à l'étape concernée.

## 1. Projets

1. `discover_projects`. Si l'utilisateur a cité des dossiers, passe-les en `roots`.
2. Présente les dépôts trouvés : nom, moteur et version, dernier commit, déjà configuré ou non.
   Demande lesquels suivre.
3. Pour chaque projet retenu, propose une entrée complète, puis enregistre-la avec
   `edit_config("projects", <clé courte>, {...})` :
   - `name`, `repo_path` ;
   - `engine` : `unity`, `unreal`, `web` ou `other` ;
   - `languages` : demande-les. Habituellement FR pour un jeu destiné à une communauté
     francophone, EN + FR pour un produit vendu sur Fab ;
   - `pitch` : une phrase par langue, à rédiger d'après le README du dépôt si tu peux le lire ;
   - `tone`, `audience` ;
   - `links` : site, Discord, Fab, Steam, déduits du README ou du remote ;
   - `hashtags` : 2 à 4 ;
   - `changelog` s'il existe ;
   - `unity.project_path` ou `unreal.uproject` d'après `engine_path`.
   Les canaux viennent à l'étape 2.
4. Supprime les projets d'exemple inutilisés : `edit_config("projects", "<clé>", remove=true)`.
   Si un canal d'exemple bloque la suppression, supprime d'abord le projet, puis le canal.

## 2. Canaux de publication

Demande les plateformes voulues, puis pour chacune :

- **Discord**, un webhook par salon :
  1. Explique en une ligne : *Paramètres du salon > Intégrations > Webhooks > Nouveau webhook >
     Copier l'URL*.
  2. Crée le canal : `edit_config("channels", "discord.<projet>", {"type": "discord_webhook",
     "label": …, "webhook_env": "DISCORD_WEBHOOK_<PROJET>"})`.
  3. Pour le secret, recommande `open_config_file("env")` : l'utilisateur colle l'URL dans `.env`,
     et elle ne passe pas par la conversation. S'il colle quand même l'URL dans le chat, enregistre-la
     avec `set_secret` et ne la répète jamais.
  4. `test_channel(..., send_test=true)` seulement avec son accord : le message est visible dans le salon.
- **X** :
  - Par défaut, `mode: intent` : gratuit, rien à brancher.
  - Mentionne l'option API payante (clés, budget mensuel), sans la pousser.
- **YouTube** :
  - Par défaut, `mode: manual`.
  - Signale qu'il faudra un projet Google audité pour l'API, et qu'il vaut mieux lancer la demande tôt.
- Rattache les canaux au projet par langue : `edit_config("projects", "<projet>", {"channels":
  {"fr": [...], "en": [...]}})`.

## 3. Captures et voix (facultatif, proposer)

- Moteur :
  - `engine_setup(project)` pour le diagnostic ;
  - `engine_setup(project, apply=true)` seulement avec l'accord de l'utilisateur, car il modifie
    le dépôt (manifest Unity, `.uproject`) ;
  - pour Unity, demande le chemin du build si l'utilisateur veut des captures automatiques sans
    toucher à son éditeur : `unity.build_exe` ;
  - pour Unreal, renseigne `unreal.editor_cmd` (UnrealEditor-Cmd.exe de sa version) et
    `default_map`.
- OBS : demande s'il l'utilise. Si oui, mot de passe WebSocket via `.env` (`OBS_WEBSOCKET_PASSWORD`).
- Voix : Piper par défaut ; propose ElevenLabs ou sa propre voix.

## 4. Vérification et premier essai

1. `status` : résume en quelques lignes ce qui est prêt et ce qui manque.
2. Propose un premier essai réel, Discord uniquement sur un salon de test : « prépare une news de
   test », puis `publish` limité à ce canal. C'est le meilleur moyen de valider l'installation.

Règles :

- Ne modifie jamais `monthly_budget_usd`, `audited` ni `capture.engine_auto` sans le demander
  explicitement.
- Ne recopie jamais un secret dans tes réponses.
