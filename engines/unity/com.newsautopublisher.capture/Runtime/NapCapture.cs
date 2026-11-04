using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;

namespace NewsAutoPublisher.Capture
{
    /// <summary>
    /// Point d'entrée de la capture. S'active uniquement :
    ///  - dans un build lancé avec « -napRequest chemin/vers/requete.json » ;
    ///  - dans l'éditeur, quand NapEditorBridge a déposé Library/NewsAutoPublisher/active.json.
    /// Définis le symbole NAP_CAPTURE_DISABLED pour retirer complètement la capture d'un build.
    /// </summary>
    public static class NapCapture
    {
        public const string RequestArgument = "-napRequest";

        /// <summary>Vrai pendant une capture : le jeu peut sauter ses menus, sa connexion, etc.</summary>
        public static bool IsCapturing { get; internal set; }

        public static NapCaptureRequest Current { get; internal set; }

        /// <summary>Appelé avant le chargement de la scène et la préparation du monde.</summary>
        public static event Action<NapCaptureRequest> BeforeCapture;

        /// <summary>
        /// Préparation spécifique au jeu (mode hors ligne, apparition du joueur, météo…), exécutée
        /// comme une coroutine après le chargement de la scène. Exemple pour un MMORPG :
        /// NapCapture.PrepareWorld = req => MonJeu.DemarrerHorsLigne();
        /// </summary>
        public static Func<NapCaptureRequest, IEnumerator> PrepareWorld;

        /// <summary>Appelé juste avant chaque plan.</summary>
        public static event Action<NapShot> BeforeShot;

        /// <summary>Appelé à la fin, que la capture ait réussi ou non.</summary>
        public static event Action<NapCaptureResult> AfterCapture;

        internal static void RaiseBeforeCapture(NapCaptureRequest r) { if (BeforeCapture != null) BeforeCapture(r); }
        internal static void RaiseBeforeShot(NapShot s) { if (BeforeShot != null) BeforeShot(s); }
        internal static void RaiseAfterCapture(NapCaptureResult r) { if (AfterCapture != null) AfterCapture(r); }

#if !NAP_CAPTURE_DISABLED
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Bootstrap()
        {
            string json = ReadRequest();
            if (string.IsNullOrEmpty(json))
            {
                return;
            }

            NapCaptureRequest request;
            try
            {
                request = JsonUtility.FromJson<NapCaptureRequest>(json);
            }
            catch (Exception e)
            {
                Debug.LogError("[NewsAutoPublisher] Requête de capture illisible : " + e.Message);
                return;
            }

            var go = new GameObject("NewsAutoPublisher Capture");
            UnityEngine.Object.DontDestroyOnLoad(go);
            go.AddComponent<NapCaptureDirector>().Begin(request);
        }
#endif

        static string ReadRequest()
        {
            string[] args = Environment.GetCommandLineArgs();
            for (int i = 0; i < args.Length - 1; i++)
            {
                if (string.Equals(args[i], RequestArgument, StringComparison.OrdinalIgnoreCase) && File.Exists(args[i + 1]))
                {
                    return File.ReadAllText(args[i + 1]);
                }
            }
#if UNITY_EDITOR
            string active = EditorActiveRequestPath();
            if (File.Exists(active))
            {
                string json = File.ReadAllText(active);
                File.Delete(active); // une seule session Play par requête
                return json;
            }
#endif
            return null;
        }

        public static string EditorActiveRequestPath()
        {
            return Path.GetFullPath(Path.Combine(Application.dataPath, "..", "Library", "NewsAutoPublisher", "active.json"));
        }
    }

    /// <summary>Exécute la requête : scène, préparation, plans, écriture de result.json, sortie.</summary>
    public class NapCaptureDirector : MonoBehaviour
    {
        NapCaptureRequest request;
        NapCaptureResult result;
        readonly List<NapShotResult> shotResults = new List<NapShotResult>();
        readonly List<string> warnings = new List<string>();
        readonly List<GameObject> generated = new List<GameObject>();
        bool finished;

