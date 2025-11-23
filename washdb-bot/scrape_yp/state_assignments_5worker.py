"""
State assignments for 5-worker parallel scraping system.

Each worker is assigned exactly 10 US states for balanced load distribution.
State assignments are designed to:
1. Distribute workload evenly across workers
2. Avoid geographic clustering (spread across US)
3. Mix high-population and low-population states
4. Enable independent monitoring per worker
"""

from typing import Dict, List

# 5 workers × 10 states each = 50 US states + DC
# Note: Worker 4 gets 11 states to accommodate DC (51 total / 5 = 10.2)
STATE_ASSIGNMENTS: Dict[int, List[str]] = {
    0: ["CA", "TX", "FL", "NY", "PA", "IL", "OH", "GA", "NC", "MI"],  # Mix: Large states
    1: ["NJ", "VA", "WA", "AZ", "MA", "TN", "IN", "MO", "MD", "WI"],  # Mix: Medium-large states
    2: ["CO", "MN", "SC", "AL", "LA", "KY", "OR", "OK", "CT", "UT"],  # Mix: Medium states
    3: ["IA", "NV", "AR", "MS", "KS", "NM", "NE", "WV", "ID", "HI"],  # Mix: Smaller states
    4: ["NH", "ME", "RI", "MT", "DE", "SD", "ND", "AK", "VT", "WY", "DC"],  # Mix: Small + DC (11 states)
}

# Reverse mapping: state_id -> worker_id
STATE_TO_WORKER: Dict[str, int] = {}
for worker_id, states in STATE_ASSIGNMENTS.items():
    for state in states:
        STATE_TO_WORKER[state] = worker_id


def get_states_for_worker(worker_id: int) -> List[str]:
    """
    Get list of state IDs assigned to a specific worker.

    Args:
        worker_id: Worker number (0-4)

    Returns:
        List of 2-letter state codes (e.g., ["CA", "TX", "FL", "NY", ...])

    Raises:
        ValueError: If worker_id is not in range 0-4
    """
    if worker_id not in STATE_ASSIGNMENTS:
        raise ValueError(f"Invalid worker_id: {worker_id}. Must be 0-4.")

    return STATE_ASSIGNMENTS[worker_id]


def get_worker_for_state(state_id: str) -> int:
    """
    Get the worker ID assigned to a specific state.

    Args:
        state_id: 2-letter state code (e.g., "CA")

    Returns:
        Worker ID (0-4)

    Raises:
        ValueError: If state_id is not found
    """
    state_id = state_id.upper()
    if state_id not in STATE_TO_WORKER:
        raise ValueError(f"Invalid state_id: {state_id}")

    return STATE_TO_WORKER[state_id]


def get_all_assignments() -> Dict[int, List[str]]:
    """
    Get complete state assignment mapping.

    Returns:
        Dictionary mapping worker_id -> list of state_ids
    """
    return STATE_ASSIGNMENTS.copy()


def get_proxy_assignments(worker_id: int, proxies_per_worker: int = 10) -> List[int]:
    """
    Get proxy indices assigned to a specific worker.

    With 50 proxies and 5 workers:
    - Worker 0: Proxies 0-9
    - Worker 1: Proxies 10-19
    - Worker N: Proxies (N*10) to (N*10+9)

    Args:
        worker_id: Worker number (0-4)
        proxies_per_worker: Number of proxies per worker (default 10)

    Returns:
        List of proxy indices (e.g., [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] for worker 0)

    Raises:
        ValueError: If worker_id is not in range 0-4
    """
    if worker_id not in range(5):
        raise ValueError(f"Invalid worker_id: {worker_id}. Must be 0-4.")

    start_idx = worker_id * proxies_per_worker
    end_idx = start_idx + proxies_per_worker

    return list(range(start_idx, end_idx))


def validate_assignments():
    """
    Validate that all 50 US states + DC are assigned exactly once.

    Raises:
        AssertionError: If validation fails
    """
    # All 50 US states + DC
    all_states = {
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
        "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
        "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
        "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
        "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
        "DC"
    }

    # Collect all assigned states
    assigned_states = set()
    for worker_id, states in STATE_ASSIGNMENTS.items():
        # Check each worker has 10 or 11 states (worker 4 has 11 for DC)
        if worker_id == 4:
            assert len(states) == 11, f"Worker {worker_id} has {len(states)} states (expected 11)"
        else:
            assert len(states) == 10, f"Worker {worker_id} has {len(states)} states (expected 10)"

        # Check for duplicates within worker
        assert len(states) == len(set(states)), f"Worker {worker_id} has duplicate states"

        # Add to global set
        for state in states:
            assert state not in assigned_states, f"State {state} assigned multiple times"
            assigned_states.add(state)

    # Check all states are assigned
    missing = all_states - assigned_states
    assert not missing, f"Missing states: {missing}"

    # Check no extra states
    extra = assigned_states - all_states
    assert not extra, f"Extra states: {extra}"

    print("✓ State assignments validated successfully")
    print(f"  - 5 workers")
    print(f"  - 10 states per worker (worker 4 has 11)")
    print(f"  - 51 total states (50 + DC)")
    print(f"  - No duplicates")
    print(f"  - No missing states")


if __name__ == "__main__":
    # Validate assignments on import
    validate_assignments()

    # Print assignment summary
    print("\n" + "="*70)
    print("STATE ASSIGNMENTS FOR 5-WORKER SYSTEM")
    print("="*70)

    for worker_id in range(5):
        states = get_states_for_worker(worker_id)
        proxies = get_proxy_assignments(worker_id)
        print(f"Worker {worker_id}: States {states} | Proxies {proxies}")

    print("="*70)
