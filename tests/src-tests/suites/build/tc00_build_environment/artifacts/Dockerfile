# Thin per-run image built from the prebuilt toolchain base in the local registry.
# Toolchains live in src-build-base (built once, pushed to 192.168.10.1:5000).
# Intentional: always pull the current toolchain base image from the local registry.
# hadolint ignore=DL3007
FROM 192.168.10.1:5000/src-build-base:latest
