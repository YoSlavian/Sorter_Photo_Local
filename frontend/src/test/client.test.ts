import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api } from '../api/client';
import { defaultBuildOptions } from '../api/types';

function mockFetch(response: Partial<Response> & { json?: () => Promise<unknown> }) {
  return vi.fn(async () => response as unknown as Response);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('api client', () => {
  it('posts to the expected path with a JSON body', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({ bpmn: '<x/>' }),
    })) as unknown as typeof fetch;
    vi.stubGlobal('fetch', fetchMock);

    await api.build('текст', defaultBuildOptions);

    const [url, init] = (fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(url).toBe('/api/build');
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual({
      text: 'текст',
      options: defaultBuildOptions,
    });
  });

  it('surfaces the server detail message', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch({
        ok: false,
        status: 400,
        statusText: 'Bad Request',
        json: async () => ({ detail: 'the description is empty' }),
      }),
    );
    await expect(api.build('', defaultBuildOptions)).rejects.toThrow('the description is empty');
  });

  it('flattens FastAPI validation errors', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch({
        ok: false,
        status: 422,
        statusText: 'Unprocessable',
        json: async () => ({
          detail: [{ loc: ['body', 'options', 'mode'], msg: 'unexpected value' }],
        }),
      }),
    );
    await expect(api.validate('<x/>')).rejects.toThrow('options.mode: unexpected value');
  });

  it('reports an unreachable backend in plain language', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    }));
    await expect(api.info()).rejects.toThrow(/Сервер недоступен/);
  });

  it('keeps the HTTP status on the error', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch({ ok: false, status: 503, statusText: 'Unavailable', json: async () => ({}) }),
    );
    const error = await api.info().catch((value: unknown) => value);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(503);
  });
});
