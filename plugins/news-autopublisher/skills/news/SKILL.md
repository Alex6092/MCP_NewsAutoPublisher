---
name: news
description: Prépare une news de projet (posts Discord / X / YouTube + short vertical avec voix off et sous-titres) à partir de ce qui vient d'être développé, puis la soumet à validation. À utiliser quand l'utilisateur demande de « publier une news », « annoncer », « faire un devlog », « communiquer sur ce qu'on vient de faire » ou « faire un short ». Passe en argument le projet si connu et un résumé concret du travail réalisé dans la session (fonctionnalités, captures disponibles).
argument-hint: "[projet] [sujet ou résumé de ce qui a été fait]"
context: fork
agent: news-producer
---

# Préparer une news

Tu prépares une news **en brouillon**. Tu ne publies jamais : la validation et la publication
se font ensuite dans la session principale (skill `publish`).

Demande reçue : $ARGUMENTS

## 1. Projet et matière première

1. Identifie le projet : argument explicite, sinon `detect_project` avec le dossier courant,
   sinon `list_projects` et choisis d'après la demande. Si c'est ambigu, arrête-toi et demande.
2. `list_projects` donne le ton, le public, les liens, les hashtags et les langues du projet.
3. `collect_changes(project)` (par défaut depuis la dernière news publiée). Croise avec le
   résumé fourni en argument : c'est lui qui dit ce qui compte pour l'utilisateur.
4. Lis au besoin quelques fichiers du dépôt pour comprendre une fonctionnalité, sans plus.

## 2. Choisir l'angle

- **Une news = une idée forte.** Ce que le joueur ou le développeur y gagne, pas la liste des commits.
- Écarte le bruit : refactors, CI, typos, dépendances, tests internes.
- **Confidentialité** : aucun chemin local, nom de machine, e-mail, IP, clé, nom d'élève, ni
  détail de sécurité ou de serveur. Pas de date de sortie ou de promesse que l'utilisateur n'a pas donnée.
- Rien d'intéressant à montrer ? Dis-le et propose plutôt d'attendre ou un format « coulisses ».

## 3. Rédiger (un brouillon par langue du projet)

Respecte `references/platforms.md` et le ton du projet (`references/tone-exode.md`,
`references/tone-plugins.md`). Pour un projet bilingue, écris chaque langue nativement : pas
de traduction littérale.

- **Discord** : `title` accrocheur + `description` en Markdown (3 à 5 puces concrètes, puis un
  appel à l'action) + `url`. Le short y est joint automatiquement.
- **X** : un seul post de 280 caractères pondérés maximum. Accroche dès les premiers mots,
  1 ou 2 hashtags, lien dans `url`.
- **YouTube** : titre ≤ 100 caractères avec `#Shorts`, description avec les liens et 3 à 5 hashtags.

Crée le brouillon avec `create_draft` puis lis `issues`. Corrige toutes les erreurs avec
`update_draft`. Corrige aussi les avertissements pertinents.

## 4. Short vertical (20 à 45 s)

Suis `references/short-recipes.md`. En résumé :

1. **Rushes**, par ordre de préférence :
   - `list_media(project)` : médias récents déjà capturés.
   - Si le jeu ou l'éditeur est ouvert (`list_windows`, Windows), `capture_screenshot` ou
     `start_recording`/`stop_recording`. Pour un clip de gameplay, demande à l'utilisateur de jouer
     la séquence, ou de déclencher `save_replay` si le tampon de relecture d'OBS tourne.
   - Fichiers indiqués par l'utilisateur : `import_media`.
   - Sans rushes : scènes `title`/`text` sur fond de marque, et dis-le dans ton rapport.
2. **Script voix off** : 50 à 110 mots, phrases courtes, à l'oral, accroche dans la première
   phrase, appel à l'action à la fin.
3. **Voix**, selon le moteur du projet :
   - `generate_voiceover` pour Piper ou ElevenLabs.
   - Si l'utilisateur veut **sa voix** (engine `recorded`) : `prepare_voice_recording`, puis
     arrête-toi. Rends le script numéroté et l'emplacement du fichier attendu. Le montage se fera
     après son enregistrement, via `import_voice_recording` puis `render_short`.
4. **Storyboard** :
   - `title` (accroche, 2 s) ;
   - 2 à 4 scènes `clip`/`image` avec un bandeau court (`text` ≤ 30 caractères) ;
   - `outro` (appel à l'action + `subtext` = lien court).
   - Les durées s'ajustent toutes seules à la voix (`fit_to_voice`). Pour une capture 16:9,
     `zoom` entre 1.2 et 1.5 remplit mieux l'écran vertical.
5. `render_short(draft_id, storyboard)`. Si le rendu échoue, lis l'erreur, corrige le storyboard
   et relance une seule fois.

## 5. Rendre la main

1. `render_preview(draft_id)` : ouvre la page de prévisualisation.
2. Réponds avec un rapport court :
   - id du ou des brouillons ;
   - sujet et angle retenus ;
   - chemin du short et sa durée ;
   - problèmes restants ;
   - ce qui manque, s'il y a lieu (rushes, enregistrement de voix).
3. Termine par : « Relis la prévisualisation ; dis-moi “publie” ou ce qu'il faut changer. »

N'appelle **jamais** `approve_draft`, `publish` ni `mark_published`.
