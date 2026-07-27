// sample-api is a small B2B-SaaS-style HTTP service used to exercise the
// observability stack. It emits the three signals through their idiomatic
// paths:
//
//	metrics : Prometheus RED metrics on /metrics  (pulled by Prometheus)
//	traces  : OTLP spans to the OTel Collector    (pushed)
//	logs    : structured JSON to stdout w/ trace_id (tailed by the Collector)
//
// It also exposes /fault so we can inject latency and error rate
// deterministically for the AI SRE RCA demo — no need to actually break
// anything unrecoverable.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"math/rand"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"sync/atomic"
	"syscall"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	semconv "go.opentelemetry.io/otel/semconv/v1.26.0"
	"go.opentelemetry.io/otel/trace"
)

const serviceName = "sample-api"

// ---------------------------------------------------------------------------
// Metrics (names must match platform/config/slo-rules.yaml)
// ---------------------------------------------------------------------------
var (
	reqTotal = prometheus.NewCounterVec(prometheus.CounterOpts{
		Name: "http_requests_total",
		Help: "Total HTTP requests processed.",
	}, []string{"service", "method", "route", "code"})

	reqDuration = prometheus.NewHistogramVec(prometheus.HistogramOpts{
		Name:    "http_request_duration_seconds",
		Help:    "HTTP request latency in seconds.",
		Buckets: []float64{0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5},
	}, []string{"service", "method", "route"})
)

// ---------------------------------------------------------------------------
// Fault-injection state (atomic; toggled via POST /fault)
// ---------------------------------------------------------------------------
type faults struct {
	latencyMS atomic.Int64 // extra latency added to /api/work
	errorPct  atomic.Int64 // % of /api/work requests that fail with 500
}

var fx = &faults{}

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(logger)

	prometheus.MustRegister(reqTotal, reqDuration)

	shutdownTracing, err := initTracing(context.Background())
	if err != nil {
		logger.Warn("tracing init failed; continuing without traces", "error", err)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", healthz)
	mux.HandleFunc("/readyz", readyz)
	mux.Handle("/metrics", promhttp.Handler())
	mux.HandleFunc("/fault", faultHandler)
	mux.Handle("/api/work", instrument("/api/work", http.HandlerFunc(work)))

	srv := &http.Server{
		Addr:              ":8080",
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
	}

	go func() {
		logger.Info("sample-api listening", "addr", srv.Addr)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			logger.Error("server error", "error", err)
			os.Exit(1)
		}
	}()

	// Graceful shutdown.
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop
	logger.Info("shutting down")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_ = srv.Shutdown(ctx)
	if shutdownTracing != nil {
		_ = shutdownTracing(ctx)
	}
}

// ---------------------------------------------------------------------------
// Handlers
// ---------------------------------------------------------------------------

func healthz(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusOK); _, _ = w.Write([]byte("ok")) }

// readyz stays ready unless faults make the service unhealthy — we keep it
// simple and always-ready; liveness/readiness split is demonstrated structurally.
func readyz(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusOK); _, _ = w.Write([]byte("ready")) }

// work is the primary business endpoint: it opens a child span for a simulated
// downstream call, honours injected faults, and logs with the trace id.
func work(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	tr := otel.Tracer(serviceName)
	ctx, span := tr.Start(ctx, "process-work")
	defer span.End()

	// Simulated downstream dependency call.
	callDownstream(ctx)

	// Injected latency.
	if extra := fx.latencyMS.Load(); extra > 0 {
		span.SetAttributes(attribute.Int64("fault.injected_latency_ms", extra))
		time.Sleep(time.Duration(extra) * time.Millisecond)
	}

	log := slog.With(traceAttrs(span)...)

	// Injected errors.
	if pct := fx.errorPct.Load(); pct > 0 && rand.Int63n(100) < pct {
		span.SetStatus(codes.Error, "injected fault")
		log.Error("request failed (injected fault)", "route", "/api/work", "code", 500)
		http.Error(w, `{"error":"internal error"}`, http.StatusInternalServerError)
		return
	}

	log.Info("request served", "route", "/api/work", "code", 200)
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{"status": "ok", "service": serviceName})
}

func callDownstream(ctx context.Context) {
	_, span := otel.Tracer(serviceName).Start(ctx, "downstream.db-query")
	defer span.End()
	time.Sleep(time.Duration(5+rand.Intn(20)) * time.Millisecond)
}

// faultHandler toggles fault injection. Example:
//
//	curl -XPOST localhost:8080/fault -d '{"latency_ms":800,"error_pct":30}'
func faultHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "POST only", http.StatusMethodNotAllowed)
		return
	}
	var body struct {
		LatencyMS int64 `json:"latency_ms"`
		ErrorPct  int64 `json:"error_pct"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		http.Error(w, "bad json", http.StatusBadRequest)
		return
	}
	fx.latencyMS.Store(body.LatencyMS)
	fx.errorPct.Store(body.ErrorPct)
	slog.Warn("fault state changed", "latency_ms", body.LatencyMS, "error_pct", body.ErrorPct)
	_ = json.NewEncoder(w).Encode(map[string]any{"latency_ms": body.LatencyMS, "error_pct": body.ErrorPct})
}

// ---------------------------------------------------------------------------
// Instrumentation middleware — records RED metrics for every request.
// ---------------------------------------------------------------------------

type statusRecorder struct {
	http.ResponseWriter
	code int
}

func (s *statusRecorder) WriteHeader(c int) { s.code = c; s.ResponseWriter.WriteHeader(c) }

func instrument(route string, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		rec := &statusRecorder{ResponseWriter: w, code: http.StatusOK}
		next.ServeHTTP(rec, r)
		dur := time.Since(start).Seconds()
		reqDuration.WithLabelValues(serviceName, r.Method, route).Observe(dur)
		reqTotal.WithLabelValues(serviceName, r.Method, route, strconv.Itoa(rec.code)).Inc()
	})
}

// ---------------------------------------------------------------------------
// Tracing
// ---------------------------------------------------------------------------

func initTracing(ctx context.Context) (func(context.Context) error, error) {
	exp, err := otlptracegrpc.New(ctx) // endpoint from OTEL_EXPORTER_OTLP_ENDPOINT
	if err != nil {
		return nil, err
	}
	res, _ := resource.New(ctx,
		resource.WithAttributes(
			semconv.ServiceName(serviceName),
			semconv.ServiceVersion(getenv("APP_VERSION", "dev")),
			attribute.String("deployment.environment", getenv("ENV", "local")),
		),
	)
	tp := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(exp),
		sdktrace.WithResource(res),
		sdktrace.WithSampler(sdktrace.AlwaysSample()),
	)
	otel.SetTracerProvider(tp)
	return tp.Shutdown, nil
}

// traceAttrs returns slog attributes carrying the current trace/span ids so
// Loki can link a log line to its Tempo trace (derived field "trace_id").
func traceAttrs(span trace.Span) []any {
	sc := span.SpanContext()
	if !sc.IsValid() {
		return nil
	}
	return []any{slog.String("trace_id", sc.TraceID().String()), slog.String("span_id", sc.SpanID().String())}
}

func getenv(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}
