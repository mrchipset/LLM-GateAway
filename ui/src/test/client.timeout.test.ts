import { describe, expect, it, vi } from 'vitest';

import { getHealth } from '../api/client';
import { installFetchMock } from './fetchMock';

function removeNativeAny(): () => void {
  const original = Object.getOwnPropertyDescriptor(AbortSignal, 'any');
  Object.defineProperty(AbortSignal, 'any', { value: undefined, configurable: true });
  return () => {
    if (original === undefined) {
      Reflect.deleteProperty(AbortSignal, 'any');
      return;
    }
    Object.defineProperty(AbortSignal, 'any', original);
  };
}

describe('api request timeout signal', () => {
  it('resolves a request through the native AbortSignal.any path', async () => {
    const anySpy = vi.spyOn(AbortSignal, 'any');
    installFetchMock();
    const controller = new AbortController();

    await expect(getHealth(controller.signal)).resolves.toEqual({
      status: 'ok',
      version: '0.1.0',
    });
    expect(anySpy).toHaveBeenCalledOnce();
  });

  it('resolves a request when AbortSignal.any is unavailable', async () => {
    const restore = removeNativeAny();
    try {
      installFetchMock();
      const controller = new AbortController();
      await expect(getHealth(controller.signal)).resolves.toEqual({
        status: 'ok',
        version: '0.1.0',
      });
    } finally {
      restore();
    }
  });

  it('still propagates a caller abort when AbortSignal.any is unavailable', async () => {
    const restore = removeNativeAny();
    try {
      vi.stubGlobal(
        'fetch',
        vi.fn<typeof fetch>((_input, init) => {
          return new Promise<Response>((_resolve, reject) => {
            const signal = init?.signal;
            if (signal === null || signal === undefined) {
              reject(new Error('The request was sent without an abort signal'));
              return;
            }
            signal.addEventListener(
              'abort',
              () => reject(new DOMException('Aborted', 'AbortError')),
              { once: true },
            );
          });
        }),
      );

      const controller = new AbortController();
      const assertion = expect(getHealth(controller.signal)).rejects.toMatchObject({
        name: 'AbortError',
      });
      controller.abort();
      await assertion;
    } finally {
      restore();
    }
  });
});
