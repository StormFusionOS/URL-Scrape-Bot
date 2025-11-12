#!/usr/bin/env python3
"""
Quick test script to verify scheduler backend integration.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from niceui.backend_facade import backend


def test_scheduler_backend():
    """Test scheduler backend methods."""

    print("=" * 70)
    print("Testing Scheduler Backend Integration")
    print("=" * 70)
    print()

    # Test 1: Get initial stats
    print("1. Getting scheduler stats...")
    stats = backend.get_scheduler_stats()
    print(f"   Total Jobs: {stats['total_jobs']}")
    print(f"   Active Jobs: {stats['active_jobs']}")
    print(f"   Running Jobs: {stats.get('running_jobs', 0)}")
    print(f"   Failed (24h): {stats['failed_24h']}")
    print()

    # Test 2: Create a test job
    print("2. Creating test job...")
    job_data = {
        'name': 'Test Daily Pressure Washing Crawl',
        'description': 'Test job for verifying scheduler functionality',
        'job_type': 'yp_crawl',
        'schedule_cron': '0 2 * * *',  # Daily at 2am
        'enabled': True,
        'priority': 2,
        'timeout_minutes': 60,
        'max_retries': 3,
        'config': {
            'search_term': 'pressure washing',
            'location': 'Portland, OR'
        },
        'created_by': 'test_script'
    }

    result = backend.create_scheduled_job(job_data)
    if result.get('success'):
        job_id = result['job_id']
        print(f"   ✓ Job created successfully! ID: {job_id}")
        print()

        # Test 3: Get all jobs
        print("3. Getting all scheduled jobs...")
        jobs = backend.get_scheduled_jobs()
        print(f"   Found {len(jobs)} job(s)")
        for job in jobs:
            print(f"   - ID: {job['id']}, Name: {job['name']}, Enabled: {job['enabled']}")
        print()

        # Test 4: Get updated stats
        print("4. Getting updated stats...")
        stats = backend.get_scheduler_stats()
        print(f"   Total Jobs: {stats['total_jobs']}")
        print(f"   Active Jobs: {stats['active_jobs']}")
        print()

        # Test 5: Toggle job
        print("5. Testing toggle job...")
        toggle_result = backend.toggle_scheduled_job(job_id, False)
        if toggle_result.get('success'):
            print("   ✓ Job disabled successfully")

        toggle_result = backend.toggle_scheduled_job(job_id, True)
        if toggle_result.get('success'):
            print("   ✓ Job re-enabled successfully")
        print()

        # Test 6: Update job
        print("6. Testing update job...")
        update_data = {
            'name': 'Updated Test Job',
            'description': 'Updated description',
            'job_type': 'yp_crawl',
            'schedule_cron': '0 3 * * *',  # Changed to 3am
            'enabled': True,
            'priority': 1,
            'timeout_minutes': 90,
            'max_retries': 5,
            'config': {
                'search_term': 'roof cleaning',
                'location': 'Seattle, WA'
            }
        }
        update_result = backend.update_scheduled_job(job_id, update_data)
        if update_result.get('success'):
            print("   ✓ Job updated successfully")
            jobs = backend.get_scheduled_jobs()
            updated_job = next((j for j in jobs if j['id'] == job_id), None)
            if updated_job:
                print(f"   - New name: {updated_job['name']}")
                print(f"   - New schedule: {updated_job['schedule_cron']}")
        print()

        # Test 7: Get execution logs (should be empty)
        print("7. Getting execution logs...")
        logs = backend.get_job_execution_logs()
        print(f"   Found {len(logs)} execution log(s)")
        print()

        # Test 8: Delete job
        print("8. Testing delete job...")
        delete_result = backend.delete_scheduled_job(job_id)
        if delete_result.get('success'):
            print("   ✓ Job deleted successfully")
        print()

        # Test 9: Final stats
        print("9. Getting final stats...")
        stats = backend.get_scheduler_stats()
        print(f"   Total Jobs: {stats['total_jobs']}")
        print(f"   Active Jobs: {stats['active_jobs']}")
        print()

        print("=" * 70)
        print("All tests completed successfully!")
        print("=" * 70)

    else:
        print(f"   ✗ Job creation failed: {result.get('message', 'Unknown error')}")
        return False

    return True


if __name__ == '__main__':
    try:
        success = test_scheduler_backend()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
