# -*- coding: utf-8 -*-
"""Workspace tracker for the ``general_writing`` flow.

Importing the package registers ``WorkspaceModule`` and exposes the singleton
``WorkspaceStore``. See ``store.py`` for the data model and ``module.py`` for
the front-end reply contract.
"""

from agent.workspace.module import WorkspaceModule  # noqa: F401  (registers)
from agent.workspace.store import WorkspaceStore, get_store

__all__ = ["WorkspaceModule", "WorkspaceStore", "get_store"]
