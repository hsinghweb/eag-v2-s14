
# 📖 S15 Manual Codebase: The "How-To" Guide

## 🚀 How to Run It

1.  **Navigate to the folder**:
    ```bash
    cd S15_Manual
    ```
2.  **Add your API Key**:
    Edit `.env` and add: `GEMINI_API_KEY=your_key_here`
3.  **Run the Agent**:
    ```bash
    uv run main.py
    ```
4.  **Test It**:
    Enter a query like: *"Plan a 3 day trip to Tokyo"*

---

## 🧭 How to Read the Code (The "Tour")

The code is separated by **Logic Responsibilities**. Here is the map:

### 1. The Brain (Agents)
*   **`perception/perception.py`**: The **Eye**. It looks at the user input and the current history. It verifies if we are done or if we need to plan more.
    *   *Key Logic*: Returns a `route` (usually "decision" or "browserAgent").
*   **`decision/decision.py`**: The **Brain**. It generates the **Plan Graph**.
    *   *Key Logic*: It outputs a JSON `plan_graph` containing nodes (tasks) and edges (dependencies). It does NOT execute them.
*   **`agent/agent_loop3.py`**: The **Body**. It connects the Eye and the Brain.
    *   *Key Logic*: This is the `while true` loop. It calls Perception -> Decision -> Execution.

### 2. The State (Manual Graph)
This is the most unique part of S15 Manual.
*   **`agent/contextManager.py`**: The **Memory**.
    *   **Old Way (Libraries)**: `self.graph = nx.DiGraph()`
    *   **S15 Manual Way**:
        *   `self.steps`: A Python dictionary `{ "step_1": StepNode(...) }`.
        *   `self.edges`: A Python list `[ {"source": "step_1", "target": "step_2"} ]`.
    *   *Reason*: To teach you how to manage Directed Acyclic Graphs (DAGs) from scratch.

### 3. The Tools
*   **`mcp_servers/`**: Connectors that provide tools (Search, PDF reading) to the agent.
*   **`utils/utils.py`**: Helper functions, including the manual `render_graph` which draws the table in your terminal.

---

## 🧠 The Logic Flow: How a Plan is Made & Followed

Here is the lifecycle of a request, step-by-step:

### Phase 1: Planning (Perception + Decision)
1.  **User inputs**: *"Research Tokyo"*
2.  **Perception** sees this is a new task and routes to `decision`.
3.  **Decision** thinks and outputs a JSON plan:
    ```json
    {
      "nodes": [
        {"id": "0", "description": "Search Tokyo attractions", "type": "CODE"},
        {"id": "1", "description": "Summarize results", "type": "CODE"}
      ],
      "edges": [{"source": "0", "target": "1"}]
    }
    ```

### Phase 2: Storing (ContextManager)
4.  **`AgentLoop`** takes this JSON and feeds it to `ContextManager`.
5.  **`ContextManager`** manually builds the graph:
    *   Creates a `StepNode` object for "0".
    *   Stores it in `self.steps["0"]`.
    *   Sets its status to `pending`.

### Phase 3: Following & Executing (The Loop)
6.  **`AgentLoop`** asks: *"What step is pending and has all parents completed?"*
    *   It manually checks `self.edges` to find the root.
7.  **Execution**:
    *   It runs the code for **Step 0**.
    *   If successful, `self.steps["0"].status` becomes `completed`.
8.  **Next Turn**:
    *   The loop runs again. It sees **Step 0** is done.
    *   It checks **Step 1**. Its parent (0) is done.
    *   It executes **Step 1**.

### Phase 4: Failure & Self-Correction (The "Recurse" Magic)
If Step 0 fails:
1.  **Decision** sees the error.
2.  it outputs a **Retry Node**: `0F1`.
3.  **ContextManager** must manually "rename/prune" the old path using the recursive logic in `_get_descendants`.
4.  The Agent tries the new path.

---

