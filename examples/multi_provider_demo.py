import os
import asyncio
from dotenv import load_dotenv
from facto import FactoClient, FactoConfig, ExecutionMeta

# Load environment variables
load_dotenv()

# Initialize Facto Client
client = FactoClient(FactoConfig(
    endpoint="http://127.0.0.1:8080",
    agent_id="multi-provider-agent-001",
))

# --- 1. Decorator Pattern (OpenAI) ---
# Using the @client.factod decorator to automatically facto function calls
@client.factod("openai_completion", ExecutionMeta(model_id="gpt-5.2"))
async def test_openai():
    print("\n--- Testing OpenAI (Responses API) - Wrapped with Decorator ---")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("Skipping OpenAI: OPENAI_API_KEY not found")
        return

    from openai import AsyncOpenAI
    oai_client = AsyncOpenAI(api_key=api_key)

    try:
        # Using the new Responses API
        response = await oai_client.responses.create(
            model="gpt-5.2",
            input="Say hello to Facto!"
        )
        content = response.output_text
        print(f"OpenAI Response: {content}")
        
        # When using the decorator, return value is captured as output by default
        return {
            "content": content,
            "id": response.id,
            "decorator_worked": True
        }
    except Exception as e:
        print(f"OpenAI Error: {e}")
        raise # Re-raise to let the decorator capture the error

# --- 2. Manual Tracing Pattern (Anthropic) ---
# Manually calling client.record() for detached/async-agnostic tracing
async def test_anthropic():
    print("\n--- Testing Anthropic - Manual Tracing ---")
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Skipping Anthropic: ANTHROPIC_API_KEY not found")
        return

    from anthropic import AsyncAnthropic
    ant_client = AsyncAnthropic(api_key=api_key)

    try:
        # Manual start not needed for simple record, but let's emulate a flow:
        # 1. Record input
        facto_id = client.record(
            action_type="anthropic_call_start",
            input_data={"model": "claude-sonnet-4-5", "prompt": "Hello!"},
            output_data={}, # Required by client.record
            execution_meta=ExecutionMeta(
                model_id="claude-sonnet-4-5"
            )
        )
        print(f"Recorded start event: {facto_id}")

        message = await ant_client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=20,
            messages=[{"role": "user", "content": "Say hello to Facto!"}]
        )
        content = message.content[0].text
        print(f"Anthropic Response: {content}")
        
        # 2. Record output linked to previous facto if supported, or just a completion event
        # For simplicity in this demo, we record a completion event
        completion_facto_id = client.record(
            action_type="anthropic_call_end",
            input_data={}, # Required
            output_data={
                "content": content,
                "id": message.id
            },
            # In a real manual flow, you might link these via parent_id or session logic
            execution_meta=ExecutionMeta(
                model_id="claude-sonnet-4-5",
                # Mock token usage as it's not always in simple response object depending on SDK version
                max_tokens=20, 
                tags={"related_facto_id": facto_id}
            )
        )
        print(f"Recorded completion event: {completion_facto_id}")

    except Exception as e:
        print(f"Anthropic Error: {e}")
        client.record("anthropic_error", {"error": str(e)}, {})

# --- 3. Context Manager Pattern (Gemini) ---
# Using 'with client.facto(...)' for block-scoped tracing
async def test_gemini():
    print("\n--- Testing Gemini (Google GenAI) - Context Manager ---")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Skipping Gemini: GEMINI_API_KEY not found")
        return

    # Using the new google-genai SDK
    from google import genai
    g_client = genai.Client(api_key=api_key)

    try:
        with client.facto("gemini_completion", {"model": "gemini-3-flash-preview", "prompt": "Hello!"}) as ctx:
            # Using async client if available, otherwise sync wrapper
            # Assuming standard async pattern for the new SDK
            response = await g_client.aio.models.generate_content(
                model="gemini-3-flash-preview",
                contents="Say hello to Facto!"
            )
            content = response.text
            print(f"Gemini Response: {content}")
            
            ctx.output = {
                "content": content,
                "usage": str(response.usage_metadata) if hasattr(response, 'usage_metadata') else "N/A"
            }
    except Exception as e:
        print(f"Gemini Error: {e}")

async def main():
    print("Starting Multi-Provider Agent Test (Coverage: Decorator, Manual, Context)...")
    
    # 1. Decorator
    await test_openai()
    
    # 2. Manual
    await test_anthropic()
    
    # 3. Context
    await test_gemini()
    
    # Allow background batcher to flush
    client.close()
    print("\nDone! Check the Facto logs/dashboard to verify events.")

if __name__ == "__main__":
    asyncio.run(main())
