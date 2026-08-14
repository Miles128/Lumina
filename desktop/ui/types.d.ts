/**
 * Lumina UI global contract types.
 *
 * Cross-module window globals, SSE progress events and the main API shapes
 * live here so `// @ts-check` files get real checking at the boundaries
 * where bugs actually happen (typos in event kinds, wrong API shapes,
 * changed module exports).
 */

/* ---------- SSE progress events (mirrors backend ProgressKind) ---------- */

type LuminaProgressKind =
  | "turn_started"
  | "turn_completed"
  | "pause_confirmation"
  | "iteration_started"
  | "iteration_completed"
  | "context_compacted"
  | "context_ready"
  | "tool_started"
  | "tool_finished"
  | "subagent_started"
  | "subagent_paused"
  | "subagent_finished"
  | "idp_update"
  | "final_reply"
  | "stopped"
  | "reply_start"
  | "reply_delta"
  | "reply_end"
  | "thought";

interface LuminaProgressEvent {
  kind: LuminaProgressKind;
  schema_version?: number;
  iteration?: number;
  turn_id?: string;
  parent_turn_id?: string;
  thread_id?: string;
  trace_id?: string;
  sub_run_id?: string;
  tool_name?: string;
  success?: boolean;
  message?: string;
  detail?: string;
  label?: string;
  delta?: string;
  latency_ms?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  paths?: string[];
  archetype?: string;
  subagent_status?: string;
  goal?: string;
  idp?: Record<string, unknown>;
  context_snapshot?: Record<string, unknown>;
  context?: Record<string, unknown>;
}

/* ---------- Chat API shapes ---------- */

interface LuminaChatResponse {
  reply: string;
  raw_reply?: string;
  profile_excerpt?: string;
  used_llm?: boolean;
  memory_hits?: number;
  used_tools?: string[];
  total_steps?: number;
  grounding_verified?: boolean;
  grounding_note?: string;
  needs_confirmation?: boolean;
  pending_confirmation?: {
    action_id?: string;
    tool_name?: string;
    description?: string;
    risk_level?: string;
    confirmation_kind?: string;
    diff_preview?: string;
  } | null;
  confirmation_kind?: string;
  allow_permanent_read?: boolean;
  allow_session_write?: boolean;
  context_snapshot?: Record<string, unknown> | null;
  trace_id?: string;
}

interface LuminaThreadMessage {
  id: string;
  role: "user" | "assistant" | "bot";
  text?: string;
  content?: string;
  archived?: boolean;
  parent_id?: string;
  created?: string;
}

interface LuminaThread {
  id: string;
  title?: string;
  summary?: string;
  messages: LuminaThreadMessage[];
  active_leaf_id?: string;
  updatedAt?: string;
  auto_title_at_turn?: number;
  archived?: boolean;
}

interface LuminaThreadsPayload {
  current_id: string;
  threads: LuminaThread[];
}

/* ---------- window globals ---------- */

interface LuminaUtilsApi {
  escapeHtml(value: unknown, options?: { attrs?: boolean }): string;
}

interface LuminaSecretaryApi {
  request<T = unknown>(
    method: string,
    path: string,
    body?: unknown,
    options?: { timeoutMs?: number; signal?: AbortSignal },
  ): Promise<T>;
  subscribeChatProgress(
    traceId: string,
    onEvent: (event: LuminaProgressEvent) => void,
    signal?: AbortSignal,
  ): Promise<void>;
  ApiTimeoutError: new (message?: string) => Error;
  ApiAbortError: new (message?: string) => Error;
}

interface LuminaI18nApi {
  t(key: string, vars?: Record<string, string | number>): string;
  applyDocument(root?: Element | Document): void;
}

interface LuminaMarkdownApi {
  render(text: string): string;
}

interface LuminaArtifactsApi {
  noteToolEvent(event: LuminaProgressEvent): void;
  noteFile(path: string, source?: string): void;
  setWorkspace(path: string): void;
  setThread(threadId: string): void;
  setContextSnapshot(snapshot: Record<string, unknown>, threadId?: string): void;
  setMode(mode: "documents" | "context"): void;
  open(): void;
  openContext(): void;
  preview(path: string): void;
  close(): void;
  isOpen(): boolean;
}

interface LuminaConfirmApi {
  confirmDanger(options?: {
    title?: string;
    message?: string;
    confirmText?: string;
    secondTitle?: string;
    secondMessage?: string;
  }): Promise<boolean>;
}

interface LuminaThemeApi {
  apply(theme?: string): void;
  toggle?(): void;
}

interface LuminaLunarApi {
  phase(): unknown;
  greeting?(): string;
  info?(): unknown;
}

interface LuminaChatModule {
  send(message: string): void;
  [key: string]: unknown;
}

interface LuminaSettingsModule {
  open(): void;
  reload(): void;
}

interface LuminaSkillsModule {
  open(): void;
  close(): void;
}

interface LuminaWorkflowsModule {
  open(): void;
  close(): void;
}

interface LuminaConversationMapModule {
  init(): void;
  open(): void;
  close(): void;
  toggle?(): void;
}

interface Window {
  LuminaUtils?: LuminaUtilsApi;
  SecretaryAPI?: LuminaSecretaryApi;
  LuminaI18n?: LuminaI18nApi;
  LuminaMarkdown?: LuminaMarkdownApi;
  LuminaArtifacts?: LuminaArtifactsApi;
  LuminaConfirm?: LuminaConfirmApi;
  LuminaTheme?: LuminaThemeApi;
  LuminaLunar?: LuminaLunarApi;
  ChatModule?: LuminaChatModule;
  SettingsModule?: LuminaSettingsModule;
  SkillsModule?: LuminaSkillsModule;
  WorkflowsModule?: LuminaWorkflowsModule;
  ConversationMapModule?: LuminaConversationMapModule;
  secretary?: LuminaSecretaryBridge;
  DOMPurify?: { sanitize(html: string, options?: unknown): string };
}

/* Global values (files reference LuminaUtils etc. without window.) */
declare const LuminaUtils: LuminaUtilsApi;
declare const SecretaryAPI: LuminaSecretaryApi;
declare const LuminaI18n: LuminaI18nApi;
declare const LuminaMarkdown: LuminaMarkdownApi;
declare const LuminaArtifacts: LuminaArtifactsApi;
declare const LuminaConfirm: LuminaConfirmApi;
declare const LuminaTheme: LuminaThemeApi;
declare const LuminaLunar: LuminaLunarApi;

/* Artifact panel API shapes */
interface LuminaArtifactsContextResponse {
  sandbox: string;
  workspace: string;
  roots: { path: string; label?: string; id?: string }[];
}

interface LuminaArtifactsEntry {
  name: string;
  path: string;
  kind: "dir" | "file";
  type?: string;
  depth?: number;
  size?: number;
  children?: LuminaArtifactsEntry[];
  truncated?: boolean;
}

interface LuminaArtifactsTreeResponse {
  root: string;
  entries: LuminaArtifactsEntry[];
  truncated?: boolean;
}
