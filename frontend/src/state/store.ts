/**
 * Application state.
 *
 * One store holds the document (description, diagram, everything the server
 * derived from it) and the shell state (selection, panels, notifications).
 * Undo/redo is deliberately **not** here: the bpmn-js command stack already
 * owns the edit history, and a second history would drift from it.
 *
 * The diagram itself lives in the modeller once loaded; `bpmn` here is the
 * last synchronised XML and is what every API call is made against, so there
 * is exactly one place that knows the current document.
 */

import { create } from 'zustand';
import { ApiError, api } from '../api/client';
import {
  type BuildOptions,
  type Clarification,
  type Diagram,
  type ElementInfo,
  type ServerInfo,
  type SourceSpan,
  defaultBuildOptions,
} from '../api/types';

export type PanelId = 'properties' | 'elements' | 'validation' | 'questions' | 'explain';
/** The left column shows either the description or the element palette. */
export type LeftMode = 'text' | 'palette';
export type Theme = 'light' | 'dark';
export type NoticeKind = 'info' | 'success' | 'warning' | 'error';

export interface Notice {
  id: number;
  kind: NoticeKind;
  message: string;
}

/** A pipeline stage, shown as it actually completes. */
export interface Stage {
  id: string;
  label: string;
  state: 'pending' | 'running' | 'done' | 'failed';
}

const STAGE_LABELS: [string, string][] = [
  ['parse', 'Разбор текста'],
  ['graph', 'Построение графа'],
  ['validate', 'Проверка структуры'],
  ['layout', 'Компоновка'],
];

const THEME_KEY = 'bpmn-architect.theme';
const DRAFT_KEY = 'bpmn-architect.draft';

export interface StudioState {
  // -- document ------------------------------------------------------------
  sourceText: string;
  bpmn: string;
  diagram: Diagram | null;
  options: BuildOptions;
  projectName: string;
  dirty: boolean;

  // -- shell ---------------------------------------------------------------
  info: ServerInfo | null;
  busy: boolean;
  stages: Stage[];
  panel: PanelId;
  leftMode: LeftMode;
  selectedId: string | null;
  highlighted: string[];
  caretOffset: number | null;
  notices: Notice[];
  theme: Theme;
  commandPaletteOpen: boolean;

  // -- actions -------------------------------------------------------------
  loadInfo: () => Promise<void>;
  setSourceText: (text: string) => void;
  setOptions: (patch: Partial<BuildOptions>) => void;
  setPanel: (panel: PanelId) => void;
  setLeftMode: (mode: LeftMode) => void;
  setProjectName: (name: string) => void;
  build: () => Promise<void>;
  analyse: () => Promise<void>;
  relayout: () => Promise<void>;
  answer: (answers: Record<string, string>) => Promise<void>;
  openBpmn: (xml: string, name?: string) => Promise<void>;
  openProject: (json: string) => Promise<void>;
  saveProject: () => Promise<{ project: string; filename: string } | null>;
  syncFromModeler: (xml: string) => Promise<void>;
  markDirty: () => void;
  select: (id: string | null) => void;
  highlightFromCaret: (offset: number) => void;
  clearHighlight: () => void;
  notify: (kind: NoticeKind, message: string) => void;
  dismiss: (id: number) => void;
  setTheme: (theme: Theme) => void;
  toggleCommandPalette: (open?: boolean) => void;
  reset: () => void;
}

function initialStages(): Stage[] {
  return STAGE_LABELS.map(([id, label]) => ({ id, label, state: 'pending' }));
}

function readTheme(): Theme {
  try {
    const stored = localStorage.getItem(THEME_KEY);
    if (stored === 'light' || stored === 'dark') return stored;
  } catch {
    /* private mode */
  }
  return document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
}

function readDraft(): string {
  try {
    return localStorage.getItem(DRAFT_KEY) ?? '';
  } catch {
    return '';
  }
}

let noticeId = 0;

