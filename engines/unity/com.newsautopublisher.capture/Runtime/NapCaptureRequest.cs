using System;

namespace NewsAutoPublisher.Capture
{
    /// <summary>Requête écrite par le serveur MCP (JSON, lu avec JsonUtility : noms de champs = clés).</summary>
    [Serializable]
    public class NapCaptureRequest
    {
        public string id = "";
        public string mode = "video"; // "video" (suite d'images) ou "screenshot" (une image par point de passage)
        public string[] shots = new string[0]; // noms des NapShot ; vide = tous les plans de la scène
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
        public NapShotResult[] shots = new NapShotResult[0];
    }
}
