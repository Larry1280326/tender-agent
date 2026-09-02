export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type Session = {
  id: string;
  title: string;
  tender_id: string;
  created_at: string;
  updated_at: string;
};

export type TextItem = { type: "text"; text: string };
export type ToolItem = { type: "tool"; name: string; result?: string; done: boolean };
export type Item = TextItem | ToolItem;
export type Message = { role: "user" | "assistant"; items: Item[]; markdown?: string };

export type ChatEvent = {
  event: string;
  delta?: string;
  node?: string;
  message?: string;
  markdown?: string;
  interrupt_id?: string;
  payload?: { to?: string; subject?: string; body?: string };
};

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  }
  return res.json() as Promise<T>;
}

export async function listSessions(): Promise<Session[]> {
  return json<{ sessions: Session[] }>(await fetch(`${API_URL}/sessions`)).then(
    (r) => r.sessions,
  );
}

export async function createSession(): Promise<Session> {
  return json(
    await fetch(`${API_URL}/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "新專案" }),
    }),
  );
}

export async function deleteSession(id: string): Promise<void> {
  const res = await fetch(`${API_URL}/sessions/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

export async function getMessages(id: string): Promise<Message[]> {
  return json<{ messages: Message[] }>(
    await fetch(`${API_URL}/sessions/${id}/messages`),
  ).then((r) => r.messages);
}

export async function uploadFile(
  threadId: string,
  file: File,
): Promise<{ path: string; filename: string; size: number }> {
  const fd = new FormData();
  fd.append("thread_id", threadId);
  fd.append("file", file);
  // 唔好手動設 Content-Type：瀏覽器要自己加 multipart boundary。
  return json(await fetch(`${API_URL}/upload`, { method: "POST", body: fd }));
}

async function consumeSSE(res: Response, onEvent: (e: ChatEvent) => void): Promise<void> {
  if (!res.ok || !res.body) {
    throw new Error(`HTTP ${res.status}`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const raw = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      for (const line of raw.split("\n")) {
        if (line.startsWith("data: ")) {
          try {
            onEvent(JSON.parse(line.slice(6)) as ChatEvent);
          } catch {
            /* ignore malformed frames */
          }
        }
      }
    }
  }
}

export async function streamChat(
  threadId: string,
  message: string,
  onEvent: (e: ChatEvent) => void,
): Promise<void> {
  const res = await fetch(`${API_URL}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ thread_id: threadId, message }),
  });
  await consumeSSE(res, onEvent);
}

export async function resumeChat(
  threadId: string,
  approved: boolean,
  onEvent: (e: ChatEvent) => void,
): Promise<void> {
  const res = await fetch(`${API_URL}/chat/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ thread_id: threadId, approved }),
  });
  await consumeSSE(res, onEvent);
}
