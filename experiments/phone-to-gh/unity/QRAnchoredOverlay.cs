using System.Collections.Generic;
using UnityEngine;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.ARSubsystems;

namespace Compas.GeoViewerXR
{
    /// <summary>
    /// Lines given in the QR marker's cm frame (MESSAGES.md, "The scale": origin where the red and
    /// green lines meet, x along red, y along green), drawn in AR on the printed marker Tracker_10.
    /// AR Foundation tracks the marker, so the lines stay on the stones while the phone moves
    /// (added 2026-11-27; before, the outlines were fixed to the screen).
    /// <para>The reference image QR10 of the course library is the printed square itself (red X
    /// along its bottom edge, green Y along its left edge), so its bottom-left corner is the
    /// frame's origin (as in QRLocalizer). Tracked images report their centre, X to the right, Z
    /// towards the top edge, Y out of the paper.</para>
    /// </summary>
    public class QRAnchoredOverlay : MonoBehaviour
    {
        [Tooltip("The reference image of the printed marker in the tracked image library.")]
        public string imageName = "QR10";

        [Tooltip("Side of the printed square (red and green lines) in cm: the frame's cm map onto the tracked image by this.")]
        public float frameCm = 14.8f;

        [Tooltip("How far above the paper the lines are drawn, in cm: the height of the stone tops (the outlines are their tops). OutlineReview sets it from the stones' size.")]
        public float liftCm = 0.3f;

        [Tooltip("Lay the lines level (by gravity) and take only the position and the turn from the marker. A slightly bent or tilted sheet then does not tilt lines 30 cm away from it (phone test 2026-11-27).")]
        public bool levelWithGravity = true;

        [Tooltip("How fast the lines follow the marker's pose, 0-1 per frame: lower = calmer, slower.")]
        [Range(0.05f, 1f)] public float follow = 0.35f;

        [Tooltip("Tick if the lines come out mirrored top to bottom on the phone (the tracked image's Z pointing to the paper's bottom edge instead of its top).")]
        public bool flipImageY = false;

        /// <summary>The marker is seen (or was, and AR still keeps its place).</summary>
        public bool IsTracking { get; private set; }

        /// <summary>Lines are given and the marker is tracked: they are on screen.</summary>
        public bool Showing => IsTracking && _lines.Count > 0;

        private class Line
        {
            public LineRenderer Renderer;
            public Vector2[] Cm;
            public float WidthCm;
        }

        private readonly List<Line> _lines = new List<Line>();
        private ARTrackedImageManager _images;
        private Transform _root;
        private Material _material;
        private float _metresPerCm = -1;
        private float _placedLiftCm = -1;
        private Vector2 _offsetCm;          // the person's fine adjustment, in the frame's cm
        private bool _hasPose;

        private void Awake()
        {
            _images = FindAnyObjectByType<ARTrackedImageManager>();
            if (_images == null) Debug.LogWarning("QRAnchoredOverlay: no ARTrackedImageManager in the scene.", this);
            _root = new GameObject("QR anchored overlay").transform;
            _root.gameObject.SetActive(false);
            _material = new Material(Shader.Find("Sprites/Default"));
        }

        private void OnDestroy()
        {
            if (_root != null) Destroy(_root.gameObject);
            if (_material != null) Destroy(_material);
        }

        private void LateUpdate()
        {
            ARTrackedImage image = FindImage();
            IsTracking = image != null;
            if (!IsTracking || _lines.Count == 0)
            {
                _root.gameObject.SetActive(false);
                return;
            }

            // The frame's origin: the image's bottom-left corner.
            float zCorner = flipImageY ? image.size.y / 2 : -image.size.y / 2;
            Vector3 corner = image.transform.TransformPoint(-image.size.x / 2, 0, zCorner);
            Quaternion turn = image.transform.rotation;
            if (levelWithGravity)
            {
                // Only the marker's heading; its up is the world's up (the table is level).
                Vector3 ahead = Vector3.ProjectOnPlane(image.transform.forward, Vector3.up);
                if (ahead.sqrMagnitude > 1e-6f) turn = Quaternion.LookRotation(ahead.normalized, Vector3.up);
            }
            if (!_hasPose)
            {
                _root.SetPositionAndRotation(corner, turn);
                _hasPose = true;
            }
            else
            {
                // Smooth the tracked pose's small jumps from frame to frame.
                _root.SetPositionAndRotation(Vector3.Lerp(_root.position, corner, follow),
                                             Quaternion.Slerp(_root.rotation, turn, follow));
            }
            float m = image.size.x / frameCm;
            if (Mathf.Abs(m - _metresPerCm) > 1e-6f || Mathf.Abs(liftCm - _placedLiftCm) > 1e-4f)
            {
                _metresPerCm = m;
                _placedLiftCm = liftCm;
                foreach (Line line in _lines) Place(line);
            }
            _root.gameObject.SetActive(true);
        }

        private ARTrackedImage FindImage()
        {
            if (_images == null) return null;
            foreach (ARTrackedImage image in _images.trackables)
            {
                // Limited: out of view, but AR still knows where it is; keep drawing there.
                if (image.referenceImage.name == imageName && image.trackingState != TrackingState.None)
                {
                    return image;
                }
            }
            return null;
        }

