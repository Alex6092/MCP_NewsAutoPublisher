# NewsAutoPublisher Capture (Unity)

Ce package permet à Claude Code (plugin NewsAutoPublisher) de capturer automatiquement des **plans
de caméra** de ton jeu. Il produit :

- des séquences d'images à **temps de jeu fixe** (`Time.captureFramerate`), donc fluides même si la
  capture est lente, transformées en vidéo par le plugin ;
- ou des captures d'écran fixes.

## Installation

*Window > Package Manager > + > Add package from git URL…*

```
https://github.com/Alex6092/MCP_NewsAutoPublisher.git?path=/engines/unity/com.newsautopublisher.capture
```

Unity 2021.3 ou plus récent. Built-in, URP et HDRP sont pris en charge.

## Créer un plan

1. Dans la vue Scène, cadre ce que tu veux montrer.
2. Clic droit dans la hiérarchie : *NewsAutoPublisher > Nap Shot*. Le plan est créé avec un premier
   point de passage, celui de la vue Scène.
3. Déplace la vue Scène et clique **« Ajouter un point depuis la vue Scène »** autant de fois que
   nécessaire. La caméra suit une courbe douce entre les points.
4. Renseigne :
   - `shotName` : l'identifiant que Claude utilisera ;
   - `description` : ce que montre le plan ;
   - `duration` : la durée du plan.
5. Options :
   - `lookAt` : la caméra suit une cible ;
   - `captureCamera` : utilise ta propre caméra, utile pour garder des réglages de post-process précis ;
   - `activateDuringCapture` : objets de démonstration à n'afficher que pendant la capture.

Les plans sont visibles dans la vue Scène (trajet violet et pyramides de caméra). Claude les trouve
en lisant les fichiers `.unity` : garde la sérialisation en texte (*Project Settings > Editor >
Asset Serialization : Force Text*, réglage par défaut).

## Comment Claude lance la capture

- **Éditeur ouvert** (recommandé pendant le développement) :
  1. Le plugin dépose `Library/NewsAutoPublisher/request.json`.
  2. L'éditeur ouvre la scène et passe en mode Play.
  3. Il capture les plans, quitte le mode Play et rouvre ta scène.
  - Garde la **vue Game visible** pendant la capture.
- **Build** : le plugin lance `TonJeu.exe -napRequest requete.json -screen-fullscreen 0 …`. Le jeu
  capture, écrit `result.json` et se ferme.
  - La scène demandée doit être dans les Build Settings.

Par défaut, l'image vient d'une copie de la caméra principale rendue dans une RenderTexture à la
résolution demandée (1080×1920 par défaut). Les fenêtres et l'UI en overlay ne gênent donc pas.
Avec `includeUi`, c'est l'écran entier qui est capturé, UI comprise.

## Adapter le démarrage du jeu (MMORPG, connexion, menus…)

Si ta scène a besoin d'un serveur, d'une connexion ou d'un joueur, branche ton propre démarrage
hors ligne :

```csharp
using NewsAutoPublisher.Capture;

public static class ExodeCaptureHooks
{
    [UnityEngine.RuntimeInitializeOnLoadMethod(UnityEngine.RuntimeInitializeLoadType.BeforeSceneLoad)]
    static void Register()
    {
        NapCapture.PrepareWorld = request => MonJeu.DemarrerModeHorsLigne(); // IEnumerator
        NapCapture.BeforeShot += shot => MonJeu.MasquerHUD();
    }
}
```

`NapCapture.IsCapturing` permet aussi à ton code de sauter un écran titre ou un tutoriel.

## Sécurité

Le code ne s'active qu'avec l'argument `-napRequest` ou une requête déposée par l'éditeur. Pour le
retirer complètement d'un build public, ajoute le symbole `NAP_CAPTURE_DISABLED` dans *Player
Settings > Scripting Define Symbols*.
