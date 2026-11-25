using System;
using System.Collections;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Text;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Unity.Collections;
using UnityEngine;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.ARSubsystems;
using uPLibrary.Networking.M2Mqtt;
using uPLibrary.Networking.M2Mqtt.Messages;

namespace Compas.GeoViewerXR
{
    /// <summary>
    /// AlpineAR flow steps 1-2: a "Tap when in position" button takes a photo from the AR
    /// camera feed (no UI drawn on it), sends it to Grasshopper as MESSAGES.md message 1, and
    /// vibrates once the broker confirmed it got the photo.
    ///
    /// <para>It has its own MQTT connection for the alpinear/proto1/* topics (plain JSON). The
    /// course MqttManager stays as it is: it decodes everything as ProtoBuf, keeps only one
    /// subscribed topic and draws every message it receives, so the JSON topics are kept away
    /// from it. Same M2Mqtt library, second connection.</para>
    ///
    /// Add it to any object in the GeoViewer scene; it finds the AR camera by itself.
    /// </summary>
    public class PhotoSender : MonoBehaviour
    {
        // MESSAGES.md, messages 1-6. Do not change here without changing MESSAGES.md first.
        public const string PhotoTopic = "alpinear/proto1/photo";
        public const string OutlinesTopic = "alpinear/proto1/outlines";
        public const string AnswerTopic = "alpinear/proto1/answer";
        public const string ZoneTopic = "alpinear/proto1/zone";
        public const string CandidateTopic = "alpinear/proto1/candidate";
        public const string FitTopic = "alpinear/proto1/fit";
        public const string PlacedTopic = "alpinear/proto1/placed";
        public const string PlacementTopic = "alpinear/proto1/placement";

        public string brokerAddress = "broker.hivemq.com";
        public int brokerPort = 1883;

        [Tooltip("Real long side of the biggest stone in the photo, in cm. Placeholder for the scale.")]
        public float refCm = 45f;

        [Tooltip("Long side of the sent photo, in pixels.")]
        public int maxLongSide = 1280;

        [Range(1, 100)]
        public int jpegQuality = 85;

        [Tooltip("Seconds to wait for the broker's receipt (PUBACK) before saying 'Not sent'.")]
        public float ackTimeout = 6f;

        [Tooltip("Draw the button on screen. OutlineReview turns it off while it shows a photo.")]
        public bool showButton = true;

        [SerializeField] private ARCameraManager cameraManager;
        [SerializeField] private ARRaycastManager raycastManager;

        /// <summary>
        /// Height of the camera above the surface in the middle of the view, in cm, measured
        /// when the last photo was taken (NaN if no surface was found). Not sent yet (step B2).
        /// </summary>
        public float LastHeightCm { get; private set; } = float.NaN;

        /// <summary>Main thread: a photo reached the broker. The receiver now owns the texture.</summary>
        public event Action<Texture2D, double> PhotoSent;

        /// <summary>Main thread: the raw JSON of a message on <see cref="OutlinesTopic"/>.</summary>
        public event Action<string> OutlinesReceived;

        /// <summary>Main thread: the raw JSON of a message on <see cref="ZoneTopic"/>.</summary>
        public event Action<string> ZoneReceived;

        /// <summary>Main thread: the raw JSON of a message on <see cref="FitTopic"/>.</summary>
        public event Action<string> FitReceived;

        /// <summary>Main thread: the raw JSON of a message on <see cref="PlacementTopic"/>.</summary>
        public event Action<string> PlacementReceived;

        private const ushort KeepAliveSeconds = 20;
        private const float ConnectTimeout = 10f;

        private MqttClient _client;
        private bool _connecting;
        private bool _stale;  // the connection may be dead although IsConnected still says true
        private readonly HashSet<ushort> _acked = new HashSet<ushort>();  // filled by the MQTT thread
        private readonly ConcurrentQueue<(string topic, string json)> _incoming = new ConcurrentQueue<(string, string)>();

        private static readonly List<ARRaycastHit> Hits = new List<ARRaycastHit>();

