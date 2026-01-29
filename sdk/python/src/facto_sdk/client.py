"""Facto client for sending events to the ingestion service."""

import asyncio
import atexit
import threading
import time
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Dict, Generator, List, Optional, TypeVar, Union

import httpx

from .crypto import CryptoProvider
from .models import (
    ExecutionMeta,
    Proof,
    FactoConfig,
    FactoContext,
    FactoEvent,
    current_time_ns,
    generate_facto_id,
)


F = TypeVar("F", bound=Callable[..., Any])


class FactoClient:
    """Synchronous client for sending facto events."""

    def __init__(self, config: FactoConfig):
        """
        Initialize the Facto client.

        Args:
            config: Configuration for the client
        """
        self.config = config
        self._crypto = CryptoProvider(
            private_key=config.private_key,
            public_key=config.public_key,
        )
        self._batch: List[FactoEvent] = []
        self._batch_lock = threading.Lock()
        self._http_client = httpx.Client(
            base_url=config.endpoint,
            timeout=config.timeout_seconds,
        )
        self._closed = False

        # Start background flush thread
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()

        # Register cleanup on exit
        atexit.register(self.close)

    def _flush_loop(self) -> None:
        """Background thread that periodically flushes the batch."""
        while not self._closed:
            time.sleep(self.config.flush_interval_seconds)
            if not self._closed:
                self.flush()

    def record(
        self,
        action_type: str,
        input_data: Dict[str, Any],
        output_data: Dict[str, Any],
        status: str = "success",
        parent_facto_id: Optional[str] = None,
        execution_meta: Optional[ExecutionMeta] = None,
        started_at: Optional[int] = None,
        completed_at: Optional[int] = None,
    ) -> str:
        """
        Record a facto event.

        Args:
            action_type: Type of action (e.g., "llm_call", "tool_use", "decision")
            input_data: Input data for the action
            output_data: Output data from the action
            status: Status of the action ("success", "error", etc.)
            parent_facto_id: Optional parent facto ID for nested actions
            execution_meta: Optional execution metadata
            started_at: Optional start time in nanoseconds
            completed_at: Optional completion time in nanoseconds

        Returns:
            The facto_id of the recorded event
        """
        facto_id = generate_facto_id()
        now = current_time_ns()

        if execution_meta is None:
            execution_meta = ExecutionMeta(tags=self.config.tags.copy())
        else:
            # Merge config tags with execution meta tags
            merged_tags = self.config.tags.copy()
            merged_tags.update(execution_meta.tags)
            execution_meta.tags = merged_tags

        # Build event dict for signing
        event_dict = {
            "facto_id": facto_id,
            "agent_id": self.config.agent_id,
            "session_id": self.config.session_id,
            "parent_facto_id": parent_facto_id,
            "action_type": action_type,
            "status": status,
            "input_data": input_data,
            "output_data": output_data,
            "execution_meta": {
                "model_id": execution_meta.model_id,
                "model_hash": execution_meta.model_hash,
                "temperature": execution_meta.temperature,
                "seed": execution_meta.seed,
                "max_tokens": execution_meta.max_tokens,
                "tool_calls": execution_meta.tool_calls,
                "sdk_version": execution_meta.sdk_version,
                "sdk_language": execution_meta.sdk_language,
                "tags": execution_meta.tags,
            },
            "proof": {
                "prev_hash": self._crypto.prev_hash,
            },
            "started_at": started_at or now,
            "completed_at": completed_at or now,
        }

        # Sign the event
        event_hash, signature = self._crypto.sign_event(event_dict)

        # Create the complete event
        event = FactoEvent(
            facto_id=facto_id,
            agent_id=self.config.agent_id,
            session_id=self.config.session_id,
            parent_facto_id=parent_facto_id,
            action_type=action_type,
            status=status,
            input_data=input_data,
            output_data=output_data,
            execution_meta=execution_meta,
            proof=Proof(
                signature=signature,
                public_key=self._crypto.public_key_base64,
                prev_hash=self._crypto.prev_hash,
                event_hash=event_hash,
            ),
            started_at=started_at or now,
            completed_at=completed_at or now,
        )

        # Update prev_hash for chain linking
        self._crypto.update_prev_hash(event_hash)

        # Add to batch
        with self._batch_lock:
            self._batch.append(event)
            if len(self._batch) >= self.config.batch_size:
                self._flush_batch()

        return facto_id

    @contextmanager
    def facto(
        self,
        action_type: str,
        input_data: Optional[Dict[str, Any]] = None,
        parent_facto_id: Optional[str] = None,
        execution_meta: Optional[ExecutionMeta] = None,
    ) -> Generator[FactoContext, None, None]:
        """
        Context manager for tracing an action.

        Args:
            action_type: Type of action
            input_data: Optional input data
            parent_facto_id: Optional parent facto ID
            execution_meta: Optional execution metadata

        Yields:
            FactoContext that can be used to set output and status
        """
        ctx = FactoContext(
            client=self,
            action_type=action_type,
            input_data=input_data or {},
            started_at=current_time_ns(),
            parent_facto_id=parent_facto_id,
            execution_meta=execution_meta,
        )

        try:
            yield ctx
        except Exception as e:
            ctx.set_error(e)
            raise
        finally:
            output_data = ctx.output
            if not isinstance(output_data, dict):
                output_data = {"result": output_data} if output_data is not None else {}

            self.record(
                action_type=ctx.action_type,
                input_data=ctx.input_data,
                output_data=output_data,
                status=ctx.status,
                parent_facto_id=ctx.parent_facto_id,
                execution_meta=ctx.execution_meta,
                started_at=ctx.started_at,
            )

    def factod(
        self,
        action_type: str,
        execution_meta: Optional[ExecutionMeta] = None,
    ) -> Callable[[F], F]:
        """
        Decorator for tracing a function.

        Args:
            action_type: Type of action
            execution_meta: Optional execution metadata

        Returns:
            Decorated function
        """

        def decorator(func: F) -> F:
            @wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                input_data = {"args": args, "kwargs": kwargs}
                
                # We need to handle async functions differently
                if asyncio.iscoroutinefunction(func):
                    async def async_wrapper():
                        with self.facto(action_type, input_data, execution_meta=execution_meta) as ctx:
                            result = await func(*args, **kwargs)
                            ctx.output = result
                            return result
                    return async_wrapper()
                
                # Sync function handling
                with self.facto(action_type, input_data, execution_meta=execution_meta) as ctx:
                    result = func(*args, **kwargs)
                    ctx.output = result
                    return result

            return wrapper  # type: ignore

        return decorator

    def flush(self) -> None:
        """Flush the current batch of events."""
        with self._batch_lock:
            self._flush_batch()

    def _flush_batch(self) -> None:
        """Internal method to flush batch (must hold lock)."""
        if not self._batch:
            return

        batch = self._batch
        self._batch = []

        try:
            self._send_batch(batch)
        except Exception as e:
            # On failure, add events back to batch for retry
            self._batch = batch + self._batch
            raise e

    def _send_batch(self, events: List[FactoEvent]) -> None:
        """Send a batch of events to the ingestion service."""
        if not events:
            return

        payload = {
            "events": [event.to_dict() for event in events],
        }

        for attempt in range(self.config.max_retries):
            try:
                response = self._http_client.post("/v1/ingest/batch", json=payload)
                response.raise_for_status()
                return
            except httpx.HTTPStatusError as e:
                if e.response.status_code < 500:
                    raise  # Don't retry client errors
                if attempt == self.config.max_retries - 1:
                    raise
            except httpx.RequestError:
                if attempt == self.config.max_retries - 1:
                    raise

            # Exponential backoff
            time.sleep(2**attempt)

    def close(self) -> None:
        """Close the client and flush remaining events."""
        if self._closed:
            return

        self._closed = True
        self.flush()
        self._http_client.close()


