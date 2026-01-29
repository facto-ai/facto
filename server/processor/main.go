package main

import (
	"context"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"syscall"
	"time"

	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
)

// Config holds the processor configuration
type Config struct {
	NatsURL       string
	ScyllaHosts   []string
	BatchSize     int
	FlushInterval time.Duration
	MetricsPort   int
}

func loadConfig() *Config {
	natsURL := os.Getenv("NATS_URL")
	if natsURL == "" {
		natsURL = "nats://localhost:4222"
	}

	scyllaHosts := os.Getenv("SCYLLA_HOSTS")
	if scyllaHosts == "" {
		scyllaHosts = "localhost:9042"
	}

	batchSize := 1000 // Each event creates 3 INSERT queries executed in parallel batches
	if bs := os.Getenv("BATCH_SIZE"); bs != "" {
		if parsed, err := strconv.Atoi(bs); err == nil {
			batchSize = parsed
		}
	}

	flushIntervalMs := 1000
	if fi := os.Getenv("FLUSH_INTERVAL_MS"); fi != "" {
		if parsed, err := strconv.Atoi(fi); err == nil {
			flushIntervalMs = parsed
		}
	}

	metricsPort := 8081
	if mp := os.Getenv("METRICS_PORT"); mp != "" {
		if parsed, err := strconv.Atoi(mp); err == nil {
			metricsPort = parsed
		}
	}

	return &Config{
		NatsURL:       natsURL,
		ScyllaHosts:   []string{scyllaHosts},
		BatchSize:     batchSize,
		FlushInterval: time.Duration(flushIntervalMs) * time.Millisecond,
		MetricsPort:   metricsPort,
	}
}

func main() {
	// Setup logging
	zerolog.TimeFieldFormat = zerolog.TimeFormatUnix
	log.Logger = log.Output(zerolog.ConsoleWriter{Out: os.Stderr, TimeFormat: time.RFC3339})

	log.Info().Msg("Starting Facto Processor Service")

	// Load configuration
	config := loadConfig()
	log.Info().
		Str("nats_url", config.NatsURL).
		Strs("scylla_hosts", config.ScyllaHosts).
		Int("batch_size", config.BatchSize).
		Dur("flush_interval", config.FlushInterval).
		Int("metrics_port", config.MetricsPort).
		Msg("Configuration loaded")

	// Create context with cancellation
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Initialize storage
	storage, err := NewStorage(config.ScyllaHosts)
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to initialize storage")
	}
	defer storage.Close()
	log.Info().Msg("Connected to ScyllaDB")

	// Initialize consumer
	consumer, err := NewConsumer(config.NatsURL, storage, config.BatchSize, config.FlushInterval)
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to initialize consumer")
	}
	defer consumer.Close()
	log.Info().Msg("Connected to NATS")

	// Start metrics server
	go func() {
		http.Handle("/metrics", promhttp.Handler())
		http.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(http.StatusOK)
			w.Write([]byte(`{"status":"healthy"}`))
		})
		addr := ":" + strconv.Itoa(config.MetricsPort)
		log.Info().Str("addr", addr).Msg("Starting metrics server")
		if err := http.ListenAndServe(addr, nil); err != nil {
			log.Error().Err(err).Msg("Metrics server error")
		}
	}()

	// Start consuming messages
	go func() {
		if err := consumer.Start(ctx); err != nil {
			log.Error().Err(err).Msg("Consumer error")
			cancel()
		}
	}()

	// Wait for shutdown signal
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
	<-sigChan

	log.Info().Msg("Shutting down...")
	cancel()

	// Give time for graceful shutdown
	time.Sleep(2 * time.Second)
	log.Info().Msg("Shutdown complete")
}
