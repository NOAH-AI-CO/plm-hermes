import sys
import os
import logging.config
import logging.handlers
from contextvars import ContextVar

# ContextVar for passing request log IDs in async environments
log_id_var: ContextVar[str] = ContextVar('log_id', default='')
task_id_var: ContextVar[str] = ContextVar('task_id', default='')


class LogIDFilter(logging.Filter):
    """Custom filter to add log_id to log records"""
    def filter(self, record):
        record.log_id = log_id_var.get('') or 'no-log-id'
        
        # Defailt otel fields
        if not hasattr(record, 'otelTraceID'):
            record.otelTraceID = '0' * 32
        if not hasattr(record, 'otelSpanID'):
            record.otelSpanID = '0' * 16
        if not hasattr(record, 'otelServiceName'):
            record.otelServiceName = ''
        return True

LOG_DIR: str = r'logs'

"""
Log file structure:
logs/
├── agent.log                    # Current main log (actively writing)
├── agent.log.2026-01-31.00      # Today's 1st backup (full at 300MB)
├── agent.log.2026-01-31.01      # Today's 2nd backup (full at 300MB)
├── agent_error.log              # Current error log
├── agent_error.log.2026-01-31.00 # Today's error log backup
├── agent_error.log.2026-01-30.00 # Yesterday's error log backup
├── access.log                   # Current access log
├── access.log.2026-01-31.00      # Today's access log backup
└── access.log.2026-01-30.00      # Yesterday's access log backup
"""

LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,

    'root': {
        'level': 'INFO',
        'handlers': ['info_rotating', 'error_rotating', 'console'],
    },

    'loggers': {
        'uvicorn': {
            'level': 'INFO',
            'handlers': ['console', 'info_rotating'],
            'propagate': False,
        },
        'uvicorn.error': {
            'level': 'WARNING',
            'handlers': ['console', 'error_rotating', 'info_rotating'],
            'propagate': False,
        },
        'uvicorn.access': {
            'level': 'INFO',
            'handlers': ['access_rotating'],
            'propagate': False,
        },
        'sqlalchemy': {
            'level': 'CRITICAL',
            'handlers': ['console', 'error_rotating'],
            'propagate': False,
        },
        'azure': {
            'level': 'CRITICAL',
            'handlers': ['console', 'error_rotating'],
            'propagate': False,
        }
    },

    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'generic',
            'stream': sys.stdout,
            'level': 'INFO',
            'filters': ['log_id_filter']
        },

        # ===== Main log =====
        'info_rotating': {
            'class': 'concurrent_log_handler.ConcurrentTimedRotatingFileHandler',
            'formatter': 'generic',
            'filename': f'{LOG_DIR}/agent.log',
            'when': 'midnight',
            'interval': 1,
            'backupCount': 100,
            'maxBytes': 300 * 1024 * 1024,
            'encoding': 'utf-8',
            'delay': False,
            'utc': False,
            'level': 'INFO',
            'filters': ['log_id_filter'],

            # 关键：锁文件放本地盘（避免挂载盘锁不靠谱）
            'lock_file_directory': '/tmp',
        },

        # ===== Error log =====
        'error_rotating': {
            'class': 'concurrent_log_handler.ConcurrentTimedRotatingFileHandler',
            'formatter': 'error',
            'filename': f'{LOG_DIR}/agent_error.log',
            'when': 'midnight',
            'interval': 1,
            'backupCount': 100,
            'maxBytes': 300 * 1024 * 1024,
            'encoding': 'utf-8',
            'delay': False,
            'utc': False,
            'level': 'WARNING',
            'filters': ['log_id_filter'],
            'lock_file_directory': '/tmp',
        },

        # ===== Access log =====
        'access_rotating': {
            'class': 'concurrent_log_handler.ConcurrentTimedRotatingFileHandler',
            'formatter': 'access',
            'filename': f'{LOG_DIR}/access.log',
            'when': 'midnight',
            'interval': 1,
            'backupCount': 100,
            'maxBytes': 300 * 1024 * 1024,
            'encoding': 'utf-8',
            'delay': False,
            'utc': False,
            'level': 'INFO',
            'filters': ['log_id_filter'],
            'lock_file_directory': '/tmp',
        },
    },

    'formatters': {
        'generic': {
            'format': '%(asctime)s [%(log_id)s] [%(name)s] [%(module)s:%(lineno)d] [%(levelname)s] [trace_id=%(otelTraceID)s span_id=%(otelSpanID)s resource.service.name=%(otelServiceName)s] %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S',
            'class': 'logging.Formatter',
        },
        'access': {
            'format': '%(asctime)s [%(log_id)s] [ACCESS] [trace_id=%(otelTraceID)s span_id=%(otelSpanID)s resource.service.name=%(otelServiceName)s] %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S',
            'class': 'logging.Formatter',
        },
        'error': {
            'format': '%(asctime)s [%(log_id)s] [%(name)s] [%(module)s:%(lineno)d] [%(levelname)s] [trace_id=%(otelTraceID)s span_id=%(otelSpanID)s resource.service.name=%(otelServiceName)s] %(message)s\n%(pathname)s',
            'datefmt': '%Y-%m-%d %H:%M:%S',
            'class': 'logging.Formatter',
        },
    },

    'filters': {
        'log_id_filter': {
            '()': LogIDFilter,
        },
    },
}
