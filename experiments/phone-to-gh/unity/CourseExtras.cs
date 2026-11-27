using System.Collections.Generic;
using UnityEngine;
using UnityEngine.XR.ARFoundation;

namespace Compas.GeoViewerXR
{
    /// <summary>
    /// Hides two things of the course's AR template that sit over our photo flow:
    /// the dotted AR planes (and feature points, if shown) and the cube "Create Button"
    /// at the bottom. Nothing is removed: plane detection keeps running and the button
    /// keeps its listeners. Untick <see cref="hide"/> (OutlineReview's "Hide Course Extras")
    /// to get both back.
    /// OutlineReview adds this component; it is not in the scene by itself.
    /// </summary>
    public class CourseExtras : MonoBehaviour
    {
        public bool hide = true;

        // The template's menu turns the button back on every frame, so it is made
        // invisible with a CanvasGroup instead of SetActive(false).
        private const string ButtonName = "Create Button";

        private ARPlaneManager _planes;
        private ARPointCloudManager _points;
        private CanvasGroup _buttonGroup;
        private readonly Dictionary<Component, Renderer[]> _renderers = new Dictionary<Component, Renderer[]>();
        private bool _wasHidden;

        private void Start()
        {
            _planes = FindAnyObjectByType<ARPlaneManager>();
            _points = FindAnyObjectByType<ARPointCloudManager>();
            foreach (var t in FindObjectsByType<RectTransform>(FindObjectsInactive.Include, FindObjectsSortMode.None))
            {
                if (t.name != ButtonName) continue;
                _buttonGroup = t.GetComponent<CanvasGroup>();
                if (_buttonGroup == null) _buttonGroup = t.gameObject.AddComponent<CanvasGroup>();
                break;
            }
        }

        // After the AR visualizers' Update, so they cannot switch the renderers back on.
        private void LateUpdate()
        {
            if (!hide && !_wasHidden) return;
            if (_buttonGroup != null)
            {
                _buttonGroup.alpha = hide ? 0f : 1f;
                _buttonGroup.interactable = !hide;
                _buttonGroup.blocksRaycasts = !hide;
            }
            if (_planes != null)
                foreach (var plane in _planes.trackables) Show(plane, !hide);
            if (_points != null)
                foreach (var cloud in _points.trackables) Show(cloud, !hide);
            _wasHidden = hide;
        }

        private void Show(Component trackable, bool visible)
        {
            if (!_renderers.TryGetValue(trackable, out var list) || list == null)
                _renderers[trackable] = list = trackable.GetComponentsInChildren<Renderer>(true);
            foreach (var r in list)
                if (r != null) r.enabled = visible;
            if (visible) _renderers.Remove(trackable);
        }
    }
}