        public void Begin(NapCaptureRequest r)
        {
            request = r;
            result = new NapCaptureResult
            {
                id = r.id,
                unityVersion = Application.unityVersion,
                renderPipeline = GraphicsSettings.currentRenderPipeline != null
                    ? GraphicsSettings.currentRenderPipeline.GetType().Name
                    : "Built-in",
            };
            NapCapture.Current = r;
            NapCapture.IsCapturing = true;
            Application.runInBackground = true;
            Application.logMessageReceived += OnLog;
            StartCoroutine(Run());
        }

        void OnDestroy()
        {
            Application.logMessageReceived -= OnLog;
        }

        void OnLog(string condition, string stackTrace, LogType type)
        {
            // Seules les exceptions de la capture elle-même l'interrompent ; celles du jeu sont ignorées.
            if (type == LogType.Exception && !finished && stackTrace != null && stackTrace.Contains("NewsAutoPublisher"))
            {
                Fail("Exception pendant la capture : " + condition);
            }
        }

        IEnumerator Run()
        {
            if (string.IsNullOrEmpty(request.outputDir))
            {
                Fail("outputDir manquant dans la requête.");
                yield break;
            }
            Directory.CreateDirectory(request.outputDir);
            NapCapture.RaiseBeforeCapture(request);

            if (!string.IsNullOrEmpty(request.scene) && !IsActiveScene(request.scene))
            {
                AsyncOperation load = SceneManager.LoadSceneAsync(request.scene);
                if (load == null)
                {
                    Fail("Scène introuvable dans les Build Settings : " + request.scene);
                    yield break;
                }
                while (!load.isDone)
                {
                    yield return null;
                }
            }

            if (NapCapture.PrepareWorld != null)
            {
                yield return StartCoroutine(NapCapture.PrepareWorld(request));
            }

            float warmupEnd = Time.realtimeSinceStartup + Mathf.Max(0f, request.warmupSeconds);
            while (Time.realtimeSinceStartup < warmupEnd)
            {
                yield return null;
            }

            List<NapShot> shots = ResolveShots();
            if (request.procedural != null)
            {
                foreach (NapProceduralShot spec in request.procedural)
                {
                    string error;
                    NapShot built = NapProcedural.Build(spec, generated, out error);
                    if (built != null)
                    {
                        shots.Add(built);
                    }
                    else
                    {
                        warnings.Add(error);
                        Debug.LogWarning("[NewsAutoPublisher] " + error);
                    }
                }
            }
            if (shots.Count == 0)
            {
                Fail("Aucun plan à capturer dans la scène « " + SceneManager.GetActiveScene().name + " ». "
                     + string.Join(" ", warnings.ToArray()));
                yield break;
            }

            foreach (NapShot shot in shots)
            {
                if (finished)
                {
                    yield break;
                }
                yield return StartCoroutine(CaptureShot(shot));
            }

            if (!finished)
            {
                result.status = "done";
                Finish();
            }
        }

        static bool IsActiveScene(string scene)
        {
            Scene active = SceneManager.GetActiveScene();
            return active.path == scene || active.name == scene || active.name == Path.GetFileNameWithoutExtension(scene);
        }

        List<NapShot> ResolveShots()
        {
            var found = new List<NapShot>();
            foreach (NapShot s in Resources.FindObjectsOfTypeAll<NapShot>())
            {
                if (s.gameObject.scene.IsValid() && s.gameObject.scene.isLoaded)
                {
                    found.Add(s);
                }
            }
            if (request.shots == null || request.shots.Length == 0)
            {
                if (request.procedural != null && request.procedural.Length > 0)
                {
                    return new List<NapShot>(); // uniquement les plans générés
                }
                found.Sort((a, b) => string.CompareOrdinal(a.shotName, b.shotName));
                return found;
            }
            var ordered = new List<NapShot>();
            foreach (string name in request.shots)
            {
                NapShot match = found.Find(s => s.shotName == name);
                if (match != null)
                {
                    ordered.Add(match);
                }
                else
                {
                    warnings.Add("Plan introuvable : " + name);
                    Debug.LogWarning("[NewsAutoPublisher] Plan introuvable : " + name);
                }
            }
            return ordered;
        }

