import { describe, it, expect } from "vitest";
import {
  canComplete,
  completeTask,
  loadTasks,
  nextStep,
  saveTasks,
  toggleStep,
  TASK_KEY,
} from "./tasks";
import type { Answer, Task } from "./types";
const answer: Answer = {
  result_type: "answered",
  summary: [],
  steps: Array.from({ length: 4 }, (_, i) => ({
    text: `Synthetic ${i}`,
    citation_ids: ["test"],
  })),
  citations: [],
  missing_information: [],
  clarifications: [],
  conflicts: [],
  corpus_revision: "test",
};
const task: Task = {
  id: "test",
  question: "Synthetic question",
  answer,
  completed: [],
  status: "active",
  createdAt: "2026-11-14",
  updatedAt: "2026-11-14",
};
describe("task state", () => {
  it("supports every combination and undo without disturbing other marks", () => {
    for (let mask = 0; mask < 16; mask++) {
      let value = {
        ...task,
        completed: Array.from({ length: 4 }, (_, i) => i).filter(
          (i) => mask & (1 << i),
        ),
      };
      for (let i = 0; i < 4; i++) {
        const changed = toggleStep(value, i);
        expect(changed.completed).toEqual(
          Array.from({ length: 4 }, (_, j) => j).filter(
            (j) => (mask ^ (1 << i)) & (1 << j),
          ),
        );
        expect(toggleStep(changed, i).completed).toEqual(value.completed);
      }
      expect(canComplete(value)).toBe(mask === 15);
      expect(nextStep(value)).toBe(
        Array.from({ length: 4 }, (_, i) => i).find(
          (i) => !(mask & (1 << i)),
        ) ?? -1,
      );
    }
  });
  it("cannot complete zero-step or partially completed answers", () => {
    expect(completeTask(task).status).toBe("active");
    expect(canComplete({ ...task, answer: { ...answer, steps: [] } })).toBe(
      false,
    );
    expect(completeTask({ ...task, completed: [0, 1, 2, 3] }).status).toBe(
      "completed",
    );
  });
  it("restores marks from storage and reports quota errors", () => {
    let raw = "";
    const storage = {
      getItem: () => raw,
      setItem: (_key: string, value: string) => {
        raw = value;
      },
    };
    const changed = toggleStep(task, 2);
    expect(saveTasks([changed], storage)).toBe(true);
    expect(loadTasks(storage)[0].completed).toEqual([2]);
    expect(
      saveTasks([task], {
        setItem: () => {
          throw new Error("quota");
        },
      }),
    ).toBe(false);
    raw = "invalid";
    expect(loadTasks(storage)).toEqual([]);
    raw = JSON.stringify([
      { ...task, completed: [-1] },
      { ...task, completed: [0, 0] },
    ]);
    expect(loadTasks(storage)).toEqual([]);
  });
});