        private bool _busy;
        private bool _configChosen;
        private string _status = "";
        private string _heightText = "";

        /// <summary>The line above the button.</summary>
        public void ShowStatus(string text) => _status = text ?? "";

        private void Awake()
        {
            if (cameraManager == null) cameraManager = FindAnyObjectByType<ARCameraManager>();
            if (raycastManager == null) raycastManager = FindAnyObjectByType<ARRaycastManager>();
            if (cameraManager == null) Debug.LogError("PhotoSender: no ARCameraManager in the scene.", this);
            if (raycastManager == null) Debug.LogWarning("PhotoSender: no ARRaycastManager, no height.", this);
        }

        private void Start()
        {
            // Connect early, so the outlines topic is subscribed before the first photo goes out.
            StartCoroutine(EnsureConnected());
        }

        private void OnEnable()
        {
            if (cameraManager != null && !_configChosen) cameraManager.frameReceived += OnFirstFrame;
        }

        private void OnDisable()
        {
            if (cameraManager != null) cameraManager.frameReceived -= OnFirstFrame;
        }

        private void OnApplicationPause(bool paused)
        {
            // After the app was in the background the connection often is dead, but the client
            // only notices at its next keep-alive. Do not trust it: connect anew.
            if (paused) _stale = true;
            else StartCoroutine(EnsureConnected());
        }

        private void Update()
        {
            while (_incoming.TryDequeue(out (string topic, string json) m))
            {
                if (m.topic == OutlinesTopic) OutlinesReceived?.Invoke(m.json);
                else if (m.topic == ZoneTopic) ZoneReceived?.Invoke(m.json);
                else if (m.topic == PlacementTopic) PlacementReceived?.Invoke(m.json);
                else FitReceived?.Invoke(m.json);
            }

            // While aiming: only say so when AR has not found the surface yet (the height
            // and tilt numbers are not needed on screen, 2026-11-25; they stay in the log).
            if (showButton)
            {
                float height = MeasureHeight(out float tilt, out string source);
                _heightText = float.IsNaN(height) ? "No surface found yet…" : "";
            }
        }

        /// <summary>
        /// Height of the camera above the surface in the middle of the screen, in cm: the
        /// vertical distance (AR world y is up) from the camera to the first upward-facing AR
        /// plane hit by the ray through the screen centre (= the photo's centre). Falls back to
        /// the plane extended past its detected edge, then to ARCore's feature points.
        /// <paramref name="tilt"/> is how far the camera looks away from straight down, in degrees.
        /// </summary>
        private float MeasureHeight(out float tilt, out string source)
        {
            source = "";
            tilt = float.NaN;
            if (cameraManager == null) return float.NaN;

            Transform cam = cameraManager.transform;
            tilt = Vector3.Angle(cam.forward, Vector3.down);
            if (raycastManager == null) return float.NaN;

            var centre = new Vector2(Screen.width * 0.5f, Screen.height * 0.5f);
            (TrackableType type, string name)[] tries =
            {
                (TrackableType.PlaneWithinPolygon, "plane"),
                (TrackableType.PlaneWithinInfinity, "plane, extended"),
                (TrackableType.FeaturePoint, "points"),
            };

            foreach ((TrackableType type, string label) in tries)
            {
                if (!raycastManager.Raycast(centre, Hits, type)) continue;
                foreach (ARRaycastHit hit in Hits)  // nearest first
                {
                    bool upward = type == TrackableType.FeaturePoint || Vector3.Dot(hit.pose.up, Vector3.up) > 0.9f;
                    float height = (cam.position.y - hit.pose.position.y) * 100f;
                    if (upward && height > 0f)
                    {
                        source = label;
                        return height;
                    }
                }
            }

            return float.NaN;
        }

        private void OnDestroy()
        {
            MqttClient old = _client;
            _client = null;
            if (old != null) Task.Run(() => Close(old));
        }

