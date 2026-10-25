type AbortSignalWithAny = typeof AbortSignal & {
  any?: (signals: AbortSignal[]) => AbortSignal;
};

export function withTimeout(signal: AbortSignal | undefined, timeoutMs: number): AbortSignal {
  const timeout = AbortSignal.timeout(timeoutMs);
  if (signal === undefined) return timeout;
  const callerSignal = signal;

  const nativeAny = (AbortSignal as AbortSignalWithAny).any;
  if (typeof nativeAny === 'function') {
    return nativeAny.call(AbortSignal, [callerSignal, timeout]);
  }

  const controller = new AbortController();
  const onCallerAbort = () => abortFrom(callerSignal);
  const onTimeout = () => abortFrom(timeout);

  function abortFrom(source: AbortSignal) {
    controller.abort(source.reason);
    callerSignal.removeEventListener('abort', onCallerAbort);
    timeout.removeEventListener('abort', onTimeout);
  }

  if (callerSignal.aborted) {
    controller.abort(callerSignal.reason);
    return controller.signal;
  }
  if (timeout.aborted) {
    controller.abort(timeout.reason);
    return controller.signal;
  }

  callerSignal.addEventListener('abort', onCallerAbort, { once: true });
  timeout.addEventListener('abort', onTimeout, { once: true });
  return controller.signal;
}
