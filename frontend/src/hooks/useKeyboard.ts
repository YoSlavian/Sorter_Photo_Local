import { useEffect } from 'react';
import { useStudio } from '../state/store';

export interface Shortcut {
  id: string;
  label: string;
  hint: string;
  run: () => void;
  /** Matches an event; undefined means the command is palette-only. */
  match?: (event: KeyboardEvent) => boolean;
}

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.tagName === 'INPUT' ||
    target.tagName === 'TEXTAREA' ||
    target.tagName === 'SELECT' ||
    target.isContentEditable
  );
}

/**
 * Application shortcuts.
 *
 * Editing shortcuts (undo, redo, delete, copy, paste) are deliberately left to
 * bpmn-js, which already binds them and already knows when the canvas has
 * focus. Binding them twice would mean two handlers racing over one command
 * stack.
 */
export function useKeyboard(shortcuts: Shortcut[]): void {
  const toggleCommandPalette = useStudio((state) => state.toggleCommandPalette);
  const commandPaletteOpen = useStudio((state) => state.commandPaletteOpen);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const mod = event.ctrlKey || event.metaKey;

      if (mod && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        toggleCommandPalette();
        return;
      }
      if (event.key === 'Escape' && commandPaletteOpen) {
        toggleCommandPalette(false);
        return;
      }
      // Ctrl+Enter is meant to work *from* the description field.
      const typing = isTyping(event.target);
      for (const shortcut of shortcuts) {
        if (!shortcut.match?.(event)) continue;
        if (typing && !(mod && event.key === 'Enter')) continue;
        event.preventDefault();
        shortcut.run();
        return;
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [shortcuts, toggleCommandPalette, commandPaletteOpen]);
}
