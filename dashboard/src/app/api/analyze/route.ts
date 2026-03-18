import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import { NextResponse } from 'next/server';

const ANALYSIS_PROMPT = `You are a nutrition analysis assistant. When given food (photo or text description), provide:

A table with columns: Food Item | Weight | Protein | Carbs | Fat | Calories | Water

Be concise. Estimate portions if not specified.

IMPORTANT: At the very end, include: $$TOTALS: kcal=NUMBER, protein=NUMBER, carbs=NUMBER, fat=NUMBER, water=NUMBER$$`;

export async function POST(request: Request) {
  const session = await getServerSession(authOptions);
  if (!session?.user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

  const formData = await request.formData();
  const text = formData.get('text') as string | null;
  const photo = formData.get('photo') as File | null;

  if (!text && !photo) {
    return NextResponse.json({ error: 'Provide text or photo' }, { status: 400 });
  }

  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) return NextResponse.json({ error: 'AI not configured' }, { status: 500 });

  try {
    // Use Gemini REST API directly
    const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key=${apiKey}`;

    let parts: any[] = [{ text: ANALYSIS_PROMPT + '\n\n' }];

    if (photo) {
      const bytes = await photo.arrayBuffer();
      const base64 = Buffer.from(bytes).toString('base64');
      parts.push({
        inlineData: { mimeType: photo.type || 'image/jpeg', data: base64 }
      });
      parts.push({ text: 'Analyze this meal photo.' });
    } else if (text) {
      parts.push({ text: `I ate: ${text}\n\nEstimate macros and calories.` });
    }

    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        contents: [{ parts }],
        generationConfig: { maxOutputTokens: 1024 },
      }),
    });

    const data = await response.json();
    const analysisText = data.candidates?.[0]?.content?.parts?.[0]?.text || '';

    if (!analysisText) {
      return NextResponse.json({ error: 'No analysis from AI' }, { status: 500 });
    }

    return NextResponse.json({ analysis: analysisText });
  } catch (error: any) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
