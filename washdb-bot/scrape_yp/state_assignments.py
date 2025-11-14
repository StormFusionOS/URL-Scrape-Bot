"""
State assignments for 10-worker parallel scraping system.

Each worker is assigned exactly 5 US states for balanced load distribution.
State assignments are designed to:
1. Distribute workload evenly across workers
2. Avoid geographic clustering (spread across US)
3. Mix high-population and low-population states
4. Enable independent monitoring per worker
"""

from typing import Dict, List

# 10 workers × 5 states each = 50 US states + DC
# Note: Worker 4 gets 6 states to accommodate DC (51 total / 10 = 5.1)
STATE_ASSIGNMENTS: Dict[int, List[str]] = {
    0: ["CA", "MT", "RI", "MS", "ND"],  # Mix: Largest + small states
    1: ["TX", "WY", "VT", "WV", "SD"],  # Mix: Large + small states
    2: ["FL", "AK", "NH", "NM", "DE"],  # Mix: Large + small + sparse
    3: ["NY", "ID", "ME", "NV", "HI"],  # Mix: Large + small + islands
    4: ["PA", "UT", "MA", "NE", "NJ", "DC"],  # Mix: Large + medium + NJ + capital (6 states)
    5: ["IL", "OR", "CT", "KS", "AR"],  # Mix: Large + medium states
    6: ["OH", "OK", "IA", "LA", "WI"],  # Mix: Midwest + South
    7: ["GA", "AZ", "KY", "SC", "MN"],  # Mix: South + Southwest + North
    8: ["NC", "WA", "AL", "CO", "IN"],  # Mix: East Coast + West + Central
    9: ["MI", "TN", "MD", "MO", "VA"],  # Mix: Great Lakes + Mid-Atlantic
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
        worker_id: Worker number (0-9)

    Returns:
        List of 2-letter state codes (e.g., ["CA", "MT", "RI", "MS", "ND"])

    Raises:
        ValueError: If worker_id is not in range 0-9
    """
    if worker_id not in STATE_ASSIGNMENTS:
        raise ValueError(f"Invalid worker_id: {worker_id}. Must be 0-9.")

    return STATE_ASSIGNMENTS[worker_id]


def get_worker_for_state(state_id: str) -> int:
    """
    Get the worker ID assigned to a specific state.

    Args:
        state_id: 2-letter state code (e.g., "CA")

    Returns:
        Worker ID (0-9)

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


def get_proxy_assignments(worker_id: int, proxies_per_worker: int = 5) -> List[int]:
    """
    Get proxy indices assigned to a specific worker.

    With 50 proxies and 10 workers:
    - Worker 0: Proxies 0-4
    - Worker 1: Proxies 5-9
    - Worker N: Proxies (N*5) to (N*5+4)

    Args:
        worker_id: Worker number (0-9)
        proxies_per_worker: Number of proxies per worker (default 5)

    Returns:
        List of proxy indices (e.g., [0, 1, 2, 3, 4] for worker 0)

    Raises:
        ValueError: If worker_id is not in range 0-9
    """
    if worker_id not in range(10):
        raise ValueError(f"Invalid worker_id: {worker_id}. Must be 0-9.")

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
        # Check each worker has 5 or 6 states (worker 4 has 6 for DC)
        if worker_id == 4:
            assert len(states) == 6, f"Worker {worker_id} has {len(states)} states (expected 6)"
        else:
            assert len(states) == 5, f"Worker {worker_id} has {len(states)} states (expected 5)"

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
    print(f"  - 10 workers")
    print(f"  - 5 states per worker (worker 4 has 6)")
    print(f"  - 51 total states (50 + DC)")
    print(f"  - No duplicates")
    print(f"  - No missing states")


if __name__ == "__main__":
    # Validate assignments on import
    validate_assignments()

    # Print assignment summary
    print("\n" + "="*70)
    print("STATE ASSIGNMENTS FOR 10-WORKER SYSTEM")
    print("="*70)

    for worker_id in range(10):
        states = get_states_for_worker(worker_id)
        proxies = get_proxy_assignments(worker_id)
        print(f"Worker {worker_id}: States {states} | Proxies {proxies}")

    print("="*70)
