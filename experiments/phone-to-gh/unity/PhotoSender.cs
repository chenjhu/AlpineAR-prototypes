using System;
using System.Collections;
using System.Collections.Generic;
using Compas.Unity.Core.Mqtt;
using Unity.Collections;
using UnityEngine;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.ARSubsystems;

namespace Compas.GeoViewerXR
{
    /// <summary>
    /// AlpineAR flow steps 1-2: a "Tap when in position" button takes a photo from the AR
    /// camera feed (no UI drawn on it), sends it to Grasshopper as MESSAGES.md message 1 over
    /// the scene's existing MqttManager connection, and vibrates once it is sent.
    /// Add it to any object in the GeoViewer scene; it finds the camera and MQTT by itself.
    /// </summary>
    public class PhotoSender : MonoBehaviour
    {
        // MESSAGES.md, message 1. Do not change here without changing MESSAGES.md first.
        private const string Topic = "alpinear/proto1/photo";

        [Tooltip("Real long side of the biggest stone in the photo, in cm. Placeholder for the scale.")]
        public float refCm = 45f;

        [Tooltip("Long side of the sent photo, in pixels.")]
        public int maxLongSide = 1280;

        [Range(1, 100)]
        public int jpegQuality = 85;

        [Tooltip("Draw the button on screen. Turn off if a UI Button calls TakeAndSend instead.")]
        public bool showButton = true;

        [SerializeField] private ARCameraManager cameraManager;
        [SerializeField] private MqttManager mqtt;

        private bool _busy;
        private bool _configChosen;
        private string _status = "";
        private GUIStyle _buttonStyle;
        private GUIStyle _labelStyle;

        private void Awake()
        {
            if (cameraManager == null) cameraManager = FindAnyObjectByType<ARCameraManager>();
            if (mqtt == null) mqtt = FindAnyObjectByType<MqttManager>();
            if (cameraManager == null) Debug.LogError("PhotoSender: no ARCameraManager in the scene.", this);
            if (mqtt == null) Debug.LogError("PhotoSender: no MqttManager in the scene.", this);
        }

        private void OnEnable()
        {
            if (cameraManager != null && !_configChosen) cameraManager.frameReceived += OnFirstFrame;
        }

        private void OnDisable()
        {
            if (cameraManager != null) cameraManager.frameReceived -= OnFirstFrame;
        }

        /// <summary>Takes the photo and sends it. Can also be called from a UI Button's On Click.</summary>
        public void TakeAndSend()
        {
            if (!_busy) StartCoroutine(TakeAndSendRoutine());
        }

        private IEnumerator TakeAndSendRoutine()
        {
            _busy = true;

            // The course scene does not connect by itself (autoConnect is off).
            if (!mqtt.IsConnected)
            {
                _status = "Connecting...";
                if (GeoViewerHub.Instance != null) GeoViewerHub.Instance.Connect();
                else mqtt.Connect();

                float giveUpAt = Time.time + 10f;
                while (!mqtt.IsConnected && Time.time < giveUpAt) yield return null;

                if (!mqtt.IsConnected)
                {
                    _status = "No MQTT connection, try again";
                    _busy = false;
                    yield break;
                }
            }

            byte[] jpg = CaptureJpg();
            if (jpg == null)
            {
                _status = "No camera image yet, try again";
                _busy = false;
                yield break;
            }

            var message = new Dictionary<string, object>
            {
                { "photo", Convert.ToBase64String(jpg) },
                { "ref_cm", refCm },
                { "ts", DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0 },
            };

            // The scene's MqttManager is set to ProtoBuf for the geometry coming from Grasshopper,
            // but MESSAGES.md wants plain JSON. Switch for this one message and back. Safe: the
            // message is encoded right here, and incoming messages are decoded in MqttManager's
            // Update, on this same main thread, so nothing is decoded in between.
            SerializationProtocol before = mqtt.Protocol;
            mqtt.Protocol = SerializationProtocol.Json;
            try
            {
                mqtt.PublishToTopic(Topic, message);
            }
            finally
            {
                mqtt.Protocol = before;
            }

            Handheld.Vibrate();
            _status = $"Sent ({jpg.Length / 1024} kB)";
            _busy = false;
        }

        /// <summary>The latest camera image (camera feed only, no UI), scaled down, as JPEG.</summary>
        private byte[] CaptureJpg()
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
                byte[] jpg = texture.EncodeToJPG(jpegQuality);
                Destroy(texture);
                return jpg;
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

            float w = Screen.width * 0.7f;
            float h = Screen.height * 0.08f;
            var buttonRect = new Rect((Screen.width - w) / 2f, Screen.height * 0.72f, w, h);
            var labelRect = new Rect(buttonRect.x, buttonRect.y - h * 0.6f, w, h * 0.6f);

            if (_buttonStyle == null)
            {
                _buttonStyle = new GUIStyle(GUI.skin.button) { fontSize = Mathf.RoundToInt(h * 0.3f) };
                _labelStyle = new GUIStyle(GUI.skin.label)
                {
                    fontSize = Mathf.RoundToInt(h * 0.25f),
                    alignment = TextAnchor.MiddleCenter,
                };
            }

            GUI.Label(labelRect, _status, _labelStyle);

            GUI.enabled = !_busy;
            if (GUI.Button(buttonRect, _busy ? "Sending..." : "Tap when in position", _buttonStyle))
            {
                TakeAndSend();
            }
            GUI.enabled = true;
        }
    }
}
