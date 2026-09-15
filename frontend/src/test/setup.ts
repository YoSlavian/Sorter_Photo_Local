import '@testing-library/jest-dom/vitest';

// bpmn-js measures real geometry; jsdom reports zeroes, which makes the
// modeller log noise during component tests. A stable stub keeps test output
// about the test.
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});
