using UnityEditor;
using UnityEngine;

namespace NewsAutoPublisher.Capture.Editor
{
    [CustomEditor(typeof(NapShot))]
    class NapShotEditor : UnityEditor.Editor
    {
        public override void OnInspectorGUI()
        {
            var shot = (NapShot)target;
            EditorGUILayout.HelpBox(
                "Plan « " + shot.shotName + " » : les enfants de cet objet sont les points de passage de la caméra, "
                + "dans l'ordre. Place la vue Scène comme tu veux voir le jeu, puis ajoute un point.",
                MessageType.Info);

            DrawDefaultInspector();
            EditorGUILayout.Space();

            if (GUILayout.Button("Ajouter un point depuis la vue Scène"))
            {
                AddWaypointFromSceneView(shot);
            }

            var points = shot.Waypoints;
            for (int i = 0; i < points.Count; i++)
            {
                EditorGUILayout.BeginHorizontal();
                EditorGUILayout.LabelField((i + 1) + ". " + points[i].name);
                if (GUILayout.Button("Voir", GUILayout.Width(60)) && SceneView.lastActiveSceneView != null)
                {
                    SceneView.lastActiveSceneView.AlignViewToObject(points[i]);
                }
                if (GUILayout.Button("Remplacer", GUILayout.Width(80)))
                {
                    SetFromSceneView(points[i]);
                }
                EditorGUILayout.EndHorizontal();
            }
        }

        static void AddWaypointFromSceneView(NapShot shot)
        {
            var point = new GameObject("Point " + (shot.transform.childCount + 1));
            Undo.RegisterCreatedObjectUndo(point, "Ajouter un point NapShot");
            point.transform.SetParent(shot.transform, false);
            SetFromSceneView(point.transform);
            Selection.activeGameObject = shot.gameObject;
        }

        static void SetFromSceneView(Transform point)
        {
            SceneView view = SceneView.lastActiveSceneView;
            if (view == null || view.camera == null)
            {
                Debug.LogWarning("[NewsAutoPublisher] Aucune vue Scène active.");
                return;
            }
            Undo.RecordObject(point, "Placer un point NapShot");
            point.SetPositionAndRotation(view.camera.transform.position, view.camera.transform.rotation);
        }

        [MenuItem("GameObject/NewsAutoPublisher/Nap Shot", false, 10)]
        static void CreateShot(MenuCommand command)
        {
            var go = new GameObject("NapShot");
            Undo.RegisterCreatedObjectUndo(go, "Créer un NapShot");
            GameObjectUtility.SetParentAndAlign(go, command.context as GameObject);
            var shot = go.AddComponent<NapShot>();
            shot.shotName = "plan_" + System.DateTime.Now.ToString("HHmmss");
            AddWaypointFromSceneView(shot);
        }
    }
}
