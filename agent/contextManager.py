
from utils.utils import log_step, log_error, render_graph
# import networkx as nx  <-- REMOVED
from typing import Any, Dict, Optional, Set, List
from dataclasses import dataclass
import json
from collections import defaultdict


@dataclass
class StepNode:
    index: str  # Now string to support labels like "0A", "0B"
    description: str
    type: str  # CODE, CONCLUDE, NOP
    status: str = "pending"
    result: Optional[Dict[str, Any]] = None
    conclusion: Optional[str] = None
    error: Optional[str] = None
    perception: Optional[Dict[str, Any]] = None
    from_step: Optional[str] = None  # for debugging lineage


class ContextManager:
    def __init__(self, session_id: str, original_query: str):
        self.session_id = session_id
        self.original_query = original_query
        self.globals: Dict[str, Any] = {}
        self.session_memory: list[dict] = []  # Full memory, not compressed
        self.failed_nodes: list[str] = []     # Node labels of failed steps
        
        # MANUAL GRAPH REPLACEMENT
        self.steps: Dict[str, StepNode] = {}
        self.edges: List[Dict[str, str]] = []  # List of {"source": "A", "target": "B", "type": "normal"}

        self.latest_node_id: Optional[str] = None
        self.executed_variants: Dict[str, Set[str]] = defaultdict(set)

        root_node = StepNode(index="ROOT", description=original_query, type="ROOT", status="completed")
        self.steps["ROOT"] = root_node

    def add_step(self, step_id: str, description: str, step_type: str, from_node: Optional[str] = None, edge_type: str = "normal") -> str:
        step_node = StepNode(index=step_id, description=description, type=step_type, from_step=from_node)
        self.steps[step_id] = step_node
        
        if from_node:
            self.edges.append({"source": from_node, "target": step_id, "type": edge_type})
            
        self.latest_node_id = step_id
        # self._print_graph(depth=1)
        return step_id

    def is_step_completed(self, step_id: str) -> bool:
        node = self.steps.get(step_id)
        return node is not None and node.status == "completed"

    def update_step_result(self, step_id: str, result: dict):
        node: StepNode = self.steps[step_id]
        node.result = result
        node.status = "completed"
        self._update_globals(result)
        # self._print_graph(depth=2)

    def mark_step_completed(self, step_id: str):
        if step_id in self.steps:
            node: StepNode = self.steps[step_id]
            node.status = "completed"

    def mark_step_failed(self, step_id: str, error_msg: str):
        node: StepNode = self.steps[step_id]
        node.status = "failed"
        node.error = error_msg
        self.failed_nodes.append(step_id)
        self.session_memory.append({
            "query": node.description,
            "result_requirement": "Tool failed",
            "solution_summary": str(error_msg)[:300]
        })
        # self._print_graph(depth=2)

    def attach_perception(self, step_id: str, perception: dict):
        if step_id not in self.steps:
            fallback_node = StepNode(index=step_id, description="Perception-only node", type="PERCEPTION")
            self.steps[step_id] = fallback_node
            
        node: StepNode = self.steps[step_id]
        node.perception = perception
        if not perception.get("local_goal_achieved", True):
            self.failed_nodes.append(step_id)
        # self._print_graph(depth=2)

    def conclude(self, step_id: str, conclusion: str):
        node: StepNode = self.steps[step_id]
        node.status = "completed"
        node.conclusion = conclusion
        # self._print_graph(depth=2)

    def get_latest_node(self) -> Optional[str]:
        return self.latest_node_id

    def _update_globals(self, new_vars: Dict[str, Any]):
        for k, v in new_vars.items():
            if k in self.globals:
                versioned_key = f"{k}__{self.latest_node_id}"
                self.globals[versioned_key] = v
            else:
                self.globals[k] = v

    def _print_graph(self, depth: int = 1, only_if: bool = True):
        if only_if:
            # Pass ONLY the steps dict to render_graph (we will modify it to accept dict)
            render_graph(self.steps, depth=depth)

    def get_context_snapshot(self):
        def serialize_node_data(data):
            if hasattr(data, '__dict__'):
                return data.__dict__
            return data
            
        # MANUAL SERIALIZATION (Replaces nx.node_link_data)
        nodes_list = []
        for node_id, node_obj in self.steps.items():
            node_dict = serialize_node_data(node_obj)
            # Add 'id' field as expected by some consumers
            node_dict["id"] = node_id
            
            # Wrap in "data" key to match previous NetworkX structure if needed, 
            # OR flatten it. NetworkX usually does: {"id": "ROOT", "data": {...}} 
            # or just properties.
            # agent_loop3 expects node["id"] and node["description"] at top level for plan_graph
            # but here we are serializing internal state.
            
            # Let's match the structure expected by the viewer: usually list of nodes
            nodes_list.append({
                "id": node_id,
                "data": node_dict
            })
            
        graph_data = {
            "directed": True,
            "multigraph": False,
            "nodes": nodes_list,
            "links": self.edges
        }

        return {
            "session_id": self.session_id,
            "original_query": self.original_query,
            "globals": self.globals,
            "memory": self.session_memory,
            "graph": graph_data,
        }

    # --- MANUAL GRAPH ALGORITHMS (The Complexity!) ---

    def _get_descendants(self, root_id: str) -> Set[str]:
        """
        Manually find all descendants using recursion.
        NetworkX would just be: nx.descendants(G, root_id)
        """
        descendants = set()
        
        # Find direct children: scan ALL edges (Efficiency: O(Edges))
        children = []
        for edge in self.edges:
            if edge["source"] == root_id:
                children.append(edge["target"])
        
        # Add children and their descendants
        for child in children:
            if child not in descendants: # Prevent infinite cycles
                descendants.add(child)
                descendants.update(self._get_descendants(child))
                
        return descendants

    def rename_subtree_from(self, from_step_id: str, suffix: str):
        if from_step_id not in self.steps:
            return
            
        # 1. Find all nodes to rename using manual traversal
        to_rename = [from_step_id] + list(self._get_descendants(from_step_id))
        
        mapping = {}
        
        # 2. Create new nodes with updated IDs
        for old_id in to_rename:
            new_id = f"{old_id}{suffix}"
            node = self.steps[old_id]
            node.index = new_id  # Update internal index
            self.steps[new_id] = node
            mapping[old_id] = new_id
            
        # 3. Update Edges
        new_edges = []
        for edge in self.edges:
            src = edge["source"]
            tgt = edge["target"]
            
            # Remap source and target if they are in the rename list
            new_src = mapping.get(src, src)
            new_tgt = mapping.get(tgt, tgt)
            
            # Only add if it's a valid edge (nodes exist)
            if new_src in self.steps and new_tgt in self.steps:
                 new_edges.append({"source": new_src, "target": new_tgt, "type": edge["type"]})
                 
        self.edges = new_edges

        # 4. Remove old nodes
        for old_id in to_rename:
            if old_id in self.steps:
                del self.steps[old_id]

        # 5. Update failed_nodes list
        self.failed_nodes = [mapping.get(x, x) for x in self.failed_nodes]

    def attach_summary(self, summary: dict):
        """Attach summarizer output to session memory."""
        self.session_memory.append({
            "original_query": self.original_query,
            "result_requirement": "Final summary",
            "summarizer_summary": summary.get("summarizer_summary", summary if isinstance(summary, str) else ""),
            "confidence": summary.get("confidence", 0.95),
            "original_goal_achieved": True,
            "route": "summarize"
        })
