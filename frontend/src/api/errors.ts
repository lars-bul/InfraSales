// An answer with an error status. The generated client otherwise throws only the parsed body,
// which cannot tell a client error (4xx: never retried) from a server error (5xx: retried).
export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, body: unknown) {
    super(`The API answered ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

// The generated client's error interceptor: an answer becomes an `ApiError`; without one (no
// connection, the deadline, an abort) the error stays as `fetch` raised it.
export function withStatus(error: unknown, response: Response | undefined): unknown {
  return response ? new ApiError(response.status, error) : error;
}
