using System;

namespace NewsAutoPublisher.Capture
{
    /// <summary>Requête écrite par le serveur MCP (JSON, lu avec JsonUtility : noms de champs = clés).</summary>
    [Serializable]
    public class NapCaptureRequest
    {
        public string id = "";
        public string mode = "video"; // "video" (suite d'images) ou "screenshot" (une image par point de passage)
        public string[] shots = new string[0]; // noms des NapShot ; vide = tous les plans de la scène (sauf si procedural)
        public NapProceduralShot[] procedural = new NapProceduralShot[0]; // plans générés autour d'objets
        public string scene = ""; // chemin (Assets/…/X.unity) ou nom de scène ; vide = scène courante
        public int width = 1080;
        public int height = 1920;
        public int fps = 30;
        public int supersize = 1;
        public float warmupSeconds = 1.5f;
        public string outputDir = "";
        public string format = "jpg"; // "jpg" ou "png"
        public int msaa = 4;
        public bool includeUi; // true : capture de l'écran (UI comprise) au lieu d'une RenderTexture
        public bool quitWhenDone = true;
    }

    /// <summary>Plan généré automatiquement autour d'une cible (voir NapProcedural).</summary>
    [Serializable]
    public class NapProceduralShot
    {
        public string name = "auto";
        public string target = ""; // nom ou chemin du GameObject (ex. "QuestBoard" ou "Hub/QuestBoard")
        public string move = "orbit"; // orbit | dolly | pullback | flyover | static | follow
        public float duration = 5f;
        public float distance = 1f; // 1 = la cible remplit le cadre ; 1.5 = plus large
        public float elevation = 15f; // degrés au-dessus de l'horizon
        public float angle = 25f; // décalage horizontal par rapport à l'avant de la cible (vue de 3/4)
        public float arc = 90f; // amplitude de l'orbite en degrés
        public float fov; // 0 = celui de la caméra principale
    }

    [Serializable]
    public class NapShotResult
    {
        public string name = "";
        public string description = "";
        public string folder = "";
        public int frames;
        public int fps;
        public int width;
        public int height;
        public string[] files = new string[0];
    }

    [Serializable]
    public class NapCaptureResult
    {
        public string id = "";
        public string status = "running"; // running | done | error
        public string error = "";
        public string unityVersion = "";
        public string renderPipeline = "";
        public string[] warnings = new string[0];
        public NapShotResult[] shots = new NapShotResult[0];
    }
}
