"""
Structured logging configuration with structlog.
Extracted from api.py - DO NOT MODIFY unless updating source.
"""
import logging
import structlog
from contextvars import ContextVar

# Configure structured logging with structlog
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

# Request ID context variable for tracking
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")

# Get structured logger
logger = structlog.get_logger("markitdown-api")
