
from agent.contextManager import ContextManager, StepNode
import json

def test_manual_graph():
    print("🧪 Testing Manual ContextManager...")
    ctx = ContextManager("test-session", "Test Query")
    
    # 1. Add Steps
    ctx.add_step("A", "Step A", "CODE", from_node="ROOT")
    ctx.add_step("B", "Step B", "CODE", from_node="A")
    ctx.add_step("C", "Step C", "CODE", from_node="B")
    ctx.add_step("D", "Step D", "CODE", from_node="A") # Branch off A
    
    print("\n[Graph Structure]")
    print(f"Steps: {list(ctx.steps.keys())}")
    print(f"Edges: {ctx.edges}")
    
    assert "A" in ctx.steps
    assert "ROOT" in ctx.steps
    assert len(ctx.edges) == 4 # ROOT->A, A->B, B->C, A->D
    
    # 2. Test Descendants (Manual Recursion)
    desc_A = ctx._get_descendants("A")
    print(f"\nDescendants of A: {desc_A}")
    assert "B" in desc_A
    assert "C" in desc_A
    assert "D" in desc_A
    assert "ROOT" not in desc_A
    
    desc_B = ctx._get_descendants("B")
    print(f"Descendants of B: {desc_B}")
    assert "C" in desc_B
    assert "A" not in desc_B
    
    # 3. Test Rename Subtree
    print("\nRenaming subtree from B with suffix 'x'...")
    ctx.rename_subtree_from("B", "x")
    
    print(f"Steps after rename: {list(ctx.steps.keys())}")
    print(f"Edges after rename: {ctx.edges}")
    
    # B should be gone, Bx should exist
    assert "B" not in ctx.steps
    assert "Bx" in ctx.steps
    assert "Cx" in ctx.steps
    # A->B should become A->Bx
    assert any(e["source"] == "A" and e["target"] == "Bx" for e in ctx.edges)
    # B->C should become Bx->Cx
    assert any(e["source"] == "Bx" and e["target"] == "Cx" for e in ctx.edges)
    
    # 4. Serialization
    snap = ctx.get_context_snapshot()
    print("\nSnapshot Graph Data:")
    print(json.dumps(snap["graph"], indent=2))
    
    assert snap["graph"]["directed"] is True
    assert len(snap["graph"]["nodes"]) == 5 # ROOT, A, D, Bx, Cx
    
    print("\n✅ All Manual Graph Tests Passed!")

if __name__ == "__main__":
    test_manual_graph()
