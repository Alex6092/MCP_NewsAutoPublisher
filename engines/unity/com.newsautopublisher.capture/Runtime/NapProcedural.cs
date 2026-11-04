using System.Collections.Generic;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace NewsAutoPublisher.Capture
{
    /// <summary>
    /// Plans générés automatiquement autour d'un objet de la scène, sans point de passage à placer :
    /// la caméra est calculée à partir de l'encombrement (bounds) de la cible.
    /// </summary>
    public static class NapProcedural
    {
        /// <summary>Crée un NapShot temporaire. Renvoie null (et un message) si la cible est introuvable.</summary>
        public static NapShot Build(NapProceduralShot spec, List<GameObject> created, out string error)
        {
            error = null;
            GameObject target = FindTarget(spec.target);
            if (target == null)
            {
                error = "Cible introuvable dans la scène : « " + spec.target + " ».";
                return null;
            }

            Bounds bounds = ComputeBounds(target);
            float radius = Mathf.Max(bounds.extents.magnitude, 0.5f);
            Camera main = Camera.main;
            float fov = spec.fov > 0f ? spec.fov : (main != null ? main.fieldOfView : 60f);
            float fit = radius / Mathf.Sin(0.5f * fov * Mathf.Deg2Rad) * 1.1f;
            float distance = fit * (spec.distance > 0f ? spec.distance : 1f);
            float elevation = spec.elevation;
            Vector3 forward = target.transform.forward;
            forward.y = 0f;
            if (forward.sqrMagnitude < 1e-4f) forward = Vector3.forward;
            float baseYaw = Mathf.Atan2(forward.x, forward.z) * Mathf.Rad2Deg + spec.angle;

            var shotGo = new GameObject("NAP Procedural " + spec.name);
            created.Add(shotGo);
            NapShot shot = shotGo.AddComponent<NapShot>();
            shot.shotName = spec.name;
            shot.description = spec.move + " autour de " + target.name;
            shot.duration = Mathf.Max(0.5f, spec.duration);
            shot.overrideFieldOfView = true;
            shot.fieldOfView = fov;

            var pivot = new GameObject("NAP Pivot " + spec.name);
            created.Add(pivot);
            pivot.transform.position = bounds.center;
            shot.lookAt = pivot.transform;

            var points = new List<Vector3>();
            Vector3 c = bounds.center;
            switch (spec.move)
            {
                case "dolly":
                    points.Add(Orbit(c, distance * 1.5f, baseYaw, elevation));
                    points.Add(Orbit(c, distance * 0.85f, baseYaw, elevation));
                    break;
                case "pullback":
                    points.Add(Orbit(c, distance * 0.85f, baseYaw, elevation));
                    points.Add(Orbit(c, distance * 1.6f, baseYaw, elevation + 10f));
                    break;
                case "flyover":
                    for (int i = 0; i < 5; i++)
                    {
                        float yaw = baseYaw - 40f + 80f * i / 4f;
                        points.Add(Orbit(c, distance * 1.6f, yaw, Mathf.Max(elevation, 50f)));
                    }
                    break;
                case "static":
                    points.Add(Orbit(c, distance * 1.03f, baseYaw, elevation));
                    points.Add(Orbit(c, distance, baseYaw, elevation));
                    break;
                case "follow":
                    // Caméra de poursuite : le plan suit la cible (utile pour un personnage en mouvement).
                    shotGo.transform.SetParent(target.transform, false);
                    pivot.transform.SetParent(target.transform, true);
                    points.Add(target.transform.InverseTransformPoint(Orbit(c, distance, baseYaw + 180f, elevation)));
                    points.Add(target.transform.InverseTransformPoint(Orbit(c, distance * 0.92f, baseYaw + 180f, elevation)));
                    for (int i = 0; i < points.Count; i++)
                    {
                        AddWaypoint(shotGo.transform, points[i], i, true);
                    }
                    return shot;
                default: // orbit
                    int count = 7;
                    float arc = spec.arc > 0f ? spec.arc : 90f;
                    for (int i = 0; i < count; i++)
                    {
                        float yaw = baseYaw - arc * 0.5f + arc * i / (count - 1);
                        points.Add(Orbit(c, distance, yaw, elevation));
                    }
                    break;
            }

            for (int i = 0; i < points.Count; i++)
            {
                AddWaypoint(shotGo.transform, points[i], i, false);
            }
            return shot;
        }

        static void AddWaypoint(Transform parent, Vector3 position, int index, bool local)
        {
            var point = new GameObject("Point " + (index + 1));
            point.transform.SetParent(parent, false);
            if (local)
            {
                point.transform.localPosition = position;
            }
            else
            {
                point.transform.position = position;
            }
        }

        static Vector3 Orbit(Vector3 center, float distance, float yawDeg, float elevationDeg)
        {
            float yaw = yawDeg * Mathf.Deg2Rad;
            float el = Mathf.Clamp(elevationDeg, -80f, 85f) * Mathf.Deg2Rad;
            return center + new Vector3(Mathf.Cos(el) * Mathf.Sin(yaw), Mathf.Sin(el), Mathf.Cos(el) * Mathf.Cos(yaw)) * distance;
        }

        /// <summary>Recherche par chemin ou nom exact, puis par nom contenant le texte (objets inactifs compris).</summary>
        public static GameObject FindTarget(string query)
        {
            if (string.IsNullOrEmpty(query))
            {
                return null;
            }
            GameObject direct = GameObject.Find(query);
            if (direct != null)
            {
                return direct;
            }
            GameObject fuzzy = null;
            string lower = query.ToLowerInvariant();
            for (int s = 0; s < SceneManager.sceneCount; s++)
            {
                Scene scene = SceneManager.GetSceneAt(s);
                if (!scene.isLoaded) continue;
                foreach (GameObject root in scene.GetRootGameObjects())
                {
                    foreach (Transform t in root.GetComponentsInChildren<Transform>(true))
                    {
                        if (t.name == query) return t.gameObject;
                        if (fuzzy == null && t.name.ToLowerInvariant().Contains(lower)) fuzzy = t.gameObject;
                    }
                }
            }
            return fuzzy;
        }

        public static Bounds ComputeBounds(GameObject target)
        {
            bool has = false;
            var bounds = new Bounds(target.transform.position, Vector3.one);
            foreach (Renderer r in target.GetComponentsInChildren<Renderer>())
            {
                if (!r.enabled || r is ParticleSystemRenderer) continue;
                if (!has) { bounds = r.bounds; has = true; }
                else bounds.Encapsulate(r.bounds);
            }
            if (!has)
            {
                foreach (Collider col in target.GetComponentsInChildren<Collider>())
                {
                    if (!has) { bounds = col.bounds; has = true; }
                    else bounds.Encapsulate(col.bounds);
                }
            }
            return bounds;
        }
    }
}
