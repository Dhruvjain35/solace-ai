# Parked pages

These are the marketing pages, intact and unedited. They are here rather than in
`src/pages/` because Astro builds whatever it finds in `src/pages/`, and there is
no supported way to tell it to skip a file. Moving the directory is therefore the
whole mechanism: nothing in here is emitted, so every one of these URLs returns a
404 in production.

Live right now: `/`, `/waitlist`, `/privacy`, `/terms`.

To bring one back, move the file into `src/pages/` and restore its links in
`src/components/Header.astro` and `src/components/Footer.astro`. Both of those
were cut down to match this list, so a page moved back with no nav entry will
build and be unreachable.

Nothing in here is stale. They were current as of the launch cut, and the
components they import are still in `src/components/` and still maintained by the
landing page, so they will build the moment they are moved back.

Note: `demo.astro` in here is the FULL-SITE demo page. The live one at
`src/pages/demo.astro` is the launch-mode version — same form, copy written
for a site with nothing else on it. Do not restore this one over that one
without merging the two.
