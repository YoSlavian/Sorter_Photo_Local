import { useRef, useState } from 'react';
import { useStudio } from '../state/store';
import type { ModelerApi } from '../hooks/useModeler';
import { baseName, downloadText, readTextFile } from '../lib/download';
import { exportPdf, exportPng, exportSvg } from '../lib/export';
import { describeError } from '../state/store';

interface Props {
  modeler: ModelerApi;
}

export function Toolbar({ modeler }: Props) {
  const store = useStudio();
  const fileRef = useRef<HTMLInputElement>(null);
  const [exportOpen, setExportOpen] = useState(false);

  const hasDiagram = Boolean(store.bpmn);

  const open = async (file: File) => {
    const text = await readTextFile(file);
    if (file.name.endsWith('.bpmn-project') || text.trimStart().startsWith('{')) {
      await store.openProject(text);
    } else {
      await store.openBpmn(text, baseName(file.name));
    }
  };

  const save = async () => {
    // Save what is on the canvas right now, not the last synced copy.
    const xml = await modeler.exportXml();
    if (xml) await store.syncFromModeler(xml);
    const payload = await store.saveProject();
    if (payload) {
      downloadText(payload.project, payload.filename, 'application/json');
      store.notify('success', `Проект сохранён: ${payload.filename}`);
    }
  };

  const doExport = async (kind: 'bpmn' | 'svg' | 'png' | 'pdf' | 'json') => {
    setExportOpen(false);
    const name = baseName(store.projectName || 'process');
    try {
      if (kind === 'bpmn') {
        downloadText(await modeler.exportXml(), `${name}.bpmn`, 'application/xml');
      } else if (kind === 'json') {
        const xml = await modeler.exportXml();
        const { api } = await import('../api/client');
        const blob = await api.exportJson(xml);
        downloadText(await blob.text(), `${name}.json`, 'application/json');
      } else {
        const svg = await modeler.exportSvg();
        if (kind === 'svg') exportSvg(svg, name);
        if (kind === 'png') await exportPng(svg, name);
        if (kind === 'pdf') await exportPdf(svg, name);
      }
      store.notify('success', `Экспорт ${kind.toUpperCase()} готов.`);
    } catch (error) {
      store.notify('error', describeError(error));
    }
  };

  return (
    <header className="ba-toolbar">
      <div className="ba-toolbar__brand">
        <span className="ba-toolbar__title">BPMN Architect Studio</span>
      </div>

      <div className="ba-toolbar__group">
        <button
          type="button"
          className="ba-btn"
          onClick={() => {
            store.reset();
            store.notify('info', 'Создан новый пустой проект.');
          }}
        >
          Новый
        </button>
        <button type="button" className="ba-btn" onClick={() => fileRef.current?.click()}>
          Открыть
        </button>
        <button type="button" className="ba-btn" onClick={() => void save()} disabled={!hasDiagram}>
          Сохранить
        </button>
        <div style={{ position: 'relative' }}>
          <button
            type="button"
            className="ba-btn"
            disabled={!hasDiagram}
            aria-expanded={exportOpen}
            onClick={() => setExportOpen((value) => !value)}
          >
            Экспорт ▾
          </button>
          {exportOpen && (
            <div
              className="ba-command"
              style={{ position: 'absolute', top: 32, left: 0, width: 190, zIndex: 50 }}
              onMouseLeave={() => setExportOpen(false)}
            >
              {(['bpmn', 'svg', 'png', 'pdf', 'json'] as const).map((kind) => (
                <button
                  key={kind}
                  type="button"
                  className="ba-command__item"
                  onClick={() => void doExport(kind)}
                >
                  <span>{kind.toUpperCase()}</span>
                  <span className="ba-command__hint">
                    {kind === 'bpmn' ? 'стандарт' : kind === 'json' ? 'данные' : 'изображение'}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="ba-toolbar__group">
        <button
          type="button"
          className="ba-btn ba-btn--icon"
          onClick={modeler.undo}
          disabled={!modeler.canUndo}
          title="Отменить (Ctrl+Z)"
        >
          ↶
        </button>
        <button
          type="button"
          className="ba-btn ba-btn--icon"
          onClick={modeler.redo}
          disabled={!modeler.canRedo}
          title="Повторить (Ctrl+Shift+Z)"
        >
          ↷
        </button>
        <button
          type="button"
          className="ba-btn"
          onClick={() => void store.relayout()}
          disabled={!hasDiagram || store.busy}
          title="Перестроить компоновку движком (Ctrl+L)"
        >
          Авто-компоновка
        </button>
      </div>

      <div className="ba-toolbar__group">
        <input
          className="ba-toolbar__name"
          value={store.projectName}
          placeholder="Название процесса"
          onChange={(event) => store.setProjectName(event.target.value)}
          aria-label="Название процесса"
        />
      </div>

      <span className="ba-toolbar__spacer" />

      <div className="ba-toolbar__group">
        <button
          type="button"
          className="ba-btn ba-btn--sm"
          aria-pressed={store.leftMode === 'text'}
          onClick={() => store.setLeftMode('text')}
        >
          Текст
        </button>
        <button
          type="button"
          className="ba-btn ba-btn--sm"
          aria-pressed={store.leftMode === 'palette'}
          onClick={() => store.setLeftMode('palette')}
        >
          Элементы
        </button>
      </div>

      <div className="ba-toolbar__group">
        <select
          className="ba-btn ba-btn--sm"
          value={store.options.mode}
          onChange={(event) =>
            store.setOptions({ mode: event.target.value as typeof store.options.mode })
          }
          title="Режим интерпретации текста"
          aria-label="Режим интерпретации"
        >
          <option value="deterministic">Детерминированный</option>
          <option value="hybrid">Гибридный</option>
          <option value="ai">AI</option>
        </select>
        <button
          type="button"
          className="ba-btn ba-btn--icon"
          onClick={() => store.setTheme(store.theme === 'dark' ? 'light' : 'dark')}
          title="Светлая / тёмная тема"
        >
          {store.theme === 'dark' ? '☀' : '☾'}
        </button>
      </div>

      <input
        ref={fileRef}
        type="file"
        accept=".bpmn,.xml,.bpmn-project,application/xml,application/json"
        hidden
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void open(file);
          event.target.value = '';
        }}
      />
    </header>
  );
}