        IEnumerator CaptureShot(NapShot shot)
        {
            NapCapture.RaiseBeforeShot(shot);
            foreach (GameObject go in shot.activateDuringCapture)
            {
                if (go != null) go.SetActive(true);
            }

            bool createdCamera = shot.captureCamera == null;
            Camera cam = createdCamera ? CreateCaptureCamera() : shot.captureCamera;
            bool previousEnabled = cam.enabled;
            cam.enabled = true;
            if (shot.overrideFieldOfView)
            {
                cam.fieldOfView = shot.fieldOfView;
            }

            int ss = Mathf.Clamp(request.supersize, 1, 4);
            int w = Mathf.Max(16, request.width * ss);
            int h = Mathf.Max(16, request.height * ss);
            bool hdrp = result.renderPipeline.Contains("HDRenderPipeline");

            RenderTexture rt = null;
            RenderTexture previousTarget = cam.targetTexture;
            if (!request.includeUi)
            {
                rt = new RenderTexture(w, h, 24, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB);
                rt.antiAliasing = hdrp ? 1 : Mathf.Clamp(request.msaa, 1, 8);
                rt.Create();
                cam.targetTexture = rt;
            }
            else
            {
                cam.depth = 100f; // au-dessus des autres caméras, l'UI en overlay reste visible
            }

            string folder = Path.Combine(request.outputDir, Sanitize(shot.shotName));
            Directory.CreateDirectory(folder);
            var files = new List<string>();
            int fps = Mathf.Clamp(request.fps, 1, 120);
            bool screenshot = request.mode == "screenshot";

            if (screenshot)
            {
                int count = Mathf.Max(1, shot.Waypoints.Count);
                for (int k = 0; k < count; k++)
                {
                    float t = count > 1 ? k / (float)(count - 1) : 0f;
                    Pose(cam, shot, t);
                    // Quelques images pour stabiliser les effets temporels (TAA, exposition…).
                    for (int settle = 0; settle < 4; settle++)
                    {
                        yield return null;
                    }
                    yield return new WaitForEndOfFrame();
                    files.Add(SaveFrame(rt, folder, "still_" + (k + 1).ToString("00")));
                }
            }
            else
            {
                Time.captureFramerate = fps; // temps de jeu fixe : chaque image correspond à 1/fps s
                int frames = Mathf.Max(1, Mathf.RoundToInt(shot.duration * fps));
                for (int i = -4; i < frames; i++)
                {
                    float t = frames > 1 ? Mathf.Clamp01(i / (float)(frames - 1)) : 0f;
                    Pose(cam, shot, t);
                    yield return new WaitForEndOfFrame();
                    if (i >= 0)
                    {
                        files.Add(SaveFrame(rt, folder, "frame_" + (i + 1).ToString("00000")));
                    }
                }
                Time.captureFramerate = 0;
            }

            cam.targetTexture = previousTarget;
            cam.enabled = previousEnabled;
            if (rt != null)
            {
                rt.Release();
                Destroy(rt);
            }
            if (createdCamera)
            {
                Destroy(cam.gameObject);
            }
            foreach (GameObject go in shot.activateDuringCapture)
            {
                if (go != null) go.SetActive(false);
            }

            shotResults.Add(new NapShotResult
            {
                name = shot.shotName,
                description = shot.description,
                folder = folder,
                frames = files.Count,
                fps = screenshot ? 0 : fps,
                width = request.includeUi ? Screen.width : w,
                height = request.includeUi ? Screen.height : h,
                files = screenshot ? files.ToArray() : new string[0],
            });
        }

        static void Pose(Camera cam, NapShot shot, float t)
        {
            Vector3 position;
            Quaternion rotation;
            shot.Evaluate(t, out position, out rotation);
            cam.transform.SetPositionAndRotation(position, rotation);
        }

