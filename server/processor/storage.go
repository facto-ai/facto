package main

import (
	"context"
	"encoding/json"
	"time"

	"github.com/gocql/gocql"
	"github.com/rs/zerolog/log"
	"golang.org/x/sync/errgroup"
)

// Storage handles ScyllaDB operations
type Storage struct {
	session *gocql.Session
}

// NewStorage creates a new storage instance
func NewStorage(hosts []string) (*Storage, error) {
	cluster := gocql.NewCluster(hosts...)
	cluster.Keyspace = "facto"
	cluster.Consistency = gocql.LocalQuorum
	cluster.Timeout = 10 * time.Second
	cluster.ConnectTimeout = 30 * time.Second
	cluster.RetryPolicy = &gocql.ExponentialBackoffRetryPolicy{
		Min:        100 * time.Millisecond,
		Max:        10 * time.Second,
		NumRetries: 5,
	}

	session, err := cluster.CreateSession()
	if err != nil {
		return nil, err
	}

	return &Storage{session: session}, nil
}

// eventData holds pre-processed event data to avoid recomputation
type eventData struct {
	event         FactoEvent
	inputData     []byte
	outputData    []byte
	toolCalls     []byte
	completedTime time.Time
	eventDate     time.Time
	modelID       string
	modelHash     string
	sdkVersion    string
	sdkLanguage   string
	temperature   float32
	seed          int64
	maxTokens     int32
	parentFactoID string
}

// StoreBatch stores a batch of events using concurrent per-table batches
// This allows processing 1000 events (3000 total inserts) by splitting into
// 3 concurrent batches of 1000 inserts each, staying within ScyllaDB limits
func (s *Storage) StoreBatch(ctx context.Context, events []FactoEvent) error {
	// Pre-process all events once
	processedEvents := make([]eventData, len(events))
	for i, event := range events {
		inputData, _ := json.Marshal(event.InputData)
		outputData, _ := json.Marshal(event.OutputData)
		toolCalls, _ := json.Marshal(event.ExecutionMeta.ToolCalls)

		completedTime := time.Unix(0, event.CompletedAt)
		eventDate := completedTime.UTC().Truncate(24 * time.Hour)

		var modelID, modelHash, sdkVersion, sdkLanguage string
		var temperature float32
		var seed int64
		var maxTokens int32

		if event.ExecutionMeta.ModelID != nil {
			modelID = *event.ExecutionMeta.ModelID
		}
		if event.ExecutionMeta.ModelHash != nil {
			modelHash = *event.ExecutionMeta.ModelHash
		}
		if event.ExecutionMeta.Temperature != nil {
			temperature = float32(*event.ExecutionMeta.Temperature)
		}
		if event.ExecutionMeta.Seed != nil {
			seed = *event.ExecutionMeta.Seed
		}
		if event.ExecutionMeta.MaxTokens != nil {
			maxTokens = *event.ExecutionMeta.MaxTokens
		}
		sdkVersion = event.ExecutionMeta.SDKVersion
		sdkLanguage = event.ExecutionMeta.SDKLanguage

		var parentFactoID string
		if event.ParentFactoID != nil {
			parentFactoID = *event.ParentFactoID
		}

		processedEvents[i] = eventData{
			event:         event,
			inputData:     inputData,
			outputData:    outputData,
			toolCalls:     toolCalls,
			completedTime: completedTime,
			eventDate:     eventDate,
			modelID:       modelID,
			modelHash:     modelHash,
			sdkVersion:    sdkVersion,
			sdkLanguage:   sdkLanguage,
			temperature:   temperature,
			seed:          seed,
			maxTokens:     maxTokens,
			parentFactoID: parentFactoID,
		}
	}

	// Execute 3 table batches concurrently
	g, ctx := errgroup.WithContext(ctx)

	// Batch 1: Main events table
	g.Go(func() error {
		return s.storeEventsBatch(ctx, processedEvents)
	})

	// Batch 2: events_by_facto_id lookup table
	g.Go(func() error {
		return s.storeByFactoIDBatch(ctx, processedEvents)
	})

	// Batch 3: events_by_session lookup table
	g.Go(func() error {
		return s.storeBySessionBatch(ctx, processedEvents)
	})

	if err := g.Wait(); err != nil {
		log.Error().Err(err).Int("batch_size", len(events)).Msg("Failed to store batch")
		return err
	}

	return nil
}

