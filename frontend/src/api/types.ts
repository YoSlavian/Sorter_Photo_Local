/**
 * The API contract, mirrored from the FastAPI schemas.
 *
 * Kept as hand-written types rather than generated ones on purpose: the set is
 * small, and an explicit file makes it obvious when the backend contract
 * changes — a generated blob tends to drift without anyone noticing.
 */

export type InterpreterMode = 'deterministic' | 'ai' | 'hybrid';
export type Syntax = 'auto' | 'text' | 'dsl';
export type Language = 'ru' | 'en';
export type Severity = 'error' | 'warning' | 'info';

export interface BuildOptions {
  mode: InterpreterMode;
  syntax: Syntax;
  language: Language | null;
  useLanes: boolean;
  infinitiveNames: boolean;
  executable: boolean;
  includeDocumentation: boolean;
  processId: string;
  processName: string;
  llmProvider: string | null;
  llmModel: string;
}

export const defaultBuildOptions: BuildOptions = {
  mode: 'deterministic',
  syntax: 'auto',
  language: null,
  useLanes: true,
  infinitiveNames: true,
  executable: false,
  includeDocumentation: true,
  processId: '',
  processName: '',
  llmProvider: null,
  llmModel: '',
};

export interface ElementInfo {
  id: string;
  type: string;
  name: string;
  category: 'event' | 'gateway' | 'activity' | 'other';
  lane: string | null;
  laneName: string;
  eventDefinition: string | null;
  documentation: string;
  incoming: string[];
  outgoing: string[];
  attributes: Record<string, string>;
}

export interface LaneInfo {
  id: string;
  name: string;
  order: number;
}

export interface FlowInfo {
  id: string;
  source: string;
  target: string;
  name: string;
  condition: string;
  isDefault: boolean;
}

export interface Diagnostic {
  code: string;
  severity: Severity;
  message: string;
  elementId: string | null;
  line: number;
}

export interface Validation {
  ok: boolean;
  counts: Record<Severity, number>;
  diagnostics: Diagnostic[];
}

export interface SourceSpan {
  elementId: string;
  sentence: string;
  line: number;
  start: number;
  end: number;
  exact: boolean;
}

export interface ClarificationOption {
  value: string;
  label: string;
  freeText: boolean;
}

export interface Clarification {
  id: string;
  kind: 'actor' | 'naming' | 'condition' | 'branch_label';
  question: string;
  elementId: string | null;
  flowId: string | null;
  options: ClarificationOption[];
  sentence: string;
  line: number;
}

export interface DiagramMeta {
  processId?: string;
  processName?: string;
  elementCount?: number;
  flowCount?: number;
  laneCount?: number;
  language?: string;
  mode?: InterpreterMode;
  provider?: string;
  deterministic?: boolean;
  notes?: string[];
  layoutWasGenerated?: boolean;
  relaidOut?: boolean;
}

export interface Diagram {
  bpmn: string;
  elements: ElementInfo[];
  lanes: LaneInfo[];
  flows: FlowInfo[];
  validation: Validation;
  sourceMap: Record<string, SourceSpan>;
  clarifications: Clarification[];
  explanation: string;
  narrative: string;
  meta: DiagramMeta;
}

export interface ParseResult {
  explanation: string;
  language: string;
  mode: string;
  deterministic: boolean;
  notes: string[];
}

export interface ServerInfo {
  version: string;
  modes: InterpreterMode[];
  providers: Record<string, boolean>;
  languages: Language[];
  elementTypes: { type: string; category: string }[];
}

export interface ProjectPayload {
  project: string;
  filename: string;
}

export interface ProjectLoad {
  diagram: Diagram;
  sourceText: string;
  settings: Record<string, unknown>;
  metadata: Record<string, string>;
}
