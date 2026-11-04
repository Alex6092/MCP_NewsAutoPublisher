# NewsAutoPublisher

Plugin **Claude Code** pour communiquer régulièrement sur tes projets (Exode, plugins Unreal…) :
depuis n'importe quelle session de développement, tu dis **« publie une news sur ce qu'on vient de faire »**.
Claude prépare alors :

1. des **brouillons** de posts adaptés à **Discord**, **X** et **YouTube Shorts**, dans chaque langue
   du projet, à partir de l'historique git ;
2. un **short vertical** 1080×1920 avec :
   - des rushes capturés automatiquement (OBS ou capture de fenêtre) ;
   - une voix off (Piper en local, ElevenLabs, ou ta propre voix) ;
   - des sous-titres mot à mot et une musique atténuée sous la voix ;
3. une **prévisualisation** HTML locale.

**Rien n'est publié sans ton accord explicite.**

```
Session Claude Code (dépôt Exode, plugin UE…)
 └─ « publie une news »
     └─ skill news ──► sous-agent news-producer (arrière-plan, contexte séparé)
          │             git log ▸ angle ▸ textes ▸ captures ▸ voix ▸ montage ▸ preview.html
          ▼
     tu relis la prévisualisation ─► « publie »
          ▼
     skill publish ─► Discord (webhook) · X (éditeur prérempli) · YouTube (upload guidé)
```

## Ce que fait chaque plateforme

| Plateforme | Mode | Coût | Ce qui se passe |
|---|---|---|---|
| Discord | webhook | gratuit | Publication automatique : embed + short joint (version ≤ 10 Mo générée automatiquement). |
| X | `intent` | gratuit | L'éditeur X s'ouvre prérempli dans ton navigateur. Tu glisses le short, tu cliques « Poster », puis tu donnes l'URL à Claude. |
| YouTube | `manual` | gratuit | YouTube Studio s'ouvre, le dossier du MP4 aussi. Le titre est dans le presse-papiers, le reste dans `youtube.txt`. |

Pourquoi X et YouTube ne sont pas 100 % automatiques :

- **X** : l'API est payante depuis février 2026 (environ 0,015 $ par post, environ 0,20 $ avec un
  lien). Automatiser la page web est interdit par les conditions d'X, avec un risque de suspension
  du compte. Le mode API, avec un plafond de budget, est prévu en option (phase 3).
- **YouTube** : sans audit de conformité de Google, les vidéos envoyées par l'API restent bloquées
  en privé. Le mode API arrivera quand l'audit sera obtenu (phase 3).

## Installation (Windows)

### 1. Prérequis

Dans PowerShell :

```bash
winget install astral-sh.uv
```

```bash
winget install Gyan.FFmpeg
```

Git est déjà installé si tu développes avec Claude Code. Redémarre ensuite le terminal ou Claude
Code pour que `uv` et `ffmpeg` soient dans le PATH. Python n'est pas nécessaire : `uv` télécharge
la bonne version.

Facultatif, mais recommandé pour les captures : **OBS Studio 28+**.

1. Ouvre *Outils > Paramètres du serveur WebSocket*.
2. Coche *Activer le serveur WebSocket* et note le mot de passe.
3. Pour sauvegarder les « 30 dernières secondes » à la demande : *Paramètres > Sortie > Tampon de
   relecture*.

### 2. Installer le plugin

Dans Claude Code :

```
/plugin marketplace add Alex6092/MCP_NewsAutoPublisher
/plugin install news-autopublisher@alex6092
```

Au premier lancement, `uv` installe les dépendances (environ 1 minute). Si le serveur MCP n'a pas
le temps de démarrer, ouvre `/mcp` et choisis *Reconnect* : la deuxième fois est instantanée.
Tu peux aussi définir `MCP_TIMEOUT=120000` dans ton environnement.

### 3. Configurer

