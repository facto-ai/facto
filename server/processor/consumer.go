package main

import (
	"context"
	"encoding/json"
	"os"
	"time"

	"github.com/nats-io/nats.go"
	"github.com/nats-io/nats.go/jetstream"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"github.com/rs/zerolog/log"
)

var (
	eventsConsumed = promauto.NewCounter(prometheus.CounterOpts{
		Name: "facto_processor_events_consumed_total",
		Help: "Total number of events consumed from NATS",
	})

	eventsProcessed = promauto.NewCounter(prometheus.CounterOpts{
		Name: "facto_processor_events_processed_total",
		Help: "Total number of events processed successfully",
	})

	eventsFailedTotal = promauto.NewCounter(prometheus.CounterOpts{
		Name: "facto_processor_events_failed_total",
		Help: "Total number of events that failed processing",
	})

	batchesProcessed = promauto.NewCounter(prometheus.CounterOpts{
		Name: "facto_processor_batches_processed_total",
		Help: "Total number of batches processed",
	})

	batchSize = promauto.NewHistogram(prometheus.HistogramOpts{
		Name:    "facto_processor_batch_size",
		Help:    "Size of processed batches",
		Buckets: []float64{1, 10, 50, 100, 250, 500, 1000},
	})

	processingLatency = promauto.NewHistogram(prometheus.HistogramOpts{
		Name:    "facto_processor_batch_latency_seconds",
		Help:    "Latency of batch processing in seconds",
		Buckets: []float64{0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5},
	})

	merkleTreesCreated = promauto.NewCounter(prometheus.CounterOpts{
		Name: "facto_processor_merkle_trees_created_total",
		Help: "Total number of Merkle trees created",
	})
)

// FactoEvent represents an event received from NATS
type FactoEvent struct {
	FactoID       string                 `json:"facto_id"`
	AgentID       string                 `json:"agent_id"`
	SessionID     string                 `json:"session_id"`
	ParentFactoID *string                `json:"parent_facto_id"`
	ActionType    string                 `json:"action_type"`
	Status        string                 `json:"status"`
	InputData     map[string]interface{} `json:"input_data"`
	OutputData    map[string]interface{} `json:"output_data"`
	ExecutionMeta ExecutionMeta          `json:"execution_meta"`
	Proof         Proof                  `json:"proof"`
	StartedAt     int64                  `json:"started_at"`
	CompletedAt   int64                  `json:"completed_at"`
}

// ExecutionMeta contains execution metadata
type ExecutionMeta struct {
	ModelID     *string           `json:"model_id"`
	ModelHash   *string           `json:"model_hash"`
	Temperature *float64          `json:"temperature"`
	Seed        *int64            `json:"seed"`
	MaxTokens   *int32            `json:"max_tokens"`
	ToolCalls   []interface{}     `json:"tool_calls"`
	SDKVersion  string            `json:"sdk_version"`
	SDKLanguage string            `json:"sdk_language"`
	Tags        map[string]string `json:"tags"`
}

// Proof contains cryptographic proof
type Proof struct {
	Signature string `json:"signature"`
	PublicKey string `json:"public_key"`
	PrevHash  string `json:"prev_hash"`
	EventHash string `json:"event_hash"`
}

// Consumer handles NATS message consumption
type Consumer struct {
	nc            *nats.Conn
	js            jetstream.JetStream
	storage       *Storage
	batchSize     int
	flushInterval time.Duration
	events        []FactoEvent
	messages      []jetstream.Msg
}

// NewConsumer creates a new NATS consumer
func NewConsumer(natsURL string, storage *Storage, batchSize int, flushInterval time.Duration) (*Consumer, error) {
	nc, err := nats.Connect(natsURL,
		nats.RetryOnFailedConnect(true),
		nats.MaxReconnects(-1),
		nats.ReconnectWait(time.Second),
		nats.DisconnectErrHandler(func(nc *nats.Conn, err error) {
			log.Warn().Err(err).Msg("NATS disconnected")
		}),
		nats.ReconnectHandler(func(nc *nats.Conn) {
			log.Info().Msg("NATS reconnected")
		}),
	)
	if err != nil {
		return nil, err
	}

	js, err := jetstream.New(nc)
	if err != nil {
		nc.Close()
		return nil, err
	}

	return &Consumer{
		nc:            nc,
		js:            js,
		storage:       storage,
		batchSize:     batchSize,
		flushInterval: flushInterval,
		events:        make([]FactoEvent, 0, batchSize),
		messages:      make([]jetstream.Msg, 0, batchSize),
	}, nil
}

