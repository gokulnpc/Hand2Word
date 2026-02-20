"use client";
import React, { useState } from "react";
import ChatFab from "./ChatFab";
import ChatWindow from "./ChatWindow";
import { buildEchoRequest, parseEchoResponse, formatStubResponse } from "./utils";

export type ChatMessage = { id: string; role: "user" | "assistant"; content: string };
const initMessage: ChatMessage = {
    id: (typeof crypto !== "undefined" && crypto.randomUUID) ? crypto.randomUUID() : `${Date.now()}-welcome`,
    role: "assistant",
    content: "Welcome to Glossa! Ask me anything, and I will assist you to the best of my capability!",
}
export default function ChatWidget() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([initMessage]);
  const [isReplying, setIsReplying] = useState(false);

  async function sendMessage(text: string) {
    const trimmed = text.trim();
    if (!trimmed) return;
    const userMsg: ChatMessage = { 
        id: (typeof crypto !== "undefined" && crypto.randomUUID) ? crypto.randomUUID() : `${Date.now()}-user`, 
        role: "user", 
        content: trimmed
    };
    setMessages((m) => [...m, userMsg]); // Add user message
    setIsReplying(true);

    // Call minimal echo API
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildEchoRequest(trimmed)),
      });
      const data = await res.json();
      const echo = parseEchoResponse(data) ?? formatStubResponse(trimmed);
      const botMsg: ChatMessage = {
        id: (typeof crypto !== "undefined" && crypto.randomUUID) ? crypto.randomUUID() : `${Date.now()}-bot`,
        role: "assistant",
        content: echo,
      };
      setMessages((m) => [...m, botMsg]);
    } catch (e) {
      const botMsg: ChatMessage = {
        id: (typeof crypto !== "undefined" && crypto.randomUUID) ? crypto.randomUUID() : `${Date.now()}-boterr`,
        role: "assistant",
        content: formatStubResponse(trimmed),
      };
      setMessages((m) => [...m, botMsg]);
    } finally {
      setIsReplying(false);
    }
  }

  return (
    <div className="fixed bottom-4 right-4 z-50">
        <ChatWindow open={open} onClose={() => setOpen(false)} messages={messages} isReplying={isReplying} onSend={sendMessage} onClear={() => setMessages([initMessage])} />
        <div className="flex justify-end">
            <ChatFab open={open} onToggle={() => setOpen((v) => !v)} />
        </div>
    </div>
  );
}
