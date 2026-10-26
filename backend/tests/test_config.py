"""Tests for core configuration (app.core.config)."""

from __future__ import annotations

import os

import pytest

from app.core.config import KubernetesMode, Settings


class TestSettings:
    """Verify that Settings loads and validates correctly."""

    def test_defaults(self) -> None:
        """Default settings should match local development values."""
        s = Settings()
        assert s.kubernetes_mode == KubernetesMode.LOCAL
        assert s.prometheus_url == "http://localhost:9090"
        assert "http://localhost:5173" in s.cors_origins
        assert "http://localhost:5174" in s.cors_origins
        assert s.log_level == "INFO"
        assert s.max_query_range_hours == 168  # 7 days
        assert s.metrics_step_seconds == 60

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Environment variables should override defaults."""
        monkeypatch.setenv("KUBERNETES_MODE", "in_cluster")
        monkeypatch.setenv("PROMETHEUS_URL", "http://prom:9090")
        monkeypatch.setenv("CORS_ORIGINS", '["http://example.com"]')
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")

        s = Settings()
        assert s.kubernetes_mode == KubernetesMode.IN_CLUSTER
        assert s.prometheus_url == "http://prom:9090"
        assert s.cors_origins == ["http://example.com"]
        assert s.log_level == "DEBUG"

    def test_cors_origins_comma_separated_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Comma-separated string in CORS_ORIGINS should parse into list."""
        monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173, http://localhost:5174")
        s = Settings()
        assert s.cors_origins == ["http://localhost:5173", "http://localhost:5174"]

    def test_kubernetes_mode_enum_values(self) -> None:
        """KubernetesMode enum should have exactly two values."""
        assert KubernetesMode.LOCAL.value == "local"
        assert KubernetesMode.IN_CLUSTER.value == "in_cluster"
        assert len(KubernetesMode) == 2

    def test_kube_context_default_none(self) -> None:
        """kube_context should default to None (current context)."""
        s = Settings()
        assert s.kube_context is None
