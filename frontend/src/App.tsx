import { useEffect, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { useUiTransition } from "./lib/ui-motion";
import { Brand } from "./components/brand";
import {
  BookOpen,
  CheckCheck,
  ChevronDown,
  Files,
  GitBranch,
  Inbox,
  ListTodo,
  Mail,
  Menu,
  Plus,
  Settings2,
  ShieldCheck,
  X,
} from "lucide-react";
import {
  AdminAccess,
  Checks,
  Documents,
  ImportDocument,
  KnowledgeGraph,
  MailPanel,
  Requests,
} from "./components/admin";
import {
  NewTask,
  TaskJourney,
  TaskList,
  taskHref,
} from "./components/task-journey";
import { Empty, Modal, Notice, SourceModal } from "./components/primitives";
import { api } from "./lib/api";
import { loadTasks, saveTasks } from "./lib/tasks";
import type { Task } from "./lib/types";

import {
  DocumentReader,
  type DocumentSelection,
} from "./components/document-reader";

function useRoute() {
  const read = () => location.hash.slice(2).split("?")[0].split("/");
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const update = () => {
      setRoute(read());
      window.scrollTo({ top: 0 });
    };
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  return route;
}
function loadPreferences() {
  try {
    const p = JSON.parse(localStorage.getItem("smena.display.v1") || "null");
    return Array.isArray(p) &&
      p.every((v) => ["concise", "sources"].includes(v))
      ? p
      : ["concise", "sources"];
  } catch {
    return ["concise", "sources"];
  }
}
export default function App() {
  const transition = useUiTransition(),
    reducedMotion = useReducedMotion();
  const route = useRoute(),
    admin = route[0] === "admin",
    page = admin ? route[1] || "documents" : route[0] || "new";
  const [tasks, setTasks] = useState(loadTasks),
    [preferences, setPreferences] = useState<string[]>(loadPreferences),
    [storageError, setStorageError] = useState(false),
    [documentSelection, setDocument] = useState<DocumentSelection | null>(null),
    [sourceId, setSourceId] = useState<string | null>(null),
    [menu, setMenu] = useState(false),
    [adminUser, setAdminUser] = useState<string | null>(null),
    [checkingAdmin, setCheckingAdmin] = useState(true);
  useEffect(() => {
    if (!admin) return;
    const controller = new AbortController();
    const expire = () => setAdminUser(null);
    window.addEventListener("admin-session-expired", expire);
    setCheckingAdmin(true);
    api.adminSession(controller.signal)
      .then(({ username }) => setAdminUser(username))
      .catch(() => { if (!controller.signal.aborted) expire(); })
      .finally(() => { if (!controller.signal.aborted) setCheckingAdmin(false); });
    return () => {
      controller.abort();
      window.removeEventListener("admin-session-expired", expire);
    };
  }, [admin]);
  const task =
    page === "task" ? tasks.find((t) => t.id === route[1]) : undefined;
  const step =
    page === "task" && route[2] === "step" ? Number(route[3]) : undefined;
  useEffect(() => {
    setSourceId(null);
    setDocument(null);
    setMenu(false);
  }, [route.join("/")]);
  function persist(next: Task[]) {
    setTasks(next);
    setStorageError(!saveTasks(next));
  }
  function updateTask(updated: Task) {
    persist(tasks.map((t) => (t.id === updated.id ? updated : t)));
  }
  function createTask(created: Task) {
    persist([created, ...tasks].slice(0, 50));
    location.hash = taskHref(created.id).slice(1);
  }
  function display(values: string[]) {
    setPreferences(values);
    try {
      localStorage.setItem("smena.display.v1", JSON.stringify(values));
    } catch {
      setStorageError(true);
    }
  }
  const nav = admin
    ? [
        {
          to: "admin/documents",
          label: "Регламенты",
          icon: Files,
          active: ["documents", "import"].includes(page),
        },
        {
          to: "admin/map",
          label: "Карта знаний",
          icon: GitBranch,
          active: page === "map",
        },
        {
          to: "admin/checks",
          label: "Проверка регламентов",
          icon: ShieldCheck,
          active: page === "checks",
        },
        {
          to: "admin/requests",
          label: "Запросы материалов",
          icon: Inbox,
          active: page === "requests",
        },
        {
          to: "admin/mail",
          label: "Почтовый бот",
          icon: Mail,
          active: page === "mail",
        },
      ]
    : [
        {
          to: "new",
          label: "Новая задача",
          icon: Plus,
          active: page === "new",
        },
        {
          to: "tasks",
          label: "Мои задачи",
          icon: ListTodo,
          active: ["task", "tasks"].includes(page),
        },
        {
          to: "documents",
          label: "Документы",
          icon: BookOpen,
          active: page === "documents",
        },
      ];
  const Navigation = () => (
    <nav
      aria-label={admin ? "Навигация администратора" : "Рабочее пространство"}
    >
      <p className="nav-label">
        {admin ? "Администрирование" : "Рабочее пространство"}
      </p>
      {nav.map(({ to, label, icon: Icon, active }) => (
        <a
          key={to}
          href={`#/${to}`}
          onClick={() => setMenu(false)}
          className="sm-nav-item"
          aria-current={active ? "page" : undefined}
        >
          <Icon size={16} />
          {label}
        </a>
      ))}
    </nav>
  );
  return (
    <div className="sm-app">
      <a
        className="skip-link"
        href="#main"
        onClick={(e) => {
          e.preventDefault();
          document.getElementById("main")?.focus();
        }}
      >
        К содержимому
      </a>
      <aside className="sm-sidebar">
        <a className="brand" href={admin ? "#/admin/documents" : "#/new"}>
          <Brand />
        </a>
        <Navigation />
        <div className="sidebar-bottom">
          <span className="meta">
            {admin ? "Администратор" : "Сотрудник МФТИ"}
          </span>
          <a
            className="sm-nav-item"
            href={admin ? "#/new" : "#/admin/documents"}
          >
            {admin ? <ListTodo size={16} /> : <Settings2 size={16} />}{" "}
            {admin ? "Рабочее пространство" : "Администрирование"}
          </a>
        </div>
      </aside>
      <div className="app-workspace">
        <header className="sm-topbar">
          <span>Смена</span>
          <span>/</span>
          <span>{admin ? "Администрирование" : "Рабочее пространство"}</span>
          <span className="topbar-role">
            {admin ? "Администратор" : "Сотрудник"}
          </span>
        </header>
        <header className="sm-mobilebar">
          <button
            className="sm-icon-button"
            aria-label="Открыть меню"
            onClick={() => setMenu(true)}
          >
            <Menu size={20} />
          </button>
          <a className="mobile-brand" href="#/new">
            <Brand compact />
          </a>
          <span className="meta">{admin ? "Администрирование" : ""}</span>
        </header>
        <main className="sm-page" id="main" tabIndex={-1}>
          <motion.div
            key={`${admin}/${page}/${route[1] || ""}/${step ?? ""}`}
            className="page-content"
            initial={reducedMotion ? false : { opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={transition}
          >
            {storageError && (
              <Notice title="Не удалось сохранить прогресс">
                Задача доступна до закрытия страницы. Освободите место в
                браузере или разрешите локальное хранилище.
              </Notice>
            )}
            {admin && (checkingAdmin
              ? <p role="status">Проверяем вход…</p>
              : <AdminAccess username={adminUser} onSession={setAdminUser} />)}

            {!admin && page === "new" && (
              <NewTask
                onCreate={createTask}
                preferences={preferences}
                onPreferences={display}
              />
            )}
            {!admin && page === "tasks" && <TaskList tasks={tasks} />}
            {!admin &&
              page === "task" &&
              (task ? (
                <TaskJourney
                  key={task.id}
                  task={task}
                  step={step}
                  onUpdate={updateTask}
                  onSource={setSourceId}
                  preferences={preferences}
                />
              ) : (
                <Empty
                  title="Задача не найдена"
                  action={
                    <a href="#/tasks" className="sm-button button-primary">
                      Мои задачи
                    </a>
                  }
                >
                  Задачи сохраняются в том браузере, где были созданы.
                </Empty>
              ))}
            {page === "documents" && (!admin || !!adminUser) && (
              <Documents admin={admin} onDocument={setDocument} />
            )}
            {admin && !!adminUser && page === "import" && <ImportDocument />}
            {admin && !!adminUser && page === "map" && (
              <KnowledgeGraph onSource={setSourceId} onDocument={setDocument} />
            )}
            {admin && !!adminUser && page === "checks" && <Checks onSource={setSourceId} />}
            {admin && !!adminUser && page === "requests" && (
              <Requests onSource={setSourceId} />
            )}
            {admin && !!adminUser && page === "mail" && <MailPanel />}
            {![
              "new",
              "tasks",
              "task",
              "documents",
              "import",
              "map",
              "checks",
              "requests",
              "mail",
            ].includes(page) && (
              <Empty
                title="Страница не найдена"
                action={<a href="#/new">Новая задача</a>}
              >
                Откройте нужный раздел в меню.
              </Empty>
            )}
          </motion.div>
        </main>
      </div>
      <Modal open={menu} onClose={() => setMenu(false)} title="Смена">
        <Navigation />
        <a
          className="sm-button button-subtle"
          onClick={() => setMenu(false)}
          href={admin ? "#/new" : "#/admin/documents"}
        >
          {admin ? "Рабочее пространство" : "Администрирование"}
        </a>
      </Modal>
      <DocumentReader
        document={documentSelection}
        onClose={() => setDocument(null)}
      />
      <SourceModal sourceId={sourceId} onClose={() => setSourceId(null)} />
    </div>
  );
}
