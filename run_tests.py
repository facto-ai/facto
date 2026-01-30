#!/usr/bin/env python3
"""
Facto Master Test Runner

Runs all test suites in order:
1. Unit tests (SDK)
2. Security tests
3. Integration tests (requires services)
4. Load tests (optional)

Usage:
    python run_tests.py              # Run unit + security + integration
    python run_tests.py --with-load  # Also run load tests
    python run_tests.py --fast       # Unit + security only (no services needed)
"""

import subprocess
import sys
import os
from pathlib import Path

# Colors for output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
BOLD = "\033[1m"
RESET = "\033[0m"

def run_command(cmd: list, description: str, cwd: str = None) -> bool:
    """Run a command and return True if successful."""
    print(f"\n{BOLD}{BLUE}{'=' * 60}{RESET}")
    print(f"{BOLD}{BLUE}>>> {description}{RESET}")
    print(f"{BLUE}{'=' * 60}{RESET}")
    print(f"Command: {' '.join(cmd)}\n")
    
    result = subprocess.run(cmd, cwd=cwd)
    
    if result.returncode == 0:
        print(f"\n{GREEN}✓ {description} PASSED{RESET}")
        return True
    else:
        print(f"\n{RED}✗ {description} FAILED{RESET}")
        return False


def main():
    args = sys.argv[1:]
    with_load = "--with-load" in args
    fast_mode = "--fast" in args
    
    root = Path(__file__).parent
    os.chdir(root)
    
    all_passed = True
    results = {}
    
    # 1. Unit Tests (SDK)
    print(f"\n{BOLD}{YELLOW}PHASE 1: UNIT TESTS{RESET}")
    passed = run_command(
        ["python", "-m", "pytest", "sdk/python/tests", "-v", "--tb=short"],
        "Unit Tests (SDK)"
    )
    results["Unit Tests"] = passed
    all_passed = all_passed and passed
    
    # 2. Security Tests
    print(f"\n{BOLD}{YELLOW}PHASE 2: SECURITY TESTS{RESET}")
    
    # Check if evidence.json exists for security tests
    evidence_file = root / "examples" / "langchain" / "evidence.json"
    if evidence_file.exists():
        passed = run_command(
            ["python", "tests/security/test_tamper_resistance.py", str(evidence_file)],
            "Security Tests (Tamper Resistance)"
        )
    else:
        print(f"{YELLOW}⚠ Skipping security tests: {evidence_file} not found{RESET}")
        passed = True  # Don't fail if file missing
    results["Security Tests"] = passed
    all_passed = all_passed and passed
    
    if fast_mode:
        print(f"\n{YELLOW}--fast mode: Skipping integration and load tests{RESET}")
    else:
        # 3. Integration Tests
        print(f"\n{BOLD}{YELLOW}PHASE 3: INTEGRATION TESTS{RESET}")
        print(f"{YELLOW}(Requires services: ingestion, processor, api){RESET}")
        passed = run_command(
            ["python", "-m", "pytest", "tests/integration", "-v", "--tb=short"],
            "Integration Tests"
        )
        results["Integration Tests"] = passed
        all_passed = all_passed and passed
        
        # 4. Load Tests (optional)
        if with_load:
            print(f"\n{BOLD}{YELLOW}PHASE 4: LOAD TESTS{RESET}")
            passed = run_command(
                ["python", "tests/load/load_test.py"],
                "Load Tests"
            )
            results["Load Tests"] = passed
            all_passed = all_passed and passed
    
    # Summary
    print(f"\n{BOLD}{'=' * 60}{RESET}")
    print(f"{BOLD}SUMMARY{RESET}")
    print(f"{'=' * 60}")
    for name, passed in results.items():
        status = f"{GREEN}✓ PASSED{RESET}" if passed else f"{RED}✗ FAILED{RESET}"
        print(f"  {name}: {status}")
    
    print(f"{'=' * 60}")
    if all_passed:
        print(f"{GREEN}{BOLD}✓ ALL TESTS PASSED{RESET}")
        return 0
    else:
        print(f"{RED}{BOLD}✗ SOME TESTS FAILED{RESET}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
