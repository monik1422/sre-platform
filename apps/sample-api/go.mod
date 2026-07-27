module github.com/monik1422/sre-platform/apps/sample-api

go 1.22

require (
	github.com/prometheus/client_golang v1.19.1
	go.opentelemetry.io/otel v1.28.0
	go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc v1.28.0
	go.opentelemetry.io/otel/sdk v1.28.0
	go.opentelemetry.io/otel/trace v1.28.0
)

// NOTE: go.sum is intentionally not committed offline. Run `go mod tidy`
// once (with network access) to resolve the checksum database, or the CI
// build step will do it. See docs/design-decisions.md ADR-007.
