#!/usr/bin/env python3
"""
Test script to demonstrate state-splitting among workers.
Shows how 50 states are distributed among 5 workers using round-robin.
"""

# Simulate the state splitting logic
def split_states_among_workers(state_ids, num_workers):
    """Split states evenly among workers (round-robin)."""
    assignments = {}

    # Initialize empty lists for each worker
    for worker_id in range(num_workers):
        assignments[worker_id] = []

    # Round-robin distribution
    for idx, state in enumerate(state_ids):
        worker_id = idx % num_workers
        assignments[worker_id].append(state)

    return assignments


if __name__ == "__main__":
    # All 50 US states
    all_states = [
        'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
        'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
        'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
        'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
        'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY'
    ]

    num_workers = 5

    print("=" * 70)
    print(f"STATE SPLITTING DEMONSTRATION: {len(all_states)} states across {num_workers} workers")
    print("=" * 70)
    print()

    assignments = split_states_among_workers(all_states, num_workers)

    for worker_id in range(num_workers):
        assigned = assignments[worker_id]
        print(f"Worker {worker_id}:")
        print(f"  States ({len(assigned)}): {', '.join(assigned)}")
        print()

    print("=" * 70)
    print("BENEFITS:")
    print("  - No database locking needed (workers have exclusive states)")
    print("  - Even distribution (10 states per worker)")
    print("  - City-first processing within each state")
    print("  - No cross-worker competition for targets")
    print("=" * 70)
