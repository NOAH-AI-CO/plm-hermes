class IITTaskStatus:
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "processing"
    MDSUCCESS = "mdsucceeded"
    SUCCESS = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELED = "canceled"
    ERROR = "error"

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
    }

    FINAL = {
        SUCCESS,
        FAILED,
        TIMEOUT,
        CANCELED,
        ERROR,
    }