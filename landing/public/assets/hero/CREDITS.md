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
