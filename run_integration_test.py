#!/usr/bin/env python3
"""
Simple integration test runner script

This script can be run directly to execute the comprehensive integration test.
Usage:
    python3 run_integration_test.py
    
Or with make:
    make test-integration
    make test-integration-quick
"""

import sys
import subprocess
from pathlib import Path

def main():
    """Run the integration test"""
    project_root = Path(__file__).parent
    test_file = project_root / "tests" / "integration" / "test_comprehensive_e2e_workflow.py"
    
    if not test_file.exists():
        print(f"❌ Test file not found: {test_file}")
        sys.exit(1)
    
    print("🧪 Running Comprehensive E2E Integration Test...")
    print("⚠️  This will start/stop registry and agent processes")
    print("⏱️  Expected duration: ~8-10 minutes")
    print("="*60)
    
    try:
        # Run with pytest for detailed output
        result = subprocess.run([
            sys.executable, "-m", "pytest", 
            str(test_file),
            "-v", "-s", "--tb=short"
        ], cwd=project_root)
        
        if result.returncode == 0:
            print("="*60)
            print("✅ Integration test completed successfully!")
        else:
            print("="*60)
            print("❌ Integration test failed!")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n⚠️  Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error running test: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()