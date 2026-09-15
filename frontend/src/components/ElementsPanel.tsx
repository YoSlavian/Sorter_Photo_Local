import { useStudio } from '../state/store';
import { ELEMENT_CATALOGUE, TYPE_LABELS } from '../lib/elements';
import type { ElementInfo } from '../api/types';

const ICONS = new Map(ELEMENT_CATALOGUE.map((spec) => [spec.type, spec.icon]));

function iconFor(element: ElementInfo): string {
  const key = `bpmn:${element.type.charAt(0).toUpperCase()}${element.type.slice(1)}`;
  return ICONS.get(key) ?? 'bpmn-icon-task';
}

/**
 * Everything the description produced, as a list.
 *
 * This is the "распознанные элементы" view: each row carries the element, the
 * role performing it, and the sentence it came from, which is what lets a
 * reviewer check the diagram against the text without reading XML.
 */
export function ElementsPanel() {
  const diagram = useStudio((state) => state.diagram);
  const selectedId = useStudio((state) => state.selectedId);
  const select = useStudio((state) => state.select);

  if (!diagram?.elements.length) {
    return <p className="ba-panel__empty">Элементов пока нет.</p>;
  }

  return (
    <div className="ba-list">
      {diagram.elements.map((element) => {
        const span = diagram.sourceMap?.[element.id];
        return (
          <button
            type="button"
            key={element.id}
            className="ba-list__item"
            aria-current={element.id === selectedId}
            onClick={() => select(element.id)}
          >
            <span className={`ba-list__icon ${iconFor(element)}`} aria-hidden />
            <span className="ba-list__body">
              <span className="ba-list__title">{element.name || <em>без названия</em>}</span>
              <div className="ba-list__meta">
                {TYPE_LABELS[`bpmn:${element.type.charAt(0).toUpperCase()}${element.type.slice(1)}`] ??
                  element.type}
                {element.laneName ? ` · ${element.laneName}` : ''}
              </div>
              {span && <div className="ba-list__source">«{span.sentence}»</div>}
            </span>
          </button>
        );
      })}
    </div>
  );
}
