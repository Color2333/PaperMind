import { useState } from 'react';
import { PanelLeftClose, PanelLeft, Languages, Sparkles, GitBranch } from 'lucide-react';

export type TabId = 'translation' | 'aggregation' | 'canvas';

interface Tab {
  id: TabId;
  label: string;
  icon: React.ReactNode;
}

const TABS: Tab[] = [
  { id: 'translation', label: '翻译', icon: <Languages className="h-4 w-4" /> },
  { id: 'aggregation', label: 'AI聚合', icon: <Sparkles className="h-4 w-4" /> },
  { id: 'canvas', label: 'Canvas', icon: <GitBranch className="h-4 w-4" /> },
];

interface ToolPanelProps {
  selectedText: string;
  paperId: string;
  children: {
    translation: React.ReactNode;
    aggregation: React.ReactNode;
    canvas: React.ReactNode;
  };
}

export function ToolPanel({ selectedText, paperId, children }: ToolPanelProps) {
  const [activeTab, setActiveTab] = useState<TabId>('translation');
  const [collapsed, setCollapsed] = useState(false);

  if (collapsed) {
    return (
      <div className="flex h-full w-12 flex-col items-center gap-2 border-l border-white/10 bg-[#1e1e2e] py-4">
        <button
          type="button"
          onClick={() => setCollapsed(false)}
          className="rounded p-2 text-white/40 hover:bg-white/10 hover:text-white"
          title="展开面板"
        >
          <PanelLeft className="h-5 w-5" />
        </button>
        {TABS.map(tab => (
          <button
            type="button"
            key={tab.id}
            onClick={() => { setActiveTab(tab.id); setCollapsed(false); }}
            className="rounded p-2 text-white/40 hover:bg-white/10 hover:text-white"
            title={tab.label}
          >
            {tab.icon}
          </button>
        ))}
      </div>
    );
  }

  return (
    <div className="relative flex h-full w-full flex-col border-l border-white/10 bg-[#1e1e2e] transition-all duration-300"
         style={{ width: collapsed ? 48 : '100%' }}>
      <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
        <div className="flex items-center gap-2">
          {TABS.map(tab => (
            <button
              type="button"
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm transition-colors ${
                activeTab === tab.id
                  ? 'bg-primary/20 text-primary'
                  : 'text-white/60 hover:bg-white/10 hover:text-white'
              }`}
            >
              {tab.icon}
              <span className="hidden sm:inline">{tab.label}</span>
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={() => setCollapsed(true)}
          className="rounded p-1.5 text-white/40 hover:bg-white/10 hover:text-white"
        >
          <PanelLeftClose className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 overflow-auto">
        {activeTab === 'translation' && children.translation}
        {activeTab === 'aggregation' && children.aggregation}
        {activeTab === 'canvas' && children.canvas}
      </div>
    </div>
  );
}
