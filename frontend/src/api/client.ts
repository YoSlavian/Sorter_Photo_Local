/**
 * Typed access to the backend.
 *
 * Every call goes through one request function, so error handling, the detail
 * message the server sends and the "backend is not reachable" case are handled
 * once instead of at thirty call sites.
 */

import type {
  BuildOptions,
  Diagram,
  Language,
  ParseResult,
  ProjectLoad,
  ProjectPayload,
  ServerInfo,
  Validation,
} from './types';

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError('Сервер недоступен. Проверьте, что backend запущен.', 0);
  }

  if (!response.ok) {
    throw new ApiError(await readError(response), response.status);
  }
  return (await response.json()) as T;
}

async function readError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === 'string') return payload.detail;
    if (Array.isArray(payload.detail)) {
      // FastAPI validation errors arrive as a list of field problems.
      return payload.detail
        .map((item) => {
          const entry = item as { loc?: unknown[]; msg?: string };
          const where = Array.isArray(entry.loc) ? entry.loc.slice(1).join('.') : '';
          return where ? `${where}: ${entry.msg ?? ''}` : (entry.msg ?? '');
        })
        .join('; ');
    }
  } catch {
    /* fall through to the status text */
  }
  return `${response.status} ${response.statusText}`;
}

async function download(path: string, body: unknown): Promise<Blob> {
  const response = await fetch(`/api${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new ApiError(await readError(response), response.status);
  return response.blob();
}

export const api = {
  info: () => request<ServerInfo>('/info'),

  build: (text: string, options: BuildOptions, signal?: AbortSignal) =>
    request<Diagram>('/build', { text, options }, signal),

  parse: (text: string, options: BuildOptions) =>
    request<ParseResult>('/parse', { text, options }),

  validate: (bpmn: string) => request<Validation>('/validate', { bpmn }),

  layout: (bpmn: string) => request<Diagram>('/layout', { bpmn }),

  clarify: (bpmn: string, answers: Record<string, string>) =>
    request<Diagram>('/clarify', { bpmn, answers }),

  describe: (bpmn: string, language?: Language) =>
    request<{ text: string }>('/describe', { bpmn, language: language ?? null }),

  importBpmn: (bpmn: string, sourceText = '') =>
    request<Diagram>('/bpmn/import', { bpmn, sourceText }),

  exportSvg: (bpmn: string) => download('/export/svg', { bpmn }),

  exportJson: (bpmn: string) => download('/export/json', { bpmn }),

  saveProject: (payload: {
    bpmn: string;
    sourceText: string;
    name: string;
    settings: Record<string, unknown>;
  }) => request<ProjectPayload>('/project/export', payload),

  openProject: (project: string) => request<ProjectLoad>('/project/import', { project }),
};
