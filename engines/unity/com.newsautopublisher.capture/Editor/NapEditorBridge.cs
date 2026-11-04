using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace NewsAutoPublisher.Capture.Editor
{
    /// <summary>
    /// Pont avec le serveur MCP quand l'éditeur Unity est ouvert : surveille
    /// Library/NewsAutoPublisher/request.json, ouvre la scène demandée, lance le mode Play
    /// (la capture démarre toute seule), puis rouvre la scène d'origine.
    /// </summary>
    [InitializeOnLoad]
    static class NapEditorBridge
    {
        const string PreviousSceneKey = "NewsAutoPublisher.PreviousScene";
        const string RunningKey = "NewsAutoPublisher.Running";
        static double nextPoll;

        static NapEditorBridge()
        {
            EditorApplication.update += Poll;
            EditorApplication.playModeStateChanged += OnPlayModeChanged;
        }

        static string Folder
        {
            get { return Path.GetFullPath(Path.Combine(Application.dataPath, "..", "Library", "NewsAutoPublisher")); }
        }

        static void Poll()
        {
            if (EditorApplication.timeSinceStartup < nextPoll)
            {
                return;
            }
            nextPoll = EditorApplication.timeSinceStartup + 1.0;
            if (EditorApplication.isPlayingOrWillChangePlaymode || EditorApplication.isCompiling || EditorApplication.isUpdating)
            {
                return;
            }

            string requestPath = Path.Combine(Folder, "request.json");
            if (!File.Exists(requestPath))
            {
                return;
            }

            string json = File.ReadAllText(requestPath);
            File.Delete(requestPath);
            NapCaptureRequest request = JsonUtility.FromJson<NapCaptureRequest>(json);
            Debug.Log("[NewsAutoPublisher] Capture demandée : " + request.id);

            string previous = SceneManager.GetActiveScene().path;
            if (!string.IsNullOrEmpty(request.scene) && request.scene != previous)
            {
                if (!request.scene.EndsWith(".unity") || !File.Exists(request.scene))
                {
                    WriteError(request, "Scène introuvable : " + request.scene + " (chemin attendu : Assets/…/Scene.unity).");
                    return;
                }
                if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo())
                {
                    WriteError(request, "Scène courante modifiée non enregistrée : capture annulée.");
                    return;
                }
                EditorSceneManager.OpenScene(request.scene);
                SessionState.SetString(PreviousSceneKey, previous);
            }

            Directory.CreateDirectory(Folder);
            File.WriteAllText(Path.Combine(Folder, "active.json"), json);
            SessionState.SetBool(RunningKey, true);
            // WaitForEndOfFrame n'est appelé que si la vue Game est affichée.
            EditorApplication.ExecuteMenuItem("Window/General/Game");
            EditorApplication.EnterPlaymode();
        }

        static void OnPlayModeChanged(PlayModeStateChange state)
        {
            if (state != PlayModeStateChange.EnteredEditMode || !SessionState.GetBool(RunningKey, false))
            {
                return;
            }
            SessionState.SetBool(RunningKey, false);
            string previous = SessionState.GetString(PreviousSceneKey, "");
            SessionState.EraseString(PreviousSceneKey);
            if (!string.IsNullOrEmpty(previous) && File.Exists(previous))
            {
                EditorSceneManager.OpenScene(previous);
            }
        }

        static void WriteError(NapCaptureRequest request, string message)
        {
            Debug.LogError("[NewsAutoPublisher] " + message);
            if (string.IsNullOrEmpty(request.outputDir))
            {
                return;
            }
            Directory.CreateDirectory(request.outputDir);
            var result = new NapCaptureResult { id = request.id, status = "error", error = message, unityVersion = Application.unityVersion };
            File.WriteAllText(Path.Combine(request.outputDir, "result.json"), JsonUtility.ToJson(result, true));
        }
    }
}
