# Yellow Pages Worker Pool - State Splitting Implementation

## Overview

Implemented city-first state-splitting architecture for the Yellow Pages 5-worker pool, matching the Google Maps approach.

## What Changed

### File Modified: `scrape_yp/worker_pool.py`

**Architecture Change:**
- **Before**: All workers shared the same state list and competed for targets using database locking
- **After**: States are split among workers using round-robin distribution; each worker processes only its assigned states

### Key Changes:

1. **Module Docstring** (Lines 1-16)
   - Updated to document state-splitting architecture
   - Added architecture notes about round-robin distribution and city-first approach

2. **WorkerPoolManager Class**
   - **New Method**: `_split_states_among_workers()` (Lines 716-742)
     - Implements round-robin state distribution among workers
     - Returns dict mapping worker_id to list of assigned states
     - Logs assignments for visibility

   - **Modified `__init__`** (Line 714)
     - Added `self.worker_state_assignments` to store state assignments

   - **Modified `start()`** (Lines 744-769)
     - Changed to pass only assigned states to each worker (not full state list)
     - Added state assignment logging
     - Skips workers with no assigned states

## Benefits

### Performance
- **No Cross-Worker Competition**: Workers have exclusive states, eliminating database locking overhead
- **Even Load Distribution**: Round-robin ensures each worker gets equal number of states (10 states per worker for 50 states / 5 workers)
- **City-First Processing**: Within each state, cities are processed in order

### Reliability
- **No Database Lock Contention**: Each worker queries only its assigned states
- **Predictable Resource Usage**: Each worker processes exactly its assigned states
- **Simplified Monitoring**: Clear worker-to-state mapping for troubleshooting

## Example Distribution (50 States, 5 Workers)

```
Worker 0 (10 states): AL, CO, HI, KS, MA, MT, NM, OK, SD, VA
Worker 1 (10 states): AK, CT, ID, KY, MI, NE, NY, OR, TN, WA
Worker 2 (10 states): AZ, DE, IL, LA, MN, NV, NC, PA, TX, WV
Worker 3 (10 states): AR, FL, IN, ME, MS, NH, ND, RI, UT, WI
Worker 4 (10 states): CA, GA, IA, MD, MO, NJ, OH, SC, VT, WY
```

## Testing

Test script created: `test_state_splitting.py`
- Demonstrates round-robin distribution
- Shows even balance across workers
- Run with: `./venv/bin/python test_state_splitting.py`

## Compatibility

- **Backward Compatible**: No changes to database schema or API
- **Dashboard Integration**: Works seamlessly with YP Runner dashboard in discover page
- **Worker Config**: Uses existing WorkerConfig settings (no config changes needed)

## Usage

The state-splitting happens automatically when starting the worker pool:

```python
# States are automatically split among workers
pool = WorkerPoolManager(
    num_workers=5,
    proxy_file="path/to/proxies.txt",
    state_ids=['AL', 'AK', 'AZ', ...]  # Full state list
)
pool.start()  # Each worker gets subset of states
```

## Log Output

When starting the worker pool, you'll see:

```
======================================================================
Starting 5 workers with city-first state splitting...
Total states: 50 (AL, AK, AZ, AR, CA, ...)
======================================================================
Worker 0 assigned 10 states: AL, CO, HI, KS, MA, MT, NM, OK, SD, VA
Worker 1 assigned 10 states: AK, CT, ID, KY, MI, NE, NY, OR, TN, WA
Worker 2 assigned 10 states: AZ, DE, IL, LA, MN, NV, NC, PA, TX, WV
Worker 3 assigned 10 states: AR, FL, IN, ME, MS, NH, ND, RI, UT, WI
Worker 4 assigned 10 states: CA, GA, IA, MD, MO, NJ, OH, SC, VT, WY
Started worker 0 (PID: 12345) - 10 states
Started worker 1 (PID: 12346) - 10 states
Started worker 2 (PID: 12347) - 10 states
Started worker 3 (PID: 12348) - 10 states
Started worker 4 (PID: 12349) - 10 states
All 5 workers started with state assignments
======================================================================
```

## Implementation Details

### Round-Robin Algorithm
```python
for idx, state in enumerate(states):
    worker_id = idx % self.num_workers
    assignments[worker_id].append(state)
```

This ensures:
- States 0, 5, 10, 15, ... go to Worker 0
- States 1, 6, 11, 16, ... go to Worker 1
- States 2, 7, 12, 17, ... go to Worker 2
- States 3, 8, 13, 18, ... go to Worker 3
- States 4, 9, 14, 19, ... go to Worker 4

### Worker Isolation
Each worker's `worker_main()` function receives only its assigned states:
```python
worker = multiprocessing.Process(
    target=worker_main,
    args=(worker_id, proxy_file, assigned_states, stop_event)  # Only assigned states
)
```

## Next Steps

The implementation is complete and ready to use. The YP Runner dashboard will automatically use the new state-splitting architecture when you start the worker pool.

To test:
1. Navigate to Discover page in dashboard
2. Select "Yellow Pages (5-Worker)" from source dropdown
3. Click "Start Pool"
4. Check logs to see state assignments

---

**Date**: 2025-11-22
**Modified Files**: `scrape_yp/worker_pool.py`
**Test Files**: `test_state_splitting.py`
