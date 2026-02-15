import { NextResponse } from "next/server";

export async function POST(req: Request) {
  try {
    const body = await req.json().catch(() => ({}));
    const message: string = typeof body?.message === "string" ? body.message : "";
    // minimal echo
    return NextResponse.json({ reply: `You said: ${message}` });
  } catch (e) {
    return NextResponse.json({ reply: "You said: (unreadable)" }, { status: 200 });
  }
}