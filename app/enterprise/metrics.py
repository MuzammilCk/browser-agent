"""Enterprise operational metrics — Phase 13.

Observability for the enterprise runtime. Counters/gauges/timings are
in-process (each service/worker process records its own view); durable
causality stays in the audit trail and trace system — metrics never
become a second source of runtime truth.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _Metric:
    name: str
    value: float = 0.0
    labels: dict[str, str] = field(default_factory=dict)
    kind: str = "counter"          # counter | gauge | timing
    count: int = 0
    total: float = 0.0
    last_updated: float = field(default_factory=time.time)


class EnterpriseMetrics:
    """Thread-safe in-process metrics registry.

    Required Phase 13 metric names are exposed as explicit helper
    methods so call sites stay greppable and names cannot drift.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._metrics: dict[str, _Metric] = {}

    # -- core recording ---------------------------------------------------

    def _record(self, name: str, kind: str, amount: float = 1.0) -> None:
        with self._lock:
            m = self._metrics.get(name)
            if m is None:
                m = _Metric(name=name, kind=kind)
                self._metrics[name] = m
            m.last_updated = time.time()
            if kind == "counter":
                m.value += amount
            elif kind == "gauge":
                m.value = amount
            else:  # timing
                m.count += 1
                m.total += amount
                m.value = m.total / m.count  # running average

    def increment(self, name: str, amount: float = 1.0) -> None:
        self._record(name, "counter", amount)

    def set_gauge(self, name: str, value: float) -> None:
        self._record(name, "gauge", value)

    def observe_latency(self, name: str, seconds: float) -> None:
        self._record(name, "timing", seconds)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            out: dict[str, Any] = {}
            for name, m in self._metrics.items():
                if m.kind == "timing":
                    out[name] = {
                        "avg_seconds": round(m.value, 6),
                        "count": m.count,
                        "total_seconds": round(m.total, 6),
                    }
                else:
                    out[name] = m.value
            return out

    # -- explicit Phase 13 metric names ------------------------------------

    def workflows_created(self) -> None:
        self.increment("enterprise_workflows_created")

    def run_queued(self) -> None:
        self.increment("enterprise_runs_queued")

    def run_started(self) -> None:
        self.increment("enterprise_runs_started")

    def run_completed(self) -> None:
        self.increment("enterprise_runs_completed")

    def run_failed(self) -> None:
        self.increment("enterprise_runs_failed")

    def run_cancelled(self) -> None:
        self.increment("enterprise_runs_cancelled")

    def lease_expired(self) -> None:
        self.increment("enterprise_lease_expirations")

    def stale_worker_rejected(self) -> None:
        self.increment("enterprise_stale_workers_rejected")

    def checkpoint_failure(self) -> None:
        self.increment("enterprise_checkpoint_failures")

    def hitl_pause(self) -> None:
        self.increment("enterprise_hitl_pauses")

    def browser_failure(self) -> None:
        self.increment("enterprise_browser_failures")

    def model_failure(self) -> None:
        self.increment("enterprise_model_failures")

    def policy_denial(self) -> None:
        self.increment("enterprise_policy_denials")

    def vault_failure(self) -> None:
        self.increment("enterprise_vault_failures")

    def security_violation(self) -> None:
        self.increment("enterprise_security_violations")

    def queue_delay(self, seconds: float) -> None:
        self.observe_latency("enterprise_queue_delay_seconds", seconds)

    def execution_latency(self, seconds: float) -> None:
        self.observe_latency("enterprise_execution_latency_seconds", seconds)

    def worker_utilization(self, active_leases: int, worker_count: int) -> None:
        if worker_count > 0:
            self.set_gauge(
                "enterprise_worker_utilization", active_leases / worker_count,
            )


# Shared process-wide registry (services and workers each have one).
METRICS = EnterpriseMetrics()
