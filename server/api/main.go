package main

import (
	"context"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
)

// Config holds the API configuration
type Config struct {
	Port        int
	ScyllaHosts []string
}

func loadConfig() *Config {
	port := 8082
	if p := os.Getenv("PORT"); p != "" {
		if parsed, err := strconv.Atoi(p); err == nil {
			port = parsed
		}
	}

	scyllaHosts := os.Getenv("SCYLLA_HOSTS")
	if scyllaHosts == "" {
		scyllaHosts = "localhost:9042"
	}

	return &Config{
		Port:        port,
		ScyllaHosts: []string{scyllaHosts},
	}
}

func main() {
	// Setup logging
	zerolog.TimeFieldFormat = zerolog.TimeFormatUnix
	log.Logger = log.Output(zerolog.ConsoleWriter{Out: os.Stderr, TimeFormat: time.RFC3339})

	log.Info().Msg("Starting Facto Query API")

	// Load configuration
	config := loadConfig()
	log.Info().
		Int("port", config.Port).
		Strs("scylla_hosts", config.ScyllaHosts).
		Msg("Configuration loaded")

	// Initialize storage
	storage, err := NewStorage(config.ScyllaHosts)
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to initialize storage")
	}
	defer storage.Close()
	log.Info().Msg("Connected to ScyllaDB")

	// Create handlers
	handlers := NewHandlers(storage)

	// Setup Gin
	gin.SetMode(gin.ReleaseMode)
	router := gin.New()
	router.Use(gin.Recovery())
	router.Use(loggerMiddleware())

	// Health and metrics endpoints
	router.GET("/health", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"status": "healthy"})
	})
	router.GET("/metrics", gin.WrapH(promhttp.Handler()))

	// API v1 routes
	v1 := router.Group("/v1")
	{
		v1.GET("/events", handlers.GetEvents)
		v1.GET("/events/:facto_id", handlers.GetEventByFactoID)
		v1.GET("/sessions/:session_id/events", handlers.GetSessionEvents)
		v1.POST("/verify", handlers.VerifyEvent)
		v1.GET("/evidence-package", handlers.GetEvidencePackage)
	}

	// Create server
	srv := &http.Server{
		Addr:    ":" + strconv.Itoa(config.Port),
		Handler: router,
	}

	// Start server in goroutine
	go func() {
		log.Info().Int("port", config.Port).Msg("Starting HTTP server")
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatal().Err(err).Msg("Server error")
		}
	}()

	// Wait for shutdown signal
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	log.Info().Msg("Shutting down server...")

	// Graceful shutdown with timeout
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := srv.Shutdown(ctx); err != nil {
		log.Error().Err(err).Msg("Server forced to shutdown")
	}

	log.Info().Msg("Server exited")
}

func loggerMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		path := c.Request.URL.Path
		raw := c.Request.URL.RawQuery

		c.Next()

		latency := time.Since(start)
		status := c.Writer.Status()
		method := c.Request.Method

		if raw != "" {
			path = path + "?" + raw
		}

		log.Info().
			Str("method", method).
			Str("path", path).
			Int("status", status).
			Dur("latency", latency).
			Str("ip", c.ClientIP()).
			Msg("Request")
	}
}
