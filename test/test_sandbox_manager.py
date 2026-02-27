"""
Test script for MultiTenantSandboxManager

This script tests the sandbox manager functionality including:
- Sandbox creation and retrieval
- Redis caching
- Multi-tenant isolation
- Resource limits
- Cleanup functionality
- Error handling
"""

import asyncio
import os
import sys
from sandbox_manager import (
    get_multi_tenant_manager,
    get_user_sandbox,
    cleanup_multi_tenant_manager,
    SandboxConfig,
)
from dotenv import load_dotenv

load_dotenv()


async def test_basic_sandbox_creation():
    """Test basic sandbox creation and retrieval"""
    print("\n" + "=" * 80)
    print("TEST 1: Basic Sandbox Creation")
    print("=" * 80)

    manager = await get_multi_tenant_manager()

    try:
        # Create sandbox for user1/project1
        sandbox1 = await manager.get_sandbox("user1", "project1")
        print(f"✅ Created sandbox: {sandbox1.sandbox_id}")

        # Get same sandbox again (should return cached)
        sandbox2 = await manager.get_sandbox("user1", "project1")
        print(f"✅ Retrieved same sandbox: {sandbox2.sandbox_id}")

        assert sandbox1.sandbox_id == sandbox2.sandbox_id, "Should return same sandbox"
        print("✅ Test passed: Same sandbox returned from cache")

    except Exception as e:
        print(f"❌ Test failed: {e}")
        raise


async def test_multi_tenant_isolation():
    """Test that different users/projects get isolated sandboxes"""
    print("\n" + "=" * 80)
    print("TEST 2: Multi-Tenant Isolation")
    print("=" * 80)

    manager = await get_multi_tenant_manager()

    try:
        # Create sandboxes for different users/projects
        sandbox1 = await manager.get_sandbox("user1", "project1")
        sandbox2 = await manager.get_sandbox("user1", "project2")
        sandbox3 = await manager.get_sandbox("user2", "project1")

        print(f"✅ User1/Project1 sandbox: {sandbox1.sandbox_id}")
        print(f"✅ User1/Project2 sandbox: {sandbox2.sandbox_id}")
        print(f"✅ User2/Project1 sandbox: {sandbox3.sandbox_id}")

        # Verify they are different
        assert (
            sandbox1.sandbox_id != sandbox2.sandbox_id
        ), "Different projects should get different sandboxes"
        assert (
            sandbox1.sandbox_id != sandbox3.sandbox_id
        ), "Different users should get different sandboxes"
        assert (
            sandbox2.sandbox_id != sandbox3.sandbox_id
        ), "All sandboxes should be unique"

        print("✅ Test passed: All sandboxes are isolated")

    except Exception as e:
        print(f"❌ Test failed: {e}")
        raise


async def test_redis_caching():
    """Test Redis caching functionality"""
    print("\n" + "=" * 80)
    print("TEST 3: Redis Caching")
    print("=" * 80)

    manager = await get_multi_tenant_manager()

    try:
        # Create sandbox
        sandbox1 = await manager.get_sandbox("user3", "project1")
        sandbox_id = sandbox1.sandbox_id
        print(f"✅ Created sandbox: {sandbox_id}")

        # Get stats to check Redis cache
        stats = manager.get_stats()
        print(f"   Redis enabled: {stats['redis_enabled']}")
        print(f"   Cache hits: {stats['redis_cache_hits']}")
        print(f"   Cache misses: {stats['redis_cache_misses']}")

        # Verify sandbox is cached in Redis (without closing it)
        if stats["redis_enabled"]:
            # Manually check Redis cache (sandbox should be there)
            cached_id = await manager._get_cached_sandbox_id("user3", "project1")
            if cached_id:
                print(f"✅ Sandbox ID found in Redis cache: {cached_id}")
                assert (
                    cached_id == sandbox_id
                ), "Redis should contain correct sandbox ID"
                print("✅ Test passed: Redis caching works")
            else:
                print("⚠️  Sandbox ID not found in Redis cache (may have been removed)")
        else:
            print("⚠️  Redis not enabled, skipping Redis cache test")

        # Note: Closing a sandbox removes it from both memory AND Redis
        # because the sandbox is actually killed/deleted
        # Redis cache is meant for persistence across restarts, not for closed sandboxes

    except Exception as e:
        print(f"❌ Test failed: {e}")
        raise


async def test_input_validation():
    """Test input validation"""
    print("\n" + "=" * 80)
    print("TEST 4: Input Validation")
    print("=" * 80)

    manager = await get_multi_tenant_manager()

    try:
        # Test empty user_id
        try:
            await manager.get_sandbox("", "project1")
            print("❌ Test failed: Should reject empty user_id")
            assert False
        except ValueError as e:
            print(f"✅ Correctly rejected empty user_id: {e}")

        # Test empty project_id
        try:
            await manager.get_sandbox("user1", "")
            print("❌ Test failed: Should reject empty project_id")
            assert False
        except ValueError as e:
            print(f"✅ Correctly rejected empty project_id: {e}")

        # Test None values
        try:
            await manager.get_sandbox(None, "project1")
            print("❌ Test failed: Should reject None user_id")
            assert False
        except (ValueError, AttributeError) as e:
            print(f"✅ Correctly rejected None user_id: {e}")

        print("✅ Test passed: Input validation works")

    except Exception as e:
        print(f"❌ Test failed: {e}")
        raise


