import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useStudio } from '../state/store';
import type { Diagram } from '../api/types';

function diagramFixture(overrides: Partial<Diagram> = {}): Diagram {
  return {
    bpmn: '<?xml version="1.0"?><definitions/>',
    elements: [],
    lanes: [],
    flows: [],
    validation: { ok: true, counts: { error: 0, warning: 0, info: 0 }, diagnostics: [] },
    sourceMap: {
      Activity_1: {
        elementId: 'Activity_1',
        sentence: 'Менеджер проверяет заявку.',
        line: 2,
        start: 10,
        end: 36,
        exact: true,
      },
      Gateway_1: {
        elementId: 'Gateway_1',
        sentence: 'Если заявка корректна, то ...',
        line: 3,
        start: 0,
        end: 80,
        exact: true,
      },
    },
    clarifications: [],
    explanation: '',
    narrative: '',
    meta: {},
    ...overrides,
  };
}

describe('studio store', () => {
  beforeEach(() => {
    useStudio.setState({
      diagram: null,
      bpmn: '',
      notices: [],
      highlighted: [],
      selectedId: null,
      panel: 'properties',
      dirty: false,
      sourceText: '',
    });
  });

  it('keeps the draft in the store and in storage', () => {
    useStudio.getState().setSourceText('Менеджер проверяет заявку.');
    expect(useStudio.getState().sourceText).toBe('Менеджер проверяет заявку.');
    expect(localStorage.getItem('bpmn-architect.draft')).toBe('Менеджер проверяет заявку.');
  });

  it('maps a caret position to the innermost element first', () => {
    useStudio.setState({ diagram: diagramFixture() });
    useStudio.getState().highlightFromCaret(20);
    expect(useStudio.getState().highlighted).toEqual(['Activity_1', 'Gateway_1']);
  });

  it('highlights nothing outside a mapped sentence', () => {
    useStudio.setState({ diagram: diagramFixture() });
    useStudio.getState().highlightFromCaret(500);
    expect(useStudio.getState().highlighted).toEqual([]);
  });

  it('reveals properties when an element is selected from the list', () => {
    useStudio.setState({ panel: 'elements' });
    useStudio.getState().select('Activity_1');
    expect(useStudio.getState().panel).toBe('properties');
  });

  it('keeps the current tab when selection is cleared', () => {
    useStudio.setState({ panel: 'validation' });
    useStudio.getState().select(null);
    expect(useStudio.getState().panel).toBe('validation');
  });

  it('expires non-error notices and keeps errors', () => {
    vi.useFakeTimers();
    useStudio.getState().notify('success', 'готово');
    useStudio.getState().notify('error', 'сломалось');
    expect(useStudio.getState().notices).toHaveLength(2);
    vi.advanceTimersByTime(6000);
    expect(useStudio.getState().notices.map((n) => n.kind)).toEqual(['error']);
    vi.useRealTimers();
  });

  it('applies the theme to the document and remembers it', () => {
    useStudio.getState().setTheme('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(localStorage.getItem('bpmn-architect.theme')).toBe('dark');
  });

  it('refuses to save when there is no diagram', async () => {
    const result = await useStudio.getState().saveProject();
    expect(result).toBeNull();
    expect(useStudio.getState().notices[0]?.kind).toBe('warning');
  });

  it('resets the document but keeps the description', () => {
    useStudio.getState().setSourceText('описание');
    useStudio.setState({ diagram: diagramFixture(), bpmn: '<x/>', dirty: true });
    useStudio.getState().reset();
    expect(useStudio.getState().diagram).toBeNull();
    expect(useStudio.getState().bpmn).toBe('');
    expect(useStudio.getState().sourceText).toBe('описание');
  });
});
