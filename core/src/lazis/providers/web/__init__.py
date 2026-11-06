"""Internet research egress (Phase 12, ADR-0009 §P12).

The backend never connects to the internet: its OS sandbox allows only the local inference
runtime and one Unix socket, the one of the research helper (:mod:`.helper`). The desktop shell
starts that helper under its own narrower profile (outbound HTTPS on port 443 and DNS only, no
other connection) and the helper checks every connection again in-process (:mod:`.guard`):
public addresses on port 443 only, allowlisted hosts, HTTPS, size and time limits. The backend
talks to it with :mod:`.client` and only for a research request the user approved.
"""
