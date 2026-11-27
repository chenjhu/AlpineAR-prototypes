# Slides: how the stone detection works (steps 2-6)

Image for all steps: `it07d_real_fixed_steps.jpg` (the successful real photo,
panel by panel). Final result: `it07e_real_fixed_ar.jpg`.

## A. Flowchart keywords

One box per step: **action → result**.

```
 1 PHOTO        2 EDGES            3 COMPARE           4 CUT OUT          5 SEPARATE           6 MEASURE
 top view   →   trace outlines  →  compare to table →  auto threshold  →  flood from centres → outline + measure
                ↓                  ↓                   ↓                  ↓                    ↓
                line drawing       difference map      stone silhouette   one colour / stone   coordinates
```

Short labels, if the boxes are tiny:

| step | action | result |
|---|---|---|
| 2 Edges | trace brightness jumps | line drawing |
| 3 Compare | each pixel vs. table colour | difference map |
| 4 Cut out | automatic threshold | silhouette |
| 5 Separate | flood + check the joint | one colour per stone |
| 6 Measure | outline, centre, box | coordinates |

## B. Script

Plain English, about 20 seconds per step.

**Intro.** "The phone takes one photo from above. The program then works
through five steps. Each step turns the picture into something a bit more
useful, until the stones are no longer pixels but geometry."

**2 · Edges.** "First, it traces every place where the brightness jumps,
like drawing the outlines with a pencil. We mainly need these lines to find
where two stones touch."

**3 · Compare to the table.** "Then it learns what the table looks like
from the border of the photo, and asks every pixel: how different are you
from the table? The brighter it is here, the less it looks like table."

**4 · Cut out.** "Now it draws a line: different enough means stone, white;
otherwise table, black. The program picks this line by itself for each
photo. We get the silhouette of the stones, but the two stones are still one
shape."

**5 · Separate.** "To split them, imagine dropping coloured water in the
middle of each stone and letting it spread. Where two colours meet is the
border between the stones. We only accept that border if it is a sharp,
dark line, because a real joint has a shadow in it. A crack inside one
stone does not pass this test."

**6 · Measure.** "Finally, each coloured region is traced as an outline and
measured: its centre, its size, its box. From here on the stones are
geometry, a list of points and numbers. This is the same kind of data
Grasshopper or an AR app works with, so the rule of thirds is just
arithmetic on these numbers, and the result is four corner points any app
can draw."

## C. One line of code or formula per step

These are the actual lines in `stone_detect.py`, shortened. Put them in
small monospace text under each image.

| step | code / formula | in words |
|---|---|---|
| 2 Edges | `cv2.Canny(gray, 0.67·m, 1.33·m)` | m = median brightness of the photo, so it adapts to the light |
| 3 Compare | `d = √((0.5·ΔL)² + Δa² + Δb²)` | colour distance to the table; brightness counts half, so shadows matter less |
| 4 Cut out | `cv2.threshold(d, 0, 255, THRESH_OTSU)` | Otsu's method picks the cut that best splits the pixels into two groups |
| 5 Separate | `seeds = distance_to_edge > 0.5·max` → `cv2.watershed(photo, seeds)` | seeds in the thickest part of each stone, then flood |
| 5 Joint test | **`joint = sharpness × (1 + darkness / 20)`** | our own rule, tuned on the real photo; keep the split only if it scores ≥ 6 |
| 6 Measure | `cv2.findContours(region)` → `centre = (M₁₀/M₀₀, M₀₁/M₀₀)` | outline, then centre from the region's moments |
| 7 Rule of thirds | `must = [L₁ − w_L/3, R₀ + w_R/3]`<br>`allowed = [L₀ + w_L/3, R₁ − w_R/3]` | the zone for the next stone, from the two stones' ends |

**If you show only two:**
1. **The joint test** (step 5). It is the one rule we designed ourselves,
   and it has a story: the first version failed on the real photo, and this
   is what fixed it.
2. **The rule of thirds** (step 7). It turns the book's rule (p.22) into a
   formula, which shows that the craft rule became computable.

Everything else is standard OpenCV. That is worth saying too: we combined
well-known building blocks; we did not invent new algorithms.

## D. Closing line + output

Under the AR overlay (`it07e`), a short excerpt of what the program
actually outputs (`output/stone1.json`):

```json
{
  "stone_length_min": 641.7,
  "stone_length_max": 1262.8,
  "must_zone":    [660.1, 1301.8],
  "allowed_zone": [330.1, 1592.9]
}
```

> "From pixels to geometry: the output is a handful of numbers that any
> software can draw."
