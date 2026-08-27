# Ticket #5107 — ValueError parsing created_at from your Orders API

**Product**: Orders API integration (Python)
**Severity**: Medium — order detail page broken in production

Hi,

since we integrated your `GET /orders/{id}` endpoint, our production service
crashes when parsing the `created_at` field you return:

```
ValueError: Invalid isoformat string: '2026-01-15T09:30:00Z'
```

The confusing part: the exact same code works fine on my laptop. It only
fails on our production containers. We parse with the standard library —
`datetime.fromisoformat(...)` — nothing exotic.

Is your API returning a non-standard timestamp format? Your docs say
timestamps are ISO 8601, and `2026-01-15T09:30:00Z` looks like valid ISO 8601
to me, so why does Python reject it?

Version info attached. Full log attached.
