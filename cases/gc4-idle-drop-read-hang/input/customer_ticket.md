# Ticket #5230 (follow-up) — Hang evidence collected, as requested

**Product**: Orders API integration (Python)
**Severity**: Medium — nightly report export worker hangs a few times a week

Hi again,

following up on ticket #5230. You asked for specifics instead of guesses —
fair. We instrumented the workers like you suggested. Here's what we got the
next time it froze:

`py-spy dump` of the stuck worker (PID 3811, stuck for 41 minutes):

```
Thread 3811 (idle): "MainThread"
    readinto (socket.py:706)
    _read_status (http/client.py:281)
    begin (http/client.py:320)
    getresponse (http/client.py:1377)
    _make_request (urllib3/connectionpool.py:466)
    urlopen (urllib3/connectionpool.py:790)
    send (requests/adapters.py:486)
    send (requests/sessions.py:703)
    request (requests/sessions.py:589)
    get (requests/api.py:73)
    fetch_report (reportsync/client.py:12)
```

So it's not throwing anything — it's just sitting in `socket.readinto`
waiting for your API to answer, forever. It happens on `GET /reports/daily`,
always right after a period where the worker sat idle (we pool connections).
Our egress goes through a corporate NAT.

Versions and the calling code attached. No timeout is passed anywhere — is
that the problem, or is your API stalling? Both?
