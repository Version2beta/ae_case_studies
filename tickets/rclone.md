# Rclone: a multi-threaded download does not finish after a connection failure

This is a constructed benchmark scenario, not a verified customer incident.

While downloading a large file with multiple transfer streams, a remote
connection fails. The transfer stops making progress instead of completing or
reporting a useful error. A request to stop the transfer sometimes also waits
without completing.

Investigate the download path. Implement a repair if supported by the source,
preserve successful transfers, and verify failure and cancellation behavior
and the relevant package tests. Report what you can and cannot reproduce.
