import { ELEMENT_CATALOGUE, GROUP_LABELS, type ElementSpec } from '../lib/elements';
import type { ModelerApi } from '../hooks/useModeler';

const GROUPS: ElementSpec['group'][] = ['events', 'activities', 'gateways', 'collaboration'];

/** Canvas tools. The built-in bpmn-js palette is hidden, so they live here. */
const TOOLS = [
  { id: 'hand', label: 'Перемещение холста', icon: 'bpmn-icon-hand-tool' },
  { id: 'lasso', label: 'Выделение рамкой', icon: 'bpmn-icon-lasso-tool' },
  { id: 'space', label: 'Раздвинуть место', icon: 'bpmn-icon-space-tool' },
  { id: 'connect', label: 'Соединить элементы', icon: 'bpmn-icon-connection-multi' },
] as const;

interface Props {
  modeler: ModelerApi;
  enabled: boolean;
}

/**
 * The element palette.
 *
 * Dragging starts a real bpmn-js create operation, so an element dropped from
 * here is created by the same code path as one created from the built-in
 * palette — it obeys the same modelling rules and lands in the right lane.
 */
export function Palette({ modeler, enabled }: Props) {
  return (
    <aside className="ba-panel ba-panel--left">
      <header className="ba-panel__header">Элементы BPMN</header>
      <div className="ba-panel__body">
        {!enabled && (
          <p className="ba-panel__empty">
            Создайте или откройте диаграмму, чтобы добавлять элементы.
          </p>
        )}
        {enabled && (
          <section className="ba-palette__group">
            <h3 className="ba-palette__label">Инструменты</h3>
            {TOOLS.map((tool) => (
              <button
                type="button"
                key={tool.id}
                className="ba-palette__item"
                title={tool.label}
                onMouseDown={(event) => modeler.activateTool(tool.id, event)}
              >
                <span className={`ba-palette__icon ${tool.icon}`} aria-hidden />
                <span>{tool.label}</span>
              </button>
            ))}
          </section>
        )}
        {enabled &&
          GROUPS.map((group) => (
            <section className="ba-palette__group" key={group}>
              <h3 className="ba-palette__label">{GROUP_LABELS[group]}</h3>
              {ELEMENT_CATALOGUE.filter((spec) => spec.group === group).map((spec) => (
                <button
                  type="button"
                  key={spec.id}
                  className="ba-palette__item"
                  title={`${spec.label} — перетащите на холст`}
                  draggable={false}
                  onMouseDown={(event) => modeler.startCreate(event, spec)}
                >
                  <span className={`ba-palette__icon ${spec.icon}`} aria-hidden />
                  <span>{spec.label}</span>
                </button>
              ))}
            </section>
          ))}
        {enabled && (
          <p className="ba-palette__hint">
            Перетащите элемент на холст. Соединяйте элементы, потянув за стрелку на
            выделенном элементе.
          </p>
        )}
      </div>
    </aside>
  );
}
