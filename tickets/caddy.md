# Caddy: connections accumulate during WebSocket reconnects

This is a constructed benchmark scenario, not a verified customer incident.

A service uses Caddy to proxy a WebSocket chat application. During repeated
client reconnects on unreliable networks, the server's open connection count
keeps growing. Eventually it stops accepting connections with "too many open
files". Restarting the process clears the accumulated connections.

Investigate whether failed connection setup can account for this behavior.
Implement a repair if supported by the source, preserve successful transfers,
and verify the affected behavior and relevant package tests. Report what your
tests establish and what remains uncertain.
