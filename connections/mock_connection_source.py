"""Deterministic mock connection source for testing and safe dry-run emulation.

Generates fictional connection records representing diverse profiles without external calls.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from connections.connection_exceptions import ConnectionSourceError
from connections.connection_source import ConnectionSource

logger = logging.getLogger("linkedin_automation.connections.mock_source")


def get_default_fictional_connections() -> List[Dict[str, Any]]:
    """Return standard deterministic fictional connection records."""
    return [
        {
            "external_contact_id": "conn_ext_001",
            "name": "Sarah Connor",
            "profile_url": "https://linkedin.com/in/sarahconnor",
            "headline": "Engineering Director | Automation Systems",
            "eligibility_status": "eligible",
        },
        {
            "external_contact_id": "conn_ext_002",
            "name": "John Matrix",
            "profile_url": "https://linkedin.com/in/johnmatrix",
            "headline": "Operations Lead | Logistics & Infrastructure",
            "eligibility_status": "eligible",
        },
        {
            "external_contact_id": "conn_ext_003",
            "name": "Kyle Reese",
            "profile_url": "https://linkedin.com/in/kylereese",
            "headline": "Systems Reliability Engineer",
            "eligibility_status": "ineligible",
        },
        {
            "external_contact_id": "conn_ext_004",
            "name": "Ellen Ripley",
            "profile_url": "https://linkedin.com/in/ellenripley",
            "headline": "Executive Advisor | Technology",
            "eligibility_status": "eligible",
        },
        {
            "external_contact_id": "conn_ext_005",
            "name": "Martin Riggs",
            "profile_url": "https://linkedin.com/in/martinriggs",
            "headline": "Staff Solutions Architect",
            "eligibility_status": "eligible",
        },
    ]


class MockConnectionSource(ConnectionSource):
    """Deterministic mock connection source."""

    def __init__(
        self,
        connections: Optional[List[Dict[str, Any]]] = None,
        simulate_failure: Optional[Exception] = None,
    ) -> None:
        """Initialize mock connection source.

        Args:
            connections: Explicit list of raw connection dictionaries. If None, default set is used.
            simulate_failure: Optional exception to raise when fetch_connections is called.
        """
        self._connections = (
            connections if connections is not None else get_default_fictional_connections()
        )
        self.simulate_failure = simulate_failure

    @property
    def source_name(self) -> str:
        return "mock"

    def fetch_connections(
        self,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve connection records deterministically."""
        if self.simulate_failure is not None:
            if isinstance(self.simulate_failure, ConnectionSourceError):
                raise self.simulate_failure
            raise ConnectionSourceError(
                f"Simulated connection source failure: {self.simulate_failure}"
            ) from self.simulate_failure

        results = list(self._connections)
        if limit is not None and limit > 0:
            results = results[:limit]

        logger.debug("MockConnectionSource returning %d record(s).", len(results))
        return results