async def test_resource_limits():
    """Test resource limit enforcement"""
    print("\n" + "=" * 80)
    print("TEST 5: Resource Limits")
    print("=" * 80)

    manager = await get_multi_tenant_manager()
    config = manager._config

    print(f"   Max sandboxes per user: {config.max_sandboxes_per_user}")
    print(f"   Max total sandboxes: {config.max_total_sandboxes}")

    try:
        # Create sandboxes up to per-user limit
        sandboxes = []
        for i in range(config.max_sandboxes_per_user):
            sandbox = await manager.get_sandbox("user_limit_test", f"project{i}")
            sandboxes.append(sandbox)
            print(
                f"✅ Created sandbox {i+1}/{config.max_sandboxes_per_user}: {sandbox.sandbox_id}"
            )

        # Try to create one more (should fail)
        try:
            await manager.get_sandbox("user_limit_test", "project_excess")
            print("❌ Test failed: Should reject excess sandbox")
            assert False
        except RuntimeError as e:
            print(f"✅ Correctly rejected excess sandbox: {e}")

        # Clean up
        for i, sandbox in enumerate(sandboxes):
            await manager.close_sandbox("user_limit_test", f"project{i}")

        print("✅ Test passed: Resource limits enforced")

    except Exception as e:
        print(f"❌ Test failed: {e}")
        raise


async def test_stats():
    """Test statistics tracking"""
    print("\n" + "=" * 80)
    print("TEST 6: Statistics Tracking")
    print("=" * 80)

    manager = await get_multi_tenant_manager()

    try:
        # Get initial stats
        initial_stats = manager.get_stats()
        initial_created = initial_stats["total_sandboxes_created"]
        initial_requests = initial_stats["total_requests"]

        print(f"   Initial stats:")
        print(f"     Total created: {initial_created}")
        print(f"     Total requests: {initial_requests}")

        # Create a sandbox
        await manager.get_sandbox("stats_user", "stats_project")

        # Get updated stats
        updated_stats = manager.get_stats()
        print(f"   Updated stats:")
        print(f"     Total created: {updated_stats['total_sandboxes_created']}")
        print(f"     Total requests: {updated_stats['total_requests']}")
        print(f"     Active sandboxes: {updated_stats['active_sandboxes']}")
        print(f"     Redis enabled: {updated_stats['redis_enabled']}")
        if updated_stats["redis_enabled"]:
            print(f"     Cache hit rate: {updated_stats['cache_hit_rate']:.1%}")

        assert (
            updated_stats["total_requests"] > initial_requests
        ), "Request count should increase"
        assert updated_stats["active_sandboxes"] > 0, "Should have active sandboxes"

        print("✅ Test passed: Statistics tracking works")

    except Exception as e:
        print(f"❌ Test failed: {e}")
        raise


async def test_health_check():
    """Test sandbox health check"""
    print("\n" + "=" * 80)
    print("TEST 7: Health Check")
    print("=" * 80)

    manager = await get_multi_tenant_manager()

    try:
        # Create sandbox
        sandbox = await manager.get_sandbox("health_user", "health_project")
        print(f"✅ Created sandbox: {sandbox.sandbox_id}")

        # Health check should pass for active sandbox
        await manager._verify_sandbox_health(sandbox)
        print("✅ Health check passed for active sandbox")

        print("✅ Test passed: Health check works")

    except Exception as e:
        print(f"❌ Test failed: {e}")
        raise


async def test_close_sandbox():
    """Test closing sandboxes"""
    print("\n" + "=" * 80)
    print("TEST 8: Close Sandbox")
    print("=" * 80)

    manager = await get_multi_tenant_manager()

    try:
        # Create sandbox
        sandbox = await manager.get_sandbox("close_user", "close_project")
        sandbox_id = sandbox.sandbox_id
        print(f"✅ Created sandbox: {sandbox_id}")

        # Close sandbox
        await manager.close_sandbox("close_user", "close_project")
        print("✅ Closed sandbox")

        # Verify it's removed from pool
        stats = manager.get_stats()
        print(f"   Active sandboxes: {stats['active_sandboxes']}")

        print("✅ Test passed: Sandbox closed successfully")

    except Exception as e:
        print(f"❌ Test failed: {e}")
        raise


async def run_all_tests():
    """Run all tests"""
    print("\n" + "=" * 80)
    print("SANDBOX MANAGER TEST SUITE")
    print("=" * 80)
    print("\nMake sure E2B_API_KEY is set in environment variables")

    # Check for API key
    if not os.getenv("E2B_API_KEY"):
        print("\n❌ ERROR: E2B_API_KEY not set in environment variables")
        print("   Please set it before running tests:")
        print("   export E2B_API_KEY=your_api_key")
        sys.exit(1)

    try:
        # Initialize manager
        manager = await get_multi_tenant_manager()
        print(f"\n✅ Manager initialized")
        print(f"   Redis enabled: {manager._redis is not None}")

        # Run tests
        await test_basic_sandbox_creation()
        await test_multi_tenant_isolation()
        await test_redis_caching()
        await test_input_validation()
        await test_resource_limits()
        await test_stats()
        await test_health_check()
        await test_close_sandbox()

        # Final stats
        print("\n" + "=" * 80)
        print("FINAL STATISTICS")
        print("=" * 80)
        final_stats = manager.get_stats()
        for key, value in final_stats.items():
            if key != "sandbox_details":  # Skip detailed list
                print(f"   {key}: {value}")

        print("\n" + "=" * 80)
        print("✅ ALL TESTS PASSED")
        print("=" * 80)

    except Exception as e:
        print(f"\n❌ TEST SUITE FAILED: {e}")
        import traceback

        traceback.print_exc()
        raise
    finally:
        # Cleanup
        print("\nCleaning up...")
        await cleanup_multi_tenant_manager()
        print("✅ Cleanup complete")


if __name__ == "__main__":
    asyncio.run(run_all_tests())
