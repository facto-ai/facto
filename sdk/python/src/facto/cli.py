#!/usr/bin/env python3
"""
Facto CLI - Offline Evidence Verification Tool.

Verifies evidence bundles independently, without requiring network access.
This is the key differentiator: "Don't trust us. Verify it yourself."

Usage:
    facto verify evidence-bundle.json
"""

import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

# Import canonical form builder from crypto module to ensure consistency
from .crypto import CryptoProvider

# ANSI color codes for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"

# Shared crypto provider for canonical form building
_crypto = CryptoProvider()


def checkmark(success: bool) -> str:
    """Return a colored checkmark or X."""
    return f"{GREEN}✓{RESET}" if success else f"{RED}✗{RESET}"


def build_canonical_form(event: Dict[str, Any]) -> str:
    """
    Build the canonical JSON form for hashing/signing.
    
    Uses the shared CryptoProvider to ensure consistency between
    SDK and CLI verification.
    
    Signed fields (immutable):
        - facto_id, agent_id, session_id, action_type, status
        - input_data, output_data
        - started_at, completed_at
        - parent_facto_id, prev_hash
        - execution_meta: model_id, seed, sdk_version, temperature, tool_calls
    
    Mutable metadata (not signed):
        - execution_meta: model_hash, max_tokens, sdk_language, tags
    """
    return _crypto.build_canonical_form(event)


def compute_sha3_256(data: str) -> str:
    """Compute SHA3-256 hash of a string."""
    hasher = hashlib.sha3_256()
    hasher.update(data.encode("utf-8"))
    return hasher.hexdigest()


def verify_event_hash(event: Dict[str, Any]) -> Tuple[bool, str, str]:
    """
    Verify an event's SHA3-256 hash.
    
    Returns: (is_valid, computed_hash, stored_hash)
    """
    canonical = build_canonical_form(event)
    computed = compute_sha3_256(canonical)
    stored = event["proof"]["event_hash"]
    return computed == stored, computed, stored


