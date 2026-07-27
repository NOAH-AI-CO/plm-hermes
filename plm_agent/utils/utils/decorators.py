# -*- coding: utf-8 -*-
import warnings
import functools

def deprecated(reason):
    r"""Mark function as deprecated"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            warnings.warn(
                f"{func.__name__} is deprecated: {reason}",
                category=DeprecationWarning,
                stacklevel=2
            )
            return func(*args, **kwargs)
        return wrapper
    return decorator

def deprecated_class(reason):
    r"""Mark the class as deprecated"""
    def decorator(cls):
        original_init = cls.__init__
        
        @functools.wraps(original_init)
        def new_init(self, *args, **kwargs):
            warnings.warn(
                f"{cls.__name__} is deprecated: {reason}",
                category=DeprecationWarning,
                stacklevel=2
            )
            original_init(self, *args, **kwargs)
        
        cls.__init__ = new_init
        return cls
    return decorator

