# Ticket #5230 — API calls sometimes hang forever

**Product**: Orders API integration
**Severity**: Medium

Hi,

our integration with your API "sometimes" freezes. A request just never comes
back and our worker gets stuck. It happens maybe a few times a week? Hard to
say. Restarting the worker fixes it for a while.

We don't have logs from the exact moments it happens — our log retention is
short and by the time we notice, the window is gone. Nothing gets thrown as
far as we can tell, it just hangs.

We're on Python, using your API over HTTPS. It's probably something on your
side because our other integrations don't do this.

Can you fix this?
