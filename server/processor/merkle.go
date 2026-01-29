package main

import (
	"crypto/sha256"
	"encoding/hex"
)

// MerkleTree represents a Merkle tree
type MerkleTree struct {
	root   *MerkleNode
	leaves []*MerkleNode
}

// MerkleNode represents a node in the Merkle tree
type MerkleNode struct {
	Hash   string
	Left   *MerkleNode
	Right  *MerkleNode
	Parent *MerkleNode
}

// BuildMerkleTree builds a Merkle tree from a list of hashes
func BuildMerkleTree(hashes []string) *MerkleTree {
	if len(hashes) == 0 {
		return &MerkleTree{
			root: &MerkleNode{
				Hash: hex.EncodeToString(sha256.New().Sum(nil)),
			},
		}
	}

	// Create leaf nodes
	leaves := make([]*MerkleNode, len(hashes))
	for i, h := range hashes {
		leaves[i] = &MerkleNode{Hash: h}
	}

	// If odd number of leaves, duplicate the last one
	if len(leaves)%2 != 0 {
		leaves = append(leaves, &MerkleNode{Hash: leaves[len(leaves)-1].Hash})
	}

	tree := &MerkleTree{leaves: leaves}
	tree.root = buildTree(leaves)

	return tree
}

// buildTree recursively builds the tree from the bottom up
func buildTree(nodes []*MerkleNode) *MerkleNode {
	if len(nodes) == 1 {
		return nodes[0]
	}

	// Create parent nodes
	var parents []*MerkleNode

	for i := 0; i < len(nodes); i += 2 {
		left := nodes[i]
		right := nodes[i]
		if i+1 < len(nodes) {
			right = nodes[i+1]
		}

		parent := &MerkleNode{
			Hash:  hashPair(left.Hash, right.Hash),
			Left:  left,
			Right: right,
		}
		left.Parent = parent
		right.Parent = parent

		parents = append(parents, parent)
	}

	// If odd number of parents, duplicate the last one
	if len(parents) > 1 && len(parents)%2 != 0 {
		parents = append(parents, &MerkleNode{Hash: parents[len(parents)-1].Hash})
	}

	return buildTree(parents)
}

// hashPair computes SHA256(left || right)
func hashPair(left, right string) string {
	leftBytes, _ := hex.DecodeString(left)
	rightBytes, _ := hex.DecodeString(right)

	combined := append(leftBytes, rightBytes...)
	hash := sha256.Sum256(combined)
	return hex.EncodeToString(hash[:])
}

// Root returns the root hash of the Merkle tree
func (t *MerkleTree) Root() string {
	if t.root == nil {
		return ""
	}
	return t.root.Hash
}

// GetProof returns the Merkle proof for a given leaf index
func (t *MerkleTree) GetProof(index int) []ProofElement {
	if index < 0 || index >= len(t.leaves) {
		return nil
	}

	var proof []ProofElement
	node := t.leaves[index]

	for node.Parent != nil {
		parent := node.Parent
		var sibling *MerkleNode
		var position string

		if parent.Left == node {
			sibling = parent.Right
			position = "right"
		} else {
			sibling = parent.Left
			position = "left"
		}

		if sibling != nil {
			proof = append(proof, ProofElement{
				Hash:     sibling.Hash,
				Position: position,
			})
		}

		node = parent
	}

	return proof
}

// ProofElement represents an element in a Merkle proof
type ProofElement struct {
	Hash     string `json:"hash"`
	Position string `json:"position"` // "left" or "right"
}

// VerifyProof verifies a Merkle proof
func VerifyProof(leafHash string, proof []ProofElement, root string) bool {
	currentHash := leafHash

	for _, element := range proof {
		if element.Position == "left" {
			currentHash = hashPair(element.Hash, currentHash)
		} else {
			currentHash = hashPair(currentHash, element.Hash)
		}
	}

	return currentHash == root
}
