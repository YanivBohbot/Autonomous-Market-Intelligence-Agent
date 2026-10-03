import "@testing-library/jest-dom";

class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
window.ResizeObserver = window.ResizeObserver || ResizeObserver;

// jsdom doesn't implement scrollIntoView; ChatPane calls it whenever the
// message list changes (e.g. after sending a chat message in a test).
HTMLElement.prototype.scrollIntoView = HTMLElement.prototype.scrollIntoView || (() => {});

Object.defineProperty(HTMLElement.prototype, "offsetWidth", { configurable: true, value: 400 });
Object.defineProperty(HTMLElement.prototype, "offsetHeight", { configurable: true, value: 300 });
Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, value: 400 });
Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, value: 300 });

const originalGetBoundingClientRect = HTMLElement.prototype.getBoundingClientRect;
HTMLElement.prototype.getBoundingClientRect = function (this: HTMLElement) {
  const rect = originalGetBoundingClientRect.call(this);
  return {
    ...rect,
    width: 400,
    height: 300,
  } as any;
};
