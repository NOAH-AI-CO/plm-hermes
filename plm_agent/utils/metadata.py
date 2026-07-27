from abc import ABCMeta
class SingletonMeta(ABCMeta):
    _instances = {}
    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]

    def cleanup(cls):
        if cls in cls._instances:
            instance = cls._instances[cls]
            if hasattr(instance, "cleanup"):
                instance.cleanup()
            del cls._instances[cls]