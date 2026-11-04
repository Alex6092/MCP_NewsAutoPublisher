---
name: publish
description: Valide puis publie un brouillon de news déjà préparé (Discord, X, YouTube), après accord explicite de l'utilisateur. À utiliser quand l'utilisateur relit une prévisualisation et dit « publie », « ok pour publier », « envoie », ou demande de modifier un brouillon avant publication, ou quand il a enregistré sa voix pour un short en attente.
argument-hint: "[id du brouillon] [canaux]"
---

# Valider et publier une news

Demande : $ARGUMENTS

## Retrouver le brouillon

- Id fourni : utilise-le.
- Sinon : `list_drafts(status="draft")` (ou `approved` / `partial`) et prends le plus récent
  correspondant au contexte. En cas de doute, demande.
- Quand l'utilisateur vient de demander une modification, `get_draft` puis montre les textes
  actuels si c'est utile.

## Modifications demandées

- Texte : `update_draft` avec le post complet de la plateforme concernée.
- Short : reprends le storyboard (`get_draft` -> `short.storyboard`), modifie-le, puis `render_short`.
- Voix enregistrée par l'utilisateur :
  1. `import_voice_recording(draft_id)` (fichier `voix_enregistree.*` ou chemin donné) ;
  2. `render_short` avec le storyboard prévu.
- Termine par `render_preview` et redemande la validation.

## Publier : uniquement après un accord explicite

1. L'utilisateur doit avoir dit clairement oui à **cette** version (« publie », « go », « ok »).
   Une modification après son accord annule cet accord.
2. `approve_draft(draft_id)`. Si des erreurs bloquent, explique-les et propose une correction.
3. Optionnel : `publish(draft_id, dry_run=true)` pour une première fois ou un nouveau canal.
4. `publish(draft_id)`, éventuellement limité à certains `channels` si l'utilisateur le demande.
5. Lis chaque résultat :
   - `published` : donne le lien.
     - X en mode API : rappelle le coût estimé.
     - Discord avec crosspost : précise que l'annonce a été diffusée aux serveurs abonnés.
     - YouTube avec `publish_at` : rappelle la date de mise en ligne programmée.
   - `pending_manual` sur X : l'éditeur X s'est ouvert avec le texte. L'utilisateur glisse le
     short ou l'image affichés dans l'Explorateur, clique « Poster », puis te donne l'URL du post.
   - `pending_manual` sur YouTube : YouTube Studio et le dossier du MP4 sont ouverts. Le titre est
     dans le presse-papiers, le reste est dans `youtube.txt`. L'utilisateur publie, puis te donne l'URL.
   - `failed` : explique la cause et la solution. Cas fréquents :
     - webhook ou clés manquants dans `.env` ;
     - fichier trop lourd ;
     - budget X atteint : proposer le mode intent pour ce post, ou laisser l'utilisateur relever
       `monthly_budget_usd` lui-même ;
     - compte YouTube non connecté : `connect_account` ;
     - projet Google non audité.
6. Pour chaque URL reçue : `mark_published(draft_id, channel, url)`.
7. Récapitule en une ou deux lignes ce qui est en ligne et ce qui reste à faire.

Ne republie jamais un canal déjà `published`. L'outil l'empêche aussi.

## Comptes en mode API (une seule fois par canal)

`connect_account(channel)`, uniquement à la demande de l'utilisateur ou quand une publication
échoue faute de connexion :

- **YouTube** : ouvre le consentement Google dans le navigateur, puis affiche la chaîne connectée.
  Vérifie avec l'utilisateur que c'est la bonne chaîne (comptes de marque).
- **X** : vérifie les 4 clés et affiche le compte et le budget du mois.
- **Discord** : connecte une première fois le bot (nécessaire au crosspost) et vérifie que le
  salon est bien un salon d'annonces.

Ne modifie jamais toi-même `monthly_budget_usd` ni `audited` dans config.yaml : ce sont des
décisions de l'utilisateur.