        string SaveFrame(RenderTexture rt, string folder, string baseName)
        {
            Texture2D tex;
            if (rt != null)
            {
                RenderTexture previous = RenderTexture.active;
                RenderTexture.active = rt;
                tex = new Texture2D(rt.width, rt.height, TextureFormat.RGB24, false);
                tex.ReadPixels(new Rect(0, 0, rt.width, rt.height), 0, 0, false);
                tex.Apply(false);
                RenderTexture.active = previous;
            }
            else
            {
                tex = ScreenCapture.CaptureScreenshotAsTexture();
            }

            bool png = request.format == "png";
            byte[] bytes = png ? tex.EncodeToPNG() : tex.EncodeToJPG(95);
            Destroy(tex);
            string path = Path.Combine(folder, baseName + (png ? ".png" : ".jpg"));
            File.WriteAllBytes(path, bytes);
            return path;
        }

        /// <summary>Copie « propre » de la caméra principale : mêmes réglages, sans scripts ni enfants.</summary>
        static Camera CreateCaptureCamera()
        {
            Camera main = Camera.main;
            if (main == null)
            {
                var bare = new GameObject("NAP Capture Camera");
                return bare.AddComponent<Camera>();
            }

            // Clone créé sous un parent inactif : aucun script de la caméra d'origine (contrôleur,
            // Cinemachine…) ne s'exécute avant d'être retiré.
            var holder = new GameObject("NAP Capture Holder");
            holder.SetActive(false);
            GameObject clone = Instantiate(main.gameObject, holder.transform);
            clone.name = "NAP Capture Camera";
            clone.tag = "Untagged";
            for (int i = clone.transform.childCount - 1; i >= 0; i--)
            {
                DestroyImmediate(clone.transform.GetChild(i).gameObject);
            }
            // Plusieurs passes : certains composants dépendent d'autres (RequireComponent).
            for (int pass = 0; pass < 3; pass++)
            {
                foreach (Component c in clone.GetComponents<Component>())
                {
                    if (c == null || c is Transform || c is Camera || KeepComponent(c))
                    {
                        continue;
                    }
                    try
                    {
                        DestroyImmediate(c);
                    }
                    catch (Exception)
                    {
                        // dépendance encore présente : nouvel essai à la passe suivante
                    }
                }
            }
            clone.transform.SetParent(null, false);
            DestroyImmediate(holder);
            clone.SetActive(true);
            return clone.GetComponent<Camera>();
        }

        static bool KeepComponent(Component c)
        {
            string n = c.GetType().Name;
            // Données de caméra des pipelines (URP/HDRP), post-process v2 et volumes locaux.
            return n.Contains("AdditionalCameraData") || n.Contains("PostProcessLayer") || n.Contains("Volume");
        }

        static string Sanitize(string name)
        {
            foreach (char c in Path.GetInvalidFileNameChars())
            {
                name = name.Replace(c, '_');
            }
            return string.IsNullOrEmpty(name) ? "plan" : name;
        }

        void Fail(string message)
        {
            if (finished)
            {
                return;
            }
            Debug.LogError("[NewsAutoPublisher] " + message);
            result.status = "error";
            result.error = message;
            Finish();
        }

        void Finish()
        {
            finished = true;
            Time.captureFramerate = 0;
            result.shots = shotResults.ToArray();
            result.warnings = warnings.ToArray();
            foreach (GameObject go in generated)
            {
                if (go != null) Destroy(go);
            }
            try
            {
                if (!string.IsNullOrEmpty(request.outputDir))
                {
                    Directory.CreateDirectory(request.outputDir);
                    File.WriteAllText(Path.Combine(request.outputDir, "result.json"), JsonUtility.ToJson(result, true));
                }
            }
            catch (Exception e)
            {
                Debug.LogError("[NewsAutoPublisher] Écriture de result.json impossible : " + e.Message);
            }
            NapCapture.IsCapturing = false;
            NapCapture.RaiseAfterCapture(result);
            StopAllCoroutines();

            if (request.quitWhenDone)
            {
#if UNITY_EDITOR
                UnityEditor.EditorApplication.isPlaying = false;
#else
                Application.Quit();
#endif
            }
        }
    }
}
