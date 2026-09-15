import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useStudio } from '../state/store';
import { PropertiesPanel } from '../components/PropertiesPanel';
import { ElementsPanel } from '../components/ElementsPanel';
import { ValidationPanel } from '../components/ValidationPanel';
import { QuestionsPanel } from '../components/QuestionsPanel';
import { StatusBar } from '../components/StatusBar';
import type { ModelerApi } from '../hooks/useModeler';
import type { Diagram } from '../api/types';

function fakeModeler(overrides: Partial<ModelerApi> = {}): ModelerApi {
  return {
    ready: true,
    canUndo: true,
    canRedo: false,
    zoom: 1,
    undo: vi.fn(),
    redo: vi.fn(),
    zoomIn: vi.fn(),
    zoomOut: vi.fn(),
    zoomTo: vi.fn(),
    fit: vi.fn(),
    removeSelection: vi.fn(),
    copySelection: vi.fn(),
    paste: vi.fn(),
    selectById: vi.fn(),
    startCreate: vi.fn(),
    activateTool: vi.fn(),
    rename: vi.fn(),
    changeType: vi.fn(),
    setProperties: vi.fn(),
    moveToLane: vi.fn(),
    inspect: vi.fn(() => ({
      id: 'Activity_1',
      type: 'bpmn:UserTask',
      name: 'Проверить заявку',
      documentation: 'Менеджер проверяет заявку.',
      eventDefinitionType: '',
      timer: '',
      condition: '',
      isDefaultFlow: false,
      defaultFlowId: '',
      laneId: 'Lane_1',
      laneName: 'Менеджер',
      incoming: [{ id: 'Flow_1', name: '' }],
      outgoing: [{ id: 'Flow_2', name: 'Да' }],
      isConnection: false,
    })),
    setDocumentation: vi.fn(),
    setCondition: vi.fn(),
    setDefaultFlow: vi.fn(),
    setTimer: vi.fn(),
    lanes: vi.fn(() => [
      { id: 'Lane_1', name: 'Менеджер' },
      { id: 'Lane_2', name: 'Бухгалтер' },
    ]),
    exportXml: vi.fn(async () => '<?xml version="1.0"?><definitions/>'),
    exportSvg: vi.fn(async () => '<svg/>'),
    elementIds: vi.fn(() => ['Activity_1']),
    ...overrides,
  };
}

const diagram: Diagram = {
  bpmn: '<?xml?>',
  elements: [
    {
      id: 'Activity_1',
      type: 'userTask',
      name: 'Проверить заявку',
      category: 'activity',
      lane: 'Lane_1',
      laneName: 'Менеджер',
      eventDefinition: null,
      documentation: 'Менеджер проверяет заявку.',
      incoming: ['Flow_1'],
      outgoing: ['Flow_2'],
      attributes: {},
    },
    {
      id: 'Gateway_1',
      type: 'exclusiveGateway',
      name: 'Заявка корректна?',
      category: 'gateway',
      lane: 'Lane_1',
      laneName: 'Менеджер',
      eventDefinition: null,
      documentation: '',
      incoming: ['Flow_2'],
      outgoing: ['Flow_3', 'Flow_4'],
      attributes: {},
    },
  ],
  lanes: [{ id: 'Lane_1', name: 'Менеджер', order: 0 }],
  flows: [],
  validation: {
    ok: false,
    counts: { error: 1, warning: 0, info: 0 },
    diagnostics: [
      {
        code: 'E003',
        severity: 'error',
        message: 'Элемент недостижим',
        elementId: 'Gateway_1',
        line: 0,
      },
    ],
  },
  sourceMap: {
    Activity_1: {
      elementId: 'Activity_1',
      sentence: 'Менеджер проверяет заявку.',
      line: 2,
      start: 0,
      end: 26,
      exact: true,
    },
  },
  clarifications: [
    {
      id: 'ask_1_naming',
      kind: 'naming',
      question: 'Что именно происходит на шаге «Обработка»?',
      elementId: 'Activity_1',
      flowId: null,
      options: [{ value: '', label: 'Обработка', freeText: true }],
      sentence: 'Далее выполняется обработка.',
      line: 3,
    },
  ],
  explanation: '',
  narrative: '',
  meta: { elementCount: 2, flowCount: 0, laneCount: 1 },
};

beforeEach(() => {
  useStudio.setState({
    diagram,
    bpmn: diagram.bpmn,
    selectedId: 'Activity_1',
    notices: [],
    dirty: false,
    busy: false,
    panel: 'properties',
  });
});

