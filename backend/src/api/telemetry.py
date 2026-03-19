import logging
import os

from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry.sdk.resources import Resource

logger = logging.getLogger("brand-guardian-telemetry")


def setup_telemetry():
    """
    Initialize Azure Monitor OpenTelemetry if a connection string is configured.
    """
    connection_string = (
        os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
        or os.getenv("APPLICATIONINSIGHTS_CONNECTIONS_STRING")
    )

    if not connection_string:
        logger.warning("No Application Insights connection string found. Telemetry is disabled.")
        return

    service_name = os.getenv("OTEL_SERVICE_NAME", "brand-guardian-api")
    service_namespace = os.getenv("OTEL_SERVICE_NAMESPACE", "brand-guardian")
    service_version = os.getenv("OTEL_SERVICE_VERSION", "1.0.0")

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.namespace": service_namespace,
            "service.version": service_version,
        }
    )

    try:
        configure_azure_monitor(
            connection_string=connection_string,
            logger_name="brand-guardian-tracer",
            resource=resource,
        )
        logger.info("Azure Monitor telemetry enabled for service '%s'.", service_name)
    except Exception as exc:
        logger.error("Failed to initialize Azure Monitor telemetry: %s", exc)


# Backward-compatible alias for older imports/usages in the project.
setup_telementry = setup_telemetry
