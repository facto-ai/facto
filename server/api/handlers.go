package main

import (
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"sort"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"golang.org/x/crypto/sha3"
)

var (
	apiRequestsTotal = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "facto_api_requests_total",
		Help: "Total number of API requests",
	}, []string{"endpoint", "status"})

	apiRequestDuration = promauto.NewHistogramVec(prometheus.HistogramOpts{
		Name:    "facto_api_request_duration_seconds",
		Help:    "Duration of API requests in seconds",
		Buckets: []float64{0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5},
	}, []string{"endpoint"})
)

// Handlers contains the API handlers
type Handlers struct {
	storage *Storage
}

// NewHandlers creates a new Handlers instance
func NewHandlers(storage *Storage) *Handlers {
	return &Handlers{storage: storage}
}

// EventsQuery represents query parameters for events listing
type EventsQuery struct {
	AgentID string `form:"agent_id" binding:"required"`
	Start   string `form:"start" binding:"required"`
	End     string `form:"end" binding:"required"`
	Limit   int    `form:"limit"`
	Cursor  string `form:"cursor"`
}

// EventsResponse represents the response for events listing
type EventsResponse struct {
	Events     []EventResponse `json:"events"`
	NextCursor *string         `json:"next_cursor"`
}

// EventResponse represents a single event in API responses
type EventResponse struct {
	FactoID       string                 `json:"facto_id"`
	AgentID       string                 `json:"agent_id"`
	SessionID     string                 `json:"session_id"`
	ParentFactoID *string                `json:"parent_facto_id,omitempty"`
	ActionType    string                 `json:"action_type"`
	Status        string                 `json:"status"`
	InputData     map[string]interface{} `json:"input_data"`
	OutputData    map[string]interface{} `json:"output_data"`
	ExecutionMeta ExecutionMetaResponse  `json:"execution_meta"`
	Proof         ProofResponse          `json:"proof"`
	StartedAt     int64                  `json:"started_at"`
	CompletedAt   int64                  `json:"completed_at"`
}

// ExecutionMetaResponse represents execution metadata in API responses
type ExecutionMetaResponse struct {
	ModelID     *string           `json:"model_id,omitempty"`
	ModelHash   *string           `json:"model_hash,omitempty"`
	Temperature *float64          `json:"temperature,omitempty"`
	Seed        *int64            `json:"seed,omitempty"`
	MaxTokens   *int32            `json:"max_tokens,omitempty"`
	ToolCalls   []interface{}     `json:"tool_calls"`
	SDKVersion  string            `json:"sdk_version"`
	SDKLanguage string            `json:"sdk_language"`
	Tags        map[string]string `json:"tags"`
}

// ProofResponse represents cryptographic proof in API responses
type ProofResponse struct {
	Signature string `json:"signature"`
	PublicKey string `json:"public_key"`
	PrevHash  string `json:"prev_hash"`
	EventHash string `json:"event_hash"`
}

