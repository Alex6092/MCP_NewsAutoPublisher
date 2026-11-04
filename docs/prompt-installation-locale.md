# Installer et tester NewsAutoPublisher avec Claude Code (session locale)

Ce prompt lance une session Claude Code sur ton PC Windows. Claude t'aide à installer, configurer
et tester **toutes** les briques de NewsAutoPublisher, puis corrige les bugs qu'il rencontre.

## 1. Lancer la session

Clone le dépôt, puis lance Claude Code dedans en chargeant le plugin depuis le clone. Ainsi,
chaque correctif fait pendant les tests est pris en compte au redémarrage de la session.

```bash
git clone https://github.com/Alex6092/MCP_NewsAutoPublisher.git D:/Dev/MCP_NewsAutoPublisher
```

```bash
cd D:/Dev/MCP_NewsAutoPublisher
```

```bash
claude --plugin-dir ./plugins/news-autopublisher
```

Si l'option `--plugin-dir` n'est pas reconnue par ta version de Claude Code, lance simplement
`claude` : le prompt prévoit l'installation par la marketplace locale.

## 2. Coller le prompt

````markdown
Tu vas m'aider à installer, configurer et tester NewsAutoPublisher sur ce PC Windows.

Le dossier courant est le dépôt du projet :
- `plugins/news-autopublisher/` : le plugin Claude Code (serveur MCP Python lancé par uv, skills news / publish / setup, sous-agent news-producer, hooks de suggestions) ;
- `engines/unity/com.newsautopublisher.capture/` : le package Unity de capture ;
- `README.md` : la documentation complète. Lis-la d'abord, ainsi que les SKILL.md du plugin et le README du package Unity.

Le code a été développé et testé sous Linux (68 tests, avec des API et des moteurs simulés). Il n'a JAMAIS tourné sous Windows, ni avec de vrais services, ni avec Unity ou Unreal. Ton rôle : faire marcher chaque brique pour de vrai, trouver les bugs et les corriger.

## Règles

1. Aucune publication publique sans mon accord explicite, à chaque fois. Les tests de publication se font sur un salon Discord de TEST. Pour X et YouTube, on ouvre les écrans, mais c'est moi qui décide si je poste.
2. Secrets (webhooks, clés, mots de passe) : jamais dans un dépôt, jamais recopiés dans tes réponses. Je les colle moi-même dans `%USERPROFILE%\.newsautopublisher\.env` : ouvre-le-moi avec `open_config_file("env")`.
3. Demande-moi avant :
   - de modifier un autre dépôt que celui-ci (Exode, plugins Unreal : `engine_setup` avec apply, manifest Unity, .uproject) ;
   - d'installer un logiciel ;
   - de toute dépense (X API, ElevenLabs).
4. Bugs de NewsAutoPublisher :
   - reproduis le bug, puis corrige-le dans ce dépôt, sur une branche dédiée créée depuis `main` (ex. `fix/windows-chemins`) ;
   - ajoute un test quand c'est pertinent et relance `uv run --group dev pytest` dans `plugins/news-autopublisher/server` ;
   - ne pousse et n'ouvre de PR qu'avec mon accord ;
   - après un correctif du plugin, préviens-moi : il faut redémarrer la session pour recharger le serveur MCP.
5. Tiens un journal dans `%USERPROFILE%\.newsautopublisher\journal-installation.md` : étapes faites, résultats, bugs, correctifs, reste à faire. Au début de chaque session, relis-le et reprends là où on s'est arrêtés.
6. Avance étape par étape. Pour chaque étape : ce que tu vas faire, ce que j'ai à faire (le moins possible), puis le résultat. Quand c'est possible, pose tes questions sous forme de choix.
7. Les commandes `/mcp`, `/hooks` ou `/reload-plugins`, c'est moi qui les tape : demande-le-moi.

## Étape 0 : prérequis et tests sous Windows

- Vérifie :
  - git ;
  - uv ;
  - ffmpeg et ffprobe, y compris la présence du filtre `subtitles` (libass) ;
  - la version de Claude Code.
- Propose les installations manquantes (`winget install astral-sh.uv`, `winget install Gyan.FFmpeg`) et attends mon accord.
- Lance `uv run --group dev pytest` dans `plugins/news-autopublisher/server`. Tout échec propre à Windows (chemins, encodage, ffmpeg, processus) est un bug à corriger avant d'aller plus loin.

## Étape 1 : chargement du plugin

- Vérifie que les outils `mcp__plugin_news-autopublisher_newsautopublisher__*` sont disponibles et que le skill `news-autopublisher:setup` existe.
- Sinon, installe le plugin depuis la marketplace locale (`claude plugin marketplace add .`, puis `claude plugin install news-autopublisher@alex6092`) et demande-moi de redémarrer.
- Si le serveur MCP met trop de temps au premier démarrage (installation des dépendances par uv), demande-moi un `/mcp` puis « Reconnect ».
- Appelle `status` et commente le résultat.

## Étape 2 : configuration

- Lance le skill setup. Mes projets :
  - le MMORPG Exode (Unity, dépôt GitHub privé) ;
  - les plugins Unreal Dialogue & Quest Master et Interaction Master (GitLab privé, UE 5.5 ; un projet de démo est peut-être en 5.8).