class AsyncFactoClient:
    """Asynchronous client for sending facto events."""

    def __init__(self, config: FactoConfig):
        """
        Initialize the async Facto client.

        Args:
            config: Configuration for the client
        """
        self.config = config
        self._crypto = CryptoProvider(
            private_key=config.private_key,
            public_key=config.public_key,
        )
        self._batch: List[FactoEvent] = []
        self._batch_lock = asyncio.Lock()
        self._http_client = httpx.AsyncClient(
            base_url=config.endpoint,
            timeout=config.timeout_seconds,
        )
        self._closed = False
        self._flush_task: Optional[asyncio.Task[None]] = None

    async def start(self) -> None:
        """Start the background flush task."""
        self._flush_task = asyncio.create_task(self._flush_loop())

    async def _flush_loop(self) -> None:
        """Background task that periodically flushes the batch."""
        while not self._closed:
            await asyncio.sleep(self.config.flush_interval_seconds)
            if not self._closed:
                await self.flush()

    async def record(
        self,
        action_type: str,
        input_data: Dict[str, Any],
        output_data: Dict[str, Any],
        status: str = "success",
        parent_facto_id: Optional[str] = None,
        execution_meta: Optional[ExecutionMeta] = None,
        started_at: Optional[int] = None,
        completed_at: Optional[int] = None,
    ) -> str:
        """
        Record a facto event asynchronously.

        Args:
            action_type: Type of action
            input_data: Input data for the action
            output_data: Output data from the action
            status: Status of the action
            parent_facto_id: Optional parent facto ID
            execution_meta: Optional execution metadata
            started_at: Optional start time in nanoseconds
            completed_at: Optional completion time in nanoseconds

        Returns:
            The facto_id of the recorded event
        """
        facto_id = generate_facto_id()
        now = current_time_ns()

        if execution_meta is None:
            execution_meta = ExecutionMeta(tags=self.config.tags.copy())
        else:
            merged_tags = self.config.tags.copy()
            merged_tags.update(execution_meta.tags)
            execution_meta.tags = merged_tags

        event_dict = {
            "facto_id": facto_id,
            "agent_id": self.config.agent_id,
            "session_id": self.config.session_id,
            "parent_facto_id": parent_facto_id,
            "action_type": action_type,
            "status": status,
            "input_data": input_data,
            "output_data": output_data,
            "execution_meta": {
                "model_id": execution_meta.model_id,
                "model_hash": execution_meta.model_hash,
                "temperature": execution_meta.temperature,
                "seed": execution_meta.seed,
                "max_tokens": execution_meta.max_tokens,
                "tool_calls": execution_meta.tool_calls,
                "sdk_version": execution_meta.sdk_version,
                "sdk_language": execution_meta.sdk_language,
                "tags": execution_meta.tags,
            },
            "proof": {
                "prev_hash": self._crypto.prev_hash,
            },
            "started_at": started_at or now,
            "completed_at": completed_at or now,
        }

        event_hash, signature = self._crypto.sign_event(event_dict)

        event = FactoEvent(
            facto_id=facto_id,
            agent_id=self.config.agent_id,
            session_id=self.config.session_id,
            parent_facto_id=parent_facto_id,
            action_type=action_type,
            status=status,
            input_data=input_data,
            output_data=output_data,
            execution_meta=execution_meta,
            proof=Proof(
                signature=signature,
                public_key=self._crypto.public_key_base64,
                prev_hash=self._crypto.prev_hash,
                event_hash=event_hash,
            ),
            started_at=started_at or now,
            completed_at=completed_at or now,
        )

        self._crypto.update_prev_hash(event_hash)

        async with self._batch_lock:
            self._batch.append(event)
            if len(self._batch) >= self.config.batch_size:
                await self._flush_batch()

        return facto_id

    async def flush(self) -> None:
        """Flush the current batch of events."""
        async with self._batch_lock:
            await self._flush_batch()

    async def _flush_batch(self) -> None:
        """Internal method to flush batch (must hold lock)."""
        if not self._batch:
            return

        batch = self._batch
        self._batch = []

        try:
            await self._send_batch(batch)
        except Exception as e:
            self._batch = batch + self._batch
            raise e

    async def _send_batch(self, events: List[FactoEvent]) -> None:
        """Send a batch of events to the ingestion service."""
        if not events:
            return

        payload = {
            "events": [event.to_dict() for event in events],
        }

        for attempt in range(self.config.max_retries):
            try:
                response = await self._http_client.post("/v1/ingest/batch", json=payload)
                response.raise_for_status()
                return
            except httpx.HTTPStatusError as e:
                if e.response.status_code < 500:
                    raise
                if attempt == self.config.max_retries - 1:
                    raise
            except httpx.RequestError:
                if attempt == self.config.max_retries - 1:
                    raise

            await asyncio.sleep(2**attempt)

    async def close(self) -> None:
        """Close the client and flush remaining events."""
        if self._closed:
            return

        self._closed = True

        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        await self.flush()
        await self._http_client.aclose()
