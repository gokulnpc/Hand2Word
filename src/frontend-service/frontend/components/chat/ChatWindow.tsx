"use client";
import React, { useEffect, useRef, useState } from "react";
import type { ChatMessage } from "./ChatWidget";
import { IoIosSend } from "react-icons/io";
import { FaTrash } from "react-icons/fa";

export default function ChatWindow({
  open,
  onClose,
  messages,
  isReplying,
  onSend,
  onClear,
}: {
  open: boolean;
  onClose: () => void;
  messages: ChatMessage[];
  isReplying: boolean;
  onSend: (text: string) => void;
  onClear: () => void;
}) {
  const [text, setText] = useState("");
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, open, isReplying]);

  if (!open) return null;

  return (
    <div className="mb-3 mr-3 w-[92vw] max-w-[420px] h-[70vh] max-h-[640px] rounded-3xl border border-neutral-200 bg-white shadow-2xl overflow-hidden">
      <header className="flex items-center gap-3 px-4 py-3 border-b border-neutral-200 bg-neutral-50/80">
        <div className="size-8 rounded-xl bg-neutral-900 grid place-items-center text-white">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="3" width="7" height="7" rx="2" /><rect x="14" y="3" width="7" height="7" rx="2" /><rect x="14" y="14" width="7" height="7" rx="2" />
          </svg>
        </div>
        <div className="mr-auto leading-tight">
          <p className="font-semibold">KhoaBase</p>
          <p className="text-xs text-neutral-500">Ask me anything about Khoa</p>
        </div>
        <button onClick={onClose} className="p-2 rounded-lg hover:bg-neutral-100">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </header>

      <div ref={scrollRef} className="px-4 py-4 space-y-3 overflow-y-auto h-[calc(100%-128px)]">
        {messages.map((m) => (
          <MessageBubble key={m.id} role={m.role} text={m.content} />
        ))}
        {isReplying && <TypingBubble />}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          onSend(text);
          setText("");
        }}
        className="border-t border-neutral-200 p-3 bg-white"
      >
        <div className="flex items-end gap-2">
          <button
            type="button"
            title="Clear"
            onClick={() => (window.confirm("Clear conversation?")) && onClear()}
            className="p-2 rounded-lg border border-neutral-200 text-neutral-600 hover:bg-neutral-50"
          >
            <FaTrash />
          </button>
          <div className="flex-1">
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Say something…"
              className="w-full rounded-2xl border border-neutral-300 px-3 py-2 shadow-sm focus:outline-none focus:ring-4 focus:ring-indigo-100"
            />
          </div>
          <button type="submit" className="p-2 rounded-xl bg-indigo-600 text-white shadow hover:opacity-90">
            <IoIosSend />
          </button>
        </div>
      </form>
    </div>
  );
}

function MessageBubble({ role, text }: { role: "user" | "assistant"; text: string }) {
  const isUser = role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={
          "max-w-[85%] rounded-2xl px-3 py-2 text-sm shadow " +
          (isUser ? " bg-indigo-600 text-white rounded-br-md" : " bg-white border border-neutral-200 text-neutral-800 rounded-bl-md")
        }
      >
        {text.split('\n').map((line, i) => (
          <p key={i} className="whitespace-pre-wrap">{line}</p>
        ))}
      </div>
    </div>
  );
}

function TypingBubble() {
  return (
    <div className="flex items-center gap-2 text-neutral-500 text-sm">
      <span className="size-2 rounded-full bg-neutral-300 animate-bounce [animation-delay:-0.2s]"></span>
      <span className="size-2 rounded-full bg-neutral-300 animate-bounce"></span>
      <span className="size-2 rounded-full bg-neutral-300 animate-bounce [animation-delay:0.2s]"></span>
      <span className="ml-1">typing…</span>
    </div>
  );
}