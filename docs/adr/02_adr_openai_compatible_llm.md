# ADR 02: Language models behind any OpenAI-compatible API

## Context

InfraSales should run on any service that offers the OpenAI Chat Completions API (OpenRouter,
vLLM, LiteLLM, a provider hosted in the EU and others), without code for each of them.

These services limit how many requests a key may send, often per minute, hour, day and month at
once. Many say in each answer what is left:
`RateLimit-Remaining` and `RateLimit-Reset` for the window closest to its limit, and
`X-RateLimit-Remaining-Minute` (`-Hour`, `-Day`, `-Month`) for each one. These are the headers of
[Kong's rate limiting](https://developer.konghq.com/plugins/rate-limiting/), which refuses a request
over the limit with `429` and `Retry-After`.

## Decision

**One protocol, no vendor in the code.** `LLM__PROVIDER=openai-compatible` takes `LLM__BASE_URL`,
`LLM__MODEL` and `LLM__API_KEY`. For every service, [`build_model`](../../src/infrasales/ai/model.py)
builds Pydantic AI's `OpenAIChatModel` with its `OpenAIProvider`. Which service answers is
configuration, set in the profiles. We depend on the `openai` client directly; Pydantic AI's
`openai` extra would add `tiktoken`, which InfraSales does not use.

**The service knows its quota; InfraSales does what it says.** Quotas differ by service and by key,
so none is configured or written into the code. Two layers handle them:

| Situation | What happens |
|---|---|
| A request is refused (429, 5xx, lost connection) | The OpenAI SDK retries it: after `Retry-After` if that is at most two minutes, otherwise with a growing pause |
| No requests left, the reset comes within `LLM__MAX_WAIT_SECONDS` (default 120 s) | [`RateLimitedTransport`](../../src/infrasales/ai/limits.py) holds the next request until the reset |
| No requests left for longer (an hourly, daily or monthly quota used up) | It raises `QuotaExhaustedError` without sending anything; the run fails, and the scheduler retries and alerts as for any other failure |