// storeEventsBatch inserts into the main events table
func (s *Storage) storeEventsBatch(ctx context.Context, events []eventData) error {
	batch := s.session.NewBatch(gocql.UnloggedBatch).WithContext(ctx)

	for _, e := range events {
		batch.Query(`
			INSERT INTO events (
				agent_id, date, facto_id, session_id, parent_facto_id,
				action_type, status, input_data, output_data,
				model_id, model_hash, temperature, seed, max_tokens, tool_calls,
				sdk_version, sdk_language, tags,
				signature, public_key, prev_hash, event_hash,
				started_at, completed_at, received_at
			) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		`,
			e.event.AgentID, e.eventDate, e.event.FactoID, e.event.SessionID, e.parentFactoID,
			e.event.ActionType, e.event.Status, e.inputData, e.outputData,
			e.modelID, e.modelHash, e.temperature, e.seed, e.maxTokens, string(e.toolCalls),
			e.sdkVersion, e.sdkLanguage, e.event.ExecutionMeta.Tags,
			[]byte(e.event.Proof.Signature), []byte(e.event.Proof.PublicKey),
			e.event.Proof.PrevHash, e.event.Proof.EventHash,
			time.Unix(0, e.event.StartedAt), e.completedTime, time.Now(),
		)
	}

	return s.session.ExecuteBatch(batch)
}

// storeByFactoIDBatch inserts into the events_by_facto_id lookup table
func (s *Storage) storeByFactoIDBatch(ctx context.Context, events []eventData) error {
	batch := s.session.NewBatch(gocql.UnloggedBatch).WithContext(ctx)

	for _, e := range events {
		batch.Query(`
			INSERT INTO events_by_facto_id (
				facto_id, agent_id, date, completed_at, session_id,
				action_type, status, input_data, output_data,
				model_id, model_hash, temperature, seed, max_tokens, tool_calls,
				sdk_version, sdk_language, tags,
				signature, public_key, prev_hash, event_hash,
				parent_facto_id, started_at, received_at
			) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		`,
			e.event.FactoID, e.event.AgentID, e.eventDate, e.completedTime, e.event.SessionID,
			e.event.ActionType, e.event.Status, e.inputData, e.outputData,
			e.modelID, e.modelHash, e.temperature, e.seed, e.maxTokens, string(e.toolCalls),
			e.sdkVersion, e.sdkLanguage, e.event.ExecutionMeta.Tags,
			[]byte(e.event.Proof.Signature), []byte(e.event.Proof.PublicKey),
			e.event.Proof.PrevHash, e.event.Proof.EventHash,
			e.parentFactoID, time.Unix(0, e.event.StartedAt), time.Now(),
		)
	}

	return s.session.ExecuteBatch(batch)
}

// storeBySessionBatch inserts into the events_by_session lookup table
func (s *Storage) storeBySessionBatch(ctx context.Context, events []eventData) error {
	batch := s.session.NewBatch(gocql.UnloggedBatch).WithContext(ctx)

	for _, e := range events {
		batch.Query(`
			INSERT INTO events_by_session (
				session_id, completed_at, facto_id, agent_id,
				action_type, status, event_hash,
				input_data, output_data,
				model_id, temperature,
				sdk_version, sdk_language, tags,
				signature, public_key, prev_hash,
				parent_facto_id, started_at, received_at
			) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		`,
			e.event.SessionID, e.completedTime, e.event.FactoID, e.event.AgentID,
			e.event.ActionType, e.event.Status, e.event.Proof.EventHash,
			e.inputData, e.outputData,
			e.modelID, e.temperature,
			e.sdkVersion, e.sdkLanguage, e.event.ExecutionMeta.Tags,
			[]byte(e.event.Proof.Signature), []byte(e.event.Proof.PublicKey),
			e.event.Proof.PrevHash,
			e.parentFactoID, time.Unix(0, e.event.StartedAt), time.Now(),
		)
	}

	return s.session.ExecuteBatch(batch)
}

// StoreMerkleRoot stores a Merkle root entry
func (s *Storage) StoreMerkleRoot(ctx context.Context, bucketTime time.Time, rootHash string, eventCount int, firstFactoID, lastFactoID string, eventHashes []string) error {
	date := bucketTime.UTC().Truncate(24 * time.Hour)

	err := s.session.Query(`
		INSERT INTO merkle_roots (
			date, bucket_time, root_hash, event_count,
			first_facto_id, last_facto_id, event_hashes, created_at
		) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
	`,
		date, bucketTime, rootHash, eventCount,
		firstFactoID, lastFactoID, eventHashes, time.Now(),
	).WithContext(ctx).Exec()

	if err != nil {
		log.Error().Err(err).Str("root_hash", rootHash).Msg("Failed to store Merkle root")
		return err
	}

	return nil
}

// Close closes the storage connection
func (s *Storage) Close() {
	if s.session != nil {
		s.session.Close()
	}
}
