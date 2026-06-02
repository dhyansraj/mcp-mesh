# Thin per-run image built from the prebuilt toolchain base in the local registry.
# BASE_IMAGE is a content-addressed tag (sha of Dockerfile.base) injected by tc00,
# so a changed Dockerfile.base forces a new base instead of reusing a stale one.
ARG BASE_IMAGE=192.168.10.1:5000/src-build-base:latest
# hadolint ignore=DL3006
FROM ${BASE_IMAGE}
