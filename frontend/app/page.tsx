"use client";

import { useState } from "react";
import Sidebar from "@/components/Sidebar";
import Chat from "@/components/Chat";
import { listSessions } from "@/lib/api";

export default function Home() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionTitle, setSessionTitle] = useState("新專案");
  const [autoMessage, setAutoMessage] = useState<string | null>(null);
  const [refreshSignal, setRefreshSignal] = useState(0);

  const handleSessionsChanged = async () => {
    try {
      const list = await listSessions();
      if (sessionId) {
        const cur = list.find((s) => s.id === sessionId);
        if (cur) setSessionTitle(cur.title || "新專案");
      }
      setRefreshSignal((n) => n + 1);
    } catch {
      /* backend 未就緒 */
    }
  };

  const handleDelete = (id: string) => {
    if (sessionId === id) {
      setSessionId(null);
      setSessionTitle("新專案");
      setAutoMessage(null);
    }
    setRefreshSignal((n) => n + 1);
  };

  return (
    <div className="flex h-screen">
      <Sidebar
        activeId={sessionId}
        refreshSignal={refreshSignal}
        onSelect={(id, title) => {
          setSessionId(id);
          setSessionTitle(title);
          setAutoMessage(null);
        }}
        onCreate={(id) => {
          setSessionId(id);
          setSessionTitle("新專案");
          setAutoMessage("請列出所有香港非政府招標項目");
        }}
        onDelete={handleDelete}
      />
      <div className="flex-1 min-w-0">
        <Chat
          sessionId={sessionId}
          sessionTitle={sessionTitle}
          autoMessage={autoMessage}
          onAutoMessageConsumed={() => setAutoMessage(null)}
          onSessionsChanged={handleSessionsChanged}
        />
      </div>
    </div>
  );
}
