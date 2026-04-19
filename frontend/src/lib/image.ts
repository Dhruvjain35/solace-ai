/**
 * Resize a File (image) client-side so it fits API Gateway's 10MB payload limit.
 * Returns the original File if it's already small enough, or a downscaled JPEG otherwise.
 */
export async function resizeImageIfNeeded(
  file: File,
  opts: { maxBytes?: number; maxDimension?: number; quality?: number } = {}
): Promise<File> {
  const maxBytes = opts.maxBytes ?? 2_000_000; // 2MB ceiling; well under 10MB API GW limit
  const maxDim = opts.maxDimension ?? 1600;
  const quality = opts.quality ?? 0.82;

  if (file.size <= maxBytes) return file;
  if (!file.type.startsWith("image/")) return file;

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

  const newName = file.name.replace(/\.[^/.]+$/, "") + "-resized.jpg";
  return new File([blob], newName, { type: "image/jpeg", lastModified: Date.now() });
}
