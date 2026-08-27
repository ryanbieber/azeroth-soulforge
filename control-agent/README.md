# Control Agent

The Control Agent is an internal-only, allowlisted boundary between the
authenticated Soulforge dashboard and Docker. It may inspect service state,
start/stop/restart the game servers, update a small set of validated AzerothCore
configuration values, rename and classify the realm, adjust bounded gameplay
rates, and list random Playerbot characters.

It is never published on a host port. The agent has access to the Docker socket,
which is equivalent to host administration; do not add arbitrary command, SQL,
file, or container APIs. Browser requests must always terminate at the Soul
Service and carry a valid admin session.
