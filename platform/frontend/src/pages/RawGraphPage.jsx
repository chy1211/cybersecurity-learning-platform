import RawGraphComponent from '../components/RawGraphComponent';

export default function RawGraphPage() {
  return (
    <div className="h-full overflow-hidden flex flex-col bg-slate-950 p-6">
      <h1 className="text-2xl font-bold text-white mb-4">全知識圖譜 (Raw Knowledge Graph)</h1>
      <p className="text-slate-400 mb-6">此視圖呈現未經拓樸分層處理的原始知識節點與其所有關聯性（如 mitigates, exploits, belongs_to 等）。</p>
      <RawGraphComponent />
    </div>
  );
}