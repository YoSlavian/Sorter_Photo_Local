import { useEffect, useMemo, useRef } from 'react';
import { useStudio, type PanelId } from './state/store';
import { useModeler } from './hooks/useModeler';
import { useKeyboard, type Shortcut } from './hooks/useKeyboard';
import { Toolbar } from './components/Toolbar';
import { Palette } from './components/Palette';
import { Canvas } from './components/Canvas';
import { TextPanel } from './components/TextPanel';
import { PropertiesPanel } from './components/PropertiesPanel';
import { ElementsPanel } from './components/ElementsPanel';
import { ValidationPanel } from './components/ValidationPanel';
import { QuestionsPanel } from './components/QuestionsPanel';
import { ExplainPanel } from './components/ExplainPanel';
import { StatusBar } from './components/StatusBar';
import { Notifications } from './components/Notifications';
import { CommandPalette } from './components/CommandPalette';

import './styles/theme.css';
import './styles/app.css';

const TABS: { id: PanelId; label: string }[] = [
  { id: 'properties', label: 'Свойства' },
  { id: 'elements', label: 'Элементы' },
  { id: 'validation', label: 'Проверка' },
  { id: 'questions', label: 'Уточнения' },
  { id: 'explain', label: 'Разбор' },
];

export default function App() {
  const containerRef = useRef<HTMLDivElement>(null);
  const modeler = useModeler(containerRef);

  const panel = useStudio((state) => state.panel);
  const setPanel = useStudio((state) => state.setPanel);
  const leftMode = useStudio((state) => state.leftMode);
  const setLeftMode = useStudio((state) => state.setLeftMode);
  const diagram = useStudio((state) => state.diagram);
  const loadInfo = useStudio((state) => state.loadInfo);
  const build = useStudio((state) => state.build);
  const relayout = useStudio((state) => state.relayout);
  const dirty = useStudio((state) => state.dirty);

  useEffect(() => {
    void loadInfo();
  }, [loadInfo]);

  // Losing unsaved edits to a stray tab close is the one browser default worth
  // overriding.
  useEffect(() => {
    const handler = (event: BeforeUnloadEvent) => {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [dirty]);

  const commands = useMemo<Shortcut[]>(
    () => [
      {
        id: 'build',
        label: 'Создать BPMN из текста',
        hint: 'Ctrl+Enter',
        run: () => void build(),
        match: (event) => (event.ctrlKey || event.metaKey) && event.key === 'Enter',
      },
      {
        id: 'layout',
        label: 'Авто-компоновка',
        hint: 'Ctrl+L',
        run: () => void relayout(),
        match: (event) => (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'l',
      },
      { id: 'fit', label: 'Вписать в экран', hint: 'Ctrl+0', run: modeler.fit,
        match: (event) => (event.ctrlKey || event.metaKey) && event.key === '0' },
      { id: 'zoom-in', label: 'Увеличить', hint: 'Ctrl++', run: modeler.zoomIn,
        match: (event) => (event.ctrlKey || event.metaKey) && (event.key === '+' || event.key === '=') },
      { id: 'zoom-out', label: 'Уменьшить', hint: 'Ctrl+-', run: modeler.zoomOut,
        match: (event) => (event.ctrlKey || event.metaKey) && event.key === '-' },
      { id: 'text', label: 'Панель: описание процесса', hint: '', run: () => setLeftMode('text') },
      { id: 'palette', label: 'Панель: элементы BPMN', hint: '', run: () => setLeftMode('palette') },
      ...TABS.map((tab) => ({
        id: `tab-${tab.id}`,
        label: `Вкладка: ${tab.label}`,
        hint: '',
        run: () => setPanel(tab.id),
      })),
      { id: 'undo', label: 'Отменить', hint: 'Ctrl+Z', run: modeler.undo },
      { id: 'redo', label: 'Повторить', hint: 'Ctrl+Shift+Z', run: modeler.redo },
      { id: 'delete', label: 'Удалить выбранное', hint: 'Delete', run: modeler.removeSelection },
      { id: 'copy', label: 'Копировать', hint: 'Ctrl+C', run: modeler.copySelection },
      { id: 'paste', label: 'Вставить', hint: 'Ctrl+V', run: modeler.paste },
    ],
    [build, relayout, modeler, setLeftMode, setPanel],
  );

  useKeyboard(commands);

  const questionCount = diagram?.clarifications.length ?? 0;
  const errorCount = diagram?.validation.counts.error ?? 0;

  return (
    <div className="ba-app">
      <Toolbar modeler={modeler} />

      <div className="ba-workspace">
        {leftMode === 'palette' ? (
          <Palette modeler={modeler} enabled={Boolean(diagram)} />
        ) : (
          <aside className="ba-panel ba-panel--left">
            <header className="ba-panel__header">Описание процесса</header>
            <div className="ba-panel__body">
              <TextPanel />
            </div>
          </aside>
        )}

        <Canvas containerRef={containerRef} modeler={modeler} />

        <aside className="ba-panel ba-panel--right">
          <div className="ba-tabs" role="tablist">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                role="tab"
                className="ba-tab"
                aria-selected={panel === tab.id}
                onClick={() => setPanel(tab.id)}
              >
                {tab.label}
                {tab.id === 'validation' && errorCount > 0 && (
                  <span className="ba-tab__badge ba-tab__badge--danger">{errorCount}</span>
                )}
                {tab.id === 'questions' && questionCount > 0 && (
                  <span className="ba-tab__badge ba-tab__badge--accent">{questionCount}</span>
                )}
              </button>
            ))}
          </div>
          <div className="ba-panel__body ba-panel__body--flush" role="tabpanel">
            {panel === 'properties' && <PropertiesPanel modeler={modeler} />}
            {panel === 'elements' && <ElementsPanel />}
            {panel === 'validation' && <ValidationPanel />}
            {panel === 'questions' && <QuestionsPanel />}
            {panel === 'explain' && <ExplainPanel />}
          </div>
        </aside>
      </div>

      <StatusBar />
      <Notifications />
      <CommandPalette commands={commands} />
    </div>
  );
}
