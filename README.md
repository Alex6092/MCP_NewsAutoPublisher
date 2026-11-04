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
     skill publish ─► Discord (webhook, crosspost) · X (éditeur prérempli ou API) · YouTube (upload guidé ou API)
```

## Ce que fait chaque plateforme

Chaque canal choisit son mode dans `config.yaml`.

| Plateforme | Mode | Coût | Ce qui se passe |
|---|---|---|---|
| Discord | webhook | gratuit | Publication automatique : embed + short joint (version ≤ 10 Mo générée automatiquement). |
| Discord | webhook + `crosspost` | gratuit | Comme ci-dessus, puis un bot diffuse l'annonce aux serveurs abonnés au salon d'annonces. |
| X | `intent` (défaut) | gratuit | L'éditeur X s'ouvre prérempli dans ton navigateur. Tu glisses le short, tu cliques « Poster », puis tu donnes l'URL à Claude. |
| X | `api` | environ 0,015 $ par post, environ 0,20 $ avec un lien | Publication automatique avec la vidéo (720×1280). Plafond `monthly_budget_usd` : au-delà, la publication est refusée. |
| YouTube | `manual` (défaut) | gratuit | YouTube Studio s'ouvre, le dossier du MP4 aussi. Le titre est dans le presse-papiers, le reste dans `youtube.txt`. |
| YouTube | `api` | gratuit (quota Google) | Upload automatique, mise en ligne programmable (`publish_at`). **Projet Google audité obligatoire.** |

Pourquoi X et YouTube ne sont pas en API par défaut :

- **X** : l'API est payante depuis février 2026. Automatiser la page web est interdit par les
  conditions d'X, avec un risque de suspension du compte : c'est exclu.
- **YouTube** : sans audit de conformité de Google, toute vidéo envoyée par l'API reste
  **verrouillée en privé, sans recours**. Le plugin refuse donc un upload public tant que le canal
  n'a pas `audited: true`. Un upload de test en `privacy: private` reste possible.

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

Le plus simple : **`/news-autopublisher:setup`**, ou « configure NewsAutoPublisher ». L'assistant :

- détecte tes dépôts (Unity, Unreal, remote GitHub/GitLab, CHANGELOG) ;
- te propose une configuration pré-remplie pour chaque projet ;
- t'aide à brancher tes webhooks Discord, en ouvrant `.env` pour que tu y colles les URL toi-même ;
- prépare les moteurs ;
- termine par un message de test sur un salon de ton choix.

Les modifications de `config.yaml` conservent tes commentaires, et une configuration invalide est
refusée.

À la main, si tu préfères : demande **« initialise la config NewsAutoPublisher »** (outil `init_config`). Cela crée
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

### 4. Facultatif : modes API

Chaque mode se configure une fois. Termine en demandant à Claude **« connecte le canal … »**
(outil `connect_account`), qui vérifie que tout fonctionne.

**X en mode API**

1. Crée un compte développeur sur le portail X, avec des crédits en paiement à l'usage.
2. Crée une app avec les permissions **Read and write**.
3. Dans *Keys and tokens*, génère l'*API Key and Secret* et l'*Access Token and Secret*. Si tu
   changes les permissions après coup, régénère l'Access Token.
4. Copie les 4 valeurs dans `.env` : `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET`.
5. Sur le canal X de `config.yaml`, mets `mode: api` et un plafond `monthly_budget_usd: 5`.
   - Le suivi des dépenses est une **estimation** locale (tarifs `cost_post_usd` et `cost_post_url_usd`,
     modifiables).
   - Vérifie la consommation réelle dans le portail X.

**YouTube en mode API**

1. Dans Google Cloud Console :
   - crée un projet et active **YouTube Data API v3** ;
   - configure l'écran de consentement OAuth et ajoute-toi comme utilisateur de test ;
   - crée un *ID client OAuth* de type **Application de bureau** et télécharge le JSON.
2. Enregistre ce JSON sous `%USERPROFILE%\.newsautopublisher\credentials\youtube_client_secret.json`.
3. Sur le canal YouTube, mets `mode: api`, puis demande « connecte le canal youtube.main ».
   - Le navigateur s'ouvre pour l'autorisation.
   - Avec plusieurs chaînes (compte de marque), choisis la bonne : Claude affiche celle qui est connectée.
4. **Demande l'audit** via le formulaire *YouTube API Services – Audit and Quota Extension*. Une fois
   l'audit accepté, mets `audited: true`. Avant ça, reste en `mode: manual` pour les vidéos publiques.

**Discord : crosspost des annonces**

1. Dans le portail développeur Discord, crée une application, puis un bot. Copie son jeton dans
   `DISCORD_BOT_TOKEN`.
2. Invite le bot sur ton serveur (OAuth2 > URL Generator, scope `bot`) avec les permissions
   *Voir les salons*, *Envoyer des messages* et *Gérer les messages*.
3. Mets `crosspost: true` sur le canal Discord. Ce doit être un **salon d'annonces**.
4. Demande « connecte le canal discord.exode ». Le bot se connecte une première fois, comme Discord
   l'exige, et Claude vérifie le type de salon.

### 5. Facultatif : captures pilotées par le moteur

Claude capture lui-même des plans propres de tes jeux : rendu à temps fixe, résolution verticale
exacte, sans interface. **Aucun plan n'est à placer à la main.** Claude choisit les objets à montrer
d'après ce qui vient d'être développé, puis demande un mouvement de caméra :

- orbite ;
- travelling avant ;
- recul ;
- survol ;
- plan fixe ;
- suivi d'un personnage (Unity uniquement).

Le trajet est calculé à partir de la taille de l'objet.

**Préparation, une seule fois** : demande à Claude « prépare Exode (ou le projet du plugin) pour les
captures » (outil `engine_setup`).

- Unity : il ajoute le package de capture au `Packages/manifest.json` et vérifie que les scènes sont
  en texte (« Force Text »).
- Unreal : il active dans le `.uproject` les plugins Python Editor Script, Sequencer Scripting,
  Editor Scripting Utilities et Movie Render Queue. Redémarre l'éditeur ensuite.

Puis renseigne dans `config.yaml` :

- Unity :
  - `unity.build_exe` : le chemin de ton build, pour les captures automatiques sans toucher à ton éditeur ;
  - `capture.window_title` si besoin.
- Unreal :
  - `unreal.editor_cmd` (chemin de `UnrealEditor-Cmd.exe`) ;
  - `unreal.uproject` ;
  - `unreal.default_map`.

**Quand Claude capture-t-il sans te demander ?** Règle `capture.engine_auto` du projet :

| Valeur | Rendu Unreal | Build Unity | Éditeur Unity ouvert |
|---|---|---|---|
| `background` (défaut) | automatique | automatique | il te demande d'abord |
| `always` | automatique | automatique | automatique (mode Play) |
| `never` | il te demande | il te demande | il te demande |

Si le build Unity est plus ancien que ton dernier commit, Claude te le signale : les nouveautés
pourraient ne pas être à l'image.

**Unity (Exode) : comment ça marche**

- Claude lit les noms d'objets directement dans les fichiers `.unity` (`list_engine_targets`).
- Il envoie au package un plan procédural, par exemple « orbite autour de `QuestBoard` ». Le
  package capture :
  - depuis ton éditeur ouvert, qui passe en mode Play puis rouvre ta scène ;
  - ou depuis ton build, lancé avec `-napRequest`. La scène doit alors être dans les Build Settings.
- Si le monde d'Exode a besoin d'un serveur ou d'une connexion, branche un démarrage hors ligne via
  `NapCapture.PrepareWorld`. Voir le README du package dans `engines/unity/com.newsautopublisher.capture/`.
- Tu peux toujours ajouter des plans faits main pour les vues soignées : clic droit *NewsAutoPublisher
  > Nap Shot*, puis « Ajouter un point depuis la vue Scène ».

**Unreal (plugins) : comment ça marche**

- Claude lance `UnrealEditor-Cmd.exe` avec un script Python (`-ExecutePythonScript`), dans un
  processus séparé : ton éditeur peut rester ouvert. Le script :
  1. charge la map et trouve l'acteur ;
  2. génère une Level Sequence (CineCamera verticale, trajectoire, coupe caméra) dans
     `/Game/NewsAutoPublisher/Auto` ;
  3. configure Movie Render Queue sans preset (1080×1920, PNG) ;
  4. rend la séquence et referme Unreal.
- `list_engine_targets` liste les acteurs d'une map de la même façon.
- Les Level Sequences faites à main se déclarent dans `unreal.shots`.
- `render_mode: cli` utilise l'ancien rendu `-game -LevelSequence -MoviePipelineConfig`, avec un
  preset. C'est la solution de repli si le mode Python pose problème sur ta version.
- Compte 3 à 20 minutes par rendu, démarrage d'Unreal compris.
- Les démonstrations dans l'éditeur (graphes, panneaux) restent mieux servies par
  `capture_screenshot` et `start_recording` sur la fenêtre « Unreal Editor ».

## Utilisation

- **Préparer** : « publie une news sur ce qu'on vient de faire », ou `/news-autopublisher:news exode quêtes`.
  - Le sous-agent travaille en arrière-plan, puis ouvre la prévisualisation.
- **Captures** : jeu ou éditeur ouvert, Claude peut faire une capture d'écran, enregistrer une
  séquence pendant que tu joues (« enregistre 20 s ») ou sauvegarder le replay OBS.
  - Tu peux aussi lui donner des fichiers : clips ShadowPlay, rendus Unity Recorder ou Movie Render Queue.
- **Plans moteur** : rien à demander. Pour un devlog sur une nouveauté, Claude filme lui-même les
  objets concernés (orbite, survol…) quand ta règle le permet. Sinon, il te propose la capture. Tu
  peux aussi la demander : « fais un devlog avec un survol du hub ».
- **Ta voix** : « je veux enregistrer la voix moi-même ».
  1. Claude te donne le script numéroté et l'emplacement où déposer le fichier.
  2. Après l'enregistrement : « j'ai enregistré la voix » → nettoyage, normalisation, sous-titres
     calés, montage.
- **Valider** : relis la prévisualisation, puis « publie », ou « change le titre X par… ».
  - Pour un projet bilingue, la même page montre toutes les langues : **un seul « publie »** pour tout.
  - X et YouTube en mode gratuit : poste, puis dis simplement **« c'est posté »**. Pas besoin de
    recopier les URL.
- **Suggestions automatiques** : Claude te propose une news (sans jamais la lancer seul) dans deux cas :
  - un nouveau tag n'a pas été annoncé ;
  - beaucoup de commits se sont accumulés depuis la dernière news (8 par défaut, au plus une fois
    par jour).

  Il te rappelle aussi les brouillons en attente au démarrage d'une session. Réponds « pas
  maintenant » pour les mettre en pause une semaine. Réglages : section `hints` de `config.yaml`.

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
  - `engines/` : captures Unity (protocole du package NapShot) et Unreal (Movie Render Queue).
  - `publishers/` : Discord (webhook, crosspost par bot), X (intent, API), YouTube (manuel, API).
- `plugins/news-autopublisher/skills/` : skills `news` (préparation, exécutée dans le sous-agent),
  `publish` (validation et publication) et `setup` (assistant d'installation).
- `plugins/news-autopublisher/hooks/hooks.json` : suggestions proactives au démarrage de session et
  après `git tag`, `push` et `commit`. Elles sont asynchrones et ne ralentissent jamais la session.
- `plugins/news-autopublisher/agents/news-producer.md` : le sous-agent, qui n'a pas accès aux
  outils de publication.
- `engines/unity/com.newsautopublisher.capture/` : le package Unity (C#) à installer dans tes projets.

Variables utiles :

- `NAP_DRY_RUN=1` : publication simulée.
- `NAP_NO_OPEN=1` : n'ouvre ni navigateur ni Explorateur.
- `NAP_DATA_DIR` : dossier de données.

## Feuille de route

1. ✅ MVP : brouillons, validation (limites, fuites de secrets), prévisualisation, Discord, X intent.
2. ✅ Shorts : captures OBS / fenêtre, Piper, ElevenLabs, ta voix, montage, YouTube manuel.
3. ✅ Modes API : X API avec plafond de budget, YouTube API (après audit) avec mise en ligne
   programmée, crosspost Discord par bot.
4. ✅ Captures pilotées par les moteurs :
   - Unity : package NapShot, depuis l'éditeur ou un build ;
   - Unreal : Movie Render Queue en ligne de commande.
5. ✅ Automatisation des captures :
   - plans procéduraux autour d'objets ou d'acteurs, sans placement manuel ;
   - séquences Unreal générées par script ;
   - préparation des projets (`engine_setup`) ;
   - règle de déclenchement automatique.

6. ✅ Moins de friction :
   - assistant d'installation ;
   - une seule validation par nouveauté (toutes langues) ;
   - « c'est posté » sans URL ;
   - suggestions proactives de news.

Pistes suivantes :

- planification des publications (calendrier) ;
- statistiques de vues et de réactions ;
- sous-titres multilingues sur une même vidéo.

Police incluse : Inter (SIL Open Font License 1.1).
