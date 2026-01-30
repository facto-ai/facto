package main

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"time"

	"github.com/gocql/gocql"
	"github.com/rs/zerolog/log"
)

// Storage handles ScyllaDB operations for the Query API
type Storage struct {
	session *gocql.Session
}

// NewStorage creates a new storage instance
func NewStorage(hosts []string) (*Storage, error) {
	cluster := gocql.NewCluster(hosts...)
	cluster.Keyspace = "facto"
	cluster.Consistency = gocql.LocalOne // Use LocalOne for reads for lower latency
	cluster.Timeout = 10 * time.Second
	cluster.ConnectTimeout = 30 * time.Second
	cluster.RetryPolicy = &gocql.ExponentialBackoffRetryPolicy{
		Min:        100 * time.Millisecond,
		Max:        10 * time.Second,
		NumRetries: 3,
	}

	session, err := cluster.CreateSession()
	if err != nil {
		return nil, err
	}

	return &Storage{session: session}, nil
}

// GetEvents retrieves events for an agent within a time range
func (s *Storage) GetEvents(ctx context.Context, agentID string, start, end time.Time, limit int, cursor string) ([]EventResponse, *string, error) {
	var events []EventResponse

	// Calculate the dates to query (partition keys)
	dates := getDateRange(start, end)

	for _, date := range dates {
		query := s.session.Query(`
			SELECT facto_id, agent_id, session_id, parent_facto_id,
			       action_type, status, input_data, output_data,
			       model_id, model_hash, temperature, seed, max_tokens, tool_calls,
			       sdk_version, sdk_language, tags,
			       signature, public_key, prev_hash, event_hash,
			       started_at, completed_at
			FROM events
			WHERE agent_id = ? AND date = ?
			  AND completed_at >= ? AND completed_at <= ?
			LIMIT ?
		`, agentID, date, start, end, limit+1).WithContext(ctx)

		iter := query.Iter()

		var (
			factoID, sessionID, parentFactoID string
			actionType, status                string
			inputData, outputData             []byte
			modelID, modelHash                string
			temperature                       float64
			seed                              int64
			maxTokens                         int32
			toolCalls                         string
			sdkVersion, sdkLanguage           string
			tags                              map[string]string
			signature, publicKey              []byte
			prevHash, eventHash               string
			startedAt, completedAt            time.Time
		)

		for iter.Scan(
			&factoID, &agentID, &sessionID, &parentFactoID,
			&actionType, &status, &inputData, &outputData,
			&modelID, &modelHash, &temperature, &seed, &maxTokens, &toolCalls,
			&sdkVersion, &sdkLanguage, &tags,
			&signature, &publicKey, &prevHash, &eventHash,
			&startedAt, &completedAt,
		) {
			event := buildEventResponse(
				factoID, agentID, sessionID, parentFactoID,
				actionType, status, inputData, outputData,
				modelID, modelHash, temperature, seed, maxTokens, toolCalls,
				sdkVersion, sdkLanguage, tags,
				signature, publicKey, prevHash, eventHash,
				startedAt, completedAt,
			)
			events = append(events, event)

			if len(events) >= limit {
				break
			}
		}

		if err := iter.Close(); err != nil {
			log.Error().Err(err).Msg("Error iterating events")
			return nil, nil, err
		}

		if len(events) >= limit {
			break
		}
	}

	// Handle pagination
	var nextCursor *string
	if len(events) > limit {
		events = events[:limit]
		lastEvent := events[len(events)-1]
		cursor := base64.StdEncoding.EncodeToString([]byte(lastEvent.FactoID))
		nextCursor = &cursor
	}

	return events, nextCursor, nil
}

// GetEventByFactoID retrieves a single event by facto_id
func (s *Storage) GetEventByFactoID(ctx context.Context, factoID string) (*EventResponse, error) {
	query := s.session.Query(`
		SELECT facto_id, agent_id, date, completed_at, session_id,
		       action_type, status, input_data, output_data,
		       model_id, model_hash, temperature, seed, max_tokens, tool_calls,
		       sdk_version, sdk_language, tags,
		       signature, public_key, prev_hash, event_hash,
		       parent_facto_id, started_at
		FROM events_by_facto_id
		WHERE facto_id = ?
	`, factoID).WithContext(ctx)

	var (
		agentID, sessionID, parentFactoID string
		date                              time.Time
		completedAt, startedAt            time.Time
		actionType, status                string
		inputData, outputData             []byte
		modelID, modelHash                string
		temperature                       float64
		seed                              int64
		maxTokens                         int32
		toolCalls                         string
		sdkVersion, sdkLanguage           string
		tags                              map[string]string
		signature, publicKey              []byte
		prevHash, eventHash               string
	)

	if err := query.Scan(
		&factoID, &agentID, &date, &completedAt, &sessionID,
		&actionType, &status, &inputData, &outputData,
		&modelID, &modelHash, &temperature, &seed, &maxTokens, &toolCalls,
		&sdkVersion, &sdkLanguage, &tags,
		&signature, &publicKey, &prevHash, &eventHash,
		&parentFactoID, &startedAt,
	); err != nil {
		if err == gocql.ErrNotFound {
			return nil, nil
		}
		return nil, err
	}

	event := buildEventResponse(
		factoID, agentID, sessionID, parentFactoID,
		actionType, status, inputData, outputData,
		modelID, modelHash, temperature, seed, maxTokens, toolCalls,
		sdkVersion, sdkLanguage, tags,
		signature, publicKey, prevHash, eventHash,
		startedAt, completedAt,
	)

	return &event, nil
}

