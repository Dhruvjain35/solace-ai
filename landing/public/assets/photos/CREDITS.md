# Photography

Three photographs, one per page, none repeated anywhere on the site.

All three are from Unsplash under the Unsplash License: free for commercial
use, no attribution required. They are NOT arbitrary web images — a commercial
site cannot use search results it has no licence to, and Unsplash is the same
source the hero subject came from, so the licensing story stays consistent.

## The selection rule

None of them shows a clinician, a stethoscope, a scrub or a hospital.

A stock photograph of a doctor says nothing the copy does not already say, and
it is instantly recognisable as filler — the reader has seen the same shot on
every health site they have ever visited. These say calm, warmth and light,
which is what the product actually sells. The subject is the mood, not the
industry.

## The plates

**hands.webp** — `photo-1482164565953-04b62dcac1cd`. Two hands cupping warm
string lights on near-black. Runs on the home page's manifesto, replacing a
cloudscape: the section says calm should be standard care, and a sky says calm
without saying care. Composited with `mix-blend-mode: screen` and a radial
mask, the same treatment the hero subject gets, so the light appears to come
out of the section rather than out of a framed rectangle.

**aurora.webp** — `photo-1635776062360-af423602aff3`. Teal falling into
near-black. Carries the closing band on /product, which was three stops of
mint. Denoised 1.2px before encoding: it is heavily grained and would not
compress — 624KB at the quality knee, 86KB after. Nothing is lost, because the
section lays its own grain back over the top.

**dawn.webp** — `photo-1557316655-8715fdecd2d1`. Still water and mountains at
first light. Carries the close on /clinicians, masked at both ends so it
emerges out of that page's gradient rather than starting at an edge. The only
landscape on the site and the only one it gets.

## Encoding

Quality was found rather than guessed: step up until PSNR against the graded
master clears 40dB, which is where WebP loss starts to show on gradients.
hands and dawn cleared it at q58 (20KB and 24KB). aurora never cleared it at
any quality, which is what exposed the grain problem.
