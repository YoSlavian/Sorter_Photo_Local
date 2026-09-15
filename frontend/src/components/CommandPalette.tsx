import { useEffect, useMemo, useRef, useState } from 'react';
import { useStudio } from '../state/store';
import type { Shortcut } from '../hooks/useKeyboard';

interface Props {
  commands: Shortcut[];
}

/** Every action in one searchable list — the keyboard route to the whole app. */
export function CommandPalette({ commands }: Props) {
  const open = useStudio((state) => state.commandPaletteOpen);
  const toggle = useStudio((state) => state.toggleCommandPalette);
  const [query, setQuery] = useState('');
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return commands;
    return commands.filter((command) => command.label.toLowerCase().includes(needle));
  }, [commands, query]);

  useEffect(() => {
    if (open) {
      setQuery('');
      setCursor(0);
      // The dialog mounts in the same tick; focus after paint.
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  if (!open) return null;

  const run = (index: number) => {
    const command = matches[index];
    if (!command) return;
    toggle(false);
    command.run();
  };

  return (
    <div className="ba-overlay" onMouseDown={() => toggle(false)} role="presentation">
      <div
        className="ba-command"
        role="dialog"
        aria-modal="true"
        aria-label="Палитра команд"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <input
          ref={inputRef}
          className="ba-command__input"
          placeholder="Команда…"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setCursor(0);
          }}
          onKeyDown={(event) => {
            if (event.key === 'ArrowDown') {
              event.preventDefault();
              setCursor((value) => Math.min(matches.length - 1, value + 1));
            } else if (event.key === 'ArrowUp') {
              event.preventDefault();
              setCursor((value) => Math.max(0, value - 1));
            } else if (event.key === 'Enter') {
              event.preventDefault();
              run(cursor);
            }
          }}
        />
        <div className="ba-command__list">
          {matches.length === 0 && <div className="ba-panel__empty">Ничего не найдено</div>}
          {matches.map((command, index) => (
            <button
              type="button"
              key={command.id}
              className="ba-command__item"
              aria-selected={index === cursor}
              onMouseEnter={() => setCursor(index)}
              onClick={() => run(index)}
            >
              <span>{command.label}</span>
              <span className="ba-command__hint">{command.hint}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
