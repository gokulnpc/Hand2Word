export function formatStubResponse(input: string): string {
  return `(stub) Thanks! I received:

> ${input}

I'm just a placeholder for now.`;
}

// For the echo API
export function formatEchoReply(input: string): string {
  return `You said: ${input}`;
}

export function buildEchoRequest(message: string) {
  return { message } as const;
}

export function parseEchoResponse(json: any): string | null {
  if (json && typeof json.reply === "string") return json.reply;
  return null;
}