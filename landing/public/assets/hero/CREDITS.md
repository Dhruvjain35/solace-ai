# Hero imagery

## Current — rebuilt 2026-07-27

**The hero background is not an image.** It is four coloured radial-gradient
lights drifting over a near-black base, each on its own element so the motion is
a GPU transform rather than a gradient repaint. See `src/components/Hero.astro`.

This is the fix for the pixelation the previous hero suffered from. That hero
painted a detailed 3400px cloud photograph, upscaled it past 1.2x by the drift
animation, and was compressed to **0.15 bits/pixel** to keep the page weight
down — roughly a tenth of what a photographic WebP needs. A gradient has no
detail to lose, so it is exactly sharp at every resolution and costs zero bytes.
A little SVG grain is layered over it because 8-bit gradients band across a
field this wide.

**subject.webp / subject@2x.webp** — derived from an Unsplash photograph
(`images.unsplash.com/photo-1532074205216-d0e1f4b87368`), 2400x3157 source.
Unsplash License: free for commercial use, no attribution required.

Chosen to match the reference composition: profile, head turned up and away,
soft directional key with dark falloff, shot on a plain backdrop. Graded warm
against a cool plate — that warm/cool separation is what stops the composite
reading as one flat hue, which is exactly what went wrong with the previous
emerald-on-emerald hero.

Composited with `mix-blend-mode: screen`, **not** a matte. The backdrop is true
black, and her black top measures the same values as the backdrop
(`0.05, 5.2, 7.3` vs `0.05, 4.8, 6.6`) — there is no torso recorded in the file
at all. Every attempt to extract a silhouette there produced ragged islands and
detached blobs, because it was carving a shape out of a region with no signal.
Screen takes black to transparent for free, cannot produce an edge artefact, and
lets the fine flyaway hair feather into the plate. There is deliberately **no
light wrap** anywhere: the wrap is what put the bright rim on the previous
hero's dark hair.

Encoded at q90/q92. The quality knee was measured on the face region — q86 gave
35.6 dB PSNR, q92 gave 36.8 dB, q96 only 37.4 dB for another 67KB.

### Open item for the site owner

The subject is an **identifiable person**, and the Unsplash License grants
commercial use but does **not** convey a model release. Using an identifiable
face on a healthcare marketing page can raise publicity-rights questions in a
way that a photograph of clouds does not. This is a business decision, not a
technical one — flagging it rather than deciding it. Commissioning a shot with a
release, or licensing from a library that includes one, removes the question.

**manifesto.webp / manifesto@2x.webp** — derived from an Unsplash photograph
(`images.unsplash.com/photo-1513002749550-c59d786b8e6c`), graded to the same
ramp. Unsplash License. No identifiable people.

Still a raster plate, so it has not had the gradient treatment the hero got. It
is the obvious next candidate.

## Superseded

- The original owner-supplied clinician file (520x610, licence provenance
  undocumented) — capped sharpness no matter how it was processed.
- `photo-1623854766464-c3645e6841d8`, a studio-lit clinician in scrubs smiling
  at camera. Front-lit and posed, dropped onto a moody dark cloudscape; the
  lighting could never match the plate, so she read as clip-art regardless of
  how clean the matte was. That is a wrong-photo problem, not a compositing one.
- `photo-1560837616-fee1f3d8753a` cloudscape and its three parallax cuts,
  replaced by the CSS gradient field.


## The scroll morph — replaced 2026-07-28

**nurse.webp / nurse@2x.webp** — a masked clinician in scrubs and a surgical
cap, supplied by the client (1024x1536 PNG, opaque, shot on a lit studio grey).
It replaces an earlier frame that was the same face as the hero subject. This
one is a different person, which the mask makes workable: with the nose and
mouth covered there is far less identity to cross-fade, and what carries the
morph is the head angle, the jaw line and the eye — all of which register.

Built by `scratchpad/nurse2/`, and the interesting part is the three attempts
that did not work, because each failed for a reason worth keeping.

1. **Cut against a fitted plate — failed.** A degree-3 polynomial through the
   corners is 50 to 90 levels too dark down her right side, because the key
   light throws a rim onto the backdrop that only exists next to her. Every
   pixel of that rim then reads as subject.
2. **Cut against a diffusion-inpainted plate — failed the same way.** Rebuilding
   the backdrop by diffusing known pixels into the subject's hole follows the
   clouds beautifully and still cannot invent a rim that is only ever underneath
   her.
3. **Recover true coverage rather than difference — closer, still wrong.** For a
   dark subject on a light plate, `a = (B - I) / (B - F_dark)` is a real estimate
   of coverage, and it fixed the hair. It could not fix the rim, because the rim
   is a plate error, not a matte error.

