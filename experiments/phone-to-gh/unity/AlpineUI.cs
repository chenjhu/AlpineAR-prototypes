using System;
using System.Collections.Generic;
using UnityEngine;

namespace Compas.GeoViewerXR
{
    /// <summary>
    /// The look of the AlpineAR buttons and text (PhotoSender, OutlineReview): flat and rounded,
    /// like iOS. Pill-shaped buttons, blue for the main action and dark glass for the other one;
    /// messages on a dark rounded card. The rounded shapes are drawn in code, nothing to import.
    /// </summary>
    public static class AlpineUI
    {
        /// <summary>Height of a button in pixels (the rest of the layout follows from it).</summary>
        public static float ButtonHeight => Mathf.Round(Screen.height * 0.065f);

        private static readonly Color Blue = new Color32(10, 132, 255, 255);          // iOS system blue
        private static readonly Color BluePressed = new Color32(0, 96, 223, 255);
        private static readonly Color Glass = new Color(0.17f, 0.17f, 0.18f, 0.82f);  // dark, see-through
        private static readonly Color GlassPressed = new Color(0.32f, 0.32f, 0.34f, 0.90f);
        private static readonly Color CardColor = new Color(0.11f, 0.11f, 0.12f, 0.78f);

        private static GUIStyle _primary, _secondary, _primaryOff, _secondaryOff, _card, _chip;
        private static GUIStyle _textRegular, _textMedium;
        private static readonly Dictionary<(int, Color32), GUIStyle> Fills = new Dictionary<(int, Color32), GUIStyle>();
        private static int _builtFor;
        private static readonly List<Texture2D> Textures = new List<Texture2D>();
        private static Font _regular, _medium;
        private static bool _fontsLooked;
        private static int _buttonSize, _cardSize, _chipSize;

        // No text runs out of its shape: it first gets smaller, down to this share of its
        // size; if it still does not fit, it wraps onto more lines (and a card or chip grows
        // upwards, so it never covers the buttons below it).
        private const float Smallest = 0.7f;
        private static readonly Dictionary<string, int> FittedSize = new Dictionary<string, int>();

        /// <summary>A pill button. primary: blue (the main action), else dark glass.
        /// A disabled button is drawn faded and does not react.</summary>
        public static bool Button(Rect rect, string text, bool primary = true, bool enabled = true)
        {
            Build();
            GUIStyle s = enabled ? (primary ? _primary : _secondary) : (primary ? _primaryOff : _secondaryOff);
            var content = new GUIContent(text);
            FitOneLine("button", s, content, rect.width, _buttonSize);
            if (!enabled)
            {
                GUI.Label(rect, content, s);
                return false;
            }
            return GUI.Button(rect, content, s);
        }

        /// <summary>A message on a dark rounded card in the rect (wraps long text). Text that
        /// does not fit makes the card taller upwards; its bottom stays. Returns where it was drawn.</summary>
        public static Rect Card(Rect rect, string text)
        {
            if (string.IsNullOrEmpty(text)) return new Rect(rect.x, rect.yMax, rect.width, 0);
            Build();
            var content = new GUIContent(text);
            FitWrapped("card", _card, content, rect.width, rect.height, _cardSize);
            float need = _card.CalcHeight(content, rect.width);
            if (need > rect.height) rect.yMin = rect.yMax - need;
            GUI.Label(rect, content, _card);
            return rect;
        }

        /// <summary>A short line on a small dark pill, as wide as the text, centred in the rect
        /// and sitting on its bottom. Too long even when smaller: two lines, the pill grows
        /// upwards. Returns where it was drawn (zero height when there is no text).</summary>
        public static Rect Chip(Rect rect, string text)
        {
            if (string.IsNullOrEmpty(text)) return new Rect(rect.x, rect.yMax, rect.width, 0);
            Build();
            var content = new GUIContent(text);
            FitOneLine("chip", _chip, content, rect.width, _chipSize);
            float w = Mathf.Min(rect.width, _chip.CalcSize(content).x);
            float h = _chip.wordWrap ? Mathf.Max(rect.height, _chip.CalcHeight(content, w)) : rect.height;
            var drawn = new Rect(rect.center.x - w / 2f, rect.yMax - h, w, h);
            GUI.Label(drawn, content, _chip);
            return drawn;
        }

        /// <summary>The colour of the dark cards, for other panels in the same look.</summary>
        public static Color CardFill => CardColor;

