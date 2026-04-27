"""
mDNS/DNS-SD service advertisement for Hub discovery.

Owns a background watcher that:
  - Waits for a usable LAN IP before registering (boot-time race safe).
  - Re-registers if the local IP changes (suspend/resume, AP roaming, DHCP renewal).

The watcher only exists while the service is started; stop() halts it cleanly.
"""

import socket
import threading
from typing import Callable, Optional

import decky  # type: ignore

from steam_utils import get_local_ip, detect_platform

MDNS_SERVICE_TYPE = "_capydeploy._tcp.local."

# Steady-state poll interval: how often to check for IP changes once
# we have a registration. Low enough to react to suspend/roaming, high
# enough to keep CPU/wakeups negligible.
_WATCH_INTERVAL_SEC = 5.0

# Retry interval while waiting for the network to come up (boot race).
# Kept short so the user-visible wait after toggle-on stays under ~3s
# in the common case where the network is already up.
_RETRY_INTERVAL_SEC = 1.0

# How long to give the background thread to exit on stop().
_STOP_JOIN_TIMEOUT_SEC = 2.0


class MDNSService:
    """Advertises the agent via mDNS/DNS-SD for Hub discovery.

    Lifecycle:
      start()  -> spawns a watcher thread that registers when an IP is available
                  and re-registers on IP changes.
      stop()   -> signals the watcher to exit, unregisters the service.

    Resource use is zero while stopped: no thread, no zeroconf object.
    """

    def __init__(
        self,
        agent_id: str,
        agent_name: str,
        port: int,
        version: str,
        on_register: Optional[Callable[[str, int], None]] = None,
        on_unregister: Optional[Callable[[], None]] = None,
        on_waiting: Optional[Callable[[], None]] = None,
    ):
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.port = port
        self.version = version

        self._zeroconf = None
        self._service_info = None
        self._current_ip: Optional[str] = None

        # Notified after a successful (re-)register, after a teardown, or
        # the first time the watcher fails to find a usable IP. Invoked
        # from the watcher thread; callbacks must be thread-safe.
        self._on_register = on_register
        self._on_unregister = on_unregister
        self._on_waiting = on_waiting

        # Tracks whether on_waiting has already fired in the current
        # "no IP yet" stretch. Reset on a successful register so that a
        # later loss of network can fire it again.
        self._notified_waiting = False

        self._stop_event = threading.Event()
        self._worker: Optional[threading.Thread] = None
        # Guards _zeroconf, _service_info, _current_ip across the
        # watcher thread and the caller thread (stop()).
        self._lock = threading.Lock()

    # ── Public API ───────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the watcher. Idempotent: safe to call when already running."""
        if self._worker is not None and self._worker.is_alive():
            return
        self._stop_event.clear()
        self._worker = threading.Thread(
            target=self._run,
            name="capydeploy-mdns-watcher",
            daemon=True,
        )
        self._worker.start()
        decky.logger.info(
            f"mDNS watcher started for {self.agent_id} on port {self.port}"
        )

    def stop(self) -> None:
        """Signal the watcher to stop and unregister the service. Idempotent."""
        self._stop_event.set()
        worker = self._worker
        if worker is not None:
            worker.join(timeout=_STOP_JOIN_TIMEOUT_SEC)
            self._worker = None
        with self._lock:
            self._unregister_locked()
        decky.logger.info("mDNS watcher stopped")

    @property
    def announced_ip(self) -> Optional[str]:
        """The IP currently being announced via mDNS, or None if not registered."""
        with self._lock:
            return self._current_ip

    # ── Worker ───────────────────────────────────────────────────────────────

    def _run(self) -> None:
        """Watch for a usable IP and (re-)register on changes.

        Tries immediately on entry — no startup delay — so toggle-on
        with the network already up is registered as fast as zeroconf
        allows. Falls back to a short retry while waiting for the
        network at cold boot, then settles into a longer interval to
        watch for IP changes (suspend/resume, AP roaming).
        """
        while not self._stop_event.is_set():
            ip = get_local_ip()

            if ip is None:
                # Network not ready — retry quickly. Zero registration
                # attempts while we don't have a usable IP.
                # Notify the UI exactly once per "no IP" stretch so the
                # toast doesn't repeat every second while we wait.
                if not self._notified_waiting and self._on_waiting is not None:
                    self._notified_waiting = True
                    try:
                        self._on_waiting()
                    except Exception as e:
                        decky.logger.error(f"on_waiting callback failed: {e}")
                self._stop_event.wait(timeout=_RETRY_INTERVAL_SEC)
                continue

            with self._lock:
                if self._stop_event.is_set():
                    return
                if ip != self._current_ip:
                    # IP changed (or first registration). Tear down old
                    # registration before bringing up the new one so listeners
                    # see a clean Update event.
                    if self._current_ip is not None:
                        decky.logger.info(
                            f"mDNS IP change: {self._current_ip} -> {ip}"
                        )
                        self._unregister_locked()
                    try:
                        self._register_locked(ip)
                    except Exception as e:
                        decky.logger.error(f"mDNS register failed: {e}")
                        # Leave _current_ip None so we retry on next tick.

            self._stop_event.wait(timeout=_WATCH_INTERVAL_SEC)

    # ── Registration (must hold _lock) ───────────────────────────────────────

    def _register_locked(self, ip: str) -> None:
        from zeroconf import Zeroconf, ServiceInfo

        hostname = socket.gethostname()
        platform = detect_platform()

        properties = {
            b"id": self.agent_id.encode(),
            b"name": self.agent_name.encode(),
            b"platform": platform.encode(),
            b"version": self.version.encode(),
        }

        service_info = ServiceInfo(
            MDNS_SERVICE_TYPE,
            f"{self.agent_id}.{MDNS_SERVICE_TYPE}",
            addresses=[socket.inet_aton(ip)],
            port=self.port,
            properties=properties,
            server=f"{hostname}.local.",
        )

        zeroconf = Zeroconf()
        zeroconf.register_service(service_info)

        self._zeroconf = zeroconf
        self._service_info = service_info
        self._current_ip = ip

        decky.logger.info(
            f"mDNS service registered: {self.agent_id}._capydeploy._tcp.local on {ip}:{self.port}"
        )

        # Reset the waiting flag so that a future network loss can
        # re-notify the UI.
        self._notified_waiting = False

        if self._on_register is not None:
            try:
                self._on_register(ip, self.port)
            except Exception as e:
                decky.logger.error(f"on_register callback failed: {e}")

    def _unregister_locked(self) -> None:
        was_registered = self._zeroconf is not None and self._service_info is not None
        if was_registered:
            try:
                self._zeroconf.unregister_service(self._service_info)
                self._zeroconf.close()
            except Exception as e:
                decky.logger.error(f"Failed to unregister mDNS: {e}")
        self._zeroconf = None
        self._service_info = None
        self._current_ip = None

        if was_registered and self._on_unregister is not None:
            try:
                self._on_unregister()
            except Exception as e:
                decky.logger.error(f"on_unregister callback failed: {e}")
