import { useStudio } from '../state/store';

const SEVERITY_LABEL: Record<string, string> = {
  error: 'Ошибка',
  warning: 'Предупреждение',
  info: 'Информация',
};

/** Validation results, each one a link to the element it concerns. */
export function ValidationPanel() {
  const diagram = useStudio((state) => state.diagram);
  const select = useStudio((state) => state.select);

  if (!diagram) return <p className="ba-panel__empty">Диаграмма ещё не построена.</p>;

  const { ok, counts, diagnostics } = diagram.validation;

  return (
    <>
      <div className="ba-summary">
        <span className={`ba-pill ${ok ? 'ba-pill--ok' : 'ba-pill--error'}`}>
          {ok ? '✓ Структура корректна' : '✕ Есть ошибки'}
        </span>
        {counts.warning > 0 && <span className="ba-pill ba-pill--warning">{counts.warning} предупр.</span>}
        {counts.info > 0 && <span className="ba-pill">{counts.info} инфо</span>}
      </div>

      {diagnostics.length === 0 ? (
        <p className="ba-panel__empty">Замечаний нет.</p>
      ) : (
        <div className="ba-list">
          {diagnostics.map((item, index) => (
            <button
              type="button"
              key={`${item.code}-${item.elementId ?? index}`}
              className={`ba-list__item ba-diagnostic ba-diagnostic--${item.severity}`}
              onClick={() => item.elementId && select(item.elementId)}
              disabled={!item.elementId}
              title={item.elementId ? 'Показать элемент на схеме' : undefined}
            >
              <span className="ba-list__body">
                <span className="ba-list__title">{item.message}</span>
                <div className="ba-list__meta">
                  <span className="ba-diagnostic__code">{item.code}</span> ·{' '}
                  {SEVERITY_LABEL[item.severity] ?? item.severity}
                  {item.elementId ? ` · ${item.elementId}` : ''}
                </div>
              </span>
            </button>
          ))}
        </div>
      )}
    </>
  );
}