        /// <summary>A rounded area in one colour (radius in pixels; a pill if it is half the height).</summary>
        public static void Fill(Rect rect, Color color, float radius)
        {
            if (Event.current.type != EventType.Repaint) return;
            Build();
            int r = Mathf.Max(2, Mathf.RoundToInt(Mathf.Min(radius, rect.height / 2f, rect.width / 2f)));
            var key = (r, (Color32)color);
            if (!Fills.TryGetValue(key, out GUIStyle s))
            {
                s = new GUIStyle { border = new RectOffset(r, r, r, r) };
                s.normal.background = Rounded(r, color);
                Fills[key] = s;
            }
            s.Draw(rect, false, false, false, false);
        }

        /// <summary>A plain rectangle in one colour, e.g. a thin line (a rect 2 pixels high).</summary>
        public static void Line(Rect rect, Color color)
        {
            if (Event.current.type != EventType.Repaint) return;
            Color before = GUI.color;
            GUI.color = color;
            GUI.DrawTexture(rect, Texture2D.whiteTexture);
            GUI.color = before;
        }

        /// <summary>Text in the phone's font at a given pixel size, on no background.
        /// medium: the medium weight (numbers, captions).</summary>
        public static void Text(Rect rect, string text, float size, Color color, TextAnchor anchor, bool medium = false)
        {
            if (string.IsNullOrEmpty(text)) return;
            Build();
            GUIStyle s = medium ? _textMedium : _textRegular;
            s.fontSize = Mathf.Max(8, Mathf.RoundToInt(size));
            s.normal.textColor = color;
            s.alignment = anchor;
            GUI.Label(rect, text, s);
        }

        /// <summary>How wide <see cref="Text"/> draws this text, in pixels.</summary>
        public static float TextWidth(string text, float size, bool medium = false)
        {
            Build();
            GUIStyle s = medium ? _textMedium : _textRegular;
            s.fontSize = Mathf.Max(8, Mathf.RoundToInt(size));
            return s.CalcSize(new GUIContent(text)).x;
        }

        /// <summary>Font size so the text fits on one line in this width; wraps if even the
        /// smallest size does not fit.</summary>
        private static void FitOneLine(string kind, GUIStyle s, GUIContent c, float width, int size)
        {
            s.wordWrap = false;
            s.fontSize = Fitted($"{kind}|{width:0}|{c.text}", size, () => s.CalcSize(c).x > width, s);
            s.wordWrap = s.CalcSize(c).x > width;
        }

        /// <summary>Font size so the wrapped text fits in this width and height.</summary>
        private static void FitWrapped(string kind, GUIStyle s, GUIContent c, float width, float height, int size)
        {
            s.fontSize = Fitted($"{kind}|{width:0}|{height:0}|{c.text}", size, () => s.CalcHeight(c, width) > height, s);
        }

        /// <summary>Largest size from `size` down to Smallest × size for which tooBig() is false
        /// (remembered per text, OnGUI runs several times a frame).</summary>
        private static int Fitted(string key, int size, Func<bool> tooBig, GUIStyle s)
        {
            if (FittedSize.TryGetValue(key, out int known)) return known;
            int min = Mathf.Max(8, Mathf.RoundToInt(size * Smallest));
            s.fontSize = size;
            while (s.fontSize > min && tooBig()) s.fontSize--;
            if (FittedSize.Count > 200) FittedSize.Clear();  // e.g. the height line changes all the time
            FittedSize[key] = s.fontSize;
            return s.fontSize;
        }

        private static void Build()
        {
            int h = Mathf.Max(8, (int)ButtonHeight);
            if (_primary != null && h == _builtFor) return;  // built again after a screen turn
            _builtFor = h;
            foreach (Texture2D t in Textures) UnityEngine.Object.Destroy(t);
            Textures.Clear();
            Fills.Clear();  // their textures were just destroyed
            FittedSize.Clear();
            LoadFonts();

            _textRegular = new GUIStyle { font = _regular, wordWrap = false, clipping = TextClipping.Overflow };
            _textMedium = new GUIStyle
            {
                font = _medium,
                wordWrap = false,
                clipping = TextClipping.Overflow,
                fontStyle = _medium != null && _medium != _regular ? FontStyle.Normal : FontStyle.Bold,
            };

            _buttonSize = Mathf.RoundToInt(h * 0.27f);  // "Photograph a stone" fits half the width
            _cardSize = Mathf.RoundToInt(h * 0.27f);
            _chipSize = Mathf.RoundToInt(h * 0.24f);
            int pill = h / 2;
            _primary = ButtonStyle(pill, Blue, BluePressed, Color.white, h);
            _secondary = ButtonStyle(pill, Glass, GlassPressed, Color.white, h);
            _primaryOff = ButtonStyle(pill, Faded(Blue, 0.35f), Faded(Blue, 0.35f), new Color(1, 1, 1, 0.6f), h);
            _secondaryOff = ButtonStyle(pill, Faded(Glass, 0.5f), Faded(Glass, 0.5f), new Color(1, 1, 1, 0.45f), h);

            int corner = Mathf.RoundToInt(h * 0.32f);
            _card = TextStyle(corner, Mathf.RoundToInt(h * 0.27f));
            _card.padding = new RectOffset(corner, corner, corner / 2, corner / 2);
            _card.wordWrap = true;

            int chipR = Mathf.RoundToInt(h * 0.3f);  // the chip is 0.6 button heights tall: a pill
            _chip = TextStyle(chipR, Mathf.RoundToInt(h * 0.24f));
            _chip.padding = new RectOffset(chipR + 4, chipR + 4, chipR / 3, chipR / 3);
        }