- Discord : d'abord un salon de TEST, puis `test_channel` avec un message de test.
- Pour commencer, X en mode intent et YouTube en mode manuel.

## Étape 3 : première news de bout en bout (Discord de test uniquement)

- Prépare une news sur une vraie nouveauté récente d'un de mes projets (skill news), avec un short et une voix Piper. La voix est téléchargée depuis Hugging Face la première fois.
- Vérifie :
  - la prévisualisation s'ouvre dans le navigateur ;
  - le short est correct : ouvre-le, contrôle les sous-titres accentués, l'équilibre voix / musique et la durée ;
  - la version Discord fait moins de 10 Mo.
- `publish` en `dry_run`, puis pour de vrai, limité au canal Discord de test.
- Sur un projet FR + EN, teste :
  - la validation unique de toutes les langues ;
  - l'ouverture de l'éditeur X et de YouTube Studio ;
  - « c'est posté » (`mark_published` sans URL).

## Étape 4 : captures et voix

- `list_windows`, `capture_screenshot`, `start_recording` / `stop_recording` (gdigrab, puis ddagrab) sur une fenêtre de jeu ou d'éditeur. Vérifie : image non noire, bonne fenêtre, mise à l'échelle Windows (125 %, 150 %).
- OBS, si je l'utilise : connexion WebSocket, capture, enregistrement, tampon de relecture.
- Ma voix :
  1. `prepare_voice_recording` ;
  2. j'enregistre deux ou trois phrases ;
  3. `import_voice_recording`, puis rendu.
  Compare le calage des sous-titres par silences et par faster-whisper (commande d'installation donnée par `status`).
- ElevenLabs seulement si je le demande.

## Étape 5 : Unity (Exode)

- `engine_setup` en diagnostic, puis avec mon accord `apply=true` (ajout du package au manifest).
- Vérifie avec moi que le package compile sans erreur dans la console Unity. Sinon, corrige le C# ici.
- Avec mon accord (`user_requested=true`), lance une capture procédurale depuis l'éditeur ouvert, par exemple une orbite autour d'un objet choisi avec `list_engine_targets`. Vérifie :
  - la vue Game est visible ;
  - les images ne sont pas noires et sont en 1080×1920 ;
  - le rendu est correct selon mon pipeline (URP, HDRP ou Built-in) ;
  - l'éditeur revient bien sur ma scène.
- Si le monde a besoin du serveur ou d'une connexion pour s'afficher, note-le : on écrira le démarrage hors ligne (`NapCapture.PrepareWorld`) dans une session sur le dépôt Exode.
- Si j'ai un build : renseigne `unity.build_exe` et teste une capture automatique sans `user_requested` (règle `engine_auto: background`). Vérifie l'avertissement de build ancien.

## Étape 6 : Unreal (plugins)

- `engine_setup`, puis avec mon accord `apply=true` (plugins Python, Sequencer Scripting, Editor Scripting, Movie Render Queue dans le .uproject). Je redémarre ensuite l'éditeur.
- `list_engine_targets` sur la map de démo (tâche de fond), puis une capture procédurale (orbite autour d'un acteur).
- En cas d'échec :
  - lis `unreal.log` et `result.json` dans le dossier de la tâche ;
  - le script `engines/nap_unreal.py` journalise chaque étape : corrige les noms d'API pour ma version ;
  - solution de repli : `render_mode: cli` avec un preset Movie Render Queue.
- Teste en 5.5, et en 5.8 si le projet de démo est dans cette version.

## Étape 7 : suggestions proactives (hooks)

- Vérifie que les hooks sont chargés : demande-moi `/hooks`.
- Vérifie qu'un tag non annoncé et une accumulation de commits déclenchent bien une suggestion. Fais-le dans un petit dépôt de test configuré temporairement, pas dans mes vrais projets.
- Vérifie que `snooze_news_hints` met bien les suggestions en pause.

## Étape 8 : options payantes ou soumises à validation (seulement si je le demande)

- X en mode API, avec un petit budget.
- YouTube en mode API : upload de test en privé tant que le projet n'est pas audité.
- Bot Discord pour le crosspost.

## Fin

Rapport final :
- ce qui marche ;
- ce qui ne marche pas ;
- les correctifs faits (branche, commits, tests ajoutés) ;
- ce qu'il reste à faire.

Propose ensuite une PR des correctifs vers `main`.

Commence par lire le README et le journal s'il existe, puis attaque l'étape 0.
````

## 3. Conseils

- Prévois plusieurs sessions : chaque correctif du plugin et chaque installation de plugin moteur
  demandent un redémarrage. Le journal permet de reprendre exactement où tu en étais : relance
  Claude Code de la même façon et dis « on reprend l'installation ».
- Garde Unity ou Unreal ouverts seulement pendant les étapes 5 et 6, et un salon Discord de test
  du début à la fin.
- Si une étape bloque trop longtemps, saute-la et note-la dans le journal. Les étapes 0 à 3
  suffisent à publier tes premières news sur Discord.
