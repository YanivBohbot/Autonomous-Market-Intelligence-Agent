import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { FileListCard } from "./FileListCard";
import type { DisplayPayload } from "./types";

const display: Extract<DisplayPayload, { type: "file_list" }> = {
  type: "file_list",
  path: ".",
  dirs: ["reports", "screenshots"],
  files: [
    { name: "notes.txt", url: null },
    { name: "tv10-homepage.png", url: "/workspace/screenshots/tv10-homepage.png" },
  ],
};

describe("FileListCard", () => {
  it("shows the listed folder, its subfolders and its files", () => {
    render(<FileListCard display={display} />);
    expect(screen.getByText("workspace")).toBeInTheDocument();
    expect(screen.getByText("reports")).toBeInTheDocument();
    expect(screen.getByText("screenshots")).toBeInTheDocument();
    expect(screen.getByText("notes.txt")).toBeInTheDocument();
    expect(screen.getByText("tv10-homepage.png")).toBeInTheDocument();
  });

  it("links only the files the backend can serve", () => {
    render(<FileListCard display={display} />);
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "/workspace/screenshots/tv10-homepage.png");
    expect(links[0]).toHaveTextContent("tv10-homepage.png");
  });

  it("names a subfolder listing by its path", () => {
    render(<FileListCard display={{ ...display, path: "reports", dirs: [] }} />);
    expect(screen.getByText("workspace/reports")).toBeInTheDocument();
  });

  it("counts folders and files", () => {
    render(<FileListCard display={display} />);
    expect(screen.getByText("2 folders · 2 files")).toBeInTheDocument();
  });
});