        private static GUIStyle ButtonStyle(int r, Color fill, Color pressed, Color text, int h)
        {
            var s = new GUIStyle
            {
                border = new RectOffset(r, r, r, r),
                padding = new RectOffset(r / 2, r / 2, 0, 0),
                alignment = TextAnchor.MiddleCenter,
                clipping = TextClipping.Clip,
                font = _medium,
                fontSize = Mathf.RoundToInt(h * 0.27f),
                // A real medium-weight font if the phone has one, else the bold of the regular one.
                fontStyle = _medium != null && _medium != _regular ? FontStyle.Normal : FontStyle.Bold,
            };
            s.normal.background = s.hover.background = s.focused.background = Rounded(r, fill);
            s.active.background = Rounded(r, pressed);
            s.normal.textColor = s.hover.textColor = s.focused.textColor = s.active.textColor = text;
            return s;
        }

        private static GUIStyle TextStyle(int r, int fontSize)
        {
            var s = new GUIStyle
            {
                border = new RectOffset(r, r, r, r),
                alignment = TextAnchor.MiddleCenter,
                font = _regular,
                fontSize = fontSize,
            };
            s.normal.background = Rounded(r, CardColor);
            s.normal.textColor = new Color(1, 1, 1, 0.95f);
            return s;
        }

        private static Color Faded(Color c, float alpha) => new Color(c.r, c.g, c.b, c.a * alpha);

        /// <summary>A (2r+2)-pixel square with corners of radius r and soft (anti-aliased) edges,
        /// to stretch with border r: any size of rounded rectangle, a pill when its height is 2r.</summary>
        private static Texture2D Rounded(int r, Color color)
        {
            r = Mathf.Max(r, 2);
            int size = 2 * r + 2;
            float half = size / 2f;
            var pixels = new Color[size * size];
            for (int y = 0; y < size; y++)
            for (int x = 0; x < size; x++)
            {
                // Distance from the pixel centre to the rounded rectangle's edge (negative inside).
                float qx = Mathf.Abs(x + 0.5f - half) - (half - r);
                float qy = Mathf.Abs(y + 0.5f - half) - (half - r);
                float outside = new Vector2(Mathf.Max(qx, 0), Mathf.Max(qy, 0)).magnitude
                                + Mathf.Min(Mathf.Max(qx, qy), 0) - r;
                Color c = color;
                c.a *= Mathf.Clamp01(0.5f - outside);
                pixels[y * size + x] = c;
            }
            var t = new Texture2D(size, size, TextureFormat.RGBA32, false)
            {
                wrapMode = TextureWrapMode.Clamp,
                filterMode = FilterMode.Bilinear,
                hideFlags = HideFlags.HideAndDontSave,
            };
            t.SetPixels(pixels);
            t.Apply();
            Textures.Add(t);
            return t;
        }

        /// <summary>The phone's own UI font (Google Sans / Roboto on a Pixel), else Unity's default.</summary>
        private static void LoadFonts()
        {
            if (_fontsLooked) return;
            _fontsLooked = true;
            string[] have;
            try { have = Font.GetOSInstalledFontNames(); }
            catch (Exception) { return; }

            _regular = Pick(have, "Google Sans", "GoogleSans-Regular", "Google Sans Text", "Roboto",
                "Roboto-Regular", "SF Pro Text", "Helvetica Neue", "Segoe UI");
            _medium = Pick(have, "Google Sans Medium", "GoogleSans-Medium", "Google Sans Text Medium",
                "Roboto Medium", "Roboto-Medium", "SF Pro Text Semibold", "Segoe UI Semibold") ?? _regular;
            Debug.Log($"AlpineUI: fonts {(_regular != null ? _regular.name : "Unity default")}" +
                      $" / {(_medium != null ? _medium.name : "Unity default")}");
        }

        private static Font Pick(string[] have, params string[] wanted)
        {
            foreach (string w in wanted)
            foreach (string h in have)
                if (string.Equals(h, w, StringComparison.OrdinalIgnoreCase))
                    return Font.CreateDynamicFontFromOSFont(h, 32);
            return null;
        }
    }
}