export const useStudio = create<StudioState>((set, get) => ({
  sourceText: readDraft(),
  bpmn: '',
  diagram: null,
  options: { ...defaultBuildOptions },
  projectName: '',
  dirty: false,

  info: null,
  busy: false,
  stages: initialStages(),
  panel: 'properties',
  leftMode: 'text',
  selectedId: null,
  highlighted: [],
  caretOffset: null,
  notices: [],
  theme: readTheme(),
  commandPaletteOpen: false,

  // -- plumbing ------------------------------------------------------------

  notify: (kind, message) => {
    const id = ++noticeId;
    set((state) => ({ notices: [...state.notices, { id, kind, message }] }));
    if (kind !== 'error') {
      setTimeout(() => get().dismiss(id), 5000);
    }
  },

  dismiss: (id) => set((state) => ({ notices: state.notices.filter((n) => n.id !== id) })),

  setTheme: (theme) => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* private mode */
    }
    set({ theme });
  },

  toggleCommandPalette: (open) =>
    set((state) => ({ commandPaletteOpen: open ?? !state.commandPaletteOpen })),

  setPanel: (panel) => set({ panel }),
  setLeftMode: (leftMode) => set({ leftMode }),
  setProjectName: (projectName) => set({ projectName }),
  setOptions: (patch) => set((state) => ({ options: { ...state.options, ...patch } })),
  markDirty: () => set({ dirty: true }),

  setSourceText: (sourceText) => {
    set({ sourceText });
    try {
      localStorage.setItem(DRAFT_KEY, sourceText);
    } catch {
      /* private mode */
    }
  },

  select: (selectedId) =>
    set((state) => ({
      selectedId,
      // Selecting on the canvas is a request to see that element's properties.
      panel: selectedId && state.panel === 'elements' ? 'properties' : state.panel,
    })),
  clearHighlight: () => set({ highlighted: [], caretOffset: null }),

  highlightFromCaret: (offset) => {
    const map = get().diagram?.sourceMap;
    if (!map) return;
    const hits = Object.values(map)
      .filter((span) => span.start <= offset && offset < span.end)
      .sort((a, b) => a.end - a.start - (b.end - b.start))
      .map((span) => span.elementId);
    set({ highlighted: hits, caretOffset: offset });
  },

  // -- server --------------------------------------------------------------

  loadInfo: async () => {
    try {
      set({ info: await api.info() });
    } catch (error) {
      get().notify('error', describeError(error));
    }
  },

  build: async () => {
    const { sourceText, options } = get();
    if (!sourceText.trim()) {
      get().notify('warning', 'Введите описание процесса.');
      return;
    }
    set({ busy: true, stages: stagesWith('parse', 'running') });
    try {
      // Two real calls, so the progress a user sees reflects work that
      // actually happened rather than a timer.
      await api.parse(sourceText, options);
      set({
        stages: stagesWith('parse', 'done', ['graph', 'validate', 'layout'], 'running'),
      });
      const diagram = await api.build(sourceText, options);
      applyDiagram(set, diagram);
      set({
        stages: allDone(),
        panel: diagram.clarifications.length ? 'questions' : 'elements',
        leftMode: 'text',
      });
      get().notify(
        diagram.validation.ok ? 'success' : 'warning',
        summarise(diagram),
      );
    } catch (error) {
      set({ stages: stagesWith('parse', 'failed') });
      get().notify('error', describeError(error));
    } finally {
      set({ busy: false });
    }
  },

  analyse: async () => {
    const { sourceText, options } = get();
    if (!sourceText.trim()) {
      get().notify('warning', 'Введите описание процесса.');
      return;
    }
    set({ busy: true });
    try {
      const parsed = await api.parse(sourceText, options);
      set((state) => ({
        panel: 'explain' as PanelId,
        diagram: state.diagram
          ? { ...state.diagram, explanation: parsed.explanation }
          : ({ explanation: parsed.explanation } as unknown as Diagram),
      }));
      parsed.notes.forEach((note) => get().notify('info', note));
    } catch (error) {
      get().notify('error', describeError(error));
    } finally {
      set({ busy: false });
    }
  },

  relayout: async () => {
    const { bpmn } = get();
    if (!bpmn) return;
    set({ busy: true });
    try {
      applyDiagram(set, await api.layout(bpmn));
      get().notify('success', 'Компоновка пересобрана.');
    } catch (error) {
      get().notify('error', describeError(error));
    } finally {
      set({ busy: false });
    }
  },

  answer: async (answers) => {
    const { bpmn } = get();
    if (!bpmn) return;
    set({ busy: true });
    try {
      applyDiagram(set, await api.clarify(bpmn, answers));
      get().notify('success', 'Уточнения применены.');
    } catch (error) {
      get().notify('error', describeError(error));
    } finally {
      set({ busy: false });
    }
  },

  openBpmn: async (xml, name) => {
    set({ busy: true });
    try {
      const diagram = await api.importBpmn(xml, get().sourceText);
      applyDiagram(set, diagram);
      set({ panel: 'elements', projectName: name ?? get().projectName });
      if (diagram.meta.layoutWasGenerated) {
        get().notify('info', 'В файле не было координат — компоновка построена заново.');
      }
      get().notify('success', summarise(diagram));
    } catch (error) {
      get().notify('error', describeError(error));
    } finally {
      set({ busy: false });
    }
  },

  openProject: async (json) => {
    set({ busy: true });
    try {
      const loaded = await api.openProject(json);
      applyDiagram(set, loaded.diagram);
      get().setSourceText(loaded.sourceText);
      set({
        projectName: loaded.metadata.name ?? '',
        options: {
          ...get().options,
          ...(loaded.settings.options as Partial<BuildOptions> | undefined),
        },
        panel: 'elements',
        dirty: false,
      });
      get().notify('success', 'Проект открыт.');
    } catch (error) {
      get().notify('error', describeError(error));
    } finally {
      set({ busy: false });
    }
  },

  saveProject: async () => {
    const { bpmn, sourceText, projectName, options } = get();
    if (!bpmn) {
      get().notify('warning', 'Нечего сохранять — сначала создайте диаграмму.');
      return null;
    }
    try {
      const payload = await api.saveProject({
        bpmn,
        sourceText,
        name: projectName || 'Процесс',
        settings: { options },
      });
      set({ dirty: false });
      return payload;
    } catch (error) {
      get().notify('error', describeError(error));
      return null;
    }
  },

  syncFromModeler: async (xml) => {
    if (!xml || xml === get().bpmn) return;
    set({ bpmn: xml, dirty: true });
    try {
      const diagram = await api.importBpmn(xml, get().sourceText);
      set((state) => ({
        diagram: state.diagram
          ? { ...diagram, explanation: state.diagram.explanation, bpmn: xml }
          : diagram,
      }));
    } catch {
      // A transient parse failure while the user drags is not worth a banner;
      // the panels simply keep the last good derivation.
    }
  },

  reset: () =>
    set({
      bpmn: '',
      diagram: null,
      selectedId: null,
      highlighted: [],
      dirty: false,
      projectName: '',
      stages: initialStages(),
      panel: 'properties',
    }),
}));

