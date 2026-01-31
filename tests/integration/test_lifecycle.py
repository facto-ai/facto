import asyncio
import os
import time
import httpx
from datetime import datetime, timezone, timedelta
from facto import FactoClient, FactoConfig

# Configuration
INGEST_URL = "http://127.0.0.1:8080"
API_URL = "http://127.0.0.1:8082/v1/events"
AGENT_ID = "test-agent-cycle-001"

def main():
    print("--- Starting End-to-End Facto Cycle Test ---")
    
    # 1. Initialize Client
    client = FactoClient(FactoConfig(
        endpoint=INGEST_URL,
        agent_id=AGENT_ID,
        batch_size=1,            # Force flush quickly
        flush_interval_seconds=1 # Flush every second
    ))
    
    # 2. Record Event
    print(f"Recording event for agent: {AGENT_ID}")
    try:
        facto_id = client.record(
            action_type="test_action",
            input_data={"msg": "hello"},
            output_data={"msg": "world"}
        )
        print(f"Recorded Facto ID: {facto_id}")
    except Exception as e:
        print(f"Failed to record event: {e}")
        return

    # 3. Flush and Wait
    print("Flushing and waiting 3 seconds for ingestion...")
    client.close() # Flushes and closes
    time.sleep(3)
    
    # 4. Query API
    print("Querying API...")
    try:
        params = {
            "agent_id": AGENT_ID,
            "start": (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"), 
            "end": (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),   
            "limit": 5
        }
        resp = httpx.get(API_URL, params=params)
        print(f"API Response Status: {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            events = data.get("events") 
            if events:
                 print(f"Found {len(events)} events.")
                 if events[0]["facto_id"] == facto_id:
                     print("SUCCESS: Retrieved exact facto ID match.")
                 else:
                     print(f"WARNING: Retrieved facto ID {events[0]['facto_id']} does not match {facto_id}")
            else:
                print("FAILURE: No events found in API response.")
                print(f"Body: {data}")
        else:
            print(f"FAILURE: API verification failed. Body: {resp.text}")
            
    except Exception as e:
        print(f"Error querying API: {e}")

if __name__ == "__main__":
    main()
