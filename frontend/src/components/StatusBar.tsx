import { useStudio } from '../state/store';

export function StatusBar() {
  const diagram = useStudio((state) => state.diagram);
  const dirty = useStudio((state) => state.dirty);
  const busy = useStudio((state) => state.busy);
  const info = useStudio((state) => state.info);
  const selectedId = useStudio((state) => state.selectedId);

  const errors = diagram?.validation.counts.error ?? 0;
  const warnings = diagram?.validation.counts.warning ?? 0;
  const dotClass = errors ? 'statusbar__dot--error' : dirty ? 'statusbar__dot--dirty' : '';

  return (
    <footer className="ba-statusbar">
      <span>
        <span className={`ba-statusbar__dot ${dotClass}`} />
        {busy ? 'Обработка…' : errors ? 'Есть ошибки' : dirty ? 'Есть несохранённые правки' : 'Готово'}
      </span>
      {diagram && (
        <>
          <span>
            {diagram.elements.length} элементов · {diagram.flows.length} связей
            {diagram.lanes.length ? ` · ${diagram.lanes.length} дорожек` : ''}
          </span>
          <span>
            {errors} ошибок · {warnings} предупреждений
          </span>
        </>
      )}
      {selectedId && <span>Выбрано: {selectedId}</span>}
      <span className="ba-statusbar__spacer" />
      {diagram?.meta.mode && (
        <span>
          Режим: {diagram.meta.mode}
          {diagram.meta.deterministic === false ? ' (недетерминированный)' : ''}
        </span>
      )}
      <span>
        <span className="ba-kbd">Ctrl</span> + <span className="ba-kbd">K</span> — команды
      </span>
      {info && <span>v{info.version}</span>}
    </footer>
  );
}