What shipped: **cut inside the fringe.** The silhouette is reliable; only its
last few pixels are not. Feathering INWARD discards every partially covered
pixel instead of guessing at it, so the matte reaches zero while it is still
over hair. Under `mix-blend-mode: screen` that matters more than the strands do
— a halo is the one artefact with nowhere to hide, and the frame this dissolves
with loses its own hair to black in exactly the same way.

Three further things the pipeline needed:

- **A scanline trim.** Walking in from the right of each row and dropping pixels
  while they are still plate-bright removes the rim; the first dark pixel is the
  real hair edge. Skipped above y=150, where the silhouette IS the bright cap.
- **A read shoulder line.** Below the hair the plate has fallen into its own
  vignette and the scrubs are navy, so the two meet in the same range and no
  threshold separates them. Twelve points read off a gridded crop, interpolated,
  pulled in 8px. The only hand-placed numbers here, and they are here because
  measurement beat inference.
- **A feather that varies with what it cuts.** 4px over the bright edges — jaw,
  cap, mask — and nearly 40 over the dark ones. A single narrow feather gave the
  hair a ruled edge, and smoothing that edge only made the slice look
  deliberate. Hair has to dissolve, not end.

**Registration** is two landmarks, not correlation: the pupil at (665,335) and
the ear canal at (445,445), against (485,340) and (255,460) in the frame it
dissolves with. Scale 1.0546, offset (-216,-13), ear landing within 4px. No
correlation would have found this — the new face is behind a mask and has
almost nothing to correlate against.

**The grade is selective.** Skin is warmed toward the subject it dissolves with
and nothing else is touched, weighted by how far red already leads blue. A flat
per-channel gain lands identically on the mask and the scrubs and turns both a
yellow-grey.

**Consent, unchanged and still unresolved.** This frame depicts an identifiable
person presented as a healthcare professional, and no model release accompanies
it. Flagged, not cleared.

---

## The previous morph frame — added 2026-07-27, replaced 2026-07-28

**nurse.webp / nurse@2x.webp** — the same subject in scrubs, supplied by the
client as a generated frame (1024x1536, with a usable alpha channel already in
the PNG). It is the same face and the same head angle, which is the only reason
a morph works at all: two different people revealed through a moving edge read
as a cut, not a change.

Built by `scratchpad/build3.mjs`, in this order and for these reasons:

1. **Denoise 0.6px at source resolution.** The frame carries heavy generation
   grain. Left in, it survives the 1.93x upscale and costs megabytes, because
   noise is incompressible. It also slightly feathers the alpha edge, which
   helps the hair sit into the plate the way the original's does.
2. **Register to the original.** Scale and offset came from a whole-frame
   normalised cross-correlation (`scratchpad/reg2.mjs`): width 1974, offset
   (-326, +19), NCC 0.697. Two earlier attempts failed and are worth recording:
   a skin-mask bounding box disagreed with itself (scale 2.50 by width, 1.56 by
   height) because the "warm skin" test also catches lit hair, and a template
   NCC that called sharp inside the offset loop would have run for hours.
3. **Composite over pure black, then grade.** Grading while still transparent
   multiplies un-premultiplied edge pixels and fringes the hair.
4. **Grade chromaticity, not exposure.** Matching the original's lit-region mean
   outright needs R x1.43 and clips every skin highlight. G x0.831 and B x0.549
   against R puts both frames on the same colour axis and leaves highlights
   alone. Measured lit means: original R228.8 G148.1 B75.2, nurse R160.2 G124.8
   B95.9.
5. **Smoothstep falloff on all four sides.** The source ends at
   85% of the canvas, so without a bottom fade the morph reveals a hard
   horizontal cut across her torso. The left fade matters more: registration
   puts the frame at x = -326, so the canvas cuts straight through her arm and
   leaves a hard vertical line running the full height of the figure. 300px is
   wide enough that the eye never finds an edge and narrow enough not to eat
   into the lit shoulder. The original needs neither, because its subject sits
   inside the frame with black either side. The leading fade is 520px, not the
   300px first used: at 300 the boundary was still findable if you looked for
   it. The trailing edge and the top get one too, so no straight boundary can
   exist anywhere in the frame regardless of how the figure is later scaled or
   positioned. Cheaper than proving there is not one.

One bug worth remembering: compositing an RGBA crop onto an RGB canvas promotes
the raw buffer to FOUR channels. The fade loop indexed in threes and scrambled
every pixel. It did not look obviously broken, but the WebP came out at 3MB
instead of 183KB, because scrambled pixels are noise. The file size is what
caught it.

Result: 87KB and 183KB, against 81KB and 310KB for the original pair.

**Likeness note.** This frame depicts the same identifiable person as
subject.webp, who has no model release. The generated uniform makes her appear
to be a healthcare professional. That is a client-supplied asset and a client
decision; it is recorded here because it is not obvious from the file.
