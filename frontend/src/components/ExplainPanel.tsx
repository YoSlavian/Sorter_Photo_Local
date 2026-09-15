import { useState } from 'react';
import { api } from '../api/client';
import { describeError, useStudio } from '../state/store';

/**
 * Two readings of the same process: how the text was understood, and what the
 * diagram now says. The second is generated from the diagram, so after manual
 * edits it reflects the edits rather than the original description.
 */
export function ExplainPanel() {
  const diagram = useStudio((state) => state.diagram);
  const bpmn = useStudio((state) => state.bpmn);
  const notify = useStudio((state) => state.notify);
  const setSourceText = useStudio((state) => state.setSourceText);
  const [view, setView] = useState<'parse' | 'narrative'>('parse');
  const [narrative, setNarrative] = useState<string>('');
  const [busy, setBusy] = useState(false);

  if (!diagram) return <p className="ba-panel__empty">Диаграмма ещё не построена.</p>;

  const text = view === 'parse' ? diagram.explanation : narrative || diagram.narrative;

  const refresh = async () => {
    if (!bpmn) return;
    setBusy(true);
    try {
      const result = await api.describe(bpmn);
      setNarrative(result.text);
    } catch (error) {
      notify('error', describeError(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="ba-summary">
        <button
          type="button"
          className="ba-chip"
          aria-pressed={view === 'parse'}
          onClick={() => setView('parse')}
        >
          Как понят текст
        </button>
        <button
          type="button"
          className="ba-chip"
          aria-pressed={view === 'narrative'}
          onClick={() => {
            setView('narrative');
            void refresh();
          }}
        >
          Описание схемы
        </button>
      </div>

      <div style={{ padding: 10 }}>
        {busy ? (
          <p className="ba-panel__empty">
            <span className="ba-spinner" /> Готовим описание…
          </p>
        ) : (
          <pre className="ba-pre">{text || 'Нет данных.'}</pre>
        )}

        {view === 'narrative' && text && (
          <button
            type="button"
            className="ba-btn ba-btn--sm ba-btn--outline"
            style={{ marginTop: 8 }}
            onClick={() => {
              setSourceText(text);
              notify('info', 'Описание перенесено в текстовое поле.');
            }}
            title="Использовать это описание как исходный текст"
          >
            Перенести в описание
          </button>
        )}
      </div>
    </>
  );
}
