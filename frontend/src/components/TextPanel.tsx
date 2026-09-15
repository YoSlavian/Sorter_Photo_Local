import { useCallback, useEffect, useRef } from 'react';
import { useStudio } from '../state/store';

const SAMPLE = `Обработка заявки клиента

Процесс начинается с получения заявки от клиента.
Менеджер проверяет заявку на полноту данных.
Если заявка корректна, то бухгалтер выставляет счёт, иначе менеджер отклоняет заявку и заявка возвращается к проверке заявки на полноту данных.
После этого менеджер уведомляет клиента о результате.
Процесс завершается.`;

/**
 * The description editor — the entry point of the product.
 *
 * It is also one half of the two-way link: moving the caret highlights the
 * elements that sentence produced, and selecting an element on the canvas
 * scrolls the matching sentence into view and selects it. Both directions read
 * the same source map, so they cannot disagree.
 */
export function TextPanel() {
  const sourceText = useStudio((state) => state.sourceText);
  const setSourceText = useStudio((state) => state.setSourceText);
  const build = useStudio((state) => state.build);
  const analyse = useStudio((state) => state.analyse);
  const busy = useStudio((state) => state.busy);
  const diagram = useStudio((state) => state.diagram);
  const selectedId = useStudio((state) => state.selectedId);
  const highlightFromCaret = useStudio((state) => state.highlightFromCaret);
  const clearHighlight = useStudio((state) => state.clearHighlight);
  const reset = useStudio((state) => state.reset);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const lastSelected = useRef<string | null>(null);

  // Diagram -> text: reveal the sentence behind the selected element.
  useEffect(() => {
    if (!selectedId || selectedId === lastSelected.current) return;
    lastSelected.current = selectedId;
    const span = diagram?.sourceMap?.[selectedId];
    const textarea = textareaRef.current;
    if (!span || !textarea) return;
    textarea.focus({ preventScroll: true });
    textarea.setSelectionRange(span.start, span.end);
    // Scroll proportionally: textareas expose no per-character geometry.
    const ratio = span.start / Math.max(1, textarea.value.length);
    textarea.scrollTop = Math.max(0, ratio * textarea.scrollHeight - textarea.clientHeight / 2);
  }, [selectedId, diagram]);

  // Text -> diagram: the caret decides what is highlighted.
  const syncCaret = useCallback(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    if (textarea.selectionStart === textarea.selectionEnd && !diagram) return;
    highlightFromCaret(textarea.selectionStart);
  }, [highlightFromCaret, diagram]);

  const words = sourceText.trim() ? sourceText.trim().split(/\s+/).length : 0;
  const lines = sourceText ? sourceText.split('\n').length : 0;

  return (
    <div className="ba-editor">
      <textarea
        ref={textareaRef}
        className="ba-editor__textarea"
        value={sourceText}
        placeholder={'Опишите процесс обычным текстом.\n\nНапример:\n' + SAMPLE}
        spellCheck={false}
        aria-label="Описание процесса"
        onChange={(event) => setSourceText(event.target.value)}
        onSelect={syncCaret}
        onKeyUp={syncCaret}
        onClick={syncCaret}
        onBlur={clearHighlight}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
            event.preventDefault();
            void build();
          }
        }}
      />

      <div className="ba-editor__meta">
        <span>
          {lines} строк · {words} слов
        </span>
        {diagram && Object.keys(diagram.sourceMap ?? {}).length > 0 && (
          <span>Клик по тексту подсвечивает элемент</span>
        )}
      </div>

      <div className="ba-editor__actions">
        <button
          type="button"
          className="ba-btn ba-btn--primary"
          onClick={() => void build()}
          disabled={busy || !sourceText.trim()}
          title="Ctrl+Enter"
        >
          {busy && <span className="ba-spinner" />} Создать BPMN
        </button>
        <button
          type="button"
          className="ba-btn ba-btn--outline"
          onClick={() => void analyse()}
          disabled={busy || !sourceText.trim()}
          title="Показать, как понят текст, не строя диаграмму"
        >
          Анализировать
        </button>
        <button
          type="button"
          className="ba-btn"
          onClick={() => {
            setSourceText('');
            reset();
          }}
          disabled={busy}
        >
          Очистить
        </button>
      </div>

      {!sourceText.trim() && (
        <button
          type="button"
          className="ba-btn ba-btn--sm ba-btn--outline"
          onClick={() => setSourceText(SAMPLE)}
        >
          Вставить пример
        </button>
      )}
    </div>
  );
}
