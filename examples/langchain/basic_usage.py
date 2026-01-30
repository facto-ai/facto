#!/usr/bin/env python3
"""
LangChain + Facto Integration Example

This example demonstrates how to add cryptographic audit trails
to your LangChain agents using Facto.

Requirements:
    pip install facto-sdk langchain langchain-openai

Usage:
    export OPENAI_API_KEY=sk-...
    python basic_usage.py
"""

import os
import dotenv
import sys

dotenv.load_dotenv()

# read from dotenv
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Check for API key
if not OPENAI_API_KEY:
    print("⚠️  OPENAI_API_KEY not set. Running in demo mode with mock responses.")
    DEMO_MODE = True
else:
    DEMO_MODE = False
    from langchain_openai import ChatOpenAI

from facto_sdk import FactoClient, FactoConfig, ExecutionMeta


def main():
    # Initialize Facto client
    facto = FactoClient(FactoConfig(
        endpoint=os.getenv("FACTO_ENDPOINT", "http://localhost:8080"),
        agent_id="langchain-demo-agent",
    ))
    
    print("🔐 Facto LangChain Integration Demo")
    print("=" * 50)
    print(f"Agent ID: {facto.config.agent_id}")
    print(f"Session ID: {facto.config.session_id}")
    print()
    
    # Example 1: Using the decorator
    print("📝 Example 1: Decorator Pattern")
    print("-" * 30)
    
    @facto.factod("llm_call", ExecutionMeta(model_id="gpt-4"))
    def ask_llm(prompt: str) -> str:
        """Call LLM with automatic Facto tracing."""
        if DEMO_MODE:
            return f"[Demo response for: {prompt}]"
        llm = ChatOpenAI(model="gpt-4", temperature=0.7)
        response = llm.invoke(prompt)
        return response.content
    
    response1 = ask_llm("What is the capital of France?")
    print(f"Q: What is the capital of France?")
    print(f"A: {response1}")
    print()
    
    # Example 2: Using context manager
    print("📝 Example 2: Context Manager Pattern")
    print("-" * 30)
    
    prompt2 = "Explain quantum computing in one sentence."
    with facto.facto("llm_call", input_data={"prompt": prompt2}) as ctx:
        if DEMO_MODE:
            response2 = f"[Demo response for: {prompt2}]"
        else:
            llm = ChatOpenAI(model="gpt-4", temperature=0.5)
            response2 = llm.invoke(prompt2).content
        
        ctx.output = {"response": response2}
        ctx.meta = ExecutionMeta(
            model_id="gpt-4",
            temperature=0.5,
        )
    
    print(f"Q: {prompt2}")
    print(f"A: {response2}")
    print()
    
    # Example 3: Manual recording
    print("📝 Example 3: Manual Recording")
    print("-" * 30)
    
    prompt3 = "What is 2 + 2?"
    if DEMO_MODE:
        response3 = "4"
    else:
        llm = ChatOpenAI(model="gpt-4", temperature=0)
        response3 = llm.invoke(prompt3).content
    
    facto_id = facto.record(
        action_type="llm_call",
        input_data={"prompt": prompt3},
        output_data={"response": response3},
        status="success",
    )
    
    print(f"Q: {prompt3}")
    print(f"A: {response3}")
    print(f"Facto ID: {facto_id}")
    print()
    
    # Flush and close
    facto.flush()
    facto.close()
    
    print("=" * 50)
    print("✅ All events cryptographically signed and logged!")
    print()
    print("To verify your audit trail:")
    print(f"  curl 'http://localhost:8082/v1/evidence-package?session_id={facto.config.session_id}' > evidence.json")
    print("  facto verify evidence.json")


if __name__ == "__main__":
    main()
