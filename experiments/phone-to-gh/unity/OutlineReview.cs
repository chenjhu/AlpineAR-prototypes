using System;
using System.Collections;
using System.Collections.Generic;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace Compas.GeoViewerXR
{
    /// <summary>
    /// AlpineAR flow steps 4-10, over the live camera view, after PhotoSender sent a photo:
    /// <list type="bullet">
    /// <item>4-5: waits for Grasshopper's outlines (MESSAGES.md message 2), draws them where they
    /// were in the photo, asks "Are these the stones?" and sends Yes / No (message 3). No, or no
    /// outlines within the timeout, goes back to "Tap when in position".</item>
    /// <item>6-7: after Yes, waits for the zone (message 4) and shows only the size of the next
    /// stone, on a panel of its own ("NEXT STONE": the stone seen from above, big numbers). The
    /// boxes are not shown yet: the person now walks to the stone stock and needs the size, not
    /// the place.</item>
    /// <item>8-10 ("Check size"): the person taps the candidate stone on the camera view; that
    /// tap takes the photo and is sent with it (message 5, <c>tap</c>). Then the fit check
    /// (message 6): green outline, jingle and vibration if it fits; red outline and "Wrong size"
    /// if not (no sound, as in the group's flow, 1.5). The panel shows this stone's numbers
    /// next to the needed ones.</item>
    /// <item>"Show placement" (back at the wall): the layer's outlines and the zone's max
    /// (white) and min (blue) boxes over the live view again. Nothing is sent: the person holds
    /// the phone so the outlines sit on the stones.</item>
    /// </list>
    /// <para>Everything is fixed to the screen (2D), not placed in AR: it matches the stones
    /// only while the phone is where it took the photo.</para>
    /// Add it next to PhotoSender.
    /// </summary>
    public class OutlineReview : MonoBehaviour
    {
        [Tooltip("Seconds to wait for the outlines, the zone or the fit check before giving up.")]
        public float replyTimeout = 15f;

        public Color outlineColor = Color.red;
        public Color maxColor = Color.white;                       // Mode 1's "allowed" box
        public Color minColor = new Color(0.1f, 0.5f, 1f, 1f);     // Mode 1's "must" box
        public Color candidateColor = Color.green;                 // the checked stone, it fits
        public Color wrongSizeColor = Color.red;                   // the checked stone, it does not
        public Color tapColor = new Color(1f, 0.2f, 1f, 1f);       // where the stone was tapped

        // In photo pixels; the photo is shown about 3x larger on screen. (New names on
        // 2026-11-24, so the scene's old width of 5 does not carry over.)
        [Tooltip("Width of the stone outlines, in photo pixels.")]
        public int outlineWidth = 3;

        [Tooltip("Width of the zone's boxes, in photo pixels.")]
        public int boxWidth = 2;

        // The must zone (min) is hatched, the allowed zone (max) only outlined (2026-11-24).
        [Tooltip("Distance between the hatch lines of the must zone, in photo pixels.")]
        public int hatchSpacing = 8;

        [Tooltip("Width of the hatch lines, in photo pixels.")]
        public int hatchWidth = 2;

        [Tooltip("Hide the course template's dotted AR planes and its cube button at the bottom. Untick to get them back.")]
        public bool hideCourseExtras = true;

        [SerializeField] private PhotoSender sender;

        // Zone: the size is shown (or the zone did not come); from here stones can be tapped.
        // Placement: the layer's outlines and boxes are shown again, back at the wall.
        private enum State { Off, Waiting, Asking, WaitingZone, Zone, WaitingFit, Placement }

        // iOS system colours, for the panel's text.
        private static readonly Color Green = new Color32(48, 209, 88, 255);
        private static readonly Color Red = new Color32(255, 69, 58, 255);
        private static readonly Color Dim = new Color(1f, 1f, 1f, 0.55f);

        private State _state = State.Off;
        private bool _hasZone;
        private double _candidateTs;
        private bool _sendingCandidate;
        private AudioClip _zoneSound, _fitsSound;
        private Texture2D _overlay;  // photo-sized, transparent except the lines
        private Color32[] _pixels;
        private int _photoW, _photoH;
        private double _photoTs;
        private float _giveUpAt;
        private bool _answering;
        private string _message = "";
        private string _messageBeforePlacement = "";
        private AudioSource _audio;

        // Kept to draw them again for "Show placement".
        private readonly List<JArray> _stoneOutlines = new List<JArray>();
        private Vector2 _stoneScale = Vector2.one;
        private JArray _zoneMax, _zoneMin;
        private Vector2 _zoneScale = Vector2.one;

        // The size of the next stone (cm, [min, max]; null without the QR marker) and the
        // last checked stone (result null = none checked since the zone came).
        private double[] _needLength, _needDepth;
        private string _fitResult;
        private double _fitAlong, _fitAcross;

        private void Awake()
        {
            if (sender == null) sender = FindAnyObjectByType<PhotoSender>();
            if (sender == null) Debug.LogError("OutlineReview: no PhotoSender in the scene.", this);

            _audio = gameObject.AddComponent<AudioSource>();
            _audio.playOnAwake = false;
            _zoneSound = MakeTones("Zone", 0.15f, 660f, 990f);
            _fitsSound = MakeTones("Fits", 0.12f, 784f, 988f, 1319f);  // rising: the jingle

            gameObject.AddComponent<CourseExtras>().hide = hideCourseExtras;
        }

        private void OnEnable()
        {
            if (sender == null) return;
            sender.PhotoSent += OnPhotoSent;
            sender.OutlinesReceived += OnOutlines;
            sender.ZoneReceived += OnZone;
            sender.FitReceived += OnFit;
        }

        private void OnDisable()
        {
            if (sender == null) return;
            sender.PhotoSent -= OnPhotoSent;
            sender.OutlinesReceived -= OnOutlines;
            sender.ZoneReceived -= OnZone;
            sender.FitReceived -= OnFit;
        }

        private void Update()
        {
            if (Time.realtimeSinceStartup <= _giveUpAt) return;

            if (_state == State.Waiting)
            {
                BackToStart("No answer from Grasshopper");
            }
            else if (_state == State.WaitingZone)
            {
                _message = "No zone from Grasshopper";
                _state = State.Zone;
            }
            else if (_state == State.WaitingFit)
            {
                _message = "No answer from Grasshopper, tap the stone again";
                _state = State.Zone;
            }
        }

        private void OnPhotoSent(Texture2D photo, double ts)
        {
            // Only the photo's size is needed: the live camera view is shown instead.
            _photoW = photo.width;
            _photoH = photo.height;
            Destroy(photo);

            ClearOverlay();
            _photoTs = ts;
            _hasZone = false;
            _stoneOutlines.Clear();
            _zoneMax = _zoneMin = null;
            _needLength = _needDepth = null;
            _fitResult = null;
            _state = State.Waiting;
            _giveUpAt = Time.realtimeSinceStartup + replyTimeout;
            _message = "Waiting for Grasshopper...";
            sender.showButton = false;
        }

        private void OnOutlines(string json)
        {
            if (_state != State.Waiting) return;

            try
            {
                JObject msg = JObject.Parse(json);
                if (!IsForThisPhoto(msg)) return;

                _pixels = new Color32[_photoW * _photoH];  // all transparent
                _stoneScale = ScaleOf(msg);
                _stoneOutlines.Clear();
                foreach (JToken stone in msg["stones"] ?? new JArray())
                {
                    if (stone["outline"] is JArray outline && DrawOutline(outline, _stoneScale, outlineColor, outlineWidth))
                    {
                        _stoneOutlines.Add(outline);
                    }
                }

                ShowOverlay();
                int count = _stoneOutlines.Count;
                _message = count == 1 ? "1 stone found" : $"{count} stones found";
                _state = State.Asking;
            }
            catch (Exception e)
            {
                Debug.LogWarning($"OutlineReview: outlines message ignored ({e.Message})");
            }
        }

        private void OnZone(string json)
        {
            if (_state != State.WaitingZone) return;

            try
            {
                JObject msg = JObject.Parse(json);
                if (!IsForThisPhoto(msg)) return;

                // The layer's outlines go off the screen now; they come back with "Show placement".
                ClearOverlay();
                string note = (string)msg["note"];
                if (!string.IsNullOrEmpty(note))
                {
                    _message = $"No zone: {note}";
                }
                else
                {
                    _zoneMax = msg["max"] as JArray;
                    _zoneMin = msg["min"] as JArray;
                    _zoneScale = ScaleOf(msg);
                    _needLength = RangeOf(msg["length_cm"]);
                    _needDepth = RangeOf(msg["depth_range_cm"]);
                    _hasZone = true;
                    _fitResult = null;
                    _message = _needLength != null
                        ? "Find a stone of this size, then tap it on the screen to check it"
                        : "No size without the QR marker in the photo. Take the photo again with it";
                }

                _audio.PlayOneShot(_zoneSound);
                _state = State.Zone;
            }
            catch (Exception e)
            {
                Debug.LogWarning($"OutlineReview: zone message ignored ({e.Message})");
            }
        }

        /// <summary>[min, max] from a JSON pair, or null.</summary>
        private static double[] RangeOf(JToken token)
        {
            return token is JArray a && a.Count == 2 && a[0].Type != JTokenType.Null
                ? new[] { (double)a[0], (double)a[1] }
                : null;
        }

        /// <summary>
        /// Flow step 8 ("Check size"): the person tapped the candidate stone at
        /// <paramref name="tapGui"/> (screen point, GUI coordinates). That tap takes the photo.
        /// </summary>
        private void CheckSize(Vector2 tapGui)
        {
            if (!_sendingCandidate) StartCoroutine(CheckSizeRoutine(tapGui));
        }

        private IEnumerator CheckSizeRoutine(Vector2 tapGui)
        {
            _sendingCandidate = true;
            _fitResult = null;
            _message = "Sending the stone photo...";

            bool captured = false, arrived = false;
            yield return sender.SendCandidate(_photoTs, (w, h) => ScreenToPhoto(tapGui, w, h), (ts, size, tap) =>
            {
                // Wait for the fit from now on: Grasshopper may answer before the broker's
                // receipt for the photo comes back (as with the zone).
                captured = true;
                _candidateTs = ts;
                _state = State.WaitingFit;
                _giveUpAt = Time.realtimeSinceStartup + replyTimeout;

                // Mark where the stone was tapped.
                _pixels = new Color32[_photoW * _photoH];
                if (tap.HasValue) DrawTap(tap.Value, new Vector2((float)_photoW / size.x, (float)_photoH / size.y));
                ShowOverlay();
            }, r => arrived = r);
            _sendingCandidate = false;

            if (!captured)
            {
                _message = "No camera image yet, tap again";
            }
            else if (_state == State.WaitingFit)  // the fit has not come yet
            {
                if (arrived)
                {
                    _message = "Checking the stone...";
                }
                else
                {
                    _state = State.Zone;
                    _message = "Not sent, tap the stone again";
                }
            }
        }

        /// <summary>
        /// A screen point (GUI coordinates: top-left origin, y down) -> the pixel of a w x h
        /// camera photo shown there (top-left origin, y down, as sent). The exact inverse of how
        /// OnGUI places the photo-sized overlay: turned with the screen, scaled to fill it,
        /// centred. (Checked: screen -> photo -> screen gives the same point, all orientations.)
        /// </summary>
        private static Vector2 ScreenToPhoto(Vector2 gui, int w, int h)
        {
            float turn = TurnFor(Screen.orientation);
            bool sideways = Mathf.Abs(Mathf.Abs(turn) - 90f) < 1f;
            float scale = Mathf.Max(Screen.width / (sideways ? (float)h : w), Screen.height / (sideways ? (float)w : h));
            Vector2 d = gui - new Vector2(Screen.width / 2f, Screen.height / 2f);
            // OnGUI turns by +turn around the centre (GUIUtility.RotateAroundPivot); undo it.
            float a = -turn * Mathf.Deg2Rad;
            var u = new Vector2(d.x * Mathf.Cos(a) - d.y * Mathf.Sin(a), d.x * Mathf.Sin(a) + d.y * Mathf.Cos(a));
            return new Vector2(Mathf.Clamp(u.x / scale + w / 2f, 0, w - 1), Mathf.Clamp(u.y / scale + h / 2f, 0, h - 1));
        }

        /// <summary>Flow steps 9-10: the fit check for the candidate (message 6).</summary>
        private void OnFit(string json)
        {
            if (_state != State.WaitingFit) return;

            try
            {
                JObject msg = JObject.Parse(json);
                double photoTs = (double?)msg["photo_ts"] ?? -1;
                if (Math.Abs(photoTs - _candidateTs) > 0.001) return;  // another stone's check

                string result = (string)msg["result"];
                string note = (string)msg["note"];
                // Which side goes along the wall (MESSAGES.md, message 6).
                _fitAlong = (double?)msg["along_cm"] ?? (double?)msg["length_cm"] ?? 0;
                _fitAcross = (double?)msg["across_cm"] ?? (double?)msg["width_cm"] ?? 0;
                _fitResult = result;
                bool fits = result == "fits";

                // Show which stone was checked: its outline in the candidate photo, over the live
                // view (it matches while the phone stays where it took the photo).
                _pixels = new Color32[_photoW * _photoH];
                DrawOutline(msg["outline"] as JArray, ScaleOf(msg), fits ? candidateColor : wrongSizeColor, outlineWidth);
                ShowOverlay();

                switch (result)
                {
                    case "fits":
                        _message = "This stone fits. Back at the wall, tap Show placement";
                        _audio.PlayOneShot(_fitsSound);
                        Handheld.Vibrate();
                        break;
                    case "too_short":
                    case "too_long":
                    case "too_shallow":
                    case "too_deep":
                        _message = "Wrong size. Try another stone or shape it";
                        break;  // no jingle or vibration (flow 1.5)
                    default:  // "unknown": no check possible
                        _fitResult = null;  // no numbers to show
                        _message = $"No check: {note}. Tap the stone again";
                        break;
                }

                _state = State.Zone;
            }
            catch (Exception e)
            {
                Debug.LogWarning($"OutlineReview: fit message ignored ({e.Message})");
            }
        }

        /// <summary>Back at the wall: the layer's outlines and the zone's boxes, as in the first photo.</summary>
        private void ShowPlacement()
        {
            _pixels = new Color32[_photoW * _photoH];
            foreach (JArray outline in _stoneOutlines) DrawOutline(outline, _stoneScale, outlineColor, outlineWidth);
            DrawOutline(_zoneMax, _zoneScale, maxColor, boxWidth);   // allowed zone: a contour
            DrawHatch(_zoneMin, _zoneScale, minColor);                // must zone: a hatch
            ShowOverlay();
            _messageBeforePlacement = _message;
            _message = "Hold the phone so the red outlines sit on your stones. The new stone must cover the hatched zone and stay inside the white outline";
            _state = State.Placement;
        }

        private void HidePlacement()
        {
            ClearOverlay();
            _message = _messageBeforePlacement;
            _state = State.Zone;
        }

        private bool IsForThisPhoto(JObject msg)
        {
            double photoTs = (double?)msg["photo_ts"] ?? -1;
            return Math.Abs(photoTs - _photoTs) <= 0.001;
        }

        /// <summary>
        /// Points are pixels of the photo as sent. If Grasshopper got it in another size,
        /// scale them to this one.
        /// </summary>
        private Vector2 ScaleOf(JObject msg)
        {
            if (msg["image_size"] is JArray size && size.Count == 2)
            {
                return new Vector2((float)_photoW / (int)size[0], (float)_photoH / (int)size[1]);
            }
            return Vector2.one;
        }

        /// <summary>Draws one closed outline into <see cref="_pixels"/>. False if there is none.</summary>
        private bool DrawOutline(JArray points, Vector2 scale, Color color, int width)
        {
            if (points == null || points.Count < 2 || _pixels == null) return false;

            var line = new List<Vector2>(points.Count);
            foreach (JToken p in points)
            {
                // In the JPEG the origin is top-left with y down; in a texture it is
                // bottom-left with y up.
                line.Add(new Vector2((float)p[0] * scale.x, _photoH - 1 - (float)p[1] * scale.y));
            }

            for (int i = 0; i < line.Count; i++)
            {
                DrawLine(line[i], line[(i + 1) % line.Count], color, width);  // closed
            }
            return true;
        }

        /// <summary>
        /// Fills one closed outline with diagonal lines (a hatch) into <see cref="_pixels"/>,
        /// with a thin edge so the hatch ends cleanly.
        /// </summary>
        private void DrawHatch(JArray points, Vector2 scale, Color color)
        {
            if (points == null || points.Count < 3 || _pixels == null) return;

            var poly = new List<Vector2>(points.Count);
            float yMin = float.MaxValue, yMax = float.MinValue;
            foreach (JToken p in points)
            {
                var v = new Vector2((float)p[0] * scale.x, _photoH - 1 - (float)p[1] * scale.y);
                poly.Add(v);
                yMin = Mathf.Min(yMin, v.y);
                yMax = Mathf.Max(yMax, v.y);
            }

            Color32 c = color;
            int spacing = Mathf.Max(3, hatchSpacing), width = Mathf.Clamp(hatchWidth, 1, spacing - 1);
            var xs = new List<float>();
            for (int y = Mathf.Max(0, Mathf.CeilToInt(yMin)); y <= Mathf.Min(_photoH - 1, Mathf.FloorToInt(yMax)); y++)
            {
                // Where this row crosses the outline; inside = between pairs (even-odd).
                xs.Clear();
                for (int i = 0; i < poly.Count; i++)
                {
                    Vector2 a = poly[i], b = poly[(i + 1) % poly.Count];
                    if ((a.y <= y && b.y > y) || (b.y <= y && a.y > y))
                    {
                        xs.Add(a.x + (y - a.y) / (b.y - a.y) * (b.x - a.x));
                    }
                }
                xs.Sort();
                for (int k = 0; k + 1 < xs.Count; k += 2)
                {
                    int x0 = Mathf.Max(0, Mathf.CeilToInt(xs[k])), x1 = Mathf.Min(_photoW - 1, Mathf.FloorToInt(xs[k + 1]));
                    for (int x = x0; x <= x1; x++)
                    {
                        if ((x + y) % spacing < width) _pixels[y * _photoW + x] = c;   // 45-degree lines
                    }
                }
            }
            DrawOutline(points, scale, color, 1);
        }

        /// <summary>A small cross where the stone was tapped (photo pixels, y down).</summary>
        private void DrawTap(Vector2 tap, Vector2 scale)
        {
            var p = new Vector2(tap.x * scale.x, _photoH - 1 - tap.y * scale.y);
            const float arm = 14f;
            DrawLine(p - new Vector2(arm, arm), p + new Vector2(arm, arm), tapColor, outlineWidth);
            DrawLine(p - new Vector2(arm, -arm), p + new Vector2(arm, -arm), tapColor, outlineWidth);
        }

        private void DrawLine(Vector2 a, Vector2 b, Color32 color, int width)
        {
            int w = _photoW, h = _photoH;
            int lo = -(width - 1) / 2, hi = width / 2;  // e.g. width 2 -> 0..1, width 3 -> -1..1
            int steps = Mathf.CeilToInt(Vector2.Distance(a, b)) + 1;
            for (int s = 0; s <= steps; s++)
            {
                Vector2 p = Vector2.Lerp(a, b, (float)s / steps);
                int cx = Mathf.RoundToInt(p.x), cy = Mathf.RoundToInt(p.y);
                for (int y = cy + lo; y <= cy + hi; y++)
                {
                    if (y < 0 || y >= h) continue;
                    for (int x = cx + lo; x <= cx + hi; x++)
                    {
                        if (x >= 0 && x < w) _pixels[y * w + x] = color;
                    }
                }
            }
        }

        private void ShowOverlay()
        {
            if (_overlay == null) _overlay = new Texture2D(_photoW, _photoH, TextureFormat.RGBA32, false);
            _overlay.SetPixels32(_pixels);
            _overlay.Apply();
        }

        private void Answer(bool ok)
        {
            if (!_answering) StartCoroutine(AnswerRoutine(ok));
        }

        private IEnumerator AnswerRoutine(bool ok)
        {
            _answering = true;
            _message = "Sending...";

            // MESSAGES.md, message 3
            string json = JsonConvert.SerializeObject(new Dictionary<string, object>
            {
                { "photo_ts", _photoTs },
                { "ok", ok },
                { "ts", DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0 },
            });

            // Wait for the zone from now on, not only after the broker's receipt: Grasshopper may
            // answer so fast that the zone arrives before the receipt does (seen on the Pixel 8).
            if (ok)
            {
                _state = State.WaitingZone;
                _giveUpAt = Time.realtimeSinceStartup + replyTimeout;
            }

            bool arrived = false;
            yield return sender.PublishJson(PhotoSender.AnswerTopic, json, r => arrived = r);
            _answering = false;

            if (_state == State.Zone)
            {
                // the zone came already, so the answer got through
            }
            else if (!arrived)
            {
                _state = State.Asking;
                _message = "Not sent, tap again";
            }
            else if (ok)
            {
                if (_state == State.WaitingZone) _message = "OK, waiting for the size...";
            }
            else
            {
                BackToStart("Take the photo again");
            }
        }

        private void BackToStart(string status)
        {
            ClearOverlay();
            _state = State.Off;
            _message = "";
            sender.ShowStatus(status);
            sender.showButton = true;
        }

        private void ClearOverlay()
        {
            if (_overlay != null) Destroy(_overlay);
            _overlay = null;
            _pixels = null;
        }

        private void OnDestroy()
        {
            ClearOverlay();
        }

        /// <summary>A few short notes (Hz) one after another, made in code so no sound file is needed.</summary>
        private static AudioClip MakeTones(string name, float noteLength, params float[] notes)
        {
            const int rate = 44100;
            int perNote = (int)(rate * noteLength);
            var samples = new float[perNote * notes.Length];
            for (int n = 0; n < notes.Length; n++)
            {
                for (int i = 0; i < perNote; i++)
                {
                    float t = (float)i / rate;
                    float fade = 1f - (float)i / perNote;
                    samples[n * perNote + i] = 0.4f * fade * Mathf.Sin(2f * Mathf.PI * notes[n] * t);
                }
            }

            AudioClip clip = AudioClip.Create(name, samples.Length, 1, rate, false);
            clip.SetData(samples, 0);
            return clip;
        }

        /// <summary>
        /// How far to turn the photo to match the screen. The photo is the camera sensor's
        /// image (landscape); with the phone held upright it turns a quarter counterclockwise
        /// (checked on the Pixel 8: +90 showed it upside down).
        /// </summary>
        private static float TurnFor(ScreenOrientation orientation)
        {
            switch (orientation)
            {
                case ScreenOrientation.Portrait: return -90f;
                case ScreenOrientation.PortraitUpsideDown: return 90f;
                case ScreenOrientation.LandscapeRight: return 180f;
                default: return 0f;  // LandscapeLeft: the sensor's own orientation
            }
        }

        /// <summary>"4.7" below 10 cm, "21" from 10 cm on.</summary>
        private static string Cm(double v) => v < 10 ? v.ToString("0.0") : v.ToString("0");

        private static string RangeText(double[] r) => r == null ? "–" : $"{Cm(r[0])}–{Cm(r[1])}";

        private static bool InRange(double v, double[] r) => r == null || (v >= r[0] - 1e-6 && v <= r[1] + 1e-6);

        /// <summary>
        /// The "NEXT STONE" panel at the top. Left: the stone seen from above as a soft rounded
        /// shape (as long and deep as asked) with its two dimension lines. Right: the two numbers,
        /// big, each with a small word above it. After a check, this stone's own number under
        /// each, green in range and red out of it, and the shape turns green or red.
        /// Returns where the panel is.
        /// </summary>
        private Rect DrawSizePanel()
        {
            float h = AlpineUI.ButtonHeight;
            // Below the course scene's status line and left of its round buttons at the top right
            // (seen in the Pixel 8 video, 2026-11-24), so neither is covered.
            float top = Mathf.Max(Screen.height - Screen.safeArea.yMax + h * 0.3f, Screen.height * 0.085f);
            var panel = new Rect(Screen.width * 0.05f, top, Screen.width * 0.78f, h * 3.5f);
            AlpineUI.Fill(panel, AlpineUI.CardFill, h * 0.32f);

            float pad = h * 0.4f;
            AlpineUI.Text(new Rect(panel.x + pad, panel.y + h * 0.22f, panel.width, h * 0.3f),
                          "NEXT STONE", h * 0.19f, Dim, TextAnchor.UpperLeft, true);

            if (_needLength == null)
            {
                AlpineUI.Text(new Rect(panel.x + pad, panel.y, panel.width - 2 * pad, panel.height),
                              "No size yet", h * 0.3f, Dim, TextAnchor.MiddleLeft);
                return panel;
            }

            // Left: the shape. length : depth, so a stone deeper than long is drawn taller than
            // wide (as in the 2026-11-24 test: length 1.7-5.0, depth 4.1-5.0).
            double midLength = (_needLength[0] + _needLength[1]) / 2;
            double midDepth = _needDepth != null ? (_needDepth[0] + _needDepth[1]) / 2 : midLength / 2;
            float ratio = Mathf.Clamp((float)(midLength / Math.Max(midDepth, 0.1)), 0.5f, 3f);
            var area = new Rect(panel.x + pad, panel.y + h * 0.75f, panel.width * 0.34f, h * 2.3f);
            float maxW = area.width - h * 0.45f, maxH = area.height - h * 0.45f;  // room for the lines
            float shapeW = Mathf.Min(maxW, maxH * ratio);
            float shapeH = shapeW / ratio;
            var shape = new Rect(area.x + (maxW - shapeW) / 2, area.y + (maxH - shapeH) / 2, shapeW, shapeH);

            bool checkedStone = _fitResult != null;
            bool fits = _fitResult == "fits";
            Color fill = !checkedStone ? new Color(1f, 1f, 1f, 0.16f)
                : fits ? new Color(Green.r, Green.g, Green.b, 0.35f) : new Color(Red.r, Red.g, Red.b, 0.35f);
            AlpineUI.Fill(shape, fill, h * 0.16f);

            // Its dimension lines: length under it, depth beside it (which number is which).
            float line = Mathf.Max(2f, h * 0.02f), tick = h * 0.1f;
            var lineColor = new Color(1f, 1f, 1f, 0.6f);
            float ly = shape.yMax + h * 0.22f;
            AlpineUI.Line(new Rect(shape.x, ly - line / 2, shape.width, line), lineColor);
            AlpineUI.Line(new Rect(shape.x, ly - tick, line, 2 * tick), lineColor);
            AlpineUI.Line(new Rect(shape.xMax - line, ly - tick, line, 2 * tick), lineColor);
            float dx = shape.xMax + h * 0.22f;
            AlpineUI.Line(new Rect(dx - line / 2, shape.y, line, shape.height), lineColor);
            AlpineUI.Line(new Rect(dx - tick, shape.y, 2 * tick, line), lineColor);
            AlpineUI.Line(new Rect(dx - tick, shape.yMax - line, 2 * tick, line), lineColor);

            // Right: the numbers.
            float tx = area.xMax + h * 0.3f, tw = panel.xMax - pad - tx;
            float y = NumberBlock(tx, panel.y + h * 0.72f, tw, "LENGTH · along the wall", _needLength, _fitAlong, h);
            NumberBlock(tx, y + h * 0.15f, tw, "DEPTH · into the wall", _needDepth, _fitAcross, h);
            return panel;
        }

        /// <summary>A small word, the range big with a small "cm", and after a check this stone's
        /// number in green or red. Returns the y under it (the same with or without a check, so
        /// nothing moves).</summary>
        private float NumberBlock(float x, float y, float w, string label, double[] need, double measured, float h)
        {
            float small = h * 0.19f, big = h * 0.5f;
            AlpineUI.Text(new Rect(x, y, w, small * 1.4f), label, small, Dim, TextAnchor.UpperLeft, true);
            y += small * 1.45f;
            string range = RangeText(need);
            AlpineUI.Text(new Rect(x, y, w, big * 1.25f), range, big, Color.white, TextAnchor.UpperLeft, true);
            float rangeW = AlpineUI.TextWidth(range, big, true);
            AlpineUI.Text(new Rect(x + rangeW + h * 0.08f, y + big * 0.5f, w, small * 1.5f), "cm", small * 1.2f, Dim, TextAnchor.UpperLeft);
            y += big * 1.2f;
            if (_fitResult != null && need != null)
            {
                AlpineUI.Text(new Rect(x, y, w, small * 1.5f), $"this stone {Cm(measured)}", small * 1.15f,
                              InRange(measured, need) ? Green : Red, TextAnchor.UpperLeft, true);
            }
            return y + small * 1.5f;
        }

        private void OnGUI()
        {
            if (_state == State.Off) return;

            float buttonH = AlpineUI.ButtonHeight;  // look: AlpineUI.cs

            if (_overlay != null)
            {
                // The AR view shows the camera image turned and scaled to fill the whole
                // screen (cut off at the sides). Place the lines the same way.
                var screen = new Rect(0, 0, Screen.width, Screen.height);
                float turn = TurnFor(Screen.orientation);
                bool sideways = Mathf.Abs(Mathf.Abs(turn) - 90f) < 1f;
                float onScreenW = sideways ? _photoH : _photoW;
                float onScreenH = sideways ? _photoW : _photoH;
                float scale = Mathf.Max(screen.width / onScreenW, screen.height / onScreenH);

                var rect = new Rect(0, 0, _photoW * scale, _photoH * scale) { center = screen.center };
                Matrix4x4 before = GUI.matrix;
                GUIUtility.RotateAroundPivot(turn, screen.center);
                GUI.DrawTexture(rect, _overlay);
                GUI.matrix = before;
            }

            // Text card and buttons at the bottom, over the camera view. Blue = the main action.
            var labelRect = new Rect(Screen.width * 0.05f, Screen.height * 0.70f, Screen.width * 0.9f, buttonH * 1.3f);
            float buttonY = labelRect.yMax + buttonH * 0.25f;
            float gap = Screen.width * 0.03f;
            float buttonW = (labelRect.width - gap) / 2f;
            var leftButton = new Rect(labelRect.x, buttonY, buttonW, buttonH);
            var rightButton = new Rect(labelRect.x + buttonW + gap, buttonY, buttonW, buttonH);
            var middleButton = new Rect((Screen.width - buttonW) / 2f, buttonY, buttonW, buttonH);

            switch (_state)
            {
                case State.Waiting:
                case State.WaitingZone:
                    AlpineUI.Card(labelRect, _message);
                    break;

                case State.Asking:
                    AlpineUI.Card(labelRect, $"Are these the stones?  ({_message})");
                    if (AlpineUI.Button(leftButton, "Yes", true, !_answering)) Answer(true);
                    if (AlpineUI.Button(rightButton, "No", false, !_answering)) Answer(false);
                    break;

                case State.Zone:
                case State.WaitingFit:
                    Rect panel = _hasZone ? DrawSizePanel() : new Rect(0, 0, 0, 0);
                    Rect card = AlpineUI.Card(labelRect, _message);
                    bool on = _state == State.Zone && !_sendingCandidate;
                    // "Check size" is a tap on the stone itself, between the panel and the text
                    // card (GUI.matrix is back to normal here, so the point is a plain screen point).
                    Event e = Event.current;
                    if (_hasZone && on && _needLength != null && e.type == EventType.MouseDown
                        && e.mousePosition.y > panel.yMax && e.mousePosition.y < card.y)
                    {
                        CheckSize(e.mousePosition);
                        e.Use();
                    }
                    if (_hasZone)
                    {
                        // Blue once a stone fits: that is the next thing to do.
                        if (AlpineUI.Button(leftButton, "Show placement", _fitResult == "fits", on)) ShowPlacement();
                        if (AlpineUI.Button(rightButton, "New photo", false, on)) BackToStart("");
                    }
                    else if (AlpineUI.Button(middleButton, "New photo", false, on))
                    {
                        BackToStart("");
                    }
                    break;

                case State.Placement:
                    AlpineUI.Card(labelRect, _message);
                    if (AlpineUI.Button(leftButton, "Back", false)) HidePlacement();
                    // The stone is placed: the next round starts with a new photo of the layer.
                    if (AlpineUI.Button(rightButton, "Next stone", true)) BackToStart("");
                    break;
            }
        }
    }
}