// --------------------------------------------------------------------------- //
// Helpers
// --------------------------------------------------------------------------- //

type Setter = (partial: Partial<StudioState>) => void;

function applyDiagram(set: Setter, diagram: Diagram): void {
  set({ diagram, bpmn: diagram.bpmn, dirty: false, selectedId: null, highlighted: [] });
}

function stagesWith(
  id: string,
  state: Stage['state'],
  others: string[] = [],
  othersState: Stage['state'] = 'pending',
): Stage[] {
  return STAGE_LABELS.map(([stageId, label]) => ({
    id: stageId,
    label,
    state:
      stageId === id ? state : others.includes(stageId) ? othersState : ('pending' as const),
  }));
}

function allDone(): Stage[] {
  return STAGE_LABELS.map(([id, label]) => ({ id, label, state: 'done' as const }));
}

function summarise(diagram: Diagram): string {
  const counts = diagram.validation.counts;
  const parts = [`${diagram.elements.length} элементов`, `${diagram.flows.length} связей`];
  if (diagram.lanes.length) parts.push(`${diagram.lanes.length} дорожек`);
  if (counts.error) parts.push(`${counts.error} ошибок`);
  if (diagram.clarifications.length) parts.push(`${diagram.clarifications.length} уточнений`);
  return parts.join(' · ');
}

export function describeError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return String(error);
}

/** The element a span belongs to, used by the text ↔ diagram link. */
export function spanOf(diagram: Diagram | null, elementId: string): SourceSpan | null {
  return diagram?.sourceMap?.[elementId] ?? null;
}

export function elementById(diagram: Diagram | null, id: string | null): ElementInfo | null {
  if (!diagram || !id) return null;
  return diagram.elements.find((element) => element.id === id) ?? null;
}

export function pendingQuestions(diagram: Diagram | null): Clarification[] {
  return diagram?.clarifications ?? [];
}
