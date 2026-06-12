import { useEffect, useRef, useState } from 'react';
import * as MP4Box from 'mp4box';
import {
  INTAKE_ANIM_SRC,
  INTAKE_POSTER_SRC,
  INTAKE_VIDEO_SRC,
} from '../../lib/hims';

/*
 * CanvasIntake — the blocked-autoplay player. Safari configs like Low Power
 * Mode refuse to start a <video> without a gesture, and the animated-image
 * fallback decodes in SOFTWARE, which stutters on exactly those throttled
 * machines. This player instead demuxes the same mp4 (mp4box) and decodes
 * it with WebCodecs — the same HARDWARE decoder <video> uses — painting
 * frames onto a <canvas>. A canvas is not a media element, so no autoplay
 * policy applies: full video quality, hardware-smooth, zero gestures, and
 * no system play button can ever appear.
 *
 * Playback runs at 2x (RATE) like the <video> path. If WebCodecs is
 * missing or anything throws, it falls back to the animated WebP.
 */

const RATE = 2;
const W = 786;
const H = 1704;
// Keep the decoder a few frames ahead without hoarding VideoFrames (they
// pin GPU surfaces); ~12 in flight is plenty for 30fps content at 2x.
const QUEUE_AHEAD = 12;

type Stamped = { frame: VideoFrame; ts: number };

function extractDescription(file: any, trackId: number): Uint8Array {
  const trak = file.getTrackById(trackId);
  for (const entry of trak.mdia.minf.stbl.stsd.entries) {
    const box = entry.avcC ?? entry.hvcC ?? entry.vpcC ?? entry.av1C;
    if (box) {
      const stream = new (MP4Box as any).DataStream(
        undefined,
        0,
        (MP4Box as any).DataStream.BIG_ENDIAN,
      );
      box.write(stream);
      return new Uint8Array(stream.buffer as ArrayBuffer, 8); // strip box header
    }
  }
  throw new Error('no decoder description in mp4');
}

export default function CanvasIntake() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [failed, setFailed] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (failed) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    if (typeof VideoDecoder === 'undefined') {
      setFailed(true);
      return;
    }
    const ctx = canvas.getContext('2d');
    if (!ctx) {
      setFailed(true);
      return;
    }

    let dead = false;
    let raf = 0;
    let decoder: VideoDecoder | null = null;
    const chunks: EncodedVideoChunk[] = []; // whole encoded stream (~3 MB)
    const frames: Stamped[] = [];
    let feedIndex = 0;
    let loopOffset = 0; // µs added to output timestamps per completed loop
    let durationUs = 0;
    let flushing = false;
    let epoch = -1; // wall-clock start of playback (ms)
    let revealed = false;

    const fail = () => {
      if (!dead) setFailed(true);
    };

    const pump = () => {
      if (!decoder || dead || flushing) return;
      while (
        feedIndex < chunks.length &&
        decoder.decodeQueueSize + frames.length < QUEUE_AHEAD
      ) {
        decoder.decode(chunks[feedIndex++]);
      }
      // End of stream: drain the tail, then restart from the keyframe at 0.
      if (feedIndex >= chunks.length && chunks.length > 0) {
        flushing = true;
        decoder
          .flush()
          .then(() => {
            if (dead) return;
            loopOffset += durationUs;
            feedIndex = 0;
            flushing = false;
          })
          .catch(() => {
            // flush rejects if the decoder was closed mid-flight — fatal
            // only if we're still alive.
            fail();
          });
      }
    };

    const tick = (now: number) => {
      if (dead) return;
      if (epoch < 0 && frames.length >= 4) {
        epoch = now;
        if (!revealed) {
          revealed = true;
          setReady(true);
        }
      }
      if (epoch >= 0) {
        const media = (now - epoch) * 1000 * RATE; // µs on the 2x clock
        let due: Stamped | null = null;
        while (frames.length > 0 && frames[0].ts <= media) {
          if (due) due.frame.close();
          due = frames.shift()!;
        }
        if (due) {
          ctx.drawImage(due.frame, 0, 0, W, H);
          due.frame.close();
        }
      }
      pump();
      raf = requestAnimationFrame(tick);
    };

    (async () => {
      const buf = await (await fetch(INTAKE_VIDEO_SRC)).arrayBuffer();
      const file = (MP4Box as any).createFile();
      // mp4box only emits samples for data appended AFTER extraction is
      // configured, and configuration needs the moov atom — so the asset
      // is remuxed with +faststart (moov first) and streamed in chunks:
      // onReady fires on an early chunk, extraction starts, and the rest
      // of the stream delivers the samples.
      let track: any;
      const samplesP = new Promise<any[]>((resolve, reject) => {
        const all: any[] = [];
        file.onError = reject;
        file.onReady = (info: any) => {
          track = info.videoTracks[0];
          file.onSamples = (_id: number, _user: unknown, batch: any[]) => {
            all.push(...batch);
            if (all.length >= track.nb_samples) resolve(all);
          };
          file.setExtractionOptions(track.id, null, { nbSamples: 200 });
          file.start();
        };
      });
      const CHUNK = 512 * 1024;
      for (let off = 0; off < buf.byteLength; off += CHUNK) {
        const piece: ArrayBuffer & { fileStart?: number } = buf.slice(
          off,
          Math.min(off + CHUNK, buf.byteLength),
        );
        piece.fileStart = off;
        file.appendBuffer(piece);
      }
      file.flush();
      const samples = await samplesP;
      const description = extractDescription(file, track.id);
      if (dead) return;

      for (const s of samples) {
        chunks.push(
          new EncodedVideoChunk({
            type: s.is_sync ? 'key' : 'delta',
            timestamp: (s.cts * 1e6) / s.timescale,
            duration: (s.duration * 1e6) / s.timescale,
            data: s.data,
          }),
        );
      }
      const last = samples[samples.length - 1];
      durationUs = ((last.cts + last.duration) * 1e6) / last.timescale;

      decoder = new VideoDecoder({
        output: (frame) => {
          if (dead) {
            frame.close();
            return;
          }
          frames.push({ frame, ts: frame.timestamp + loopOffset });
        },
        error: fail,
      });
      decoder.configure({ codec: track.codec, description });
      pump();
      raf = requestAnimationFrame(tick);
    })().catch(fail);

    return () => {
      dead = true;
      cancelAnimationFrame(raf);
      frames.forEach((s) => s.frame.close());
      frames.length = 0;
      try {
        decoder?.close();
      } catch {
        /* already closed */
      }
    };
  }, [failed]);

  if (failed) {
    // Last resort: the animated-WebP twin (software decode, may drop
    // frames on throttled machines, but it always plays).
    return (
      <div
        aria-hidden="true"
        className="pointer-events-none relative mt-[13.5cqw] w-full"
      >
        <img
          src={INTAKE_POSTER_SRC}
          alt=""
          className="absolute inset-0 h-full w-full"
        />
        <img src={INTAKE_ANIM_SRC} alt="" className="relative block h-auto w-full" />
      </div>
    );
  }

  return (
    <div
      aria-hidden="true"
      className="pointer-events-none relative mt-[13.5cqw] w-full"
    >
      {/* poster keeps the screen filled until the first frames are decoded */}
      <img
        src={INTAKE_POSTER_SRC}
        alt=""
        className="absolute inset-0 h-full w-full"
      />
      <canvas
        ref={canvasRef}
        width={W}
        height={H}
        className="relative block h-auto w-full"
        style={{ opacity: ready ? 1 : 0, transition: 'opacity 0.25s' }}
      />
    </div>
  );
}
