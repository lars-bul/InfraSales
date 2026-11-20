// A request still unanswered by then fails, as one without a connection does: no screen waits
// longer. A write's outcome is then unknown; callers reread before writing again.
export const DEADLINE_MS = 15_000;

// The deadline aborts the request, its body included; the caller's own signal still can too.
// A timer rather than AbortSignal.timeout: test clocks drive it.
export function withDeadline(request: Request): Request {
  const deadline = new AbortController();
  const late = new DOMException("No answer in time", "TimeoutError");
  setTimeout(() => deadline.abort(late), DEADLINE_MS);
  return new Request(request, { signal: AbortSignal.any([request.signal, deadline.signal]) });
}
