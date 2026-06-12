// One-shot asset prep: knock the phone's screen out of hand-phone.png so the
// intake video can sit UNDER the photo and be masked by the real bezel + hand.
// The cut starts below the photographed iOS status bar (9:41 stays visible,
// like the forhims reference). Measured against the 984×671 source:
//   screen quad ≈ x 258→832, tilted ~3.2° CCW, status bar bottom ≈ y 92.
import sharp from 'sharp';

const SRC = 'public/assets/hand-phone.png';
const OUT = 'public/assets/hand-phone-cut.png';

// Rect overshoots the bezel by a few px on the sides (the video underneath
// paints there, reading as a hair-thinner bezel) and runs off the bottom of
// the frame (the phone is cropped at the image edge anyway).
const svg = `<svg width="984" height="671" xmlns="http://www.w3.org/2000/svg">
  <rect x="242" y="88" width="606" height="604" rx="14"
        transform="rotate(-3.2 545 390)" fill="#000"/>
</svg>`;

await sharp(SRC)
  .composite([{ input: Buffer.from(svg), blend: 'dest-out' }])
  .png()
  .toFile(OUT);

console.log('wrote', OUT);