        /// <summary>Takes the photo and sends it. Can also be called from a UI Button's On Click.</summary>
        public void TakeAndSend()
        {
            if (!_busy) StartCoroutine(TakeAndSendRoutine());
        }

        private IEnumerator TakeAndSendRoutine()
        {
            _busy = true;

            // Take the photo first: the phone is in position now.
            LastHeightCm = MeasureHeight(out float tilt, out string source);
            Debug.Log($"PhotoSender: photo at height {LastHeightCm:0.0} cm ({source}), tilt {tilt:0.0}°");
            Texture2D photo = CapturePhoto();
            if (photo == null)
            {
                _status = "No camera image yet, try again";
                _busy = false;
                yield break;
            }

            byte[] jpg = photo.EncodeToJPG(jpegQuality);
            double ts = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;
            string json = JsonConvert.SerializeObject(new Dictionary<string, object>
            {
                { "photo", Convert.ToBase64String(jpg) },
                { "ref_cm", refCm },
                { "ts", ts },
            });

            _status = "Sending...";
            bool arrived = false;
            yield return PublishJson(PhotoTopic, json, ok => arrived = ok);

            if (!arrived)
            {
                Destroy(photo);
                _status = "Not sent, tap again";
                _busy = false;
                yield break;
            }

            Handheld.Vibrate();
            _status = "Sent";
            _busy = false;

            if (PhotoSent != null) PhotoSent(photo, ts);
            else Destroy(photo);
        }

        /// <summary>
        /// Flow step 8 ("Check size"): takes a photo of a candidate stone and sends it as
        /// MESSAGES.md message 5, for the zone of the layer photo <paramref name="layerTs"/>.
        /// <paramref name="tapInPhoto"/> turns the photo's size (width, height) into the point the
        /// person tapped on the stone, in that photo's pixels (top-left origin, y down), sent as
        /// <c>tap</c>; null = no tap. <paramref name="captured"/> gets the photo's ts, size and tap
        /// before it is sent (so the caller can wait for the fit from then on);
        /// <paramref name="done"/> gets whether it arrived. No vibration here: in the flow it
        /// only means success, so it comes with a stone that fits.
        /// </summary>
        public IEnumerator SendCandidate(double layerTs, Func<int, int, Vector2?> tapInPhoto,
                                         Action<double, Vector2Int, Vector2?> captured, Action<bool> done)
        {
            return SendStonePhoto(CandidateTopic, layerTs, tapInPhoto, captured, done);
        }

        /// <summary>
        /// After placing: takes a photo of the wall and sends it as MESSAGES.md message 7, for the
        /// zone of the layer photo <paramref name="layerTs"/>; the same arguments as
        /// <see cref="SendCandidate"/> (<c>tap</c> = where the person tapped the new stone).
        /// </summary>
        public IEnumerator SendPlaced(double layerTs, Func<int, int, Vector2?> tapInPhoto,
                                      Action<double, Vector2Int, Vector2?> captured, Action<bool> done)
        {
            return SendStonePhoto(PlacedTopic, layerTs, tapInPhoto, captured, done);
        }

        private IEnumerator SendStonePhoto(string topic, double layerTs, Func<int, int, Vector2?> tapInPhoto,
                                           Action<double, Vector2Int, Vector2?> captured, Action<bool> done)
        {
            Texture2D photo = CapturePhoto();
            if (photo == null)
            {
                done(false);
                yield break;
            }

            var size = new Vector2Int(photo.width, photo.height);
            Vector2? tap = tapInPhoto?.Invoke(size.x, size.y);
            byte[] jpg = photo.EncodeToJPG(jpegQuality);
            Destroy(photo);
            double ts = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;
            var fields = new Dictionary<string, object>
            {
                { "photo", Convert.ToBase64String(jpg) },
                { "layer_ts", layerTs },
                { "ts", ts },
            };
            if (tap.HasValue)
            {
                fields["tap"] = new[] { Math.Round(tap.Value.x, 1), Math.Round(tap.Value.y, 1) };
            }

            captured(ts, size, tap);
            bool arrived = false;
            yield return PublishJson(topic, JsonConvert.SerializeObject(fields), ok => arrived = ok);
            done(arrived);
        }