        /// <summary>Moves all lines by a drag on the screen (two screen points, pixels, origin
        /// bottom-left): both are cast onto the lines' plane and the lines follow the difference.
        /// The adjustment stays until <see cref="ResetOffset"/> (2026-11-27: a constant ~0.5 cm
        /// was left, and pinned lines cannot be lined up by moving the phone).</summary>
        public void Nudge(Vector2 fromScreen, Vector2 toScreen)
        {
            Camera cam = Camera.main;
            if (cam == null || !_root.gameObject.activeSelf || _metresPerCm <= 0) return;
            var plane = new Plane(_root.up, _root.TransformPoint(0, liftCm * _metresPerCm, 0));
            Ray a = cam.ScreenPointToRay(fromScreen), b = cam.ScreenPointToRay(toScreen);
            if (!plane.Raycast(a, out float ta) || !plane.Raycast(b, out float tb)) return;
            Vector3 d = _root.InverseTransformVector(b.GetPoint(tb) - a.GetPoint(ta)) / _metresPerCm;
            _offsetCm += new Vector2(d.x, (flipImageY ? -1 : 1) * d.z);
            foreach (Line line in _lines) Place(line);
        }

        public void ResetOffset()
        {
            _offsetCm = Vector2.zero;
            foreach (Line line in _lines) Place(line);
        }

        public void Clear()
        {
            foreach (Line line in _lines) Destroy(line.Renderer.gameObject);
            _lines.Clear();
        }

        /// <summary>A polyline (closed or not), points in cm of the marker frame.</summary>
        public void AddLine(IList<Vector2> cm, Color color, float widthCm, bool closed)
        {
            if (cm == null || cm.Count < 2) return;
            var go = new GameObject("line");
            go.transform.SetParent(_root, false);
            LineRenderer lr = go.AddComponent<LineRenderer>();
            lr.useWorldSpace = false;
            lr.loop = closed;
            lr.sharedMaterial = _material;
            lr.startColor = lr.endColor = color;
            lr.numCapVertices = 2;
            lr.numCornerVertices = 2;
            lr.alignment = LineAlignment.View;
            lr.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            lr.receiveShadows = false;
            var line = new Line { Renderer = lr, Cm = new List<Vector2>(cm).ToArray(), WidthCm = widthCm };
            _lines.Add(line);
            if (_metresPerCm > 0) Place(line);
        }

        /// <summary>45-degree hatch lines inside a closed outline (cm), like the must zone on the photo.</summary>
        public void AddHatch(IList<Vector2> polygon, Color color, float widthCm, float spacingCm)
        {
            if (polygon == null || polygon.Count < 3 || spacingCm <= 0) return;
            AddLine(polygon, color, widthCm * 0.5f, true);
            // Lines x + y = c: cross each edge, sort along the line, keep the inside pieces.
            float lo = float.MaxValue, hi = float.MinValue;
            foreach (Vector2 p in polygon)
            {
                lo = Mathf.Min(lo, p.x + p.y);
                hi = Mathf.Max(hi, p.x + p.y);
            }
            var cuts = new List<float>();
            for (float c = Mathf.Ceil(lo / spacingCm) * spacingCm; c <= hi; c += spacingCm)
            {
                cuts.Clear();
                for (int i = 0; i < polygon.Count; i++)
                {
                    Vector2 a = polygon[i], b = polygon[(i + 1) % polygon.Count];
                    float fa = a.x + a.y - c, fb = b.x + b.y - c;
                    if ((fa <= 0 && fb > 0) || (fb <= 0 && fa > 0))
                    {
                        cuts.Add(Mathf.Lerp(a.x, b.x, fa / (fa - fb)));   // x where the edge crosses
                    }
                }
                cuts.Sort();
                for (int k = 0; k + 1 < cuts.Count; k += 2)
                {
                    AddLine(new[] { new Vector2(cuts[k], c - cuts[k]), new Vector2(cuts[k + 1], c - cuts[k + 1]) },
                            color, widthCm * 0.6f, false);
                }
            }
        }

        /// <summary>An arrow from one point to another (cm).</summary>
        public void AddArrow(Vector2 from, Vector2 to, Color color, float widthCm)
        {
            Vector2 d = to - from;
            if (d.sqrMagnitude < 1e-6f) return;
            AddLine(new[] { from, to }, color, widthCm, false);
            Vector2 back = -d.normalized;
            float head = Mathf.Clamp(d.magnitude * 0.35f, widthCm * 3, widthCm * 10);
            foreach (float turn in new[] { 30f, -30f })
            {
                Vector2 side = (Vector2)(Quaternion.Euler(0, 0, turn) * back) * head;
                AddLine(new[] { to, to + side }, color, widthCm, false);
            }
        }

        private void Place(Line line)
        {
            float m = _metresPerCm;
            var pts = new Vector3[line.Cm.Length];
            for (int i = 0; i < pts.Length; i++)
            {
                // frame (x, y) on the paper -> image plane (X right, Z to the top edge), Y up from the paper
                Vector2 q = line.Cm[i] + _offsetCm;
                pts[i] = new Vector3(q.x * m, liftCm * m, (flipImageY ? -1 : 1) * q.y * m);
            }
            line.Renderer.positionCount = pts.Length;
            line.Renderer.SetPositions(pts);
            line.Renderer.widthMultiplier = line.WidthCm * m;
        }
    }
}