// GetEvents handles GET /v1/events
func (h *Handlers) GetEvents(c *gin.Context) {
	start := time.Now()
	defer func() {
		apiRequestDuration.WithLabelValues("get_events").Observe(time.Since(start).Seconds())
	}()

	var query EventsQuery
	if err := c.ShouldBindQuery(&query); err != nil {
		apiRequestsTotal.WithLabelValues("get_events", "400").Inc()
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	if query.Limit <= 0 || query.Limit > 1000 {
		query.Limit = 100
	}

	startTime, err := time.Parse(time.RFC3339, query.Start)
	if err != nil {
		apiRequestsTotal.WithLabelValues("get_events", "400").Inc()
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid start time format"})
		return
	}

	endTime, err := time.Parse(time.RFC3339, query.End)
	if err != nil {
		apiRequestsTotal.WithLabelValues("get_events", "400").Inc()
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid end time format"})
		return
	}

	events, nextCursor, err := h.storage.GetEvents(c.Request.Context(), query.AgentID, startTime, endTime, query.Limit, query.Cursor)
	if err != nil {
		apiRequestsTotal.WithLabelValues("get_events", "500").Inc()
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to fetch events"})
		return
	}

	apiRequestsTotal.WithLabelValues("get_events", "200").Inc()
	c.JSON(http.StatusOK, EventsResponse{
		Events:     events,
		NextCursor: nextCursor,
	})
}

// GetEventByFactoID handles GET /v1/events/:facto_id
func (h *Handlers) GetEventByFactoID(c *gin.Context) {
	start := time.Now()
	defer func() {
		apiRequestDuration.WithLabelValues("get_event").Observe(time.Since(start).Seconds())
	}()

	factoID := c.Param("facto_id")
	if factoID == "" {
		apiRequestsTotal.WithLabelValues("get_event", "400").Inc()
		c.JSON(http.StatusBadRequest, gin.H{"error": "facto_id is required"})
		return
	}

	event, err := h.storage.GetEventByFactoID(c.Request.Context(), factoID)
	if err != nil {
		apiRequestsTotal.WithLabelValues("get_event", "500").Inc()
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to fetch event"})
		return
	}

	if event == nil {
		apiRequestsTotal.WithLabelValues("get_event", "404").Inc()
		c.JSON(http.StatusNotFound, gin.H{"error": "event not found"})
		return
	}

	apiRequestsTotal.WithLabelValues("get_event", "200").Inc()
	c.JSON(http.StatusOK, event)
}

// SessionEventsQuery represents query parameters for session events
type SessionEventsQuery struct {
	Limit  int    `form:"limit"`
	Cursor string `form:"cursor"`
}

// GetSessionEvents handles GET /v1/sessions/:session_id/events
func (h *Handlers) GetSessionEvents(c *gin.Context) {
	start := time.Now()
	defer func() {
		apiRequestDuration.WithLabelValues("get_session_events").Observe(time.Since(start).Seconds())
	}()

	sessionID := c.Param("session_id")
	if sessionID == "" {
		apiRequestsTotal.WithLabelValues("get_session_events", "400").Inc()
		c.JSON(http.StatusBadRequest, gin.H{"error": "session_id is required"})
		return
	}

	var query SessionEventsQuery
	c.ShouldBindQuery(&query)

	if query.Limit <= 0 || query.Limit > 1000 {
		query.Limit = 100
	}

	events, nextCursor, err := h.storage.GetSessionEvents(c.Request.Context(), sessionID, query.Limit, query.Cursor)
	if err != nil {
		apiRequestsTotal.WithLabelValues("get_session_events", "500").Inc()
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to fetch events"})
		return
	}

	apiRequestsTotal.WithLabelValues("get_session_events", "200").Inc()
	c.JSON(http.StatusOK, EventsResponse{
		Events:     events,
		NextCursor: nextCursor,
	})
}

// VerifyRequest represents a verification request
type VerifyRequest struct {
	Event EventResponse `json:"event" binding:"required"`
}

// VerifyResponse represents a verification response
type VerifyResponse struct {
	Valid  bool        `json:"valid"`
	Checks VerifyCheck `json:"checks"`
}

// VerifyCheck represents individual verification checks
type VerifyCheck struct {
	HashValid      bool  `json:"hash_valid"`
	SignatureValid bool  `json:"signature_valid"`
	ChainValid     *bool `json:"chain_valid"`
}

// VerifyEvent handles POST /v1/verify
func (h *Handlers) VerifyEvent(c *gin.Context) {
	start := time.Now()
	defer func() {
		apiRequestDuration.WithLabelValues("verify").Observe(time.Since(start).Seconds())
	}()

	var req VerifyRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		apiRequestsTotal.WithLabelValues("verify", "400").Inc()
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	// Verify hash
	hashValid := verifyHash(&req.Event)

	// Verify signature
	signatureValid := verifySignature(&req.Event)

	response := VerifyResponse{
		Valid: hashValid && signatureValid,
		Checks: VerifyCheck{
			HashValid:      hashValid,
			SignatureValid: signatureValid,
			ChainValid:     nil, // Would need previous event to verify chain
		},
	}

	apiRequestsTotal.WithLabelValues("verify", "200").Inc()
	c.JSON(http.StatusOK, response)
}

// ChainVerifyQuery represents query parameters for chain verification
type ChainVerifyQuery struct {
	SessionID string `form:"session_id" binding:"required"`
}

// ChainVerifyResponse represents the chain verification result
type ChainVerifyResponse struct {
	Valid       bool              `json:"valid"`
	EventCount  int               `json:"event_count"`
	Checks      ChainVerifyChecks `json:"checks"`
	FirstEvent  string            `json:"first_event,omitempty"`
	LastEvent   string            `json:"last_event,omitempty"`
	SessionHash string            `json:"session_hash,omitempty"`
	Errors      []string          `json:"errors,omitempty"`
}

// ChainVerifyChecks represents individual chain verification checks
type ChainVerifyChecks struct {
	AllHashesValid      bool `json:"all_hashes_valid"`
	AllSignaturesValid  bool `json:"all_signatures_valid"`
	ChainIntegrityValid bool `json:"chain_integrity_valid"`
}

// VerifyChain handles GET /v1/verify/chain
func (h *Handlers) VerifyChain(c *gin.Context) {
	start := time.Now()
	defer func() {
		apiRequestDuration.WithLabelValues("verify_chain").Observe(time.Since(start).Seconds())
	}()

	var query ChainVerifyQuery
	if err := c.ShouldBindQuery(&query); err != nil {
		apiRequestsTotal.WithLabelValues("verify_chain", "400").Inc()
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	// Get all events for the session
	events, _, err := h.storage.GetSessionEvents(c.Request.Context(), query.SessionID, 10000, "")
	if err != nil {
		apiRequestsTotal.WithLabelValues("verify_chain", "500").Inc()
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to fetch events"})
		return
	}

	if len(events) == 0 {
		apiRequestsTotal.WithLabelValues("verify_chain", "404").Inc()
		c.JSON(http.StatusNotFound, gin.H{"error": "no events found for session"})
		return
	}

	// Sort events by completed_at (oldest first for chain verification)
	sort.Slice(events, func(i, j int) bool {
		return events[i].CompletedAt < events[j].CompletedAt
	})

	response := ChainVerifyResponse{
		EventCount: len(events),
		FirstEvent: events[0].FactoID,
		LastEvent:  events[len(events)-1].FactoID,
		Checks: ChainVerifyChecks{
			AllHashesValid:      true,
			AllSignaturesValid:  true,
			ChainIntegrityValid: true,
		},
		Errors: []string{},
	}

	// Verify all hashes
	for _, event := range events {
		if !verifyHash(&event) {
			response.Checks.AllHashesValid = false
			response.Errors = append(response.Errors, "Hash invalid for event: "+event.FactoID)
		}
	}

	// Verify all signatures
	for _, event := range events {
		if !verifySignature(&event) {
			response.Checks.AllSignaturesValid = false
			response.Errors = append(response.Errors, "Signature invalid for event: "+event.FactoID)
		}
	}

	// Verify chain integrity (prev_hash links)
	expectedPrevHash := "0000000000000000000000000000000000000000000000000000000000000000"
	for _, event := range events {
		if event.Proof.PrevHash != expectedPrevHash {
			response.Checks.ChainIntegrityValid = false
			response.Errors = append(response.Errors,
				"Chain broken at event: "+event.FactoID+
					" (expected prev_hash: "+expectedPrevHash[:16]+"..., got: "+event.Proof.PrevHash[:16]+"...)")
		}
		expectedPrevHash = event.Proof.EventHash
	}

	// Compute session hash (hash of all event hashes concatenated)
	var hashConcat string
	for _, event := range events {
		hashConcat += event.Proof.EventHash
	}
	sessionHashBytes := sha256.Sum256([]byte(hashConcat))
	response.SessionHash = hex.EncodeToString(sessionHashBytes[:])

	// Overall validity
	response.Valid = response.Checks.AllHashesValid &&
		response.Checks.AllSignaturesValid &&
		response.Checks.ChainIntegrityValid

	apiRequestsTotal.WithLabelValues("verify_chain", "200").Inc()
	c.JSON(http.StatusOK, response)
}

// EvidencePackageQuery represents query parameters for evidence package
type EvidencePackageQuery struct {
	SessionID string `form:"session_id" binding:"required"`
}

// EvidencePackageResponse represents an evidence package
type EvidencePackageResponse struct {
	PackageID                string          `json:"package_id"`
	SessionID                string          `json:"session_id"`
	Events                   []EventResponse `json:"events"`
	MerkleProofs             []MerkleProof   `json:"merkle_proofs"`
	ExportedAt               string          `json:"exported_at"`
	VerificationInstructions string          `json:"verification_instructions"`
}

// MerkleProof represents a Merkle proof for an event
type MerkleProof struct {
	FactoID   string         `json:"facto_id"`
	EventHash string         `json:"event_hash"`
	Proof     []ProofElement `json:"proof"`
	Root      string         `json:"root"`
}

// ProofElement represents an element in a Merkle proof
type ProofElement struct {
	Hash     string `json:"hash"`
	Position string `json:"position"`
}

// GetEvidencePackage handles GET /v1/evidence-package
func (h *Handlers) GetEvidencePackage(c *gin.Context) {
	start := time.Now()
	defer func() {
		apiRequestDuration.WithLabelValues("evidence_package").Observe(time.Since(start).Seconds())
	}()

	var query EvidencePackageQuery
	if err := c.ShouldBindQuery(&query); err != nil {
		apiRequestsTotal.WithLabelValues("evidence_package", "400").Inc()
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	// Get all events for the session
	events, _, err := h.storage.GetSessionEvents(c.Request.Context(), query.SessionID, 10000, "")
	if err != nil {
		apiRequestsTotal.WithLabelValues("evidence_package", "500").Inc()
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to fetch events"})
		return
	}

	if len(events) == 0 {
		apiRequestsTotal.WithLabelValues("evidence_package", "404").Inc()
		c.JSON(http.StatusNotFound, gin.H{"error": "no events found for session"})
		return
	}

	// Build Merkle tree and proofs
	hashes := make([]string, len(events))
	for i, e := range events {
		hashes[i] = e.Proof.EventHash
	}

	tree := buildMerkleTree(hashes)
	merkleRoot := tree.root

	proofs := make([]MerkleProof, len(events))
	for i, e := range events {
		proofs[i] = MerkleProof{
			FactoID:   e.FactoID,
			EventHash: e.Proof.EventHash,
			Proof:     tree.getProof(i),
			Root:      merkleRoot,
		}
	}

	// Generate package ID
	packageHash := sha256.Sum256([]byte(query.SessionID + time.Now().String()))
	packageID := "ev-" + hex.EncodeToString(packageHash[:8])

	response := EvidencePackageResponse{
		PackageID:    packageID,
		SessionID:    query.SessionID,
		Events:       events,
		MerkleProofs: proofs,
		ExportedAt:   time.Now().UTC().Format(time.RFC3339),
		VerificationInstructions: `To verify this evidence package:

1. For each event:
   a. Reconstruct the canonical JSON form (sorted keys, no whitespace)
   b. Compute SHA3-256 hash and compare with event_hash
   c. Verify Ed25519 signature using the public_key
   d. Verify prev_hash links to previous event's event_hash

2. Verify the Merkle proofs:
   a. For each event, use the proof to compute the root
   b. All computed roots should match the package Merkle root

3. The chain of events is tamper-evident:
   - Any modification would break the hash chain
   - Any modification would invalidate the signature
   - Any modification would invalidate the Merkle proof`,
	}

	apiRequestsTotal.WithLabelValues("evidence_package", "200").Inc()
	c.JSON(http.StatusOK, response)
}

// Helper functions for verification

func verifyHash(event *EventResponse) bool {
	canonical := buildCanonicalForm(event)
	hash := sha3.Sum256([]byte(canonical))
	computedHash := hex.EncodeToString(hash[:])

	return computedHash == event.Proof.EventHash
}

func verifySignature(event *EventResponse) bool {
	// Decode public key
	pubKeyBytes, err := base64.StdEncoding.DecodeString(event.Proof.PublicKey)
	if err != nil || len(pubKeyBytes) != ed25519.PublicKeySize {
		return false
	}

	// Decode signature
	sigBytes, err := base64.StdEncoding.DecodeString(event.Proof.Signature)
	if err != nil || len(sigBytes) != ed25519.SignatureSize {
		return false
	}

	// Build canonical form and verify
	canonical := buildCanonicalForm(event)
	return ed25519.Verify(pubKeyBytes, []byte(canonical), sigBytes)
}

func buildCanonicalForm(event *EventResponse) string {
	// Build a map with sorted keys
	canonical := make(map[string]interface{})

	canonical["action_type"] = event.ActionType
	canonical["agent_id"] = event.AgentID
	canonical["completed_at"] = event.CompletedAt

	// Build execution_meta
	execMeta := make(map[string]interface{})
	if event.ExecutionMeta.ModelID != nil {
		execMeta["model_id"] = *event.ExecutionMeta.ModelID
	}
	execMeta["seed"] = event.ExecutionMeta.Seed
	execMeta["sdk_version"] = event.ExecutionMeta.SDKVersion
	if event.ExecutionMeta.Temperature != nil {
		execMeta["temperature"] = *event.ExecutionMeta.Temperature
	}
	execMeta["tool_calls"] = event.ExecutionMeta.ToolCalls
	canonical["execution_meta"] = execMeta

	canonical["input_data"] = event.InputData
	canonical["output_data"] = event.OutputData
	canonical["parent_facto_id"] = event.ParentFactoID
	canonical["prev_hash"] = event.Proof.PrevHash
	canonical["session_id"] = event.SessionID
	canonical["started_at"] = event.StartedAt
	canonical["status"] = event.Status
	canonical["facto_id"] = event.FactoID

	// Serialize with sorted keys
	bytes, _ := json.Marshal(sortedMap(canonical))
	return string(bytes)
}

func sortedMap(m map[string]interface{}) map[string]interface{} {
	// Get sorted keys
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)

	// Build new map (Go 1.12+ preserves insertion order for JSON marshal)
	result := make(map[string]interface{}, len(m))
	for _, k := range keys {
		v := m[k]
		if nested, ok := v.(map[string]interface{}); ok {
			result[k] = sortedMap(nested)
		} else {
			result[k] = v
		}
	}
	return result
}

// Merkle tree helpers for evidence package

type merkleTree struct {
	root   string
	leaves []string
	levels [][]string
}

func buildMerkleTree(hashes []string) *merkleTree {
	if len(hashes) == 0 {
		return &merkleTree{root: ""}
	}

	tree := &merkleTree{
		leaves: hashes,
		levels: [][]string{hashes},
	}

	current := hashes
	for len(current) > 1 {
		// If odd, duplicate last
		if len(current)%2 != 0 {
			current = append(current, current[len(current)-1])
		}

		var next []string
		for i := 0; i < len(current); i += 2 {
			combined := hashPair(current[i], current[i+1])
			next = append(next, combined)
		}
		tree.levels = append(tree.levels, next)
		current = next
	}

	tree.root = current[0]
	return tree
}

func hashPair(left, right string) string {
	leftBytes, _ := hex.DecodeString(left)
	rightBytes, _ := hex.DecodeString(right)
	combined := append(leftBytes, rightBytes...)
	hash := sha256.Sum256(combined)
	return hex.EncodeToString(hash[:])
}

func (t *merkleTree) getProof(index int) []ProofElement {
	if index < 0 || index >= len(t.leaves) {
		return nil
	}

	var proof []ProofElement
	idx := index

	for level := 0; level < len(t.levels)-1; level++ {
		levelNodes := t.levels[level]

		// If odd number of nodes, duplicate last
		if len(levelNodes)%2 != 0 {
			levelNodes = append(levelNodes, levelNodes[len(levelNodes)-1])
		}

		var siblingIdx int
		var position string

		if idx%2 == 0 {
			siblingIdx = idx + 1
			position = "right"
		} else {
			siblingIdx = idx - 1
			position = "left"
		}

		if siblingIdx < len(levelNodes) {
			proof = append(proof, ProofElement{
				Hash:     levelNodes[siblingIdx],
				Position: position,
			})
		}

		idx = idx / 2
	}

	return proof
}