        /// <summary>
        /// Publishes plain JSON with QoS 1 and waits for the broker's receipt (PUBACK).
        /// <paramref name="done"/> gets true only if the receipt came within <see cref="ackTimeout"/>.
        /// </summary>
        public IEnumerator PublishJson(string topic, string json, Action<bool> done)
        {
            yield return EnsureConnected();
            if (_client == null)
            {
                done(false);
                yield break;
            }

            ushort id;
            try
            {
                id = _client.Publish(topic, Encoding.UTF8.GetBytes(json), MqttMsgBase.QOS_LEVEL_AT_LEAST_ONCE, false);
            }
            catch (Exception e)
            {
                Debug.LogWarning($"PhotoSender: publish to {topic} failed: {e.Message}");
                _stale = true;
                done(false);
                yield break;
            }

            float giveUpAt = Time.realtimeSinceStartup + ackTimeout;
            while (Time.realtimeSinceStartup < giveUpAt)
            {
                bool acked;
                lock (_acked) acked = _acked.Remove(id);
                if (acked)
                {
                    done(true);
                    yield break;
                }
                yield return null;
            }

            Debug.LogWarning($"PhotoSender: no receipt from the broker for {topic}");
            _stale = true;  // so the next try starts with a fresh connection
            done(false);
        }

        /// <summary>Makes sure there is a live connection; opens a new one if not.</summary>
        private IEnumerator EnsureConnected()
        {
            while (_connecting) yield return null;
            if (_client != null && _client.IsConnected && !_stale) yield break;

            _connecting = true;
            MqttClient old = _client;
            _client = null;
            _stale = false;
            lock (_acked) _acked.Clear();

            // Connecting blocks, so it runs off the main thread.
            Task<MqttClient> task = Task.Run(() => Open(old));
            float giveUpAt = Time.realtimeSinceStartup + ConnectTimeout;
            while (!task.IsCompleted && Time.realtimeSinceStartup < giveUpAt) yield return null;

            if (task.Status == TaskStatus.RanToCompletion)
            {
                _client = task.Result;
                Debug.Log($"PhotoSender: connected to {brokerAddress}, listening on {OutlinesTopic}, {ZoneTopic}, {FitTopic}, {PlacementTopic}");
            }
            else
            {
                string why = task.IsFaulted ? task.Exception.GetBaseException().Message : "timeout";
                Debug.LogWarning($"PhotoSender: no connection to {brokerAddress} ({why})");
                // If it still connects later, close it again.
                task.ContinueWith(t => { if (t.Status == TaskStatus.RanToCompletion) Close(t.Result); });
            }

            _connecting = false;
        }

        // MQTT thread from here to OnMessage: no Unity calls.
        private MqttClient Open(MqttClient old)
        {
            if (old != null) Close(old);

            var client = new MqttClient(brokerAddress, brokerPort, false, null, null, MqttSslProtocols.None);
            client.MqttMsgPublished += OnPublished;
            client.MqttMsgPublishReceived += OnMessage;
            byte result = client.Connect(Guid.NewGuid().ToString(), null, null, true, KeepAliveSeconds);
            if (result != MqttMsgConnack.CONN_ACCEPTED) throw new Exception($"broker refused (code {result})");
            byte qos1 = MqttMsgBase.QOS_LEVEL_AT_LEAST_ONCE;
            client.Subscribe(new[] { OutlinesTopic, ZoneTopic, FitTopic, PlacementTopic }, new[] { qos1, qos1, qos1, qos1 });
            return client;
        }

        private void Close(MqttClient client)
        {
            client.MqttMsgPublished -= OnPublished;
            client.MqttMsgPublishReceived -= OnMessage;
            try
            {
                if (client.IsConnected) client.Disconnect();
            }
            catch (Exception)
            {
                // a dead connection may not close cleanly; it is dropped either way
            }
        }