// GetSessionEvents retrieves all events for a session
func (s *Storage) GetSessionEvents(ctx context.Context, sessionID string, limit int, cursor string) ([]EventResponse, *string, error) {
	var events []EventResponse

	query := s.session.Query(`
		SELECT session_id, completed_at, facto_id, agent_id,
		       action_type, status, event_hash,
		       input_data, output_data,
		       model_id, temperature,
		       sdk_version, sdk_language, tags,
		       signature, public_key, prev_hash,
		       parent_facto_id, started_at
		FROM events_by_session
		WHERE session_id = ?
		LIMIT ?
	`, sessionID, limit+1).WithContext(ctx)

	iter := query.Iter()

	var (
		factoID, agentID, parentFactoID string
		completedAt, startedAt          time.Time
		actionType, status              string
		eventHash                       string
		inputData, outputData           []byte
		modelID                         string
		temperature                     float64
		sdkVersion, sdkLanguage         string
		tags                            map[string]string
		signature, publicKey            []byte
		prevHash                        string
	)

	for iter.Scan(
		&sessionID, &completedAt, &factoID, &agentID,
		&actionType, &status, &eventHash,
		&inputData, &outputData,
		&modelID, &temperature,
		&sdkVersion, &sdkLanguage, &tags,
		&signature, &publicKey, &prevHash,
		&parentFactoID, &startedAt,
	) {
		event := buildEventResponse(
			factoID, agentID, sessionID, parentFactoID,
			actionType, status, inputData, outputData,
			modelID, "", temperature, 0, 0, "[]",
			sdkVersion, sdkLanguage, tags,
			signature, publicKey, prevHash, eventHash,
			startedAt, completedAt,
		)
		events = append(events, event)

		if len(events) > limit {
			break
		}
	}

	if err := iter.Close(); err != nil {
		log.Error().Err(err).Msg("Error iterating session events")
		return nil, nil, err
	}

	// Handle pagination
	var nextCursor *string
	if len(events) > limit {
		events = events[:limit]
		lastEvent := events[len(events)-1]
		cursor := base64.StdEncoding.EncodeToString([]byte(lastEvent.FactoID))
		nextCursor = &cursor
	}

	return events, nextCursor, nil
}

// Close closes the storage connection
func (s *Storage) Close() {
	if s.session != nil {
		s.session.Close()
	}
}

// Helper functions

func getDateRange(start, end time.Time) []time.Time {
	var dates []time.Time

	current := start.UTC().Truncate(24 * time.Hour)
	endDate := end.UTC().Truncate(24 * time.Hour)

	for !current.After(endDate) {
		dates = append(dates, current)
		current = current.Add(24 * time.Hour)
	}

	return dates
}

func buildEventResponse(
	factoID, agentID, sessionID, parentFactoID string,
	actionType, status string,
	inputData, outputData []byte,
	modelID, modelHash string,
	temperature float64,
	seed int64,
	maxTokens int32,
	toolCalls string,
	sdkVersion, sdkLanguage string,
	tags map[string]string,
	signature, publicKey []byte,
	prevHash, eventHash string,
	startedAt, completedAt time.Time,
) EventResponse {
	// Parse input/output data
	var input, output map[string]interface{}
	json.Unmarshal(inputData, &input)
	json.Unmarshal(outputData, &output)

	// Parse tool calls
	var tools []interface{}
	json.Unmarshal([]byte(toolCalls), &tools)

	// Build execution meta
	var modelIDPtr *string
	if modelID != "" {
		modelIDPtr = &modelID
	}

	var modelHashPtr *string
	if modelHash != "" {
		modelHashPtr = &modelHash
	}

	var tempPtr *float64
	if temperature != 0 {
		tempPtr = &temperature
	}

	var seedPtr *int64
	if seed != 0 {
		seedPtr = &seed
	}

	var maxTokensPtr *int32
	if maxTokens != 0 {
		maxTokensPtr = &maxTokens
	}

	var parentPtr *string
	if parentFactoID != "" {
		parentPtr = &parentFactoID
	}

	if tags == nil {
		tags = make(map[string]string)
	}

	if tools == nil {
		tools = []interface{}{}
	}

	if input == nil {
		input = make(map[string]interface{})
	}

	if output == nil {
		output = make(map[string]interface{})
	}

	return EventResponse{
		FactoID:       factoID,
		AgentID:       agentID,
		SessionID:     sessionID,
		ParentFactoID: parentPtr,
		ActionType:    actionType,
		Status:        status,
		InputData:     input,
		OutputData:    output,
		ExecutionMeta: ExecutionMetaResponse{
			ModelID:     modelIDPtr,
			ModelHash:   modelHashPtr,
			Temperature: tempPtr,
			Seed:        seedPtr,
			MaxTokens:   maxTokensPtr,
			ToolCalls:   tools,
			SDKVersion:  sdkVersion,
			SDKLanguage: sdkLanguage,
			Tags:        tags,
		},
		Proof: ProofResponse{
			Signature: string(signature), // Stored as base64 bytes, no need to re-encode
			PublicKey: string(publicKey), // Stored as base64 bytes, no need to re-encode
			PrevHash:  prevHash,
			EventHash: eventHash,
		},
		StartedAt:   startedAt.UnixNano(),
		CompletedAt: completedAt.UnixNano(),
	}
}
