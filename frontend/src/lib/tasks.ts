import { isAnswer } from "./api";
import type { Task, Answer } from "./types";
export const TASK_KEY = "smena.tasks.v1";
export function makeTask(question: string, answer: Answer): Task {
  const now = new Date().toISOString();
  return {
    id: crypto.randomUUID(),
    question,
    answer,
    completed: [],
    status: "active",
    createdAt: now,
    updatedAt: now,
  };
}
export function toggleStep(task: Task, index: number): Task {
  if (
    !Number.isInteger(index) ||
    index < 0 ||
    index >= task.answer.steps.length
  )
    return task;
  return {
    ...task,
    status: "active",
    completed: task.completed.includes(index)
      ? task.completed.filter((i) => i !== index)
      : [...task.completed, index].sort((a, b) => a - b),
    updatedAt: new Date().toISOString(),
  };
}
export const nextStep = (task: Task) =>
  task.answer.steps.findIndex((_, i) => !task.completed.includes(i));
export const canComplete = (task: Task) =>
  task.answer.steps.length > 0 && nextStep(task) === -1;
export function completeTask(task: Task): Task {
  return canComplete(task)
    ? { ...task, status: "completed", updatedAt: new Date().toISOString() }
    : task;
}
export function loadTasks(
  storage: Pick<Storage, "getItem"> = localStorage,
): Task[] {
  try {
    const rows: unknown = JSON.parse(storage.getItem(TASK_KEY) || "[]");
    if (!Array.isArray(rows)) return [];
    return rows
      .filter(
        (t): t is Task =>
          t &&
          typeof t.id === "string" &&
          typeof t.question === "string" &&
          isAnswer(t.answer) &&
          ["active", "completed"].includes(t.status) &&
          typeof t.createdAt === "string" &&
          typeof t.updatedAt === "string" &&
          Array.isArray(t.completed) &&
          t.completed.every(
            (i: unknown) =>
              typeof i === "number" &&
              Number.isInteger(i) &&
              i >= 0 &&
              i < t.answer.steps.length,
          ) &&
          new Set(t.completed).size === t.completed.length,
      )
      .slice(0, 50);
  } catch {
    return [];
  }
}
export function saveTasks(
  tasks: Task[],
  storage: Pick<Storage, "setItem"> = localStorage,
): boolean {
  try {
    storage.setItem(TASK_KEY, JSON.stringify(tasks.slice(0, 50)));
    return true;
  } catch {
    return false;
  }
}
