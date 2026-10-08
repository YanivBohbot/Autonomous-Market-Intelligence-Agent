import "@testing-library/jest-dom";

class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

if (typeof window !== "undefined") {
  window.ResizeObserver = window.ResizeObserver || ResizeObserver;

  // jsdom doesn't implement scrollIntoView; ChatPane calls it whenever the
  // message list changes (e.g. after sending a chat message in a test).
  HTMLElement.prototype.scrollIntoView = HTMLElement.prototype.scrollIntoView || (() => {});

  // jsdom's Blob/File don't implement arrayBuffer() (as of jsdom 25); ImportPanel
  // reads uploaded .xlsx files via file.arrayBuffer(). Polyfill via FileReader.
  if (typeof Blob !== "undefined" && typeof Blob.prototype.arrayBuffer !== "function") {
    Blob.prototype.arrayBuffer = function (this: Blob): Promise<ArrayBuffer> {
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result as ArrayBuffer);
        reader.onerror = () => reject(reader.error);
        reader.readAsArrayBuffer(this);
      });
    };
  }

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
}