describe('PropertiesPanel', () => {
  it('shows the selected element', () => {
    render(<PropertiesPanel modeler={fakeModeler()} />);
    expect(screen.getByLabelText('Название')).toHaveValue('Проверить заявку');
    expect(screen.getByLabelText('Идентификатор')).toHaveValue('Activity_1');
    expect(screen.getByLabelText('Документация')).toHaveValue('Менеджер проверяет заявку.');
  });

  it('renames through the modeller, not locally', async () => {
    const modeler = fakeModeler();
    render(<PropertiesPanel modeler={modeler} />);
    const input = screen.getByLabelText('Название');
    await userEvent.clear(input);
    await userEvent.type(input, 'Проверить документы{Enter}');
    expect(modeler.rename).toHaveBeenCalledWith('Activity_1', 'Проверить документы');
  });

  it('changes the element type', async () => {
    const modeler = fakeModeler();
    render(<PropertiesPanel modeler={modeler} />);
    await userEvent.selectOptions(screen.getByLabelText('Тип'), 'bpmn:ServiceTask');
    expect(modeler.changeType).toHaveBeenCalledWith('Activity_1', 'bpmn:ServiceTask');
  });

  it('moves an element to another lane', async () => {
    const modeler = fakeModeler();
    render(<PropertiesPanel modeler={modeler} />);
    await userEvent.selectOptions(screen.getByLabelText('Дорожка'), 'Lane_2');
    expect(modeler.moveToLane).toHaveBeenCalledWith('Activity_1', 'Lane_2');
  });

  it('writes documentation on blur', async () => {
    const modeler = fakeModeler();
    render(<PropertiesPanel modeler={modeler} />);
    const area = screen.getByLabelText('Документация');
    await userEvent.clear(area);
    await userEvent.type(area, 'Новое описание');
    await userEvent.tab();
    expect(modeler.setDocumentation).toHaveBeenCalledWith('Activity_1', 'Новое описание');
  });

  it('offers the timer field only for timer events', () => {
    const modeler = fakeModeler({
      inspect: vi.fn(() => ({
        id: 'Event_1',
        type: 'bpmn:IntermediateCatchEvent',
        name: 'Ожидание',
        documentation: '',
        eventDefinitionType: 'bpmn:TimerEventDefinition',
        timer: 'P3D',
        condition: '',
        isDefaultFlow: false,
        defaultFlowId: '',
        laneId: '',
        laneName: '',
        incoming: [],
        outgoing: [],
        isConnection: false,
      })),
    });
    render(<PropertiesPanel modeler={modeler} />);
    expect(screen.getByLabelText('Значение таймера')).toHaveValue('P3D');
  });

  it('blocks a condition on a default flow, as BPMN requires', () => {
    const modeler = fakeModeler({
      inspect: vi.fn(() => ({
        id: 'Flow_9',
        type: 'bpmn:SequenceFlow',
        name: 'Нет',
        documentation: '',
        eventDefinitionType: '',
        timer: '',
        condition: '',
        isDefaultFlow: true,
        defaultFlowId: '',
        laneId: '',
        laneName: '',
        incoming: [],
        outgoing: [],
        isConnection: true,
      })),
    });
    render(<PropertiesPanel modeler={modeler} />);
    expect(screen.getByLabelText('Условие')).toBeDisabled();
  });

  it('asks for a selection when nothing is selected', () => {
    useStudio.setState({ selectedId: null });
    render(<PropertiesPanel modeler={fakeModeler()} />);
    expect(screen.getByText(/Выберите элемент/)).toBeInTheDocument();
  });
});

describe('ElementsPanel', () => {
  it('lists every element with its role and source sentence', () => {
    render(<ElementsPanel />);
    expect(screen.getByText('Проверить заявку')).toBeInTheDocument();
    expect(screen.getAllByText(/Менеджер/).length).toBeGreaterThan(0);
    expect(screen.getByText('«Менеджер проверяет заявку.»')).toBeInTheDocument();
  });

  it('selects an element when its row is clicked', async () => {
    render(<ElementsPanel />);
    await userEvent.click(screen.getByText('Заявка корректна?'));
    expect(useStudio.getState().selectedId).toBe('Gateway_1');
  });
});

describe('ValidationPanel', () => {
  it('summarises the result and jumps to the problem element', async () => {
    render(<ValidationPanel />);
    expect(screen.getByText(/Есть ошибки/)).toBeInTheDocument();
    await userEvent.click(screen.getByText('Элемент недостижим'));
    expect(useStudio.getState().selectedId).toBe('Gateway_1');
  });
});

describe('QuestionsPanel', () => {
  it('sends only the answers that were filled in', async () => {
    const answer = vi.fn(async () => {});
    useStudio.setState({ answer });
    render(<QuestionsPanel />);
    const apply = screen.getByRole('button', { name: /Применить ответы/ });
    expect(apply).toBeDisabled();

    await userEvent.type(screen.getByPlaceholderText('Ваш ответ…'), 'Обработать обращение');
    await userEvent.click(screen.getByRole('button', { name: /Применить ответы/ }));
    expect(answer).toHaveBeenCalledWith({ ask_1_naming: 'Обработать обращение' });
  });
});

describe('StatusBar', () => {
  it('reports the document state', () => {
    render(<StatusBar />);
    expect(screen.getByText(/Есть ошибки/)).toBeInTheDocument();
    expect(screen.getByText(/2 элементов/)).toBeInTheDocument();
  });

  it('reports unsaved edits', () => {
    useStudio.setState({
      dirty: true,
      diagram: { ...diagram, validation: { ok: true, counts: { error: 0, warning: 0, info: 0 }, diagnostics: [] } },
    });
    render(<StatusBar />);
    expect(screen.getByText(/несохранённые/)).toBeInTheDocument();
  });
});

describe('two-way text link', () => {
  it('maps a caret offset to the element produced by that sentence', () => {
    useStudio.getState().highlightFromCaret(5);
    expect(useStudio.getState().highlighted).toEqual(['Activity_1']);
  });
});

describe('element list icons', () => {
  it('renders a BPMN icon for every element', () => {
    const { container } = render(<ElementsPanel />);
    const icons = container.querySelectorAll('.ba-list__icon[class*="bpmn-icon-"]');
    expect(icons).toHaveLength(diagram.elements.length);
  });
});
