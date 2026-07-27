class JournalRecommendationTaskStatus:
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "processing"
    MDSUCCESS = "mdsucceeded"
    SUCCESS = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELED = "canceled"
    ERROR = "error"
    DELETED = "deleted"

    ALL = {
        PENDING,
        QUEUED,
        RUNNING,
        SUCCESS,
        FAILED,
        TIMEOUT,
        CANCELED,
        ERROR,
        MDSUCCESS,
        DELETED,
    }

    FINAL = {
        SUCCESS,
        FAILED,
        TIMEOUT,
        CANCELED,
        ERROR,
        DELETED,
    }