        private void OnPublished(object sender, MqttMsgPublishedEventArgs e)
        {
            if (e.IsPublished) lock (_acked) _acked.Add(e.MessageId);
        }

        private void OnMessage(object sender, MqttMsgPublishEventArgs e)
        {
            if (e.Topic == OutlinesTopic || e.Topic == ZoneTopic || e.Topic == FitTopic || e.Topic == PlacementTopic)
            {
                _incoming.Enqueue((e.Topic, Encoding.UTF8.GetString(e.Message)));
            }
        }

        /// <summary>The latest camera image (camera feed only, no UI), scaled down.</summary>
        private Texture2D CapturePhoto()
        {
            if (cameraManager == null || !cameraManager.TryAcquireLatestCpuImage(out XRCpuImage image))
            {
                return null;
            }

            using (image)
            {
                float scale = Mathf.Min(1f, (float)maxLongSide / Mathf.Max(image.width, image.height));
                var size = new Vector2Int(Mathf.RoundToInt(image.width * scale), Mathf.RoundToInt(image.height * scale));

                var conversion = new XRCpuImage.ConversionParams
                {
                    inputRect = new RectInt(0, 0, image.width, image.height),
                    outputDimensions = size,
                    outputFormat = TextureFormat.RGBA32,
                    // The camera image starts at the top row, a texture at the bottom one.
                    transformation = XRCpuImage.Transformation.MirrorY,
                };

                var texture = new Texture2D(size.x, size.y, TextureFormat.RGBA32, false);
                image.Convert(conversion, texture.GetRawTextureData<byte>());
                texture.Apply();
                return texture;
            }
        }

        // ARCore often gives a 640x480 camera image by default. Once the camera runs, ask for the
        // largest one up to 1920 px, so there is enough for a 1280 px photo.
        private void OnFirstFrame(ARCameraFrameEventArgs _)
        {
            _configChosen = true;
            cameraManager.frameReceived -= OnFirstFrame;

            try
            {
                using NativeArray<XRCameraConfiguration> configs = cameraManager.GetConfigurations(Allocator.Temp);
                XRCameraConfiguration? best = null;
                foreach (XRCameraConfiguration config in configs)
                {
                    Vector2Int r = config.resolution;
                    if (Mathf.Max(r.x, r.y) > 1920) continue;
                    if (best == null || r.x * r.y > best.Value.resolution.x * best.Value.resolution.y) best = config;
                }

                if (best != null && best != cameraManager.currentConfiguration)
                {
                    cameraManager.currentConfiguration = best;
                    Debug.Log($"PhotoSender: camera image set to {best.Value.resolution}");
                }
            }
            catch (Exception e)
            {
                // Not every device lets the resolution be chosen; the default image still works.
                Debug.LogWarning($"PhotoSender: kept the default camera image size ({e.Message})");
            }
        }

        private void OnGUI()
        {
            if (!showButton) return;

            // Look: AlpineUI.cs. Status and height on small pills above one blue pill button.
            float h = AlpineUI.ButtonHeight;
            float w = Screen.width * 0.78f;
            var buttonRect = new Rect((Screen.width - w) / 2f, Screen.height * 0.72f, w, h);
            float chipH = h * 0.6f, gap = h * 0.2f;
            var labelRect = new Rect(Screen.width * 0.05f, buttonRect.y - gap - chipH, Screen.width * 0.9f, chipH);

            // A long line wraps and its pill grows upwards: the height pill goes above
            // wherever the status pill ended up.
            Rect status = AlpineUI.Chip(labelRect, _status);
            float heightBottom = status.height > 0 ? status.y - gap * 0.6f : labelRect.yMax;
            AlpineUI.Chip(new Rect(labelRect.x, heightBottom - chipH, labelRect.width, chipH), _heightText);
            if (AlpineUI.Button(buttonRect, _busy ? "Sending…" : "Tap when in position", true, !_busy))
            {
                TakeAndSend();
            }
        }
    }
}