Demande à Claude : **« initialise la config NewsAutoPublisher »** (outil `init_config`). Cela crée
`%USERPROFILE%\.newsautopublisher\` avec :

- `config.yaml` : tes projets (chemin du dépôt local, langues, ton, liens, hashtags, couleurs,
  logo, musiques, fenêtre ou scène OBS à capturer) et tes canaux. Un exemple pour Exode et les
  deux plugins est fourni.
- `.env` : les **secrets**. Ce fichier ne quitte pas ton PC ; ne le mets jamais dans un dépôt.
  - `DISCORD_WEBHOOK_…` : dans Discord, *Paramètres du salon > Intégrations > Webhooks > Nouveau
    webhook > Copier l'URL*.
  - `OBS_WEBSOCKET_PASSWORD`.
  - `ELEVENLABS_API_KEY` et `ELEVENLABS_VOICE_ID` (facultatif).

Les modifications sont prises en compte sans redémarrer. Demande ensuite **« statut
NewsAutoPublisher »** (outil `status`) pour vérifier ffmpeg, OBS, les dépôts et la présence des
secrets. Les valeurs des secrets ne sont jamais affichées.

Pour placer les données ailleurs, définis la variable d'environnement `NAP_DATA_DIR`.

## Utilisation

- **Préparer** : « publie une news sur ce qu'on vient de faire », ou `/news-autopublisher:news exode quêtes`.
  - Le sous-agent travaille en arrière-plan, puis ouvre la prévisualisation.
- **Captures** : jeu ou éditeur ouvert, Claude peut faire une capture d'écran, enregistrer une
  séquence pendant que tu joues (« enregistre 20 s ») ou sauvegarder le replay OBS.
  - Tu peux aussi lui donner des fichiers : clips ShadowPlay, rendus Unity Recorder ou Movie Render Queue.
- **Ta voix** : « je veux enregistrer la voix moi-même ».
  1. Claude te donne le script numéroté et l'emplacement où déposer le fichier.
  2. Après l'enregistrement : « j'ai enregistré la voix » → nettoyage, normalisation, sous-titres
     calés, montage.
- **Valider** : relis la prévisualisation, puis « publie », ou « change le titre X par… ».
  - Le skill `publish` approuve, publie et enregistre les liens.

### Voix

- **Piper** (par défaut) : local et gratuit.
  - La voix est téléchargée depuis Hugging Face au premier usage (`fr_FR-siwis-medium`,
    `en_US-lessac-medium`).
  - Autres voix : <https://huggingface.co/rhasspy/piper-voices>.
- **ElevenLabs** : voix très naturelles (payant). Renseigne la clé et l'id de voix, puis mets
  `voice.engine: elevenlabs` dans le projet.
- **Ta voix** :
  - Par défaut, les sous-titres sont calés grâce aux pauses entre les phrases.
  - Pour un calage mot à mot précis, installe faster-whisper : la commande exacte est donnée par
    l'outil `status`.

## Développement

```bash
cd plugins/news-autopublisher/server
```

```bash
uv run --group dev pytest
```

Le dossier contient :

- `plugins/news-autopublisher/server/src/newsautopublisher/` : le serveur MCP Python (SDK `mcp` 2.x).
  - `service.py` : logique métier.
  - `server.py` : outils MCP.
  - `video/` : montage ffmpeg et sous-titres ASS.
  - `voice/` : Piper, ElevenLabs, voix enregistrée.
  - `capture/` : OBS, ffmpeg gdigrab/ddagrab.
  - `publishers/` : Discord, X intent, YouTube manuel.
- `plugins/news-autopublisher/skills/` : skills `news` (préparation, exécutée dans le sous-agent)
  et `publish` (validation et publication).
- `plugins/news-autopublisher/agents/news-producer.md` : le sous-agent, qui n'a pas accès aux
  outils de publication.

Variables utiles :

- `NAP_DRY_RUN=1` : publication simulée.
- `NAP_NO_OPEN=1` : n'ouvre ni navigateur ni Explorateur.
- `NAP_DATA_DIR` : dossier de données.

## Feuille de route

1. ✅ MVP : brouillons, validation (limites, fuites de secrets), prévisualisation, Discord, X intent.
2. ✅ Shorts : captures OBS / fenêtre, Piper, ta voix, montage, YouTube manuel.
3. ⏳ Options : X API avec plafond de budget, YouTube API (après audit), bot Discord pour le crosspost.
4. ⏳ Captures pilotées par les moteurs :
   - Unreal : Movie Render Queue en ligne de commande, `HighResShot` ;
   - Unity : mode `-autocapture` du build ou Unity Recorder.

Police incluse : Inter (SIL Open Font License 1.1).
