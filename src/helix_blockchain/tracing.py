"""OpenTelemetry tracing for the consensus path.

Instrumentation uses the OTel *API*, which is a no-op until an SDK provider is
configured — so spans cost nothing unless tracing is enabled. ``configure()``
wires an OTLP exporter (Jaeger/Tempo) at startup when ``HELIX_OTEL__ENABLED`` is
set. Spans around message handling and commits, correlated across nodes via the
W3C trace context, let you follow a single height's PRE-PREPARE -> COMMIT path.
"""

from __future__ import annotations

import logging

from opentelemetry import trace

log = logging.getLogger("helix.tracing")

_TRACER = trace.get_tracer("helix_blockchain")


def tracer() -> trace.Tracer:
    return _TRACER


def configure(*, enabled: bool, endpoint: str, service_name: str) -> None:
    """Install an OTLP-exporting tracer provider when ``enabled``.

    Imports the SDK lazily so the SDK is only required when tracing is on."""
    if not enabled:
        return
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        log.warning("OTel SDK/exporter not installed; tracing stays a no-op")
        return

    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))
    exporter = OTLPSpanExporter(endpoint=endpoint) if endpoint else OTLPSpanExporter()
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    global _TRACER
    _TRACER = trace.get_tracer("helix_blockchain")
    log.info("OpenTelemetry tracing enabled (service=%s)", service_name)
