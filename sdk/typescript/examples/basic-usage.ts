/**
 * Basic usage example for the Facto SDK.
 *
 * Run with: npx ts-node examples/basic-usage.ts
 */

import { FactoClient, verifyEvent, toWireFormat } from '../src';

// Simulate an LLM call
async function simulateLLMCall(prompt: string): Promise<string> {
  await new Promise((resolve) => setTimeout(resolve, 100));
  return `Response to: ${prompt}`;
}

// Simulate a tool call
async function simulateToolCall(
  toolName: string,
  args: Record<string, unknown>
): Promise<Record<string, unknown>> {
  await new Promise((resolve) => setTimeout(resolve, 50));
  return { result: `Executed ${toolName}`, args };
}

async function main() {
  console.log('Initializing Facto client...');

  // Initialize the client
  const client = new FactoClient({
    endpoint: 'http://localhost:8080',
    agentId: 'example-agent-001',
    tags: { environment: 'development', version: '1.0.0' },
  });

  console.log(`Session ID: ${client.sessionId}`);

  // Method 1: Manual recording
  console.log('\n1. Recording events manually...');
  const initFactoId = await client.record({
    actionType: 'initialization',
    inputData: { config: { model: 'gpt-4', temperature: 0.7 } },
    outputData: { status: 'ready' },
    executionMeta: {
      modelId: 'gpt-4',
      temperature: 0.7,
    },
  });
  console.log(`   Recorded initialization event: ${initFactoId}`);

  // Method 2: Using factod wrapper
  console.log('\n2. Using factod wrapper...');
  const factodLLMCall = client.factod(
    'llm_call',
    async (prompt: string) => await simulateLLMCall(prompt)
  );
  const response = await factodLLMCall('What is the capital of France?');
  console.log(`   LLM response: ${response}`);

  // Method 3: Using startFacto for manual control
  console.log('\n3. Using startFacto context...');
  const ctx = client.startFacto('tool_use', {
    tool: 'web_search',
    query: 'latest AI news',
  });

  try {
    const toolResult = await simulateToolCall('web_search', {
      query: 'latest AI news',
    });
    ctx.setOutput(toolResult);
    ctx.setStatus('success');
  } catch (error) {
    if (error instanceof Error) {
      ctx.setError(error);
    }
  } finally {
    await ctx.end();
  }
  console.log(`   Recorded tool use event: ${ctx.factoId}`);

  // Method 4: Nested events with parent-child relationship
  console.log('\n4. Recording nested events...');
  const parentCtx = client.startFacto('agent_task', { task: 'research' });

  // Child event 1
  await client.record({
    actionType: 'llm_call',
    inputData: { prompt: 'Analyze the research topic' },
    outputData: { analysis: 'Topic is interesting' },
    parentFactoId: parentCtx.factoId,
  });

  // Child event 2
  await client.record({
    actionType: 'tool_use',
    inputData: { tool: 'database_query' },
    outputData: { records: 10 },
    parentFactoId: parentCtx.factoId,
  });

  parentCtx.setOutput({ status: 'completed', children: 2 });
  await parentCtx.end();
  console.log(`   Recorded parent event: ${parentCtx.factoId}`);

  // Method 5: Error handling
  console.log('\n5. Recording error events...');
  const errorCtx = client.startFacto('risky_operation', { action: 'divide' });
  try {
    throw new Error('Division by zero');
  } catch (error) {
    if (error instanceof Error) {
      errorCtx.setError(error);
    }
  }
  await errorCtx.end();
  console.log(`   Recorded error event: ${errorCtx.factoId}`);

  // Demonstrate event verification
  console.log('\n6. Creating and verifying an event...');
  const verifyFactoId = await client.record({
    actionType: 'verification_test',
    inputData: { test: true },
    outputData: { verified: true },
  });
  console.log(`   Created event for verification: ${verifyFactoId}`);

  // Flush events
  console.log('\n7. Flushing events...');
  try {
    await client.flush();
    console.log('   Events flushed successfully!');
  } catch (error) {
    console.log(`   Note: Could not connect to server (${error})`);
    console.log(
      '   Events are batched and would be sent when server is available'
    );
  }

  // Close client
  await client.close();
  console.log('\nClient closed.');
}

main().catch(console.error);
