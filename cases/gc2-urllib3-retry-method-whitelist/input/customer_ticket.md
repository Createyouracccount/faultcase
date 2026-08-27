# Ticket #4821 — Order sync crashes with ValueError since yesterday's incident

**Product**: Orders API integration (Python)
**Severity**: High — nightly order sync job is down

Hi team,

our nightly order sync started crashing yesterday. The weird part: nothing on
our side changed. The job has been running fine for months.

Yesterday your status page showed elevated 502s on `GET /orders` for about an
hour. Since then our sync job dies immediately with a `ValueError` about
`allowed_methods` and `method_whitelist` — which is confusing because we never
pass `allowed_methods` anywhere in our code.

We use a small `Retry` subclass (attached snippet) that we've had since 2020 so
that POSTs are retried too. Requests are made through `requests.Session` with
an `HTTPAdapter`.

What we tried:
- Re-ran the job: same crash, every time your API returns a 502.
- On a colleague's machine against staging (no 502s there): works fine, which
  makes us think it's something your 502s trigger.

Full traceback attached in error.log. Version info in sdk_version.txt.

Can you tell us why *your* 502s crash *our* retry config? Is this a bug in
your API or in our code?
