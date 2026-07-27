# syntax=docker/dockerfile:1
# ---- build ----------------------------------------------------------------
FROM golang:1.22-alpine AS build
WORKDIR /src
COPY go.mod ./
# Resolve deps (and generate go.sum) at build time — see ADR-007.
RUN go mod download || true
COPY . .
RUN go mod tidy
# Static, stripped, reproducible-ish build.
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/sample-api .

# ---- runtime --------------------------------------------------------------
# Distroless nonroot: no shell, no package manager, runs as uid 65532.
FROM gcr.io/distroless/static-debian12:nonroot
WORKDIR /
COPY --from=build /out/sample-api /sample-api
USER 65532:65532
EXPOSE 8080
ENTRYPOINT ["/sample-api"]
