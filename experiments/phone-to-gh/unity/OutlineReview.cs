using System;
using System.Collections;
using System.Collections.Generic;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace Compas.GeoViewerXR
{
    /// <summary>
    /// AlpineAR flow steps 4-7, over the live camera view, after PhotoSender sent a photo:
    /// <list type="bullet">
    /// <item>4-5: waits for Grasshopper's outlines (MESSAGES.md message 2), draws them where they
    /// were in the photo, asks "Are these the stones?" and sends Yes / No (message 3). No, or no
    /// outlines within the timeout, goes back to "Tap when in position".</item>
    /// <item>6-7: after Yes, waits for the zone (message 4), draws its max (white) and min (blue)
    /// outline the same way and plays a sound.</item>
    /// </list>
    /// <para>Everything is fixed to the screen (2D), not placed in AR: it matches the stones
    /// only while the phone stays where it took the photo.</para>
    /// Add it next to PhotoSender.
    /// </summary>
    public class OutlineReview : MonoBehaviour
    {
        [Tooltip("Seconds to wait for the outlines, and for the zone, before giving up.")]
        public float replyTimeout = 15f;

        public Color outlineColor = Color.red;
        public Color maxColor = Color.white;                       // Mode 1's "allowed" box
        public Color minColor = new Color(0.1f, 0.5f, 1f, 1f);     // Mode 1's "must" box

        [Tooltip("Line width in photo pixels (the photo is shown about 3x larger on screen).")]
        public int lineWidth = 5;

        [SerializeField] private PhotoSender sender;

        private enum State { Off, Waiting, Asking, WaitingZone, Zone }

        private State _state = State.Off;
        private Texture2D _overlay;  // photo-sized, transparent except the lines
        private Color32[] _pixels;
        private int _photoW, _photoH;
        private double _photoTs;
        private float _giveUpAt;
        private bool _answering;
        private string _message = "";
        private AudioSource _audio;
        private GUIStyle _buttonStyle;
        private GUIStyle _labelStyle;

        private void Awake()
        {
            if (sender == null) sender = FindAnyObjectByType<PhotoSender>();
            if (sender == null) Debug.LogError("OutlineReview: no PhotoSender in the scene.", this);

            _audio = gameObject.AddComponent<AudioSource>();
            _audio.playOnAwake = false;
            _audio.clip = MakeChime();
        }

        private void OnEnable()
        {
            if (sender == null) return;
            sender.PhotoSent += OnPhotoSent;
            sender.OutlinesReceived += OnOutlines;
            sender.ZoneReceived += OnZone;
        }

        private void OnDisable()
        {
            if (sender == null) return;
            sender.PhotoSent -= OnPhotoSent;
            sender.OutlinesReceived -= OnOutlines;
            sender.ZoneReceived -= OnZone;
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
        }

        private void OnPhotoSent(Texture2D photo, double ts)
        {
            // Only the photo's size is needed: the live camera view is shown instead.
            _photoW = photo.width;
            _photoH = photo.height;
            Destroy(photo);

            ClearOverlay();
            _photoTs = ts;
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
                Vector2 scale = ScaleOf(msg);
                int count = 0;
                foreach (JToken stone in msg["stones"] ?? new JArray())
                {
                    if (DrawOutline(stone["outline"] as JArray, scale, outlineColor)) count++;
                }

                ShowOverlay();
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

                string note = (string)msg["note"];
                if (!string.IsNullOrEmpty(note))
                {
                    _message = $"No zone: {note}";
                }
                else
                {
                    Vector2 scale = ScaleOf(msg);
                    DrawOutline(msg["max"] as JArray, scale, maxColor);
                    DrawOutline(msg["min"] as JArray, scale, minColor);
                    ShowOverlay();
                    _message = "Next stone: cover the blue box, stay inside the white one";
                }

                _audio.Play();
                _state = State.Zone;
            }
            catch (Exception e)
            {
                Debug.LogWarning($"OutlineReview: zone message ignored ({e.Message})");
            }
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
        private bool DrawOutline(JArray points, Vector2 scale, Color color)
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
                DrawLine(line[i], line[(i + 1) % line.Count], color);  // closed
            }
            return true;
        }

        private void DrawLine(Vector2 a, Vector2 b, Color32 color)
        {
            int w = _photoW, h = _photoH;
            int half = lineWidth / 2;
            int steps = Mathf.CeilToInt(Vector2.Distance(a, b)) + 1;
            for (int s = 0; s <= steps; s++)
            {
                Vector2 p = Vector2.Lerp(a, b, (float)s / steps);
                int cx = Mathf.RoundToInt(p.x), cy = Mathf.RoundToInt(p.y);
                for (int y = cy - half; y <= cy + half; y++)
                {
                    if (y < 0 || y >= h) continue;
                    for (int x = cx - half; x <= cx + half; x++)
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
                if (_state == State.WaitingZone) _message = "OK, waiting for the zone...";
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

        /// <summary>A short two-note chime, made in code so no sound file is needed.</summary>
        private static AudioClip MakeChime()
        {
            const int rate = 44100;
            const float noteLength = 0.15f;
            float[] notes = { 660f, 990f };
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

            AudioClip clip = AudioClip.Create("ZoneChime", samples.Length, 1, rate, false);
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

        private void OnGUI()
        {
            if (_state == State.Off) return;

            float buttonH = Screen.height * 0.08f;
            if (_buttonStyle == null)
            {
                _buttonStyle = new GUIStyle(GUI.skin.button) { fontSize = Mathf.RoundToInt(buttonH * 0.3f) };
                _labelStyle = new GUIStyle(GUI.skin.box)
                {
                    fontSize = Mathf.RoundToInt(buttonH * 0.3f),
                    alignment = TextAnchor.MiddleCenter,
                    wordWrap = true,
                };
            }

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

            // Text and buttons at the bottom, over the camera view.
            var labelRect = new Rect(Screen.width * 0.05f, Screen.height * 0.74f, Screen.width * 0.9f, buttonH * 0.9f);
            float buttonY = labelRect.yMax + Screen.height * 0.015f;
            float buttonW = Screen.width * 0.4f;
            var leftButton = new Rect(Screen.width * 0.07f, buttonY, buttonW, buttonH);
            var rightButton = new Rect(Screen.width * 0.53f, buttonY, buttonW, buttonH);
            var middleButton = new Rect((Screen.width - buttonW) / 2f, buttonY, buttonW, buttonH);

            switch (_state)
            {
                case State.Waiting:
                case State.WaitingZone:
                    GUI.Label(labelRect, _message, _labelStyle);
                    break;

                case State.Asking:
                    GUI.Label(labelRect, $"Are these the stones?  ({_message})", _labelStyle);
                    GUI.enabled = !_answering;
                    if (GUI.Button(leftButton, "Yes", _buttonStyle)) Answer(true);
                    if (GUI.Button(rightButton, "No", _buttonStyle)) Answer(false);
                    GUI.enabled = true;
                    break;

                case State.Zone:
                    GUI.Label(labelRect, _message, _labelStyle);
                    // Only so a test can go on without restarting the app (step 11 comes later).
                    if (GUI.Button(middleButton, "New photo", _buttonStyle)) BackToStart("");
                    break;
            }
        }
    }
}
