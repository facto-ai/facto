use axum::{
    extract::{Json, State},
    http::StatusCode,
    response::IntoResponse,
    routing::{get, post},
    Router,
};
use base64::{engine::general_purpose::STANDARD as BASE64, Engine};
use dashmap::DashMap;
use ed25519_dalek::{Signature, VerifyingKey};
use governor::{Quota, RateLimiter};
use metrics::{counter, gauge, histogram};
use metrics_exporter_prometheus::PrometheusBuilder;
use nonzero_ext::nonzero;
use serde::{Deserialize, Serialize};
use sha3::{Digest, Sha3_256};
use std::{
    collections::BTreeMap,
    net::SocketAddr,
    num::NonZeroU32,
    sync::Arc,
    time::Instant,
};
use tokio::sync::RwLock;
use tower_http::{
    compression::CompressionLayer,
    cors::{Any, CorsLayer},
    trace::TraceLayer,
};
use tracing::{error, info, warn};

// ============================================================================
// Data Models
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FactoEvent {
    pub facto_id: String,
    pub agent_id: String,
    pub session_id: String,
    pub parent_facto_id: Option<String>,

    pub action_type: String,
    pub status: String,

    pub input_data: serde_json::Value,
    pub output_data: serde_json::Value,

    pub execution_meta: ExecutionMeta,
    pub proof: Proof,

    pub started_at: i64,
    pub completed_at: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecutionMeta {
    pub model_id: Option<String>,
    pub model_hash: Option<String>,
    pub temperature: Option<f64>,
    pub seed: Option<i64>,
    pub max_tokens: Option<i32>,
    pub tool_calls: Vec<serde_json::Value>,
    pub sdk_version: String,
    pub sdk_language: String,
    pub tags: BTreeMap<String, String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Proof {
    pub signature: String,
    pub public_key: String,
    pub prev_hash: String,
    pub event_hash: String,
}

#[derive(Debug, Deserialize)]
pub struct BatchIngestRequest {
    pub events: Vec<FactoEvent>,
    pub batch_id: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct BatchIngestResponse {
    pub accepted_count: usize,
    pub rejected_count: usize,
    pub rejected: Vec<RejectedEvent>,
}

#[derive(Debug, Serialize)]
pub struct RejectedEvent {
    pub facto_id: String,
    pub reason: String,
}

#[derive(Debug, Serialize)]
pub struct SingleIngestResponse {
    pub accepted: bool,
    pub facto_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct HealthResponse {
    pub status: String,
    pub version: String,
}

#[derive(Debug, Serialize)]
pub struct ReadyResponse {
    pub ready: bool,
    pub nats_connected: bool,
}

// ============================================================================
// Application State
// ============================================================================

type AgentRateLimiter = RateLimiter<
    String,
    DashMap<String, governor::state::InMemoryState>,
    governor::clock::DefaultClock,
    governor::middleware::NoOpMiddleware,
>;

pub struct AppState {
    nats_client: RwLock<Option<async_nats::Client>>,
    rate_limiter: AgentRateLimiter,
    rate_limit_per_agent: NonZeroU32,
}

impl AppState {
    fn new(rate_limit_per_agent: u32) -> Self {
        let rate_limit = NonZeroU32::new(rate_limit_per_agent).unwrap_or(nonzero!(10000u32));
        let quota = Quota::per_second(rate_limit);
        let rate_limiter = RateLimiter::dashmap(quota);

        Self {
            nats_client: RwLock::new(None),
            rate_limiter,
            rate_limit_per_agent: rate_limit,
        }
    }

    async fn is_nats_connected(&self) -> bool {
        let client = self.nats_client.read().await;
        client.is_some()
    }

    async fn check_rate_limit(&self, agent_id: &str) -> bool {
        self.rate_limiter
            .check_key(&agent_id.to_string())
            .is_ok()
    }
}

// ============================================================================
// Cryptographic Verification
// ============================================================================

/// Build the canonical form of an event for hashing/signing
/// The canonical form has sorted keys and no extra whitespace
fn build_canonical_form(event: &FactoEvent) -> Result<String, String> {
    // Build a sorted map with the fields that should be included in the hash
    let mut canonical = serde_json::Map::new();

    canonical.insert("action_type".to_string(), serde_json::json!(event.action_type));
    canonical.insert("agent_id".to_string(), serde_json::json!(event.agent_id));
    canonical.insert("completed_at".to_string(), serde_json::json!(event.completed_at));

    // Build execution_meta in sorted order
    // Build execution_meta in sorted order
    let mut exec_meta = serde_json::Map::new();
    if let Some(ref model_id) = event.execution_meta.model_id {
        exec_meta.insert("model_id".to_string(), serde_json::json!(model_id));
    }
    exec_meta.insert("sdk_version".to_string(), serde_json::json!(event.execution_meta.sdk_version));
    exec_meta.insert("seed".to_string(), serde_json::json!(event.execution_meta.seed));
    if let Some(temp) = event.execution_meta.temperature {
        exec_meta.insert("temperature".to_string(), serde_json::json!(temp));
    }
    exec_meta.insert("tool_calls".to_string(), serde_json::json!(event.execution_meta.tool_calls));
    canonical.insert("execution_meta".to_string(), serde_json::Value::Object(exec_meta));

    canonical.insert("input_data".to_string(), event.input_data.clone());
    canonical.insert("output_data".to_string(), event.output_data.clone());
    canonical.insert("parent_facto_id".to_string(), serde_json::json!(event.parent_facto_id));
    canonical.insert("prev_hash".to_string(), serde_json::json!(event.proof.prev_hash));
    canonical.insert("session_id".to_string(), serde_json::json!(event.session_id));
    canonical.insert("started_at".to_string(), serde_json::json!(event.started_at));
    canonical.insert("status".to_string(), serde_json::json!(event.status));
    canonical.insert("facto_id".to_string(), serde_json::json!(event.facto_id));

    // Serialize to JSON with sorted keys (serde_json::Map maintains insertion order,
    // and we inserted in sorted order)
    serde_json::to_string(&serde_json::Value::Object(canonical))
        .map_err(|e| format!("Failed to serialize canonical form: {}", e))
}

/// Compute SHA3-256 hash of the canonical form
fn compute_event_hash(canonical: &str) -> String {
    let mut hasher = Sha3_256::new();
    hasher.update(canonical.as_bytes());
    let result = hasher.finalize();
    hex::encode(result)
}

/// Verify the event hash matches the expected hash
fn verify_hash(event: &FactoEvent) -> Result<(), String> {
    let canonical = build_canonical_form(event)?;
    let computed_hash = compute_event_hash(&canonical);

    if computed_hash != event.proof.event_hash {
        return Err(format!(
            "Hash mismatch: computed={}, provided={}",
            computed_hash, event.proof.event_hash
        ));
    }

    Ok(())
}

/// Verify the Ed25519 signature
fn verify_signature(event: &FactoEvent) -> Result<(), String> {
    // Decode the public key from base64
    let public_key_bytes = BASE64
        .decode(&event.proof.public_key)
        .map_err(|e| format!("Invalid public key encoding: {}", e))?;

    if public_key_bytes.len() != 32 {
        return Err(format!(
            "Invalid public key length: expected 32, got {}",
            public_key_bytes.len()
        ));
    }

    let public_key_array: [u8; 32] = public_key_bytes
        .try_into()
        .map_err(|_| "Failed to convert public key to array")?;

    let verifying_key = VerifyingKey::from_bytes(&public_key_array)
        .map_err(|e| format!("Invalid public key: {}", e))?;

    // Decode the signature from base64
    let signature_bytes = BASE64
        .decode(&event.proof.signature)
        .map_err(|e| format!("Invalid signature encoding: {}", e))?;

    if signature_bytes.len() != 64 {
        return Err(format!(
            "Invalid signature length: expected 64, got {}",
            signature_bytes.len()
        ));
    }

    let signature_array: [u8; 64] = signature_bytes
        .try_into()
        .map_err(|_| "Failed to convert signature to array")?;

    let signature = Signature::from_bytes(&signature_array);

    // Build the canonical form and verify the signature
    let canonical = build_canonical_form(event)?;

    verifying_key
        .verify_strict(canonical.as_bytes(), &signature)
        .map_err(|e| format!("Signature verification failed: {}", e))?;

    Ok(())
}

/// Validate a single event
fn validate_event(event: &FactoEvent) -> Result<(), String> {
    // Check required fields
    if event.facto_id.is_empty() {
        return Err("Missing facto_id".to_string());
    }
    if event.agent_id.is_empty() {
        return Err("Missing agent_id".to_string());
    }
    if event.session_id.is_empty() {
        return Err("Missing session_id".to_string());
    }
    if event.action_type.is_empty() {
        return Err("Missing action_type".to_string());
    }
    if event.status.is_empty() {
        return Err("Missing status".to_string());
    }
    if event.proof.event_hash.is_empty() {
        return Err("Missing event_hash".to_string());
    }
    if event.proof.signature.is_empty() {
        return Err("Missing signature".to_string());
    }
    if event.proof.public_key.is_empty() {
        return Err("Missing public_key".to_string());
    }

    // Verify hash
    verify_hash(event)?;

    // Verify signature
    verify_signature(event)?;

    Ok(())
}

// ============================================================================
// HTTP Handlers
// ============================================================================

async fn health_handler() -> impl IntoResponse {
    Json(HealthResponse {
        status: "healthy".to_string(),
        version: env!("CARGO_PKG_VERSION").to_string(),
    })
}

async fn ready_handler(State(state): State<Arc<AppState>>) -> impl IntoResponse {
    let nats_connected = state.is_nats_connected().await;

    let status = if nats_connected {
        StatusCode::OK
    } else {
        StatusCode::SERVICE_UNAVAILABLE
    };

    (
        status,
        Json(ReadyResponse {
            ready: nats_connected,
            nats_connected,
        }),
    )
}

async fn metrics_handler() -> impl IntoResponse {
    match metrics_exporter_prometheus::PrometheusBuilder::new()
        .build_recorder()
        .handle()
        .render()
    {
        rendered => (StatusCode::OK, rendered),
    }
}

async fn ingest_single_handler(
    State(state): State<Arc<AppState>>,
    Json(event): Json<FactoEvent>,
) -> impl IntoResponse {
    let start = Instant::now();
    counter!("facto_ingest_requests_total", "type" => "single").increment(1);

    // Check rate limit
    if !state.check_rate_limit(&event.agent_id).await {
        counter!("facto_ingest_rejected_total", "reason" => "rate_limit").increment(1);
        return (
            StatusCode::TOO_MANY_REQUESTS,
            Json(SingleIngestResponse {
                accepted: false,
                facto_id: event.facto_id,
                reason: Some("Rate limit exceeded".to_string()),
            }),
        );
    }

    // Validate event
    if let Err(reason) = validate_event(&event) {
        counter!("facto_ingest_rejected_total", "reason" => "validation").increment(1);
        return (
            StatusCode::BAD_REQUEST,
            Json(SingleIngestResponse {
                accepted: false,
                facto_id: event.facto_id,
                reason: Some(reason),
            }),
        );
    }

    // Publish to NATS
    let nats_client = state.nats_client.read().await;
    if let Some(ref client) = *nats_client {
        let subject = format!("facto.events.{}", event.agent_id);
        let payload = serde_json::to_vec(&event).unwrap();


        if let Err(e) = client.publish(subject, payload.into()).await {
            error!("Failed to publish to NATS: {}", e);
            counter!("facto_ingest_rejected_total", "reason" => "nats_error").increment(1);
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(SingleIngestResponse {
                    accepted: false,
                    facto_id: event.facto_id,
                    reason: Some("Failed to queue event".to_string()),
                }),
            );
        }
    } else {
        counter!("facto_ingest_rejected_total", "reason" => "nats_disconnected").increment(1);
        return (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(SingleIngestResponse {
                accepted: false,
                facto_id: event.facto_id,
                reason: Some("Service not ready".to_string()),
            }),
        );
    }

    counter!("facto_ingest_accepted_total").increment(1);
    histogram!("facto_ingest_duration_seconds").record(start.elapsed().as_secs_f64());

    (
        StatusCode::ACCEPTED,
        Json(SingleIngestResponse {
            accepted: true,
            facto_id: event.facto_id,
            reason: None,
        }),
    )
}

async fn ingest_batch_handler(
    State(state): State<Arc<AppState>>,
    Json(request): Json<BatchIngestRequest>,
) -> impl IntoResponse {
    let start = Instant::now();
    let total_events = request.events.len();
    counter!("facto_ingest_requests_total", "type" => "batch").increment(1);
    counter!("facto_ingest_events_received_total").increment(total_events as u64);

    let mut accepted_count = 0;
    let mut rejected: Vec<RejectedEvent> = Vec::new();
    let mut accepted_events: Vec<FactoEvent> = Vec::new();

    // Validate all events first
    for event in request.events {
        // Check rate limit
        if !state.check_rate_limit(&event.agent_id).await {
            rejected.push(RejectedEvent {
                facto_id: event.facto_id,
                reason: "Rate limit exceeded".to_string(),
            });
            continue;
        }

        // Validate event
        match validate_event(&event) {
            Ok(()) => {
                accepted_events.push(event);
            }
            Err(reason) => {
                rejected.push(RejectedEvent {
                    facto_id: event.facto_id,
                    reason,
                });
            }
        }
    }

    // Publish accepted events to NATS
    let nats_client = state.nats_client.read().await;
    if let Some(ref client) = *nats_client {
        for event in accepted_events {
            let subject = format!("facto.events.{}", event.agent_id);
            let payload = serde_json::to_vec(&event).unwrap();

            match client.publish(subject, payload.into()).await {
                Ok(()) => {
                    accepted_count += 1;
                }
                Err(e) => {
                    error!("Failed to publish to NATS: {}", e);
                    rejected.push(RejectedEvent {
                        facto_id: event.facto_id,
                        reason: "Failed to queue event".to_string(),
                    });
                }
            }
        }
    } else {
        // NATS not connected, reject all
        for event in accepted_events {
            rejected.push(RejectedEvent {
                facto_id: event.facto_id,
                reason: "Service not ready".to_string(),
            });
        }
    }

    let rejected_count = rejected.len();

    counter!("facto_ingest_accepted_total").increment(accepted_count as u64);
    counter!("facto_ingest_rejected_total", "reason" => "various").increment(rejected_count as u64);
    histogram!("facto_ingest_duration_seconds").record(start.elapsed().as_secs_f64());
    histogram!("facto_ingest_batch_size").record(total_events as f64);

    (
        StatusCode::ACCEPTED,
        Json(BatchIngestResponse {
            accepted_count,
            rejected_count,
            rejected,
        }),
    )
}

// ============================================================================
// NATS Connection
// ============================================================================

async fn connect_to_nats(state: Arc<AppState>, nats_url: &str) {
    loop {
        info!("Connecting to NATS at {}", nats_url);

        match async_nats::connect(nats_url).await {
            Ok(client) => {
                info!("Connected to NATS successfully");

                // Create JetStream context and ensure stream exists
                let jetstream = async_nats::jetstream::new(client.clone());

                // Create or update the FACTO_EVENTS stream
                match jetstream
                    .get_or_create_stream(async_nats::jetstream::stream::Config {
                        name: "FACTO_EVENTS".to_string(),
                        subjects: vec!["facto.events.>".to_string()],
                        retention: async_nats::jetstream::stream::RetentionPolicy::WorkQueue,
                        storage: async_nats::jetstream::stream::StorageType::File,
                        max_messages: 10_000_000,
                        max_bytes: 10 * 1024 * 1024 * 1024, // 10GB
                        ..Default::default()
                    })
                    .await
                {
                    Ok(_) => info!("FACTO_EVENTS stream ready"),
                    Err(e) => {
                        error!("Failed to create stream: {}", e);
                    }
                }

                {
                    let mut nats_client = state.nats_client.write().await;
                    *nats_client = Some(client);
                    gauge!("facto_nats_connected").set(1.0);
                }

                // Monitor connection
                loop {
                    tokio::time::sleep(tokio::time::Duration::from_secs(5)).await;
                    let client = state.nats_client.read().await;
                    if let Some(ref c) = *client {
                        if c.connection_state()
                            == async_nats::connection::State::Disconnected
                        {
                            warn!("NATS connection lost");
                            gauge!("facto_nats_connected").set(0.0);
                            break;
                        }
                    }
                }
            }
            Err(e) => {
                error!("Failed to connect to NATS: {}", e);
                gauge!("facto_nats_connected").set(0.0);
            }
        }

        // Wait before reconnecting
        tokio::time::sleep(tokio::time::Duration::from_secs(5)).await;
    }
}

// ============================================================================
// Main Entry Point
// ============================================================================

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Initialize tracing
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_default_env()
                .add_directive("facto_ingestion=info".parse()?)
                .add_directive("tower_http=info".parse()?),
        )
        .json()
        .init();

    // Initialize metrics
    let builder = PrometheusBuilder::new();
    builder
        .install()
        .expect("Failed to install Prometheus recorder");

    // Configuration from environment
    let port: u16 = std::env::var("PORT")
        .unwrap_or_else(|_| "8080".to_string())
        .parse()
        .expect("Invalid PORT");

    let nats_url = std::env::var("NATS_URL").unwrap_or_else(|_| "nats://localhost:4222".to_string());

    let rate_limit_per_agent: u32 = std::env::var("RATE_LIMIT_PER_AGENT")
        .unwrap_or_else(|_| "10000".to_string())
        .parse()
        .expect("Invalid RATE_LIMIT_PER_AGENT");

    info!(
        "Starting Facto Ingestion Service v{}",
        env!("CARGO_PKG_VERSION")
    );
    info!("Port: {}", port);
    info!("NATS URL: {}", nats_url);
    info!("Rate limit per agent: {} req/sec", rate_limit_per_agent);

    // Initialize application state
    let state = Arc::new(AppState::new(rate_limit_per_agent));

    // Spawn NATS connection task
    let nats_state = state.clone();
    let nats_url_clone = nats_url.clone();
    tokio::spawn(async move {
        connect_to_nats(nats_state, &nats_url_clone).await;
    });

    // Build router
    let app = Router::new()
        .route("/health", get(health_handler))
        .route("/ready", get(ready_handler))
        .route("/metrics", get(metrics_handler))
        .route("/v1/ingest", post(ingest_single_handler))
        .route("/v1/ingest/batch", post(ingest_batch_handler))
        .layer(CompressionLayer::new())
        .layer(
            CorsLayer::new()
                .allow_origin(Any)
                .allow_methods(Any)
                .allow_headers(Any),
        )
        .layer(TraceLayer::new_for_http())
        .with_state(state);

    // Start server
    let addr = SocketAddr::from(([0, 0, 0, 0], port));
    info!("Listening on {}", addr);

    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_canonical_form() {
        let event = FactoEvent {
            facto_id: "tr-test-123".to_string(),
            agent_id: "agent-test".to_string(),
            session_id: "session-test".to_string(),
            parent_facto_id: None,
            action_type: "llm_call".to_string(),
            status: "success".to_string(),
            input_data: serde_json::json!({"prompt": "test"}),
            output_data: serde_json::json!({"response": "test"}),
            execution_meta: ExecutionMeta {
                model_id: Some("gpt-4".to_string()),
                model_hash: None,
                temperature: Some(0.7),
                seed: None,
                max_tokens: Some(1000),
                tool_calls: vec![],
                sdk_version: "0.1.0".to_string(),
                sdk_language: "python".to_string(),
                tags: BTreeMap::new(),
            },
            proof: Proof {
                signature: "".to_string(),
                public_key: "".to_string(),
                prev_hash: "0".repeat(64),
                event_hash: "".to_string(),
            },
            started_at: 1000000000,
            completed_at: 1000000001,
        };

        let canonical = build_canonical_form(&event).unwrap();
        assert!(canonical.contains("action_type"));
        assert!(canonical.contains("agent_id"));
    }

    #[test]
    fn test_compute_hash() {
        let data = r#"{"test":"data"}"#;
        let hash = compute_event_hash(data);
        assert_eq!(hash.len(), 64); // SHA3-256 produces 32 bytes = 64 hex chars
    }
}
