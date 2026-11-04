# Recettes de shorts

Le rendu se fait en 1080×1920, 30 i/s. Les durées des scènes s'étirent automatiquement pour
couvrir la voix off.

Rythme de lecture : environ 2,5 mots par seconde, donc 75 mots ≈ 30 s.

## Recettes

### « Devlog en 30 s » (par défaut)

| Scène | Contenu | Voix (exemple) |
|---|---|---|
| `title` | « Les quêtes arrivent dans Exode » + `subtext` « Devlog #12 » | « Gros morceau cette semaine dans Exode : les quêtes arrivent ! » |
| `clip` | Démo de la fonctionnalité, bandeau « Quêtes à embranchements » | « Chaque choix de dialogue ouvre une suite différente… » |
| `clip`/`image` | Deuxième angle ou résultat, bandeau « Récompenses » | « …et les récompenses s'adaptent à ta classe. » |
| `outro` | « Rejoins le Discord » + `subtext` lien court | « Viens tester ça avec nous, le lien est dans la description. » |

### « Feature spotlight » (plugins)

1. `title` : le problème (« Vos quêtes en spaghetti de Blueprints ? »).
2. `clip` de l'éditeur : la solution en action.
3. `clip` en jeu : le résultat.
4. `outro` : « Disponible sur Fab » + `subtext` lien Fab.

### « Avant / après »

`title` → `image` « Avant » → `image` « Après » (même cadrage) → `outro`.

### « Patch notes »

`title` « Mise à jour 1.2 » → une scène `text` par point (3 maximum, 1 phrase chacune) → `outro`.

## Conseils

- **Accroche** : la première image et la première phrase doivent dire la nouveauté. Pas de logo
  en ouverture.
- **Bandeaux** (`text` des scènes clip/image) : 2 à 4 mots, 30 caractères maximum. Le bandeau
  par défaut est `headline`.
- **Captures 16:9** :
  - `fit: contain` + `zoom: 1.3` donne une bande large sur fond flouté ;
  - `fit: cover` recadre au centre (convient à un personnage centré) ;
  - pour un plan cinématique déjà vertical, laisser `zoom: 1`.
- **Clips** :
  - `start` choisit le point d'entrée ;
  - une scène plus longue que le clip fige sa dernière image ;
  - préférer plusieurs clips courts de 3 à 6 s.
- **Musique** :
  - `brand.music` du projet (fichier ou dossier) ; `"music": "none"` pour s'en passer ;
  - elle est automatiquement atténuée sous la voix ;
  - n'utiliser que des musiques libres de droits ou des compositions de l'utilisateur.
- **Ta voix** : script identique à ce qui sera lu ; une phrase par ligne ; pauses nettes entre
  les phrases (elles servent à caler les sous-titres sans Whisper).

## Exemple de storyboard

```json
{
  "headline": "Devlog #12",
  "scenes": [
    {"type": "title", "text": "Les quêtes arrivent dans Exode", "subtext": "Devlog #12"},
    {"type": "clip", "media": "m20261104210000ab12", "text": "Quêtes à embranchements", "zoom": 1.3},
    {"type": "image", "media": "m20261104210500cd34", "text": "Récompenses"},
    {"type": "outro", "text": "Rejoins le Discord", "subtext": "discord.gg/exode"}
  ]
}
```
