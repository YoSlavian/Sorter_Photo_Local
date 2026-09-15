/**
 * The BPMN element catalogue used by the palette and the properties panel.
 *
 * One table, two consumers: the palette drags these onto the canvas, and the
 * properties panel offers the same set when a user changes an element's type.
 * Keeping it in a single place is what stops the two from disagreeing about
 * what a "Service Task" is.
 */

export interface ElementSpec {
  /** Stable key used in the UI. */
  id: string;
  /** BPMN 2.0 element name, as bpmn-js expects it. */
  type: string;
  /** Event definition for events that carry one. */
  eventDefinitionType?: string;
  label: string;
  /** bpmn-font class, shipped with bpmn-js. */
  icon: string;
  group: 'events' | 'activities' | 'gateways' | 'collaboration';
  /** Expanded sub-processes are created differently from collapsed ones. */
  isExpanded?: boolean;
}

export const ELEMENT_CATALOGUE: ElementSpec[] = [
  // -- events ---------------------------------------------------------------
  {
    id: 'start',
    type: 'bpmn:StartEvent',
    label: 'Начальное событие',
    icon: 'bpmn-icon-start-event-none',
    group: 'events',
  },
  {
    id: 'start-message',
    type: 'bpmn:StartEvent',
    eventDefinitionType: 'bpmn:MessageEventDefinition',
    label: 'Начало по сообщению',
    icon: 'bpmn-icon-start-event-message',
    group: 'events',
  },
  {
    id: 'start-timer',
    type: 'bpmn:StartEvent',
    eventDefinitionType: 'bpmn:TimerEventDefinition',
    label: 'Начало по таймеру',
    icon: 'bpmn-icon-start-event-timer',
    group: 'events',
  },
  {
    id: 'intermediate',
    type: 'bpmn:IntermediateThrowEvent',
    label: 'Промежуточное событие',
    icon: 'bpmn-icon-intermediate-event-none',
    group: 'events',
  },
  {
    id: 'intermediate-message',
    type: 'bpmn:IntermediateCatchEvent',
    eventDefinitionType: 'bpmn:MessageEventDefinition',
    label: 'Ожидание сообщения',
    icon: 'bpmn-icon-intermediate-event-catch-message',
    group: 'events',
  },
  {
    id: 'intermediate-timer',
    type: 'bpmn:IntermediateCatchEvent',
    eventDefinitionType: 'bpmn:TimerEventDefinition',
    label: 'Таймер',
    icon: 'bpmn-icon-intermediate-event-catch-timer',
    group: 'events',
  },
  {
    id: 'end',
    type: 'bpmn:EndEvent',
    label: 'Конечное событие',
    icon: 'bpmn-icon-end-event-none',
    group: 'events',
  },
  {
    id: 'end-error',
    type: 'bpmn:EndEvent',
    eventDefinitionType: 'bpmn:ErrorEventDefinition',
    label: 'Завершение с ошибкой',
    icon: 'bpmn-icon-end-event-error',
    group: 'events',
  },
  // -- activities -----------------------------------------------------------
  { id: 'task', type: 'bpmn:Task', label: 'Задача', icon: 'bpmn-icon-task', group: 'activities' },
  {
    id: 'user-task',
    type: 'bpmn:UserTask',
    label: 'Пользовательская задача',
    icon: 'bpmn-icon-user-task',
    group: 'activities',
  },
  {
    id: 'service-task',
    type: 'bpmn:ServiceTask',
    label: 'Системная задача',
    icon: 'bpmn-icon-service-task',
    group: 'activities',
  },
  {
    id: 'manual-task',
    type: 'bpmn:ManualTask',
    label: 'Ручная задача',
    icon: 'bpmn-icon-manual-task',
    group: 'activities',
  },
  {
    id: 'script-task',
    type: 'bpmn:ScriptTask',
    label: 'Скрипт',
    icon: 'bpmn-icon-script-task',
    group: 'activities',
  },
  {
    id: 'send-task',
    type: 'bpmn:SendTask',
    label: 'Отправка сообщения',
    icon: 'bpmn-icon-send-task',
    group: 'activities',
  },
  {
    id: 'receive-task',
    type: 'bpmn:ReceiveTask',
    label: 'Приём сообщения',
    icon: 'bpmn-icon-receive-task',
    group: 'activities',
  },
  {
    id: 'rule-task',
    type: 'bpmn:BusinessRuleTask',
    label: 'Бизнес-правило',
    icon: 'bpmn-icon-business-rule-task',
    group: 'activities',
  },
  {
    id: 'subprocess',
    type: 'bpmn:SubProcess',
    label: 'Подпроцесс',
    icon: 'bpmn-icon-subprocess-collapsed',
    group: 'activities',
  },
  // -- gateways -------------------------------------------------------------
  {
    id: 'gateway-xor',
    type: 'bpmn:ExclusiveGateway',
    label: 'Исключающий шлюз',
    icon: 'bpmn-icon-gateway-xor',
    group: 'gateways',
  },
  {
    id: 'gateway-parallel',
    type: 'bpmn:ParallelGateway',
    label: 'Параллельный шлюз',
    icon: 'bpmn-icon-gateway-parallel',
    group: 'gateways',
  },
  {
    id: 'gateway-inclusive',
    type: 'bpmn:InclusiveGateway',
    label: 'Включающий шлюз',
    icon: 'bpmn-icon-gateway-or',
    group: 'gateways',
  },
  {
    id: 'gateway-event',
    type: 'bpmn:EventBasedGateway',
    label: 'Событийный шлюз',
    icon: 'bpmn-icon-gateway-eventbased',
    group: 'gateways',
  },
  // -- collaboration --------------------------------------------------------
  {
    id: 'participant',
    type: 'bpmn:Participant',
    label: 'Пул',
    icon: 'bpmn-icon-participant',
    group: 'collaboration',
  },
];

