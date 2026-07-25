# FR-45 Conversation Map Role / Status Annotations

**Goal:** Annotate conversation-map turn nodes with roles (人 / 主 Agent) and states (pending · done · rolled_back · waiting_confirm via live overlay). No multi-agent debate; no merge/conflict nodes.

## Tasks

1. Backend: add `role_user` / `role_assistant` / `status` on `/tree` nodes (derived).
2. Frontend: render role labels + status chip; CSS.
3. Live: `chat.js` dispatches progress overlay → map badges active leaf.
4. Tests + PRD FR-45 → Done.
