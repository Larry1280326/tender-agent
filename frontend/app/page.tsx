"use client";

import { useState } from "react";
import Sidebar from "@/components/Sidebar";
import Chat from "@/components/Chat";

export default function Home() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionTitle, setSessionTitle] = useState("新專案");
  const [autoMessage, setAutoMessage] = useState<string | null>(null);

  return (
    <div className="flex h-screen">
      <Sidebar
        activeId={sessionId}
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
      />
      <div className="flex-1">
        <Chat
          sessionId={sessionId}
          sessionTitle={sessionTitle}
          autoMessage={autoMessage}
          onAutoMessageConsumed={() => setAutoMessage(null)}
        />
      </div>
    </div>
  );
}
