/**
 * Raster and print exports.
 *
 * SVG comes from the modeller, so what is exported is exactly what is on
 * screen. PNG and PDF are derived from that SVG in the browser rather than on
 * the server: no headless renderer to install, no font mismatch between two
 * drawing stacks, and the result matches the canvas pixel for pixel.
 */

import { downloadBlob, downloadText } from './download';

const PNG_SCALE = 2; // readable when pasted into a document at 100%

interface SvgSize {
  width: number;
  height: number;
}

function measure(svg: string): SvgSize {
  const viewBox = /viewBox="([\d.\-\s]+)"/.exec(svg)?.[1];
  if (viewBox) {
    const parts = viewBox.trim().split(/\s+/).map(Number);
    const width = parts[2];
    const height = parts[3];
    if (width && height) return { width, height };
  }
  const width = Number(/width="(\d+(?:\.\d+)?)/.exec(svg)?.[1] ?? 1200);
  const height = Number(/height="(\d+(?:\.\d+)?)/.exec(svg)?.[1] ?? 800);
  return { width, height };
}

/** Give the exported SVG an explicit background; canvases default to transparent. */
function withBackground(svg: string, background: string): string {
  const { width, height } = measure(svg);
  const rect = `<rect x="0" y="0" width="${width}" height="${height}" fill="${background}"/>`;
  return svg.replace(/(<svg[^>]*>)/, `$1${rect}`);
}

async function rasterise(svg: string, background: string): Promise<Blob> {
  const { width, height } = measure(svg);
  const source = withBackground(svg, background);
  const url = URL.createObjectURL(new Blob([source], { type: 'image/svg+xml;charset=utf-8' }));
  try {
    const image = await loadImage(url);
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(width * PNG_SCALE));
    canvas.height = Math.max(1, Math.round(height * PNG_SCALE));
    const context = canvas.getContext('2d');
    if (!context) throw new Error('canvas 2d context is unavailable');
    context.scale(PNG_SCALE, PNG_SCALE);
    context.drawImage(image, 0, 0, width, height);
    return await new Promise<Blob>((resolve, reject) =>
      canvas.toBlob(
        (blob) => (blob ? resolve(blob) : reject(new Error('the canvas produced no image'))),
        'image/png',
      ),
    );
  } finally {
    URL.revokeObjectURL(url);
  }
}

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error('the diagram could not be rendered'));
    image.src = url;
  });
}

export async function exportPng(svg: string, filename: string): Promise<void> {
  downloadBlob(await rasterise(svg, '#ffffff'), `${filename}.png`);
}

export async function exportPdf(svg: string, filename: string): Promise<void> {
  // jsPDF is a third of the bundle and is needed only here, so it is fetched
  // the first time somebody actually exports a PDF.
  const { jsPDF } = await import('jspdf');
  const { width, height } = measure(svg);
  const png = await rasterise(svg, '#ffffff');
  const dataUrl = await blobToDataUrl(png);
  // One page sized to the diagram: a process diagram is wider than A4 as often
  // as not, and scaling it into a portrait page makes it unreadable.
  const pdf = new jsPDF({
    orientation: width >= height ? 'landscape' : 'portrait',
    unit: 'pt',
    format: [width, height],
  });
  pdf.addImage(dataUrl, 'PNG', 0, 0, width, height);
  pdf.save(`${filename}.pdf`);
}

export function exportSvg(svg: string, filename: string): void {
  downloadText(svg, `${filename}.svg`, 'image/svg+xml');
}

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error('the image could not be read'));
    reader.readAsDataURL(blob);
  });
}
