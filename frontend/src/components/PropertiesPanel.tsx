import { useEffect, useState } from 'react';
import { useStudio } from '../state/store';
import type { ElementSnapshot, ModelerApi } from '../hooks/useModeler';
import { EVENT_DEFINITIONS, TYPE_ALTERNATIVES, TYPE_LABELS, categoryOf } from '../lib/elements';

interface Props {
  modeler: ModelerApi;
}

/**
 * Properties of the selected element.
 *
 * Every control writes through the modeller, so a change here is the same
 * operation as a change on the canvas: it goes on the undo stack, it updates
 * the XML, and it reaches the server on the next sync. Nothing is kept as a
 * frontend-only overlay, which is what keeps the document single-sourced.
 */
export function PropertiesPanel({ modeler }: Props) {
  const selectedId = useStudio((state) => state.selectedId);
  const bpmn = useStudio((state) => state.bpmn);
  const [snapshot, setSnapshot] = useState<ElementSnapshot | null>(null);
  const [name, setName] = useState('');
  const [documentation, setDocumentation] = useState('');
  const [condition, setCondition] = useState('');
  const [timer, setTimer] = useState('');

  useEffect(() => {
    const next = selectedId ? modeler.inspect(selectedId) : null;
    setSnapshot(next);
    setName(next?.name ?? '');
    setDocumentation(next?.documentation ?? '');
    setCondition(next?.condition ?? '');
    setTimer(next?.timer ?? '');
  }, [selectedId, modeler, bpmn]);

  if (!selectedId || !snapshot) {
    return (
      <p className="ba-panel__empty">
        Выберите элемент на схеме, чтобы увидеть и изменить его свойства.
      </p>
    );
  }

  const category = categoryOf(snapshot.type);
  const alternatives =
    category === 'activity'
      ? TYPE_ALTERNATIVES.activity
      : category === 'gateway'
        ? TYPE_ALTERNATIVES.gateway
        : category === 'event'
          ? TYPE_ALTERNATIVES.event
          : [];
  const lanes = modeler.lanes();
  const isEvent = category === 'event';
  const isGateway = category === 'gateway';
  const isTimer = snapshot.eventDefinitionType === 'bpmn:TimerEventDefinition';

  const commitName = () => {
    if (name !== snapshot.name) modeler.rename(snapshot.id, name);
  };

  return (
    <div style={{ padding: 10 }}>
      <fieldset className="ba-fieldset">
        <legend className="ba-fieldset__legend">Основное</legend>

        <div className="ba-field">
          <label className="ba-field__label" htmlFor="prop-name">
            Название
          </label>
          <input
            id="prop-name"
            className="ba-field__control"
            value={name}
            onChange={(event) => setName(event.target.value)}
            onBlur={commitName}
            onKeyDown={(event) => event.key === 'Enter' && commitName()}
          />
        </div>

        <div className="ba-field">
          <label className="ba-field__label" htmlFor="prop-type">
            Тип
          </label>
          {alternatives.length ? (
            <select
              id="prop-type"
              className="ba-field__control"
              value={snapshot.type}
              onChange={(event) => modeler.changeType(snapshot.id, event.target.value)}
            >
              {alternatives.map((type) => (
                <option key={type} value={type}>
                  {TYPE_LABELS[type] ?? type}
                </option>
              ))}
            </select>
          ) : (
            <input id="prop-type" className="ba-field__control" value={TYPE_LABELS[snapshot.type] ?? snapshot.type} readOnly />
          )}
        </div>

        <div className="ba-field">
          <label className="ba-field__label" htmlFor="prop-id">
            Идентификатор
          </label>
          <input id="prop-id" className="ba-field__control" value={snapshot.id} readOnly />
          <div className="ba-field__hint">Используется в BPMN-файле и в диагностике.</div>
        </div>

        <div className="ba-field">
          <label className="ba-field__label" htmlFor="prop-doc">
            Документация
          </label>
          <textarea
            id="prop-doc"
            className="ba-textarea"
            rows={3}
            value={documentation}
            onChange={(event) => setDocumentation(event.target.value)}
            onBlur={() =>
              documentation !== snapshot.documentation &&
              modeler.setDocumentation(snapshot.id, documentation)
            }
          />
          <div className="ba-field__hint">
            Для сгенерированных элементов здесь исходное предложение описания.
          </div>
        </div>
      </fieldset>

      {!snapshot.isConnection && (
        <fieldset className="ba-fieldset">
          <legend className="ba-fieldset__legend">Исполнитель</legend>
          <div className="ba-field">
            <label className="ba-field__label" htmlFor="prop-lane">
              Дорожка
            </label>
            {lanes.length ? (
              <select
                id="prop-lane"
                className="ba-field__control"
                value={snapshot.laneId}
                onChange={(event) =>
                  event.target.value && modeler.moveToLane(snapshot.id, event.target.value)
                }
              >
                <option value="">— не назначена —</option>
                {lanes.map((lane) => (
                  <option key={lane.id} value={lane.id}>
                    {lane.name}
                  </option>
                ))}
              </select>
            ) : (
              <div className="ba-field__hint">
                В диаграмме нет дорожек. Добавьте пул из палитры, чтобы распределить
                элементы по ролям.
              </div>
            )}
          </div>
        </fieldset>
      )}

      {isEvent && (
        <fieldset className="ba-fieldset">
          <legend className="ba-fieldset__legend">Событие</legend>
          <div className="ba-field">
            <label className="ba-field__label" htmlFor="prop-event">
              Триггер
            </label>
            <select
              id="prop-event"
              className="ba-field__control"
              value={snapshot.eventDefinitionType}
              onChange={(event) =>
                modeler.changeType(snapshot.id, snapshot.type, event.target.value || undefined)
              }
            >
              {EVENT_DEFINITIONS.map((definition) => (
                <option key={definition.value} value={definition.value}>
                  {definition.label}
                </option>
              ))}
            </select>
          </div>

          {isTimer && (
            <div className="ba-field">
              <label className="ba-field__label" htmlFor="prop-timer">
                Значение таймера
              </label>
              <input
                id="prop-timer"
                className="ba-field__control"
                value={timer}
                placeholder="P3D, PT2H или R/P1D"
                onChange={(event) => setTimer(event.target.value)}
                onBlur={() => timer !== snapshot.timer && modeler.setTimer(snapshot.id, timer)}
              />
              <div className="ba-field__hint">ISO-8601: P3D — три дня, PT2H — два часа.</div>
            </div>
          )}
        </fieldset>
      )}

      {snapshot.isConnection && (
        <fieldset className="ba-fieldset">
          <legend className="ba-fieldset__legend">Поток</legend>
          <div className="ba-field">
            <label className="ba-field__label" htmlFor="prop-condition">
              Условие
            </label>
            <input
              id="prop-condition"
              className="ba-field__control"
              value={condition}
              disabled={snapshot.isDefaultFlow}
              placeholder={snapshot.isDefaultFlow ? 'Поток по умолчанию' : 'например: сумма > 100000'}
              onChange={(event) => setCondition(event.target.value)}
              onBlur={() =>
                condition !== snapshot.condition && modeler.setCondition(snapshot.id, condition)
              }
            />
            <div className="ba-field__hint">
              {snapshot.isDefaultFlow
                ? 'У потока по умолчанию условия быть не может — так требует спецификация BPMN.'
                : 'Отображается на схеме рядом со связью.'}
            </div>
          </div>
        </fieldset>
      )}

      {isGateway && (
        <fieldset className="ba-fieldset">
          <legend className="ba-fieldset__legend">Шлюз</legend>
          <div className="ba-field">
            <label className="ba-field__label" htmlFor="prop-default">
              Поток по умолчанию
            </label>
            <select
              id="prop-default"
              className="ba-field__control"
              value={snapshot.defaultFlowId}
              onChange={(event) =>
                modeler.setDefaultFlow(snapshot.id, event.target.value || null)
              }
            >
              <option value="">— нет —</option>
              {snapshot.outgoing.map((flow) => (
                <option key={flow.id} value={flow.id}>
                  {flow.name || flow.id}
                </option>
              ))}
            </select>
          </div>
        </fieldset>
      )}

      <fieldset className="ba-fieldset">
        <legend className="ba-fieldset__legend">Связи</legend>
        <ConnectionList
          label="Входящие"
          items={snapshot.incoming}
          onSelect={(id) => modeler.selectById(id)}
        />
        <ConnectionList
          label="Исходящие"
          items={snapshot.outgoing}
          onSelect={(id) => modeler.selectById(id)}
        />
      </fieldset>
    </div>
  );
}

function ConnectionList({
  label,
  items,
  onSelect,
}: {
  label: string;
  items: { id: string; name: string }[];
  onSelect: (id: string) => void;
}) {
  return (
    <div className="ba-field">
      <span className="ba-field__label">
        {label} ({items.length})
      </span>
      {items.length === 0 ? (
        <div className="ba-field__hint">нет</div>
      ) : (
        <div className="ba-question__options">
          {items.map((item) => (
            <button type="button" key={item.id} className="ba-chip" onClick={() => onSelect(item.id)}>
              {item.name || item.id}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
