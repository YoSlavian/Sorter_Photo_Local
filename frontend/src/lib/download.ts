/** Saving files from the browser, in one place so every export behaves alike. */

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Revoking immediately breaks the download in Safari; a tick is enough.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function downloadText(text: string, filename: string, type: string): void {
  downloadBlob(new Blob([text], { type: `${type};charset=utf-8` }), filename);
}

/** Read a file the user picked, tolerating the encodings Windows produces. */
export async function readTextFile(file: File): Promise<string> {
  const buffer = await file.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  // A UTF-8 BOM would otherwise end up inside the first XML tag.
  const withoutBom =
    bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf ? bytes.subarray(3) : bytes;
  const utf8 = new TextDecoder('utf-8', { fatal: false }).decode(withoutBom);
  if (!utf8.includes('�')) return utf8;
  // Replacement characters mean it was not UTF-8; on Windows that is cp1251.
  try {
    return new TextDecoder('windows-1251').decode(withoutBom);
  } catch {
    return utf8;
  }
}

export function baseName(name: string): string {
  return name.replace(/\.[^.]+$/, '') || 'process';
}