// Start begins consuming messages
func (c *Consumer) Start(ctx context.Context) error {
	// Get or create stream
	stream, err := c.js.Stream(ctx, "FACTO_EVENTS")
	subject := "facto.events.>"
	if filter := os.Getenv("FILTER_SUBJECT"); filter != "" {
		subject = filter
		log.Info().Str("filter_subject", subject).Msg("Using filtered subject")
	}

	if err != nil {
		// Try to create the stream if it doesn't exist
		stream, err = c.js.CreateStream(ctx, jetstream.StreamConfig{
			Name:      "FACTO_EVENTS",
			Subjects:  []string{"facto.events.>"}, // Stream needs full range
			Retention: jetstream.WorkQueuePolicy,
			Storage:   jetstream.FileStorage,
		})
		if err != nil {
			return err
		}
	}

	// Create durable consumer
	durableName := os.Getenv("DURABLE_NAME")
	if durableName == "" {
		durableName = "processor"
	}

	// Delete consumer if requested to reset state
	if os.Getenv("RESET_CONSUMER") == "true" {
		log.Info().Str("durable", durableName).Msg("Deleting consumer for reset")
		if err := stream.DeleteConsumer(ctx, durableName); err != nil {
			log.Warn().Err(err).Msg("Failed to delete consumer (maybe it didn't exist)")
		} else {
			log.Info().Msg("Consumer deleted")
		}
	}

	consumer, err := stream.CreateOrUpdateConsumer(ctx, jetstream.ConsumerConfig{
		Durable: durableName,
		// If I change the FilterSubject, I update the consumer.
		FilterSubject: subject,
		AckPolicy:     jetstream.AckExplicitPolicy,
		MaxAckPending: c.batchSize * 2,
		AckWait:       30 * time.Second,
	})
	if err != nil {
		return err
	}

	log.Info().Msg("Started consuming from FACTO_EVENTS stream")

	// Create ticker for flush interval
	ticker := time.NewTicker(c.flushInterval)
	defer ticker.Stop()

	// Consume messages
	msgChan := make(chan jetstream.Msg, c.batchSize)
	go func() {
		for {
			select {
			case <-ctx.Done():
				close(msgChan)
				return
			default:
				msgs, err := consumer.Fetch(c.batchSize, jetstream.FetchMaxWait(c.flushInterval))
				if err != nil {
					if err != context.Canceled {
						log.Debug().Err(err).Msg("Fetch returned")
					}
					continue
				}
				for msg := range msgs.Messages() {
					msgChan <- msg
				}
			}
		}
	}()

	for {
		select {
		case <-ctx.Done():
			// Flush remaining events
			if len(c.events) > 0 {
				c.flush(ctx)
			}
			return ctx.Err()

		case msg, ok := <-msgChan:
			if !ok {
				return nil
			}
			c.handleMessage(ctx, msg)

		case <-ticker.C:
			if len(c.events) > 0 {
				c.flush(ctx)
			}
		}
	}
}

func (c *Consumer) handleMessage(ctx context.Context, msg jetstream.Msg) {
	eventsConsumed.Inc()

	var event FactoEvent
	if err := json.Unmarshal(msg.Data(), &event); err != nil {
		log.Error().Err(err).Msg("Failed to unmarshal event")
		msg.Nak()
		eventsFailedTotal.Inc()
		return
	}

	c.events = append(c.events, event)
	c.messages = append(c.messages, msg)

	if len(c.events) >= c.batchSize {
		c.flush(ctx)
	}
}

func (c *Consumer) flush(ctx context.Context) {
	if len(c.events) == 0 {
		return
	}

	start := time.Now()
	eventCount := len(c.events)

	log.Debug().Int("count", eventCount).Msg("Processing batch")

	// Build Merkle tree from event hashes
	hashes := make([]string, len(c.events))
	for i, event := range c.events {
		hashes[i] = event.Proof.EventHash
	}
	tree := BuildMerkleTree(hashes)
	merkleRoot := tree.Root()
	merkleTreesCreated.Inc()

	// Store events in ScyllaDB
	if err := c.storage.StoreBatch(ctx, c.events); err != nil {
		log.Error().Err(err).Msg("Failed to store batch")
		// NAK all messages
		for _, msg := range c.messages {
			msg.Nak()
		}
		eventsFailedTotal.Add(float64(eventCount))
	} else {
		// Store Merkle root
		if len(c.events) > 0 {
			if err := c.storage.StoreMerkleRoot(ctx, time.Now(), merkleRoot, eventCount, c.events[0].FactoID, c.events[len(c.events)-1].FactoID, hashes); err != nil {
				log.Error().Err(err).Msg("Failed to store Merkle root")
			}
		}

		// ACK all messages
		for _, msg := range c.messages {
			msg.Ack()
		}
		eventsProcessed.Add(float64(eventCount))
	}

	// Update metrics
	batchesProcessed.Inc()
	batchSize.Observe(float64(eventCount))
	processingLatency.Observe(time.Since(start).Seconds())

	log.Info().
		Int("count", eventCount).
		Str("merkle_root", merkleRoot).
		Dur("duration", time.Since(start)).
		Msg("Batch processed")

	// Clear the batch
	c.events = c.events[:0]
	c.messages = c.messages[:0]
}

// Close closes the consumer
func (c *Consumer) Close() error {
	if c.nc != nil {
		c.nc.Close()
	}
	return nil
}
