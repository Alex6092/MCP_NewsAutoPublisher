using System.Collections.Generic;
using UnityEngine;

namespace NewsAutoPublisher.Capture
{
    /// <summary>
    /// Plan de caméra capturable par NewsAutoPublisher. Les enfants directs de cet objet sont les
    /// points de passage de la caméra, dans l'ordre de la hiérarchie (un seul point = plan fixe).
    /// </summary>
    [AddComponentMenu("NewsAutoPublisher/Nap Shot")]
    [DisallowMultipleComponent]
    public class NapShot : MonoBehaviour
    {
        [Tooltip("Identifiant du plan, utilisé par Claude (list_engine_shots / engine_capture). Unique dans le projet.")]
        public string shotName = "plan";

        [Tooltip("Ce que montre le plan : aide Claude à choisir les bons rushes.")]
        [TextArea(2, 4)]
        public string description = "";

        [Tooltip("Durée du plan en secondes (mode vidéo).")]
        [Min(0.1f)]
        public float duration = 5f;

        [Tooltip("Caméra dédiée (facultatif). Sinon, une copie de la caméra principale est utilisée.")]
        public Camera captureCamera;

        [Tooltip("Cible regardée pendant tout le plan (facultatif). Sinon, orientation des points de passage.")]
        public Transform lookAt;

        public bool overrideFieldOfView;

        [Range(1f, 179f)]
        public float fieldOfView = 50f;

        [Tooltip("Accélération / décélération le long du trajet.")]
        public AnimationCurve easing = AnimationCurve.EaseInOut(0f, 0f, 1f, 1f);

        [Tooltip("Objets activés seulement pendant la capture (PNJ de démonstration, effets…).")]
        public GameObject[] activateDuringCapture = new GameObject[0];

        public List<Transform> Waypoints
        {
            get
            {
                var list = new List<Transform>(transform.childCount);
                foreach (Transform child in transform)
                {
                    list.Add(child);
                }
                return list;
            }
        }

        /// <summary>Pose de la caméra à l'instant normalisé t (0 = début, 1 = fin du plan).</summary>
        public void Evaluate(float t, out Vector3 position, out Quaternion rotation)
        {
            List<Transform> points = Waypoints;
            float u = easing != null && easing.length > 0 ? easing.Evaluate(Mathf.Clamp01(t)) : Mathf.Clamp01(t);

            if (points.Count == 0)
            {
                position = transform.position;
                rotation = transform.rotation;
            }
            else if (points.Count == 1)
            {
                position = points[0].position;
                rotation = points[0].rotation;
            }
            else
            {
                float scaled = Mathf.Clamp01(u) * (points.Count - 1);
                int i = Mathf.Min(Mathf.FloorToInt(scaled), points.Count - 2);
                float f = scaled - i;
                Vector3 p0 = points[Mathf.Max(i - 1, 0)].position;
                Vector3 p1 = points[i].position;
                Vector3 p2 = points[i + 1].position;
                Vector3 p3 = points[Mathf.Min(i + 2, points.Count - 1)].position;
                position = CatmullRom(p0, p1, p2, p3, f);
                rotation = Quaternion.Slerp(points[i].rotation, points[i + 1].rotation, f);
            }

            if (lookAt != null)
            {
                Vector3 dir = lookAt.position - position;
                if (dir.sqrMagnitude > 1e-6f)
                {
                    rotation = Quaternion.LookRotation(dir, Vector3.up);
                }
            }
        }

        static Vector3 CatmullRom(Vector3 p0, Vector3 p1, Vector3 p2, Vector3 p3, float t)
        {
            float t2 = t * t;
            float t3 = t2 * t;
            return 0.5f * ((2f * p1) + (-p0 + p2) * t + (2f * p0 - 5f * p1 + 4f * p2 - p3) * t2
                           + (-p0 + 3f * p1 - 3f * p2 + p3) * t3);
        }

        void OnDrawGizmos()
        {
            List<Transform> points = Waypoints;
            if (points.Count == 0)
            {
                return;
            }

            Gizmos.color = new Color(0.49f, 0.36f, 1f, 0.9f);
            if (points.Count > 1)
            {
                Vector3 previous;
                Quaternion unused;
                Evaluate(0f, out previous, out unused);
                const int samples = 40;
                for (int s = 1; s <= samples; s++)
                {
                    Vector3 next;
                    Evaluate(s / (float)samples, out next, out unused);
                    Gizmos.DrawLine(previous, next);
                    previous = next;
                }
            }

            float fov = overrideFieldOfView ? fieldOfView : 50f;
            Matrix4x4 saved = Gizmos.matrix;
            foreach (Transform point in points)
            {
                Gizmos.matrix = Matrix4x4.TRS(point.position, point.rotation, Vector3.one);
                Gizmos.DrawFrustum(Vector3.zero, fov, 0.6f, 0.05f, 9f / 16f);
            }
            Gizmos.matrix = saved;
        }
    }
}
