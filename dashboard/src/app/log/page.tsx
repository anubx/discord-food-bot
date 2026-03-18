'use client';

import { useSession } from 'next-auth/react';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import Sidebar from '@/components/Sidebar';
import Link from 'next/link';

interface AnalysisResult {
  kcal: number;
  protein: number;
  carbs: number;
  fat: number;
  water_ml: number;
}

interface ParsedAnalysis {
  analysis: string;
  parsed?: AnalysisResult;
}

interface MealTemplate {
  id: number;
  name: string;
  kcal: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  water_ml: number;
  description: string;
}

export default function LogMealPage() {
  const { data: session, status } = useSession();
  const router = useRouter();
  const [activeTab, setActiveTab] = useState<'photo' | 'text' | 'barcode'>('photo');
  const [photoFile, setPhotoFile] = useState<File | null>(null);
  const [photoPreview, setPhotoPreview] = useState<string | null>(null);
  const [textInput, setTextInput] = useState('');
  const [analyzing, setAnalyzing] = useState(false);
  const [analysis, setAnalysis] = useState<ParsedAnalysis | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [templates, setTemplates] = useState<MealTemplate[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(true);
  const [loggingTemplate, setLoggingTemplate] = useState<string | null>(null);

  useEffect(() => {
    if (status === 'unauthenticated') {
      router.push('/login');
    }
  }, [status, router]);

  useEffect(() => {
    const fetchTemplates = async () => {
      try {
        const res = await fetch('/api/templates');
        if (res.ok) {
          const data = await res.json();
          setTemplates(data.templates || []);
        }
      } catch (err) {
        console.error('Failed to load templates:', err);
      } finally {
        setLoadingTemplates(false);
      }
    };
    if (status === 'authenticated') {
      fetchTemplates();
    }
  }, [status]);

  const handlePhotoSelect = (file: File) => {
    setPhotoFile(file);
    const reader = new FileReader();
    reader.onload = (e) => {
      setPhotoPreview(e.target?.result as string);
    };
    reader.readAsDataURL(file);
    setError(null);
  };

  const handlePhotoChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.[0]) {
      handlePhotoSelect(e.target.files[0]);
    }
  };

  const handlePhotoDrop = (e: React.DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer.files?.[0]) {
      handlePhotoSelect(e.dataTransfer.files[0]);
    }
  };

  const parseAnalysis = (text: string): AnalysisResult | null => {
    const match = text.match(/\$\$TOTALS:\s*kcal=(\d+),\s*protein=(\d+),\s*carbs=(\d+),\s*fat=(\d+)(?:,\s*water=(\d+))?\$\$/);
    if (match) {
      return {
        kcal: parseInt(match[1]),
        protein: parseInt(match[2]),
        carbs: parseInt(match[3]),
        fat: parseInt(match[4]),
        water_ml: match[5] ? parseInt(match[5]) : 0,
      };
    }
    return null;
  };

  const analyzeFood = async () => {
    if (!photoFile && !textInput.trim()) {
      setError('Please provide a photo or text description');
      return;
    }

    setAnalyzing(true);
    setError(null);

    try {
      const formData = new FormData();
      if (photoFile) formData.append('photo', photoFile);
      if (textInput) formData.append('text', textInput);

      const res = await fetch('/api/analyze', { method: 'POST', body: formData });
      if (!res.ok) throw new Error('Analysis failed');

      const { analysis: analysisText } = await res.json();
      const parsed = parseAnalysis(analysisText);

      if (!parsed) {
        throw new Error('Could not parse nutrition data from AI response');
      }

      setAnalysis({ analysis: analysisText, parsed });
    } catch (err: any) {
      setError(err.message);
    } finally {
      setAnalyzing(false);
    }
  };

  const submitMeal = async () => {
    if (!analysis?.parsed) return;

    setSubmitting(true);
    setError(null);

    try {
      const res = await fetch('/api/meals', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          analysis: analysis.analysis,
          description: textInput || 'Meal',
          photoUrl: photoPreview,
        }),
      });

      if (!res.ok) throw new Error('Failed to save meal');
      setSuccess(true);

      setTimeout(() => {
        router.push('/');
      }, 1500);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const logTemplate = async (template: MealTemplate) => {
    setLoggingTemplate(template.name);
    setError(null);

    try {
      const res = await fetch('/api/templates', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ templateName: template.name }),
      });

      if (!res.ok) throw new Error('Failed to log template');
      setSuccess(true);

      setTimeout(() => {
        router.push('/');
      }, 1500);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoggingTemplate(null);
    }
  };

  if (status === 'loading') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950">
        <div className="text-slate-400">Loading...</div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen">
      <Sidebar />

      <main className="ml-60 flex-1 p-6 lg:p-8">
        <div className="mb-6">
          <Link href="/" className="text-green-400 hover:text-green-300 text-sm font-medium flex items-center gap-1">
            ← Back to Dashboard
          </Link>
          <h1 className="text-2xl font-bold text-white mt-4">Log a Meal</h1>
          <p className="text-sm text-slate-500 mt-0.5">Use AI to analyze your food and track macros</p>
        </div>

        {!loadingTemplates && templates.length > 0 && (
          <div className="max-w-2xl mx-auto mb-6 bg-slate-900 rounded-2xl border border-slate-700 shadow-2xl p-6">
            <h2 className="text-lg font-semibold text-white mb-4">📋 Quick Log from Template</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {templates.map((template) => (
                <button
                  key={template.id}
                  onClick={() => logTemplate(template)}
                  disabled={loggingTemplate === template.name || success}
                  className="p-3 bg-slate-800 hover:bg-slate-700 disabled:bg-slate-700 disabled:opacity-50 rounded-lg border border-slate-700 hover:border-green-500 transition-all text-left"
                >
                  <div className="text-sm font-medium text-white">{template.name}</div>
                  <div className="text-xs text-slate-400 mt-1">
                    {template.kcal} kcal • {Math.round(template.protein_g)}P • {Math.round(template.carbs_g)}C • {Math.round(template.fat_g)}F
                  </div>
                  {loggingTemplate === template.name && (
                    <div className="text-xs text-green-400 mt-1">Logging...</div>
                  )}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="max-w-2xl mx-auto bg-slate-900 rounded-2xl border border-slate-700 shadow-2xl overflow-hidden">
          <div className="flex border-b border-slate-800">
            {(['photo', 'text', 'barcode'] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`flex-1 px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                  activeTab === tab
                    ? 'border-b-green-500 text-green-400'
                    : 'border-b-transparent text-slate-500 hover:text-slate-300'
                }`}
              >
                {tab === 'photo' && '📸 Photo'}
                {tab === 'text' && '✍️ Text'}
                {tab === 'barcode' && '📦 Barcode'}
              </button>
            ))}
          </div>

          <div className="p-6">
            {activeTab === 'photo' && (
              <div>
                <div
                  onDrop={handlePhotoDrop}
                  onDragOver={(e) => e.preventDefault()}
                  className="border-2 border-dashed border-slate-700 rounded-xl p-8 text-center cursor-pointer hover:border-green-500 hover:bg-green-500/5 transition-all"
                >
                  {photoPreview ? (
                    <div>
                      <img src={photoPreview} alt="Preview" className="max-h-48 mx-auto mb-4 rounded-lg" />
                      <button
                        onClick={() => {
                          setPhotoFile(null);
                          setPhotoPreview(null);
                        }}
                        className="text-sm text-slate-400 hover:text-slate-200"
                      >
                        Click to replace
                      </button>
                    </div>
                  ) : (
                    <>
                      <div className="text-4xl mb-3">📸</div>
                      <div className="text-sm font-medium text-white mb-1">Drop a food photo here</div>
                      <div className="text-xs text-slate-500 mb-4">or click to browse (JPG, PNG, WEBP)</div>
                      <label className="inline-block">
                        <input
                          type="file"
                          accept="image/*"
                          onChange={handlePhotoChange}
                          className="hidden"
                        />
                        <span className="px-4 py-2 bg-slate-800 hover:bg-slate-700 rounded-lg text-sm text-slate-300 border border-slate-700 cursor-pointer inline-block">
                          Choose File
                        </span>
                      </label>
                    </>
                  )}
                </div>
              </div>
            )}

            {activeTab === 'text' && (
              <div>
                <label className="text-xs text-slate-500 uppercase tracking-wide font-semibold mb-2 block">
                  Describe what you ate
                </label>
                <textarea
                  value={textInput}
                  onChange={(e) => setTextInput(e.target.value)}
                  placeholder="e.g. two eggs, toast with butter, coffee with milk"
                  className="w-full bg-slate-800 border border-slate-700 rounded-xl p-4 text-sm text-white placeholder-slate-500 resize-none h-28 focus:outline-none focus:border-green-500 transition-colors"
                />
              </div>
            )}

            {activeTab === 'barcode' && (
              <div>
                <div className="border-2 border-dashed border-slate-700 rounded-xl p-8 text-center cursor-pointer hover:border-green-500 hover:bg-green-500/5 transition-all">
                  <div className="text-4xl mb-3">📦</div>
                  <div className="text-sm font-medium text-white mb-1">Scan or upload a barcode</div>
                  <div className="text-xs text-slate-500 mb-4">Photo of the product barcode for exact nutrition</div>
                  <label>
                    <input type="file" accept="image/*" className="hidden" />
                    <span className="inline-block px-4 py-2 bg-slate-800 hover:bg-slate-700 rounded-lg text-sm text-slate-300 border border-slate-700 cursor-pointer">
                      Choose File
                    </span>
                  </label>
                </div>
                <div className="mt-4">
                  <label className="text-xs text-slate-500 uppercase tracking-wide font-semibold mb-2 block">
                    Quantity (optional)
                  </label>
                  <input
                    type="text"
                    placeholder='e.g. "half", "2 servings", "50g"'
                    className="w-full bg-slate-800 border border-slate-700 rounded-xl px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-green-500 transition-colors"
                  />
                </div>
              </div>
            )}

            {error && (
              <div className="mt-4 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-sm text-red-400">
                {error}
              </div>
            )}

            {success && (
              <div className="mt-4 p-3 bg-green-500/10 border border-green-500/30 rounded-lg text-sm text-green-400">
                Meal logged successfully! Redirecting...
              </div>
            )}

            {!analysis && (
              <button
                onClick={analyzeFood}
                disabled={analyzing || (!photoFile && !textInput.trim())}
                className="mt-4 w-full py-2.5 bg-green-600 hover:bg-green-500 disabled:bg-slate-700 disabled:text-slate-500 rounded-xl text-sm font-semibold text-white transition-colors"
              >
                {analyzing ? 'Analyzing...' : 'Analyze Meal'}
              </button>
            )}
          </div>

          {analysis?.parsed && (
            <div className="border-t border-slate-800 p-6 bg-slate-800/30">
              <h3 className="font-semibold text-white mb-4">Nutrition Analysis</h3>
              <div className="grid grid-cols-2 gap-4 mb-4">
                <div className="bg-slate-900 p-3 rounded-lg">
                  <div className="text-2xl font-bold text-orange-400">{analysis.parsed.kcal}</div>
                  <div className="text-xs text-slate-500">Calories</div>
                </div>
                <div className="bg-slate-900 p-3 rounded-lg">
                  <div className="text-2xl font-bold text-red-400">{analysis.parsed.protein}g</div>
                  <div className="text-xs text-slate-500">Protein</div>
                </div>
                <div className="bg-slate-900 p-3 rounded-lg">
                  <div className="text-2xl font-bold text-yellow-400">{analysis.parsed.carbs}g</div>
                  <div className="text-xs text-slate-500">Carbs</div>
                </div>
                <div className="bg-slate-900 p-3 rounded-lg">
                  <div className="text-2xl font-bold text-blue-400">{analysis.parsed.fat}g</div>
                  <div className="text-xs text-slate-500">Fat</div>
                </div>
              </div>

              <div className="mb-4 p-3 bg-slate-900 rounded-lg max-h-32 overflow-y-auto">
                <p className="text-xs text-slate-400 whitespace-pre-wrap font-mono">{analysis.analysis}</p>
              </div>

              <div className="flex gap-3">
                <button
                  onClick={() => {
                    setAnalysis(null);
                    setPhotoFile(null);
                    setPhotoPreview(null);
                    setTextInput('');
                  }}
                  className="flex-1 py-2.5 bg-slate-800 hover:bg-slate-700 rounded-xl text-sm font-semibold text-slate-300 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={submitMeal}
                  disabled={submitting || success}
                  className="flex-1 py-2.5 bg-green-600 hover:bg-green-500 disabled:bg-slate-700 disabled:text-slate-500 rounded-xl text-sm font-semibold text-white transition-colors"
                >
                  {submitting ? 'Saving...' : 'Log Meal'}
                </button>
              </div>
            </div>
          )}

          <div className="px-6 py-3 border-t border-slate-800 flex items-center justify-between bg-slate-800/20">
            <span className="text-[11px] text-slate-600">AI analyzes your meal for macros & calories</span>
            <div className="flex items-center gap-2">
              <span className="text-[11px] text-slate-600">Powered by</span>
              <span className="text-[11px] font-semibold text-slate-400">Gemini 2.5</span>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
