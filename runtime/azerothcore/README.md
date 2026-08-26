# Local AzerothCore runtime

Docker Compose bind-mounts `etc/` and `logs/` here. The official container
entrypoint materializes configuration from the compiled `.dist` files and the
`AC_*` environment settings in `compose.yaml`.

Server binaries, extracted map data, MySQL data, and model weights live in
Docker images or named volumes, not this directory. Runtime contents are
private and ignored; this README is the only committed file in the boundary.