def verify_event_signature(event: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Verify an event's Ed25519 signature.
    
    Returns: (is_valid, error_message)
    """
    try:
        public_key_b64 = event["proof"]["public_key"]
        signature_b64 = event["proof"]["signature"]
        
        public_key = base64.b64decode(public_key_b64)
        signature = base64.b64decode(signature_b64)
        
        if len(public_key) != 32:
            return False, "Invalid public key length"
        if len(signature) != 64:
            return False, "Invalid signature length"
        
        canonical = build_canonical_form(event)
        verify_key = VerifyKey(public_key)
        verify_key.verify(canonical.encode("utf-8"), signature)
        return True, ""
    except BadSignatureError:
        return False, "Signature verification failed"
    except Exception as e:
        return False, str(e)


def verify_chain_integrity(events: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    """
    Verify the prev_hash chain linking between events.
    
    Events should be sorted by completed_at (oldest first).
    
    Returns: (all_valid, list of error messages)
    """
    if not events:
        return True, []
    
    # Sort events by completed_at
    sorted_events = sorted(events, key=lambda e: e["completed_at"])
    
    errors = []
    expected_prev_hash = "0" * 64  # First event should have zero hash
    
    for i, event in enumerate(sorted_events):
        actual_prev_hash = event["proof"]["prev_hash"]
        event_hash = event["proof"]["event_hash"]
        facto_id = event["facto_id"]
        
        if actual_prev_hash != expected_prev_hash:
            errors.append(
                f"Event {i+1} ({facto_id}): prev_hash mismatch. "
                f"Expected {expected_prev_hash[:16]}..., got {actual_prev_hash[:16]}..."
            )
        
        expected_prev_hash = event_hash
    
    return len(errors) == 0, errors


def hash_pair(left: str, right: str) -> str:
    """Hash two hex strings together using SHA256."""
    left_bytes = bytes.fromhex(left)
    right_bytes = bytes.fromhex(right)
    combined = left_bytes + right_bytes
    return hashlib.sha256(combined).hexdigest()


def verify_merkle_proof(event_hash: str, proof: List[Dict[str, str]], root: str) -> bool:
    """
    Verify a Merkle inclusion proof.
    
    Args:
        event_hash: The hash of the event leaf
        proof: List of proof elements with 'hash' and 'position' (left/right)
        root: The expected Merkle root
    
    Returns: True if the proof is valid
    """
    current = event_hash
    
    for element in proof:
        sibling = element["hash"]
        position = element["position"]
        
        if position == "left":
            current = hash_pair(sibling, current)
        else:  # right
            current = hash_pair(current, sibling)
    
    return current == root


def verify_merkle_proofs(
    events: List[Dict[str, Any]], 
    merkle_proofs: List[Dict[str, Any]]
) -> Tuple[int, int, List[str]]:
    """
    Verify all Merkle proofs in the evidence bundle.
    
    Returns: (valid_count, total_count, error_messages)
    """
    # Build lookup from facto_id to proof
    proof_lookup = {p["facto_id"]: p for p in merkle_proofs}
    
    valid = 0
    errors = []
    
    # Check for consistency between events and proofs
    if len(merkle_proofs) != len(events):
        errors.append(f"Mismatch: {len(events)} events but {len(merkle_proofs)} Merkle proofs")
    
    for event in events:
        facto_id = event["facto_id"]
        event_hash = event["proof"]["event_hash"]
        
        if facto_id not in proof_lookup:
            errors.append(f"No Merkle proof for event {facto_id}")
            continue
        
        proof_data = proof_lookup[facto_id]
        proof_elements = proof_data.get("proof") or []  # Handle None
        root = proof_data.get("root", "")
        
        if not root:
            errors.append(f"No Merkle root for event {facto_id}")
            continue
        
        if verify_merkle_proof(event_hash, proof_elements, root):
            valid += 1
        else:
            errors.append(f"Invalid Merkle proof for event {facto_id}")
    
    return valid, len(events), errors


def verify_evidence_bundle(filepath: str) -> Tuple[bool, Dict[str, Any]]:
    """
    Verify an evidence bundle file.
    
    Returns: (overall_valid, detailed_results)
    """
    # Load the bundle
    path = Path(filepath)
    if not path.exists():
        return False, {"error": f"File not found: {filepath}"}
    
    try:
        with open(path, "r") as f:
            bundle = json.load(f)
    except json.JSONDecodeError as e:
        return False, {"error": f"Invalid JSON: {e}"}
    
    events = bundle.get("events", [])
    merkle_proofs = bundle.get("merkle_proofs", [])
    
    if not events:
        return False, {"error": "No events in bundle"}
    
    results = {
        "event_count": len(events),
        "hashes": {"valid": 0, "invalid": 0, "errors": []},
        "signatures": {"valid": 0, "invalid": 0, "errors": []},
        "chain": {"valid": False, "errors": []},
        "merkle": {"valid": 0, "total": 0, "errors": []},
    }
    
    # 1. Verify all event hashes
    for event in events:
        is_valid, computed, stored = verify_event_hash(event)
        if is_valid:
            results["hashes"]["valid"] += 1
        else:
            results["hashes"]["invalid"] += 1
            results["hashes"]["errors"].append(
                f"{event['facto_id']}: hash mismatch"
            )
    
    # 2. Verify all signatures
    for event in events:
        is_valid, error = verify_event_signature(event)
        if is_valid:
            results["signatures"]["valid"] += 1
        else:
            results["signatures"]["invalid"] += 1
            results["signatures"]["errors"].append(
                f"{event['facto_id']}: {error}"
            )
    
    # 3. Verify chain integrity
    chain_valid, chain_errors = verify_chain_integrity(events)
    results["chain"]["valid"] = chain_valid
    results["chain"]["errors"] = chain_errors
    
    # 4. Verify Merkle proofs (mandatory for high assurance)
    if merkle_proofs:
        valid, total, merkle_errors = verify_merkle_proofs(events, merkle_proofs)
        results["merkle"]["valid"] = valid
        results["merkle"]["total"] = total
        results["merkle"]["errors"] = merkle_errors
        merkle_ok = (valid == total) and (len(merkle_errors) == 0)
    else:
        results["merkle"]["valid"] = 0
        results["merkle"]["total"] = 0
        results["merkle"]["errors"].append("Merkle proofs missing (required for integrity)")
        merkle_ok = False
    
    # Overall validity
    all_hashes_valid = results["hashes"]["invalid"] == 0
    all_sigs_valid = results["signatures"]["invalid"] == 0
    chain_ok = results["chain"]["valid"]
    
    overall_valid = all_hashes_valid and all_sigs_valid and chain_ok and merkle_ok
    
    return overall_valid, results


def print_verification_report(valid: bool, results: Dict[str, Any], filepath: str) -> None:
    """Print a formatted verification report."""
    print()
    print(f"{BOLD}Facto Evidence Verification Report{RESET}")
    print(f"{'─' * 50}")
    print(f"File: {filepath}")
    print(f"Events: {results.get('event_count', 0)}")
    print()
    
    if "error" in results:
        print(f"{RED}Error: {results['error']}{RESET}")
        return
    
    # Hashes
    h = results["hashes"]
    hash_ok = h["invalid"] == 0
    print(f"{checkmark(hash_ok)} Hashes: {h['valid']}/{h['valid'] + h['invalid']} valid (SHA3-256)")
    for err in h["errors"][:3]:  # Show first 3 errors
        print(f"    {RED}└─ {err}{RESET}")
    
    # Signatures
    s = results["signatures"]
    sig_ok = s["invalid"] == 0
    print(f"{checkmark(sig_ok)} Signatures: {s['valid']}/{s['valid'] + s['invalid']} valid (Ed25519)")
    for err in s["errors"][:3]:
        print(f"    {RED}└─ {err}{RESET}")
    
    # Chain
    c = results["chain"]
    print(f"{checkmark(c['valid'])} Chain integrity: {'valid' if c['valid'] else 'BROKEN'} (prev_hash links)")
    for err in c["errors"][:3]:
        print(f"    {RED}└─ {err}{RESET}")
    
    # Merkle
    m = results["merkle"]
    if m["total"] > 0:
        merkle_ok = m["valid"] == m["total"]
        print(f"{checkmark(merkle_ok)} Merkle proofs: {m['valid']}/{m['total']} valid")
        for err in m["errors"][:3]:
            print(f"    {RED}└─ {err}{RESET}")
    else:
        print(f"{YELLOW}○{RESET} Merkle proofs: not included in bundle")
    
    print()
    if valid:
        print(f"{GREEN}{BOLD}✓ Evidence is cryptographically valid{RESET}")
    else:
        print(f"{RED}{BOLD}✗ Evidence verification FAILED{RESET}")
    print()


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="facto",
        description="Facto - Forensic Accountability for AI Agents",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # verify command
    verify_parser = subparsers.add_parser(
        "verify",
        help="Verify an evidence bundle offline",
    )
    verify_parser.add_argument(
        "file",
        help="Path to the evidence bundle JSON file",
    )
    verify_parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON instead of human-readable format",
    )
    
    args = parser.parse_args()
    
    if args.command == "verify":
        valid, results = verify_evidence_bundle(args.file)
        
        if args.json:
            output = {"valid": valid, "results": results}
            print(json.dumps(output, indent=2))
        else:
            print_verification_report(valid, results, args.file)
        
        sys.exit(0 if valid else 1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
