"use client";

import { useEffect, useRef, useState } from "react";
import { getMessages, Message, streamChat } from "@/lib/api";
import Markdown from "@/components/Markdown";

const EXAMPLES = [
  "幫我搵吓新嘅香港非政府招標項目",
  "列出所有香港非政府招標",
  "核實第一個招標",
];

type Props = {
  sessionId: string | null;
  sessionTitle: string;
  autoMessage: string | null;
  onAutoMessageConsumed: () => void;
  onSessionsChanged?: () => void;
};

export default function Chat({
  sessionId,
  sessionTitle,
  autoMessage,
  onAutoMessageConsumed,
  onSessionsChanged,
}: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [running, setRunning] = useState(false);
  const runningRef = useRef(false);
  const autoSentFor = useRef<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // 載入 session 歷史（新 session 喺歷史載入後先自動發訊，避免 race）
  useEffect(() => {
    setMessages([]);
    if (!sessionId) return;
    let cancelled = false;
    (async () => {
      let msgs: Message[] = [];
      try {
        msgs = await getMessages(sessionId);
      } catch {
        /* ignore */
      }
      if (cancelled) return;
      setMessages(msgs);
      if (autoMessage && autoSentFor.current !== sessionId) {
        autoSentFor.current = sessionId;
        onAutoMessageConsumed();
        void send(autoMessage);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const patchLastAssistant = (fn: (m: Message) => Message) =>
    setMessages((prev) => {
      const copy = prev.slice();
      const last = copy[copy.length - 1];
      if (last && last.role === "assistant") {
        copy[copy.length - 1] = fn(last);
      }
      return copy;
    });

  const send = async (raw: string) => {
    const text = raw.trim();
    if (!text || runningRef.current || !sessionId) return;
    runningRef.current = true;
    setRunning(true);
    setInput("");
    setMessages((prev) => [
      ...prev,
      { role: "user", items: [{ type: "text", text }] },
      { role: "assistant", items: [] },
    ]);

    try {
      await streamChat(sessionId, text, (e) => {
        if (e.event === "text" && e.delta) {
          patchLastAssistant((m) => {
            const items = m.items.slice();
            const last = items[items.length - 1];
            if (last && last.type === "text") {
              items[items.length - 1] = { ...last, text: last.text + e.delta! };
            } else {
              items.push({ type: "text", text: e.delta! });
            }
            return { ...m, items };
          });
        } else if (e.event === "tool_start") {
          patchLastAssistant((m) => ({
            ...m,
            items: [...m.items, { type: "tool", name: e.node || "tool", done: false }],
          }));
        } else if (e.event === "tool_end") {
          patchLastAssistant((m) => {
            const items = m.items.slice();
            for (let i = items.length - 1; i >= 0; i--) {
              const it = items[i];
              if (it.type === "tool" && !it.done) {
                items[i] = { ...it, done: true, result: e.message };
                break;
              }
            }
            return { ...m, items };
          });
          if (e.node === "select_tender") onSessionsChanged?.();
        } else if (e.event === "error") {
          patchLastAssistant((m) => ({
            ...m,
            items: [...m.items, { type: "text", text: `⚠️ ${e.message}` }],
          }));
        }
      });
    } catch (err) {
      patchLastAssistant((m) => ({
        ...m,
        items: [...m.items, { type: "text", text: `⚠️ ${String(err)}` }],
      }));
    } finally {
      runningRef.current = false;
      setRunning(false);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send(input);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
        <div>
          <h1 className="font-semibold">{sessionTitle}</h1>
        </div>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {!sessionId && (
          <p className="text-sm text-slate-500">
            請喺左邊選擇一個專案，或按「＋ 新專案」開始。
          </p>
        )}

        {sessionId && messages.length === 0 && (
          <div className="space-y-2">
            <p className="text-sm text-slate-500">可以試吓：</p>
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                onClick={() => {
                  setInput(ex);
                  inputRef.current?.focus();
                }}
                className="block rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
              >
                {ex}
              </button>
            ))}
          </div>
        )}

        {messages.map((m, i) => (
          <div
            key={i}
            className={m.role === "user" ? "flex justify-end" : "flex justify-start"}
          >
            <div
              className={
                m.role === "user"
                  ? "max-w-[85%] rounded-2xl bg-slate-900 px-4 py-2 text-sm text-white"
                  : "max-w-[85%] space-y-2"
              }
            >
              {m.items.map((item, j) =>
                item.type === "text" ? (
                  m.role === "user" ? (
                    <p key={j} className="whitespace-pre-wrap text-sm text-white">
                      {item.text}
                    </p>
                  ) : (
                    <div
                      key={j}
                      className="prose prose-sm max-w-none rounded-2xl bg-white px-4 py-2 shadow-sm"
                    >
                      <Markdown content={item.text || (running ? "…" : "")} />
                    </div>
                  )
                ) : (
                  <div
                    key={j}
                    className="rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-xs"
                  >
                    <div className="flex items-center gap-2 font-medium text-sky-700">
                      {item.done ? "🔧" : "⏳"} {item.name}
                    </div>
                    {item.done && item.result && (
                      <p className="mt-1 whitespace-pre-wrap text-slate-600">
                        {item.result}
                      </p>
                    )}
                  </div>
                ),
              )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="border-t border-slate-200 bg-white p-3">
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            rows={1}
            placeholder={
              sessionId
                ? "問佢搵招標、核實、下載、生成摘要…（Enter 送出）"
                : "請先建立或選擇一個專案"
            }
            disabled={!sessionId}
            className="flex-1 resize-none rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none disabled:bg-slate-50"
          />
          <button
            onClick={() => void send(input)}
            disabled={running || !input.trim() || !sessionId}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm text-white hover:bg-slate-700 disabled:opacity-50"
          >
            {running ? "處理中…" : "送出"}
          </button>
        </div>
      </div>
    </div>
  );
}
