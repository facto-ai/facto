import httpx
import json
import time
from datetime import datetime, timedelta, timezone

BASE_URL = "http://127.0.0.1:8082"
AGENT_ID = "test-agent-cycle-001"

def main():
    print(f"Targeting API at {BASE_URL}")

    # 1. List Events
    # Use a wide time window to ensure we catch recent events
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=48)
    
    # Format as RFC3339
    params = {
        "agent_id": AGENT_ID,
        "start": start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": end_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "limit": 5
    }
    
    print(f"\n--- 1. Listing Events (GET /v1/events) ---")
    print(f"Query Params: {json.dumps(params, indent=2)}")
    
    try:
        resp = httpx.get(f"{BASE_URL}/v1/events", params=params)
        resp.raise_for_status()
        data = resp.json()
        events = data.get("events")
        if events is None:
            events = []
        
        print(f"Status: {resp.status_code}")
        print(f"Full Response: {json.dumps(data, indent=2)}")
        print(f"Found {len(events)} events")
        
        if not events:
            print("No events found. Please run the agent tests first to generate factos.")
            return

        # Show the most recent event (first in list usually, depending on sort, but let's grab one)
        target_event = events[0]
        facto_id = target_event.get('facto_id')
        print(f"Selected Facto ID: {facto_id}")
        print(f"Action Type: {target_event.get('action_type')}")
        
    except Exception as e:
        print(f"Error listing events: {e}")
        if hasattr(e, 'response'): 
            print(f"Response: {e.response.text}")
        return

    # 2. Get Single Event
    print(f"\n--- 2. Get Event Details (GET /v1/events/{facto_id}) ---")
    try:
        resp = httpx.get(f"{BASE_URL}/v1/events/{facto_id}")
        resp.raise_for_status()
        event_details = resp.json()
        print(f"Status: {resp.status_code}")
        print("Successfully retrieved event details.")
        # print(json.dumps(event_details, indent=2))
    except Exception as e:
        print(f"Error getting event: {e}")
        return

    # 3. Verify Event
    print(f"\n--- 3. Verify Event (POST /v1/verify) ---")
    try:
        # The verify endpoint expects {"event": event_object}
        verify_payload = {"event": event_details}
        
        resp = httpx.post(f"{BASE_URL}/v1/verify", json=verify_payload)
        resp.raise_for_status()
        
        verify_result = resp.json()
        print(f"Status: {resp.status_code}")
        print("Verification Result:")
        print(json.dumps(verify_result, indent=2))
        
        if verify_result.get("valid"):
            print("\nSUCCESS: Event verification passed!")
        else:
            print("\nFAILURE: Event verification failed!")
            
    except Exception as e:
        print(f"Error verifying event: {e}")
        if hasattr(e, 'response'):
             print(f"Response: {e.response.text}")

if __name__ == "__main__":
    main()
