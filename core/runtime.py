"""Process-wide runtime state that is not configuration.

The start time and the server-control job are read by the status and server
endpoints; they live here so the route modules do not need app.py.
"""

import threading
import time
from typing import Any


APP_STARTED_AT = time.time()
SERVER_JOB: dict[str, Any] = {"process": None, "action": "", "started_at": ""}
SERVER_JOB_LOCK = threading.Lock()
