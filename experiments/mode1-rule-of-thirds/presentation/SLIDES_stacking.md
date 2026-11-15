# Slides: stacking, layer by layer (iterations 8 and 9)

Follows the "stones on the ground" slide. Same structure: images on top,
flow boxes below (step → action → result), code for two steps.
The camera is fixed above the wall (rig), so photo alignment is not shown.

## Images

| use | file |
|---|---|
| the bottleneck | `it08c_real_after_segmentation_merges.jpg` |
| the whole build | `it09a_layer_session_steps.jpg` (5 steps + overview) |

Layout: `it08c` as a strip on top, labelled as the problem; `it09a` below
as the solution; flow boxes at the bottom.

Caption for `it08c`: *Automatic detection: the new stone (middle) merges
with the stone below into one region.* Mark it red / "problem".

## Flow boxes (step → action → result)

| step | action | result |
|---|---|---|
| 1 Lock | stones below are saved | known outlines + layer |
| 2 Mark | tap around the new stone | its outline |
| 3 Assign | nearest open joint | which two stones it bridges |
| 4 Check | covers 1/3 - 2/3 of each | green / red |
| → next layer | compare only with the layer below | |

Mark step 2 visually as the human step (another outline style or a hand
icon) with a small label: *Wizard of Oz: a person marks it for now*.
Draw an arrow from `it08c` to this box: the problem is why this step exists.

## Code (two boxes, same style as the previous slide)

**4 Check**
```python
cover_left  = (L_end - new_start) / L_width
cover_right = (new_end - R_start) / R_width
ok = 1/3 <= cover_left <= 2/3  and  1/3 <= cover_right <= 2/3
```
(The code allows 3% tolerance on both limits.)

**1 Lock** (what the app stores, from `output/session/session.json`)
```json
{"name": "F", "layer": 2, "on": ["E", "D"],
 "check": {"ok": true, "cover_left": 0.348, "cover_right": 0.359}}
```

## Result table (if there is room)

| stone | layer | bridges | covers | result |
|---|---|---|---|---|
| D | 1 | A \| B | 52% / 31% | OK |
| E | 1 | C \| A | 52% / 38% | OK |
| F | 2 | E \| D | 35% / 36% | OK, borderline |

Outlines of D, E, F were marked by hand from the photos.

## Script

Simple and natural, about 1.5 minutes.

**Intro.** "So far the stones lay on the table. Now we stack, and here we
hit a wall, literally. The new stone lies on stones of the same rock and
the same colour."

**The problem (it08c).** "This is what happens if we let the program find
the new stone by itself. The stone in the middle is the new one, but the
program merges it with the stone underneath into one region. From above, a
photo alone cannot tell them apart."

**The idea.** "So instead of seeing better, we let the app remember better.
It follows the order of building."

**1 · Lock.** "Every time a step is confirmed, the app saves the stones it
knows: their outlines and their layer. They become background. The app never
has to find them again."

**2 · Mark.** "For the new stone, a person marks its outline, Wizard of Oz
style. In the real app this would be one tap on the stone."

**3 · Assign.** "The app looks for the joint closest to the new stone, so it
knows which two stones the new one is bridging."

**4 · Check.** "Then the rule of thirds: the new stone must cover between one
third and two thirds of each stone below. Green if it does, red if not."

**Next layer (it09a).** "Once a layer is done, the next one only looks at
the layer directly below it. We tested this with five photos, six stones
and three layers. D and E pass clearly. F, a small stone, only just reaches
one third on each side, so it passes at the limit."

**Closing.** "So without a depth sensor, just by remembering the order of
building, the app can follow a wall as it grows."
