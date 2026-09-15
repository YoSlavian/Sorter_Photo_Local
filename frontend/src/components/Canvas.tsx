import { useStudio } from '../state/store';
import type { ModelerApi } from '../hooks/useModeler';

interface Props {
  containerRef: React.RefObject<HTMLDivElement | null>;
  modeler: ModelerApi;
}

export function Canvas({ containerRef, modeler }: Props) {
  const hasDiagram = useStudio((state) => Boolean(state.bpmn));
  const busy = useStudio((state) => state.busy);
  const stages = useStudio((state) => state.stages);
  const showStages = busy || stages.some((stage) => stage.state === 'failed');

  return (
    <main className="ba-canvas">
      <div className="ba-canvas__surface" ref={containerRef} data-testid="bpmn-canvas" />

      {!hasDiagram && !busy && (
        <div className="ba-canvas__placeholder">
          <h2>Диаграммы пока нет</h2>
          <p>
            Опишите процесс обычным текстом в панели слева и нажмите «Создать BPMN» — или
            откройте существующий <code>.bpmn</code> файл.
          </p>
        </div>
      )}

      {showStages && (
        <div className="ba-canvas__progress" role="status">
          {stages.map((stage) => (
            <span key={stage.id} className={`ba-stage ba-stage--${stage.state}`}>
              {stage.state === 'running' && <span className="ba-spinner" />}
              {stage.state === 'done' && '✓ '}
              {stage.state === 'failed' && '✕ '}
              {stage.label}
            </span>
          ))}
        </div>
      )}

      {hasDiagram && (
        <div className="ba-canvas__zoom">
          <button
            type="button"
            className="ba-btn ba-btn--icon ba-btn--sm"
            onClick={modeler.zoomOut}
            title="Уменьшить (Ctrl+-)"
          >
            −
          </button>
          <span className="ba-canvas__zoom-level">{Math.round(modeler.zoom * 100)}%</span>
          <button
            type="button"
            className="ba-btn ba-btn--icon ba-btn--sm"
            onClick={modeler.zoomIn}
            title="Увеличить (Ctrl++)"
          >
            +
          </button>
          <button
            type="button"
            className="ba-btn ba-btn--sm"
            onClick={modeler.fit}
            title="Вписать в экран (Ctrl+0)"
          >
            Вписать
          </button>
        </div>
      )}
    </main>
  );
}
