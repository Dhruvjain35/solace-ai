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

**peak.webp** — `photo-1757332224684-44aec99ee4bf`. A peak above cloud at first
light. It IS the home page's manifesto section rather than a picture inside it:
full bleed, masked so it dissolves across the left half, with the copy on the
clean dark ground it leaves behind. Two earlier attempts put a framed image on
the left with copy beside it, and a framed rectangle inside a section always
reads as an illustration of the text.

**dawn.webp** — `photo-1557316655-8715fdecd2d1`. Still water and mountains at
first light. Carries the close on /clinicians, masked at both ends so it
emerges out of that page's gradient rather than starting at an edge. The only
landscape on the site and the only one it gets.

## Encoding

Both are pulled at 3840px and served at 3200px, q88.

An earlier pass encoded to a PSNR target and landed at q58 / 24KB. That is the
right answer for a 400px figure inside a card and the wrong one for a plate
stretched across a whole section — the target was met and the result was
visibly soft, because the metric was measuring the wrong thing. Full-bleed
backgrounds get resolution and quality, not a threshold.
