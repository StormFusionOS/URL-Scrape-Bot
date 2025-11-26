"""
State assignments for Yelp 5-worker system.

Divides all 50 US states across 5 workers for parallel processing.
"""

# All 50 US states
ALL_STATES = [
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
    'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
    'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
    'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
    'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY'
]

# State assignments for 5 workers (10 states each)
WORKER_ASSIGNMENTS = {
    0: ['AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA'],
    1: ['HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD'],
    2: ['MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ'],
    3: ['NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC'],
    4: ['SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY']
}


def get_states_for_worker(worker_id: int) -> list[str]:
    """
    Get assigned states for a worker.

    Args:
        worker_id: Worker ID (0-4)

    Returns:
        List of 2-letter state codes
    """
    if worker_id not in WORKER_ASSIGNMENTS:
        raise ValueError(f"Invalid worker_id: {worker_id}. Must be 0-4")

    return WORKER_ASSIGNMENTS[worker_id]


def get_worker_for_state(state_id: str) -> int:
    """
    Get worker ID responsible for a state.

    Args:
        state_id: 2-letter state code

    Returns:
        Worker ID (0-4)
    """
    state_id = state_id.upper()

    for worker_id, states in WORKER_ASSIGNMENTS.items():
        if state_id in states:
            return worker_id

    raise ValueError(f"State {state_id} not found in assignments")


def validate_assignments():
    """Validate that all states are assigned exactly once."""
    assigned_states = set()

    for worker_id, states in WORKER_ASSIGNMENTS.items():
        for state in states:
            if state in assigned_states:
                raise ValueError(f"State {state} assigned multiple times")
            assigned_states.add(state)

    missing_states = set(ALL_STATES) - assigned_states
    if missing_states:
        raise ValueError(f"States not assigned: {missing_states}")

    extra_states = assigned_states - set(ALL_STATES)
    if extra_states:
        raise ValueError(f"Invalid states in assignments: {extra_states}")

    print(f"✅ State assignments validated: {len(ALL_STATES)} states across {len(WORKER_ASSIGNMENTS)} workers")


if __name__ == "__main__":
    # Validate on import
    validate_assignments()

    # Print assignments
    print("\n5-Worker State Assignments:")
    print("="*60)
    for worker_id in sorted(WORKER_ASSIGNMENTS.keys()):
        states = WORKER_ASSIGNMENTS[worker_id]
        print(f"Worker {worker_id + 1}: {', '.join(states)} ({len(states)} states)")
    print("="*60)