export const GROUP_LABELS: Record<ElementSpec['group'], string> = {
  events: 'События',
  activities: 'Задачи',
  gateways: 'Шлюзы',
  collaboration: 'Участники',
};

/** Types a user may switch an existing element to, grouped by what fits. */
export const TYPE_ALTERNATIVES = {
  activity: [
    'bpmn:Task',
    'bpmn:UserTask',
    'bpmn:ServiceTask',
    'bpmn:ManualTask',
    'bpmn:ScriptTask',
    'bpmn:SendTask',
    'bpmn:ReceiveTask',
    'bpmn:BusinessRuleTask',
    'bpmn:SubProcess',
  ],
  gateway: [
    'bpmn:ExclusiveGateway',
    'bpmn:ParallelGateway',
    'bpmn:InclusiveGateway',
    'bpmn:EventBasedGateway',
  ],
  event: [
    'bpmn:StartEvent',
    'bpmn:IntermediateCatchEvent',
    'bpmn:IntermediateThrowEvent',
    'bpmn:EndEvent',
  ],
} as const satisfies Record<string, readonly string[]>;

export const TYPE_LABELS: Record<string, string> = {
  'bpmn:Task': 'Задача',
  'bpmn:UserTask': 'Пользовательская',
  'bpmn:ServiceTask': 'Системная',
  'bpmn:ManualTask': 'Ручная',
  'bpmn:ScriptTask': 'Скрипт',
  'bpmn:SendTask': 'Отправка',
  'bpmn:ReceiveTask': 'Приём',
  'bpmn:BusinessRuleTask': 'Бизнес-правило',
  'bpmn:SubProcess': 'Подпроцесс',
  'bpmn:CallActivity': 'Вызов процесса',
  'bpmn:ExclusiveGateway': 'Исключающий',
  'bpmn:ParallelGateway': 'Параллельный',
  'bpmn:InclusiveGateway': 'Включающий',
  'bpmn:EventBasedGateway': 'Событийный',
  'bpmn:StartEvent': 'Начальное',
  'bpmn:EndEvent': 'Конечное',
  'bpmn:IntermediateCatchEvent': 'Промежуточное (приём)',
  'bpmn:IntermediateThrowEvent': 'Промежуточное (генерация)',
  'bpmn:SequenceFlow': 'Поток управления',
  'bpmn:MessageFlow': 'Поток сообщений',
  'bpmn:Participant': 'Пул',
  'bpmn:Lane': 'Дорожка',
};

export const EVENT_DEFINITIONS: { value: string; label: string }[] = [
  { value: '', label: 'Без триггера' },
  { value: 'bpmn:MessageEventDefinition', label: 'Сообщение' },
  { value: 'bpmn:TimerEventDefinition', label: 'Таймер' },
  { value: 'bpmn:SignalEventDefinition', label: 'Сигнал' },
  { value: 'bpmn:ErrorEventDefinition', label: 'Ошибка' },
  { value: 'bpmn:EscalationEventDefinition', label: 'Эскалация' },
  { value: 'bpmn:ConditionalEventDefinition', label: 'Условие' },
  { value: 'bpmn:TerminateEventDefinition', label: 'Прерывание' },
];

export type ElementCategory = 'activity' | 'gateway' | 'event' | 'other';

export function categoryOf(type: string): ElementCategory {
  if (type.endsWith('Gateway')) return 'gateway';
  if (type.endsWith('Event')) return 'event';
  if ((TYPE_ALTERNATIVES.activity as readonly string[]).includes(type)) return 'activity';
  return 'other';
}
