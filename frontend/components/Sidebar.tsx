"use client";

import { useEffect, useState } from "react";
import { createSession, listSessions, Session } from "@/lib/api";

type Props = {
  activeId: string | null;
  onSelect: (id: string, title: string) => void;
  onCreate: (id: string) => void;
};

export default function Sidebar({ activeId, onSelect, onCreate }: Props) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    try {
      setSessions(await listSessions());
    } catch {
      /* backend 未就緒 */
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const handleCreate = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const s = await createSession();
      setSessions((prev) => [s, ...prev]);
      onCreate(s.id);
    } finally {
      setBusy(false);
    }
  };

  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-slate-200 bg-white">
      <div className="flex items-center justify-between border-b border-slate-200 px-3 py-3">
        <span className="text-sm font-semibold">招標助理</span>
        <button
          onClick={handleCreate}
          disabled={busy}
          className="rounded-lg bg-slate-900 px-2 py-1 text-xs text-white hover:bg-slate-700 disabled:opacity-50"
        >
          ＋ 新專案
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        {sessions.length === 0 ? (
          <p className="px-2 py-4 text-xs text-slate-400">
            未有專案，按「＋ 新專案」開始
          </p>
        ) : (
          sessions.map((s) => (
            <button
              key={s.id}
              onClick={() => onSelect(s.id, s.title)}
              className={`mb-1 block w-full truncate rounded-lg px-3 py-2 text-left text-sm ${
                s.id === activeId
                  ? "bg-slate-100 font-medium text-slate-900"
                  : "text-slate-600 hover:bg-slate-50"
              }`}
            >
              {s.title || "新專案"}
            </button>
          ))
        )}
      </div>
    </aside>
  );
}
