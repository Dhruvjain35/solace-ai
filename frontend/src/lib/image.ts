/**
 * Normalize any image File to a JPEG the backend will accept.
 *
 * Why unconditional re-encode instead of "resize if oversized":
 * iPhones save HEIC by default, and a HEIC under 2MB would previously skip the
 * canvas path and hit the backend — whose magic-byte check rejects HEIC (active
 * CVE surface in libheif, intentionally excluded). Running every capture through
 * createImageBitmap + canvas.toBlob("image/jpeg") converts HEIC→JPEG in Safari
 * natively, strips EXIF, and guarantees the upload matches one of the accepted
 * magic signatures server-side.
 */
export async function resizeImageIfNeeded(
  file: File,
  opts: { maxDimension?: number; quality?: number } = {}
): Promise<File> {
  const maxDim = opts.maxDimension ?? 1600;
  const quality = opts.quality ?? 0.82;

  if (!file.type.startsWith("image/") && !/\.(heic|heif)$/i.test(file.name)) {
    return file;
  }

  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, maxDim / Math.max(bitmap.width, bitmap.height));
    const w = Math.round(bitmap.width * scale);
    const h = Math.round(bitmap.height * scale);

    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) return file;
    ctx.drawImage(bitmap, 0, 0, w, h);

    const blob: Blob | null = await new Promise((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", quality)
    );
    if (!blob) return file;

    const newName = file.name.replace(/\.[^/.]+$/, "") + ".jpg";
    return new File([blob], newName, { type: "image/jpeg", lastModified: Date.now() });
  } catch {
    // Browser couldn't decode (corrupt / unsupported codec). Let the backend
    // surface the rejection with its own precise error rather than a network error.
    return file;
  }
}
